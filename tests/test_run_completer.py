"""Chat REPL autocomplete (_ChatCompleter) unit tests — no TTY needed."""
from prompt_toolkit.document import Document

from maru_lang.commands.run import _ChatCompleter


def _complete(text, teams=()):
    completer = _ChatCompleter(lambda: list(teams))
    doc = Document(text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, None)]


def test_slash_command_completion():
    out = _complete("/in")
    assert "/ingest" in out
    assert all(c.startswith("/in") for c in out)


def test_no_completion_for_plain_text():
    assert _complete("hello") == []


def test_function_options():
    assert set(_complete("/function ")) == {"feedback", "off"}
    assert _complete("/function fe") == ["feedback"]


def test_team_completion_from_current_teams():
    assert set(_complete("/team ", teams=["alpha", "beta"])) == {"alpha", "beta"}
    assert _complete("/team al", teams=["alpha", "beta"]) == ["alpha"]


def test_ingest_path_delegates_to_path_completer(tmp_path):
    (tmp_path / "doc.txt").write_text("x")
    out = _complete(f"/ingest {tmp_path}/")
    assert any("doc.txt" in o for o in out)
