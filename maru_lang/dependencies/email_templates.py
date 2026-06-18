"""Email message templates.

Built-in defaults live here as constants. To customize a message without a code
change, drop a file at ``<email_template_dir>/<name>.txt`` (the directory is set
by ``email_template_dir`` in maru_config.yaml). In each file the **first line is
the subject** and the **rest is the body**; if the file is missing the built-in
default is used.

Subject and body are rendered with ``str.format``, so placeholders use braces
and a literal ``{`` must be written as ``{{``. Available placeholders:

  otp           -> {code}
  invitation    -> {team_name}, {inviter_name}
  notification  -> {team_name}, {inviter_name}
"""
from functools import lru_cache
from pathlib import Path
from typing import Optional

# name -> (subject, body). The body may span multiple lines; the subject is one
# line, mirroring the "first line = subject" file format used for overrides.
DEFAULTS: dict[str, tuple[str, str]] = {
    "otp": (
        "{code} - Maru Lang Code",
        "Your verification code is: {code}\n\nThis code expires in 5 minutes.",
    ),
    "invitation": (
        "Maru Lang - {team_name} 팀 초대",
        "{inviter_name}님이 {team_name} 팀에 초대했습니다.\n\n"
        "Maru Lang에 가입하여 팀에 참여하세요.\n"
        "가입 후 자동으로 팀에 소속됩니다.",
    ),
    "notification": (
        "Maru Lang - {team_name} 팀에 추가되었습니다",
        "{inviter_name}님이 {team_name} 팀에 추가했습니다.\n\n"
        "로그인하여 팀을 확인하세요.",
    ),
}


@lru_cache(maxsize=None)
def get_template(name: str, template_dir: Optional[str]) -> tuple[str, str]:
    """Return ``(subject, body)`` for ``name``.

    If ``<template_dir>/<name>.txt`` exists, its first line is the subject and
    everything after the first newline is the body. Otherwise the built-in
    default from :data:`DEFAULTS` is returned.

    Results are cached per ``(name, template_dir)``; edits to a template file
    take effect on the next process restart.
    """
    if template_dir:
        path = Path(template_dir) / f"{name}.txt"
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            subject, _, body = text.partition("\n")
            return subject.strip(), body.strip("\n")
    return DEFAULTS[name]
