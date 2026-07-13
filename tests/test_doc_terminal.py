"""Terminal doc edit-loop helpers — canvas diffing, edit-command parsing.

The interactive doc graph runs entirely in the terminal now (no browser bridge):
each canvas version is diffed against the last and edit commands are parsed at the
prompt. These cover the pure helpers behind that loop.
"""
from maru_lang.commands.run import (
    _canvas_block_texts,
    _parse_edit_command,
    _render_canvas,
)


def _canvas(*blocks):
    """A one-section canvas from (block_id, text) pairs."""
    return {
        "title": "계약서",
        "sections": [
            {
                "section_id": "s1",
                "title": "본문",
                "blocks": [{"block_id": bid, "text": txt} for bid, txt in blocks],
            }
        ],
    }


def test_block_texts_flattens_sections():
    canvas = _canvas(("b1", "가"), ("b2", "나"))
    assert _canvas_block_texts(canvas) == {"b1": "가", "b2": "나"}


def test_block_texts_empty_canvas():
    assert _canvas_block_texts({}) == {}


# ── _parse_edit_command ──

def test_parse_edit():
    assert _parse_edit_command("edit b3 더 공손하게") == {
        "op": "edit", "block_id": "b3", "feedback": "더 공손하게",
    }


def test_parse_delete_and_reorder():
    assert _parse_edit_command("delete b2") == {"op": "delete", "block_id": "b2"}
    assert _parse_edit_command("reorder b1, b3 ,b2") == {
        "op": "reorder", "order": ["b1", "b3", "b2"],
    }


def test_parse_add_with_and_without_after():
    assert _parse_edit_command("add after b1 새 조항") == {
        "op": "add", "after_block_id": "b1", "content": "새 조항",
    }
    assert _parse_edit_command("add 끝에 붙는 조항") == {
        "op": "add", "after_block_id": None, "content": "끝에 붙는 조항",
    }


def test_parse_empty_and_unknown_default_to_finalize():
    assert _parse_edit_command("") == {"op": "finalize"}
    assert _parse_edit_command("finalize") == {"op": "finalize"}
    assert _parse_edit_command("bogus xyz") == {"op": "finalize"}


# ── _render_canvas diff markers ──

def _render(canvas, prev):
    """Render to a string via a temporary rich Console capture."""
    from maru_lang.commands import run as run_mod
    from rich.console import Console

    original = run_mod.console
    buf = Console(record=True, width=100)
    run_mod.console = buf
    try:
        _render_canvas(canvas, prev)
        return buf.export_text()
    finally:
        run_mod.console = original


def test_render_first_pass_has_no_diff_markers():
    out = _render(_canvas(("b1", "가"), ("b2", "나")), None)
    assert "＋" not in out and "~" not in out
    assert "b1" in out and "b2" in out


def test_render_marks_added_edited_and_removed():
    prev = _canvas(("b1", "가"), ("b2", "나"))
    curr = _canvas(("b1", "가"), ("b3", "다"))  # b2 removed, b3 added, b1 same
    out = _render(curr, prev)
    assert "＋" in out          # b3 is new
    assert "삭제됨" in out and "b2" in out
