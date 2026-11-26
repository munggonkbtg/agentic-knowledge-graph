"""All LLM calls go through this module (M4 step 4).

* Runtime: a local Ollama server (`config.yaml` llm section). No key is needed;
  a runtime that needs one would read it from an environment variable.
* Output: JSON constrained by a JSON schema (Ollama structured outputs) and
  validated with pydantic. Invalid JSON is retried `max_retries` times, then
  returned as a failure; a failure is never written to the graph.
* Cache: SQLite keyed by (content hash, prompt version + prompt file hash,
  model). Every real call logs tokens in / out, seconds and attempts.
* Thinking is switched off (`think: false`); a reply that still carries thinking
  text is counted (`thinking_chars`) so it can be reported.

Only the standard library is used for HTTP, so no new dependency.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kg.config import LLMSettings

EntityTypeName = Literal["Concept", "Role", "Artifact", "Body", "Place", "Other"]


class ExtractedMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: EntityTypeName
    term: str = Field(min_length=1, max_length=200)


class MentionList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mentions: list[ExtractedMention]


class ImpactVerdict(BaseModel):
    """M5 step 13: the checker's answer for one (change, candidate) pair."""

    model_config = ConfigDict(extra="forbid")
    verdict: Literal["needs_update", "not_affected", "unsure"]
    reason: str = Field(max_length=600)
    evidence: str = Field(max_length=600)  # quoted from the candidate passage


@dataclass
class CallResult:
    mentions: list[ExtractedMention] | None  # None = failure after all retries
    attempts: int = 0
    valid_first: bool = False
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    thinking_chars: int = 0
    errors: list[str] = field(default_factory=list)
    data: BaseModel | None = None  # the validated reply


# A transport takes the request body and returns Ollama's /api/chat response.
Transport = Callable[[dict], dict]


def ollama_transport(settings: LLMSettings) -> Transport:
    url = settings.endpoint.rstrip("/") + "/api/chat"

    def send(body: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=settings.timeout_seconds) as r:
            return json.loads(r.read().decode("utf-8"))

    return send


class LLMClient:
    def __init__(self, settings: LLMSettings, root: Path = Path("."),
                 transport: Transport | None = None) -> None:
        self.s = settings
        prompt = (root / settings.prompt_file).read_text(encoding="utf-8")
        self.system_prompt = prompt
        self.prompt_key = f"{settings.prompt_version}#{_sha(prompt)[:12]}"
        self.transport = transport or ollama_transport(settings)
        path = root / settings.cache_file
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS calls (content_hash TEXT, prompt TEXT, model TEXT, "
            "response TEXT, tokens_in INTEGER, tokens_out INTEGER, seconds REAL, "
            "attempts INTEGER, valid_first INTEGER, thinking_chars INTEGER, created TEXT, "
            "PRIMARY KEY (content_hash, prompt, model))")
        self.log: list[CallResult] = []

    def close(self) -> None:
        self.db.close()

    def _body(self, user_content: str, schema: type[BaseModel]) -> dict:
        return {"model": self.s.model, "stream": False, "think": self.s.think,
                "format": schema.model_json_schema(), "keep_alive": "10m",
                "options": {"num_ctx": self.s.num_ctx, "temperature": self.s.temperature},
                "messages": [{"role": "system", "content": self.system_prompt},
                             {"role": "user", "content": user_content}]}

    def _ask(self, key_text: str, user_content: str, schema: type[BaseModel],
             use_cache: bool) -> CallResult:
        """One validated call (cached by key_text, prompt and model). The parsed
        reply is in CallResult.data; None after all retries failed."""
        key = (_sha(key_text), self.prompt_key, self.s.model)
        if use_cache:
            row = self.db.execute(
                "SELECT response, tokens_in, tokens_out, seconds, attempts, valid_first, "
                "thinking_chars FROM calls WHERE content_hash=? AND prompt=? AND model=?",
                key).fetchone()
            if row:
                res = CallResult(None, row[4], bool(row[5]), True, row[1], row[2], row[3],
                                 row[6], data=schema.model_validate_json(row[0]))
                self.log.append(res)
                return res
        res = CallResult(None)
        start = time.time()
        for attempt in range(1, self.s.max_retries + 2):
            res.attempts = attempt
            try:
                reply = self.transport(self._body(user_content, schema))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                res.errors.append(f"transport: {type(e).__name__}")
                continue
            res.tokens_in += int(reply.get("prompt_eval_count") or 0)
            res.tokens_out += int(reply.get("eval_count") or 0)
            msg = reply.get("message") or {}
            res.thinking_chars += len(msg.get("thinking") or "")
            try:
                res.data = schema.model_validate_json(msg.get("content") or "")
            except ValidationError as e:
                res.errors.append(f"invalid: {e.error_count()} error(s)")
                continue
            res.valid_first = attempt == 1
            break
        res.seconds = time.time() - start
        if res.data is not None and use_cache:
            self.db.execute(
                "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (*key, res.data.model_dump_json(), res.tokens_in, res.tokens_out, res.seconds,
                 res.attempts, int(res.valid_first), res.thinking_chars))
            self.db.commit()
        self.log.append(res)
        return res

    def extract_mentions(self, text: str, use_cache: bool = True) -> CallResult:
        res = self._ask(text, f"Passage:\n{text}", MentionList, use_cache)
        res.mentions = res.data.mentions if res.data is not None else None
        return res

    def check_impact(self, old_text: str, new_text: str, candidate: str, context: str,
                     use_cache: bool = True) -> CallResult:
        """M5 step 13: does `candidate` need updating after old_text became new_text?
        CallResult.data is an ImpactVerdict (None after failed retries)."""
        user = (f"CHANGED PASSAGE ({context})\nOLD:\n{old_text or '(none: the passage was added)'}"
                f"\nNEW:\n{new_text or '(none: the passage was removed)'}\n\n"
                f"CANDIDATE PASSAGE:\n{candidate}")
        return self._ask(user, user, ImpactVerdict, use_cache)

    @classmethod
    def for_check(cls, settings: LLMSettings, root: Path = Path("."),
                  transport: Transport | None = None) -> LLMClient:
        """A client with the impact-check prompt and its context size."""
        s = settings.model_copy(update={"prompt_file": settings.check_prompt_file,
                                        "prompt_version": settings.check_prompt_version,
                                        "num_ctx": settings.check_num_ctx})
        return cls(s, root, transport)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
