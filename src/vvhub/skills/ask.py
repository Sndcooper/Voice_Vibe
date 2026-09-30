"""Spoken answers: "computer, how do I undo a git commit?" (text only, rule 9).

Laya routes a general question here (category chitchat); Gemini writes a
short spoken answer through FreeLLMAPI. Only real questions are answered --
anything else is handed back and typed as heard, so dictation in a session
is never answered instead of typed.
"""

from __future__ import annotations

import re

from ..schemas import Plan, Result
from .base import Skill

_QUESTION = re.compile(
    r"^\s*(?:(?:hey|ok|okay|so|and|but|please|computer)[, ]+)*"
    r"(?:what|what's|whats|who|who's|whom|whose|when|where|why|how|which|can|could|would|should"
    r"|is|are|was|were|do|does|did|will|explain|tell me|define|describe|give me|any idea)\b",
    re.IGNORECASE)

SYSTEM = ("You are Voice Vibe, a voice assistant on the user's Windows laptop. Answer the "
          "question in at most three short spoken sentences: plain words, no markdown, no "
          "lists, no code blocks (say a command name if needed). If you don't know, say so.")


def is_question(text: str) -> bool:
    return text.strip().endswith("?") or bool(_QUESTION.match(text))


class AskSkill(Skill):
    name = "ask"
    category = "chitchat"
    actions = {"answer_question": "answer a general knowledge or how-to question out loud"}

    def __init__(self, llm=None) -> None:  # noqa: ANN001
        super().__init__()
        self._llm = llm

    def _client(self):  # noqa: ANN202
        if self._llm is not None:
            return self._llm
        from .. import llm

        return llm

    async def plan(self, decision, context) -> Plan:  # noqa: ANN001
        question = str((context or {}).get("request") or decision.target or "")
        return Plan(skill=self.name, action="answer_question",
                    args={"question": question, "noop": not is_question(question)})

    async def run(self, plan: Plan, approval=None, dry_run: bool = False) -> Result:  # noqa: ANN001
        question = str(plan.args.get("question") or "").strip()
        if not question or not is_question(question):
            return Result(ok=False, speak=False, data={"handled": False})
        if dry_run:
            return Result(ok=True, text=question, speak=False)
        client = self._client()
        try:
            answer = await client.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
                # Gemini Flash thinks first; thinking counts against max_tokens,
                # and 220 cut answers off after four words.
                max_tokens=1200)
        except Exception as exc:  # noqa: BLE001 - LLMUnavailable carries a spoken line
            return Result(ok=False, text=getattr(exc, "spoken", "I can't answer that right now."))
        answer = re.sub(r"(?im)^\s*(?:draft|answer|final answer)\s*\d*\s*:\s*", "", answer)
        answer = re.sub(r"[*_`#>]+", "", answer).strip()
        return Result(ok=True, text=answer[:700])


SKILL = AskSkill()
