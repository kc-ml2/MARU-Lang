"""Tests for `maru install` (install_configs).

Guards two things that together make email-template overrides actually usable
in an installed environment:

1. install_configs() copies the bundled `*.txt.example` files into
   <target>/templates/email/.
2. pyproject.toml ships those examples as package-data — otherwise the wheel/sdist
   omits them and step 1 finds nothing to copy.
"""
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for older interpreters
    import tomli as tomllib

from maru_lang.commands.install import install_configs

REPO_ROOT = Path(__file__).resolve().parent.parent
EMAIL_TEMPLATE_SRC = REPO_ROOT / "maru_lang" / "templates" / "email"


def test_install_copies_email_examples(tmp_path):
    target = tmp_path / "maru_app"
    assert install_configs(path=target, force=True) is True

    installed = sorted(p.name for p in (target / "templates" / "email").glob("*.txt.example"))
    expected = sorted(p.name for p in EMAIL_TEMPLATE_SRC.glob("*.txt.example"))

    assert expected, "no bundled email examples found to copy"
    assert installed == expected


def test_install_is_idempotent_without_force(tmp_path):
    target = tmp_path / "maru_app"
    install_configs(path=target, force=True)

    example = next((target / "templates" / "email").glob("*.txt.example"))
    example.write_text("CUSTOM EDIT", encoding="utf-8")

    # Re-running without --force must not clobber an operator's edits.
    install_configs(path=target, force=False)
    assert example.read_text(encoding="utf-8") == "CUSTOM EDIT"


def test_email_examples_are_declared_as_package_data():
    """Every bundled email example must be matched by a package-data glob,
    so it ships in the wheel/sdist and install_configs() can find it."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["maru_lang"]

    for example in EMAIL_TEMPLATE_SRC.glob("*.txt.example"):
        rel = example.relative_to(REPO_ROOT / "maru_lang")
        assert any(_matches(rel, pat) for pat in patterns), (
            f"{rel} is not covered by any package-data pattern in pyproject.toml; "
            f"it will be missing from the built package."
        )


def _matches(rel: Path, pattern: str) -> bool:
    """setuptools package-data globs treat '**' as 'any number of dirs'.

    PurePath.match doesn't span separators with '**', so collapse a leading
    'templates/**/' to match files at any depth under templates/.
    """
    posix = rel.as_posix()
    if pattern.startswith("templates/**/"):
        suffix = pattern[len("templates/**/"):]
        return posix.startswith("templates/") and Path(posix).match(suffix)
    return Path(posix).match(pattern)
