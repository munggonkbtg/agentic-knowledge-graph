"""LLM client and fallback with a fake transport (no model, no server)."""

import json
from pathlib import Path

import pytest

from kg.config import LLMSettings
from kg.layer2_entities import EntityRegistry, LLMFallback, occurs_in
from kg.llm import LLMClient, MentionList

ROOT = Path(__file__).resolve().parents[1]


def _reply(content, thinking="", tin=50, tout=10):
    return {"message": {"content": content, "thinking": thinking},
            "prompt_eval_count": tin, "eval_count": tout}


class Fake:
    """Returns the queued replies in order and records the requests."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, body):
        self.requests.append(body)
        return self.replies.pop(0)


def _client(tmp_path, fake, **kw):
    s = LLMSettings(cache_file=tmp_path / "llm.sqlite", prompt_file=ROOT / "prompts/mentions_v1.md",
                    **kw)
    return LLMClient(s, root=ROOT, transport=fake)


def test_request_uses_schema_no_thinking_and_short_context(tmp_path):
    fake = Fake(_reply('{"mentions": []}'))
    _client(tmp_path, fake).extract_mentions("text")
    body = fake.requests[0]
    assert body["think"] is False and body["stream"] is False
    assert body["format"] == MentionList.model_json_schema()
    assert body["options"]["num_ctx"] == 2048 and body["options"]["temperature"] == 0.0


def test_invalid_json_is_retried_then_recorded_as_failure(tmp_path):
    ok = json.dumps({"mentions": [{"type": "Role", "term": "manager"}]})
    c = _client(tmp_path, Fake(_reply("not json"), _reply(ok)))
    res = c.extract_mentions("your manager")
    assert res.attempts == 2 and not res.valid_first and res.mentions[0].term == "manager"
    assert res.tokens_in == 100 and res.tokens_out == 20
    bad = _client(tmp_path, Fake(*[_reply('{"mentions": [{"type": "Person"}]}')] * 3))
    res = bad.extract_mentions("something else")
    assert res.mentions is None and res.attempts == 3 and len(res.errors) == 3


def test_cache_by_content_prompt_and_model(tmp_path):
    ok = json.dumps({"mentions": [{"type": "Concept", "term": "sabbatical"}]})
    fake = Fake(_reply(ok), _reply(ok), _reply(ok))
    c = _client(tmp_path, fake)
    c.extract_mentions("a sabbatical")
    again = c.extract_mentions("a sabbatical")
    assert again.cached and len(fake.requests) == 1
    c.extract_mentions("a sabbatical", use_cache=False)  # stability rerun bypasses it
    assert len(fake.requests) == 2
    other = _client(tmp_path, fake, model="another-model")
    assert not other.extract_mentions("a sabbatical").cached


def test_thinking_text_is_counted(tmp_path):
    c = _client(tmp_path, Fake(_reply('{"mentions": []}', thinking="let me think")))
    assert c.extract_mentions("x").thinking_chars == len("let me think")


@pytest.mark.parametrize("term,text,lang,ok", [
    ("short-term disability", "file a Short Term Disability claim", "en", True),
    ("manager", "your managers", "en", False),  # whole words only
    ("the program", "this policy", "en", False),
    ("ค่าชดเชย", "ให้จ่ายค่า ชดเชย[๓] แก่ลูกจ้าง", "th", True),
    ("ค่าชดเชยพิเศษ", "ให้จ่ายค่าชดเชย", "th", False),
])
def test_terms_must_occur_in_the_block(term, text, lang, ok):
    assert occurs_in(term, text, lang) is ok


def test_fallback_links_known_aliases_and_keeps_new_terms_apart(tmp_path):
    reg = EntityRegistry()
    known = reg.add("Sabbatical", "Concept", "en", "heading:x")
    reply = json.dumps({"mentions": [
        {"type": "Concept", "term": "sabbatical"},   # registry alias -> existing entity
        {"type": "Role", "term": "People Ops"},      # new -> LLM-sourced entity
        {"type": "Artifact", "term": "Airtable"},    # not in the text -> dropped
        {"type": "Other", "term": "onboarding"}]})   # Other -> counted, not linked
    text = "Ask People Ops about onboarding before your sabbatical."
    fb = LLMFallback(reg, _client(tmp_path, Fake(_reply(reply))), max_entities=0)
    ids = fb.entities_for(text, "en", registry_entities=set())
    assert ids == {known.entity_id, "llm:role:en:people-ops"}
    e = fb.new_entities["llm:role:en:people-ops"]
    assert e.entity_type == "Role" and e.sources == {"llm:qwen3.5:4b-q4_K_M"}
    st = fb.stats
    assert (st.returned, st.dropped, st.other, st.linked_existing, st.new_terms) == (4, 1, 1, 1, 1)
    assert known.entity_id not in fb.new_entities  # never merged into the registry entity


def test_threshold_decides_which_blocks_go_to_the_llm(tmp_path):
    fake = Fake()
    fb = LLMFallback(EntityRegistry(), _client(tmp_path, fake), max_entities=0)
    assert fb.entities_for("text", "en", registry_entities={"concept:en:x"}) == set()
    assert fake.requests == [] and fb.stats.blocks_called == 0
    assert not LLMFallback(EntityRegistry(), None, max_entities=None).needs_llm(0)
