"""vvhub.laya_engine: every Laya call in the hub goes through here.

Laya (github.com/NandhaKishorM/laya, Apache-2.0, pinned in THIRD_PARTY.lock)
answers typed questions -- `choice`, `score`, `noul` -- over a state in one
forward pass. This module only picks how to run it and keeps it cheap:

  tier      backend                                     when
  gpu       laya.Router on CUDA (english checkpoint)     torch sees a GPU
  onnx      laya.onnx_agent.ONNXAgent, INT8 export       CPU + an exported .onnx
  cpu       laya.Router on CPU                           CPU, no export yet
  keywords  KeywordBackend below (no model at all)       Laya not installed

The model loads on first use and is dropped after `idle_seconds` without a
call (rule 26: heavy parts start on demand and stop when idle). A failed load
is remembered, so a machine without torch pays for the import attempt once.

The keyword tier exists so a low-spec install still routes, but its
confidence is capped below the router's threshold: everything it decides is
asked about first (rule 10, "low confidence -> ask").

Module-level `decide` / `score` / `yes_no` are the Â§3.7 API; they use one
shared Engine that tests replace with `set_engine`.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

TIERS = ("gpu", "onnx", "cpu", "keywords")
DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_IDLE_SECONDS = 600.0
# The English checkpoint only: the user speaks English, and the multilingual
# one is another 640 MB resident.
LAYA_MODEL = "english"
LAYA_REPO = "convaiinnovations/laya"


class LayaUnavailable(RuntimeError):
    """No backend could be loaded (and the keyword tier was not allowed)."""


# --------------------------------------------------------------- keywords
_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset("a an the to of on in for and or is it this that my me i you your with "
                  "what how do does please can could would about at be are".split())


def _stem(word: str) -> str:
    """Just enough stemming that "notes"/"note" and "posting"/"posted"/"post" meet."""
    if word.endswith("ies") and len(word) >= 5:
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if (word.endswith(suffix) and len(word) - len(suffix) >= 3
                and not (suffix == "s" and word.endswith("ss"))):
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def terms(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP}


def _state_text(state: Any) -> str:
    if isinstance(state, dict):
        return " ".join(str(v) for v in state.values() if isinstance(v, (str, int, float)))
    if isinstance(state, list):
        return " ".join(map(str, state))
    return str(state)


class KeywordBackend:
    """Word overlap between the state and each option's label + description.

    Laya's result shape, so everything above it is backend-blind. Scores and
    yes/no questions get a neutral answer: there is nothing to base one on.
    """

    MAX_CONFIDENCE = 0.5

    def predict(self, state: Any, questions: dict, min_confidence: float | None = None) -> dict:
        said = terms(_state_text(state))
        answers: dict[str, dict] = {}
        for qid, q in questions.items():
            kind = q.get("type")
            if kind == "choice":
                criteria = q.get("criteria") or {}
                labels = list(criteria)
                hits = []
                for label in labels:
                    words = terms(f"{label.replace('_', ' ')} {criteria[label] or ''}")
                    hits.append(len(said & words))
                best = max(range(len(labels)), key=lambda i: (hits[i], i == len(labels) - 1))
                if hits[best] == 0:
                    best = len(labels) - 1  # the catch-all goes last by convention
                total = sum(hits) or 1
                share = hits[best] / total if hits[best] else 0.0
                confidence = round(min(self.MAX_CONFIDENCE, 0.2 + 0.3 * share), 4)
                probs = {label: round(h / total, 4) for label, h in zip(labels, hits)}
                answers[qid] = {"type": "choice", "choice": labels[best], "probabilities": probs,
                                "answer_confidence": confidence}
            elif kind == "score":
                levels = len(q.get("criteria") or [0, 1])
                answers[qid] = {"type": "score", "score": (levels - 1) / 2,
                                "answer_confidence": 0.0}
            else:
                answers[qid] = {"type": "noul", "noul": 0.5, "answer_confidence": 0.5}
            if min_confidence is not None and answers[qid]["answer_confidence"] < min_confidence:
                answers[qid]["low_confidence"] = True
        return {"answers": answers, "backend": "keywords"}


# ------------------------------------------------------------------ tiers
def _has(name: str) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def onnx_candidates() -> list[Path]:
    """Where an INT8 export may live: $VVHUB_LAYA_ONNX, then the shared caches."""
    out = []
    if os.environ.get("VVHUB_LAYA_ONNX"):
        out.append(Path(os.environ["VVHUB_LAYA_ONNX"]))
    hf = os.environ.get("HF_HOME")
    if hf:
        out.append(Path(hf) / "laya-onnx" / "laya.int8.onnx")
    root = Path(__file__).resolve().parents[3]  # ...\voicevibe
    out.append(root / "venvs" / "models" / "laya" / "laya.int8.onnx")
    return out


def _onnx_file() -> str | None:
    for path in onnx_candidates():
        if path.is_file():
            return str(path)
    return None


def detect_tier(env: dict | None = None, has: Callable[[str], bool] = _has,
                cuda: Callable[[], bool] = _cuda,
                onnx_file: Callable[[], str | None] = _onnx_file) -> str:
    """The best tier this machine can run. $VVHUB_LAYA_TIER forces one."""
    env = os.environ if env is None else env
    forced = str(env.get("VVHUB_LAYA_TIER", "")).strip().lower()
    if forced in TIERS:
        return forced
    if not has("laya"):
        return "keywords"
    if has("torch") and cuda():
        return "gpu"
    if has("onnxruntime") and onnx_file():
        return "onnx"
    if has("torch"):
        return "cpu"
    return "keywords"


def load_backend(tier: str) -> Any:
    """Build the backend for `tier`. Imports happen here, not at module load."""
    if tier == "keywords":
        return KeywordBackend()
    if tier in ("gpu", "cpu"):
        from laya import Router

        router = Router(device="cuda" if tier == "gpu" else "cpu", max_loaded=1,
                        default=LAYA_MODEL)
        router.load(LAYA_MODEL)
        return _RouterBackend(router)
    if tier == "onnx":
        from laya.onnx_agent import ONNXAgent

        path = _onnx_file()
        if not path:
            raise FileNotFoundError("no Laya INT8 export found")
        return ONNXAgent(LAYA_REPO, onnx_path=path)
    raise ValueError(f"unknown Laya tier {tier!r}")


class _RouterBackend:
    """laya.Router pinned to one checkpoint, so short text never loads another."""

    def __init__(self, router: Any) -> None:
        self.router = router

    def predict(self, state: Any, questions: dict, min_confidence: float | None = None) -> dict:
        return self.router.predict(state, questions, model=LAYA_MODEL,
                                   min_confidence=min_confidence)

    def close(self) -> None:
        try:
            self.router.unload(LAYA_MODEL)
        except Exception:
            pass
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


# ----------------------------------------------------------------- engine
class Engine:
    """A lazily loaded backend with an idle timeout. Thread-safe."""

    def __init__(self, loader: Callable[[], Any] | None = None, tier: str | None = None,
                 min_confidence: float = DEFAULT_MIN_CONFIDENCE,
                 idle_seconds: float = DEFAULT_IDLE_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 fallback: bool = False) -> None:
        # fallback: on a failed load, drop to the keyword tier instead of raising.
        self.fallback = fallback
        self.tier = tier or (None if loader else detect_tier())
        self._loader = loader or (lambda: load_backend(self.tier))
        self.min_confidence = min_confidence
        self.idle_seconds = idle_seconds
        self.clock = clock
        self._backend: Any = None
        self._failed: BaseException | None = None
        self._last = 0.0
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    def available(self) -> bool:
        return self._failed is None

    def warm(self) -> None:
        """Load now (e.g. at hub start, or before an eval). Raises LayaUnavailable."""
        self._get()

    def _get(self) -> Any:
        with self._lock:
            if self._backend is None:
                if self._failed is not None:
                    raise LayaUnavailable(str(self._failed))
                started = time.perf_counter()
                try:
                    self._backend = self._loader()
                except Exception as exc:  # noqa: BLE001 - any load failure means "no Laya"
                    log.warning("Laya (%s) unavailable: %s", self.tier, exc)
                    if not self.fallback:
                        self._failed = exc
                        raise LayaUnavailable(str(exc)) from exc
                    self.tier, self._loader = "keywords", KeywordBackend
                    self._backend = KeywordBackend()
                log.info("Laya %s loaded in %.1fs", self.tier,
                         time.perf_counter() - started)
            self._last = self.clock()
            return self._backend

    def reap(self) -> bool:
        """Drop the model if idle too long. True if it was dropped."""
        with self._lock:
            if self._backend is None or self.clock() - self._last < self.idle_seconds:
                return False
            backend, self._backend = self._backend, None
        close = getattr(backend, "close", None)
        if callable(close):
            close()
        log.info("Laya unloaded after %.0fs idle", self.idle_seconds)
        return True

    def decide(self, state: Any, questions: dict, min_confidence: float | None = None) -> dict:
        backend = self._get()
        mc = self.min_confidence if min_confidence is None else min_confidence
        started = time.perf_counter()
        result = backend.predict(state, questions, min_confidence=mc)
        result = dict(result)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result.setdefault("tier", self.tier)
        return result

    def score(self, state: Any, instruction: str, criteria: list) -> float:
        """Expected level as 0..1 (0 = first criterion, 1 = last)."""
        q = {"score": {"type": "score", "instructions": instruction, "criteria": list(criteria)}}
        answer = self.decide(state, q, min_confidence=0.0)["answers"]["score"]
        top = max(1, len(criteria) - 1)
        return max(0.0, min(1.0, float(answer["score"]) / top))

    def yes_no(self, state: Any, instruction: str) -> float:
        """Probability of yes."""
        q = {"yes_no": {"type": "noul", "instructions": instruction}}
        return float(self.decide(state, q, min_confidence=0.0)["answers"]["yes_no"]["noul"])


_engine: Engine | None = None
_engine_lock = threading.Lock()


def engine() -> Engine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = Engine(fallback=True)
        return _engine


def set_engine(new: Engine | None) -> Engine | None:
    """Install `new` as the shared engine; returns the previous one."""
    global _engine
    with _engine_lock:
        old, _engine = _engine, new
        return old


def decide(state: Any, questions: dict, min_confidence: float | None = None) -> dict:
    return engine().decide(state, questions, min_confidence)


def score(state: Any, instruction: str, criteria: list) -> float:
    return engine().score(state, instruction, criteria)


def yes_no(state: Any, instruction: str) -> float:
    return engine().yes_no(state, instruction)
