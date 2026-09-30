"""Chats for the control app: hub conversations (hub.db) + Voice Vibe's history JSONL.

Ids: `hub/<conversation>`, `history/<YYYY-MM-DD>` (kept 2 days, top level of
history\\), `saved/<YYYY-MM-DD>` (history\\saved\\, kept forever). Saving a
history day copies it into saved\\ as the union of both files, exactly like
Voice Vibe's "computer save this conversation" (voicevibe.history.History.save).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

RETENTION_SECONDS = 2 * 86400
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_MATCHES = 100


class NotFound(LookupError):
    pass


def _epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def _record_turns(rec: dict) -> list[dict]:
    ts = _epoch(rec.get("ts"))
    heard = str(rec.get("heard") or rec.get("text") or "")
    turns = [{"ts": ts, "role": "you", "text": heard, "action": str(rec.get("action") or "")}] if heard else []
    if rec.get("spoken"):
        turns.append({"ts": ts, "role": "voicevibe", "text": str(rec["spoken"]), "action": ""})
    return turns


class Chats:
    def __init__(self, store: Any, history_dir: Path, keep_days: int = 2) -> None:
        self.store = store
        self.history_dir = Path(history_dir)
        self.saved_dir = self.history_dir / "saved"
        self.keep_seconds = keep_days * 86400

    # ---- listing ----------------------------------------------------------
    def items(self) -> list[dict]:
        rows = self.store._rows(
            "SELECT c.id, c.started, c.saved, c.title, COUNT(t.id) AS n, MAX(t.ts) AS last,"
            " (SELECT text FROM turns t2 WHERE t2.conversation = c.id ORDER BY t2.ts DESC, t2.id DESC LIMIT 1)"
            " AS preview FROM conversations c LEFT JOIN turns t ON t.conversation = c.id GROUP BY c.id")
        items = []
        for r in rows:
            last = r["last"] or r["started"]
            items.append({"id": f"hub/{r['id']}", "source": "hub", "title": r["title"] or r["id"],
                          "saved": bool(r["saved"]), "started": r["started"], "last": last, "turns": r["n"],
                          "preview": (r["preview"] or "")[:160],
                          "expires": None if r["saved"] else last + RETENTION_SECONDS})
        kept = {}
        for path in sorted(self.history_dir.glob("*.jsonl")):
            if DAY.match(path.stem):
                kept[path.stem] = path
        for day, path in kept.items():
            items.append(self._day_item("history", day, path, (self.saved_dir / path.name).exists()))
        for path in sorted(self.saved_dir.glob("*.jsonl")):
            if DAY.match(path.stem) and path.stem not in kept:
                items.append(self._day_item("saved", path.stem, path, True))
        return sorted(items, key=lambda i: i["last"] or 0, reverse=True)

    def _day_item(self, kind: str, day: str, path: Path, saved: bool) -> dict:
        records = _read_jsonl(path)
        turns = [t for rec in records for t in _record_turns(rec)]
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return {"id": f"{kind}/{day}", "source": "history", "title": f"Dictation {day}", "saved": saved,
                "started": turns[0]["ts"] if turns else mtime, "last": mtime, "turns": len(turns),
                "preview": (turns[-1]["text"] if turns else "")[:160],
                "expires": None if saved else mtime + self.keep_seconds}

    # ---- search -------------------------------------------------------------
    def search(self, q: str) -> list[dict]:
        q = (q or "").strip()
        if not q:
            return []
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        hits = [{"id": f"hub/{r['conversation']}", "ts": r["ts"], "role": r["role"], "text": r["text"][:240]}
                for r in self.store._rows(
                    "SELECT conversation, ts, role, text FROM turns WHERE text LIKE ? ESCAPE '\\'"
                    " ORDER BY ts DESC LIMIT ?", (like, MAX_MATCHES))]
        needle = q.lower()
        for kind, folder in (("history", self.history_dir), ("saved", self.saved_dir)):
            for path in sorted(folder.glob("*.jsonl"), reverse=True):
                if not DAY.match(path.stem) or (kind == "saved" and (self.history_dir / path.name).exists()):
                    continue
                for rec in _read_jsonl(path):
                    for turn in _record_turns(rec):
                        if needle in turn["text"].lower():
                            hits.append({"id": f"{kind}/{path.stem}", "ts": turn["ts"], "role": turn["role"],
                                         "text": turn["text"][:240]})
        return sorted(hits, key=lambda h: h["ts"], reverse=True)[:MAX_MATCHES]

    # ---- one chat -------------------------------------------------------------
    def _split(self, cid: str) -> tuple[str, str]:
        kind, _, rest = (cid or "").partition("/")
        if kind == "hub" and rest and "/" not in rest:
            return kind, rest
        if kind in ("history", "saved") and DAY.match(rest):
            return kind, rest
        raise NotFound(cid)

    def _day_path(self, kind: str, day: str) -> Path:
        path = (self.history_dir if kind == "history" else self.saved_dir) / f"{day}.jsonl"
        if not path.exists():
            raise NotFound(day)
        return path

    def get(self, cid: str) -> dict:
        kind, key = self._split(cid)
        if kind == "hub":
            rows = self.store._rows("SELECT id, saved, title FROM conversations WHERE id = ?", (key,))
            if not rows:
                raise NotFound(cid)
            turns = []
            for t in self.store.turns(key):
                data = t.get("data")
                try:
                    source = (json.loads(data) if isinstance(data, str) else data or {}).get("source", "")
                except ValueError:
                    source = ""
                turns.append({"ts": t["ts"], "role": t["role"], "text": t["text"], "source": source})
            return {"id": cid, "title": rows[0]["title"] or key, "saved": bool(rows[0]["saved"]), "turns": turns}
        path = self._day_path(kind, key)
        turns = [t for rec in _read_jsonl(path) for t in _record_turns(rec)]
        saved = kind == "saved" or (self.saved_dir / path.name).exists()
        return {"id": cid, "title": f"Dictation {key}", "saved": saved, "turns": turns}

    def save(self, cid: str, title: str = "") -> dict:
        kind, key = self._split(cid)
        if kind == "hub":
            if not self.store._rows("SELECT id FROM conversations WHERE id = ?", (key,)):
                raise NotFound(cid)
            self.store.save_conversation(key, title.strip()[:120])
            return {"ok": True, "text": "Saved; it won't be deleted."}
        if kind == "saved":
            return {"ok": True, "text": "Already saved."}
        source = self._day_path(kind, key)
        target = self.saved_dir / source.name
        self.saved_dir.mkdir(parents=True, exist_ok=True)
        lines, seen = [], set()
        for path in (target, source):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip() and line not in seen:
                        seen.add(line)
                        lines.append(line)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"ok": True, "text": f"Saved {len(lines)} lines; they won't be deleted."}

    def export(self, cid: str, fmt: str = "md") -> dict:
        chat = self.get(cid)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", chat["id"]).strip("-")
        if fmt == "json":
            return {"filename": f"voicevibe-{safe}.json", "text": json.dumps(chat, ensure_ascii=False, indent=2)}
        lines = [f"# {chat['title']}", ""]
        for t in chat["turns"]:
            when = datetime.fromtimestamp(t["ts"]).strftime("%Y-%m-%d %H:%M:%S") if t["ts"] else ""
            lines += [f"**{t['role']}** {when}", "", t["text"], ""]
        return {"filename": f"voicevibe-{safe}.md", "text": "\n".join(lines)}
