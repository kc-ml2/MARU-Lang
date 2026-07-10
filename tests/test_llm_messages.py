"""Tests for merge_system_messages (Qwen single-leading-system invariant)."""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from maru_lang.core.llm import merge_system_messages


def test_multiple_system_messages_collapse_to_one_at_front():
    msgs = [
        SystemMessage(content="base"),
        SystemMessage(content="memory"),
        HumanMessage(content="q"),
        AIMessage(content="a"),
        SystemMessage(content="style"),
    ]
    out = merge_system_messages(msgs)
    sys = [m for m in out if isinstance(m, SystemMessage)]
    assert len(sys) == 1
    assert out[0] is sys[0]                       # single system leads
    assert sys[0].content == "base\n\nmemory\n\nstyle"
    # non-system messages keep their relative order
    assert [m.content for m in out if not isinstance(m, SystemMessage)] == ["q", "a"]


def test_zero_system_messages_returned_unchanged():
    msgs = [HumanMessage(content="hi")]
    assert merge_system_messages(msgs) is msgs


def test_single_system_message_moved_to_front():
    msgs = [HumanMessage(content="q"), SystemMessage(content="s")]
    out = merge_system_messages(msgs)
    assert isinstance(out[0], SystemMessage) and out[0].content == "s"
    assert out[1].content == "q"


def test_non_string_system_content_left_untouched():
    # Multimodal / structured content must not be corrupted by a str join.
    multimodal = SystemMessage(content=[{"type": "text", "text": "x"}])
    msgs = [multimodal, SystemMessage(content="y"), HumanMessage(content="q")]
    assert merge_system_messages(msgs) is msgs
