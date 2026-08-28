"""Built-in and filesystem-overridable email messages."""
from functools import lru_cache
from pathlib import Path

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
def get_template(name: str, template_dir: Path | None) -> tuple[str, str]:
    if template_dir:
        path = template_dir / f"{name}.txt"
        if path.is_file():
            subject, separator, body = path.read_text(encoding="utf-8").partition("\n")
            if separator and subject.strip() and body.strip():
                return subject.strip(), body.strip("\n")
    return DEFAULTS[name]
