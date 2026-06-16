from pathlib import Path
from typing import List

from maru_lang.constants import SUPPORTED_EXTENSIONS


def scan_directory(path: Path, recursive: bool = True) -> List[Path]:
    """Collect ingestible files under a directory.

    Only files with a supported extension are returned; hidden files (dotfiles
    like .DS_Store) and unsupported formats are skipped so junk never reaches
    the upload/embed pipeline.
    """
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    entries = path.rglob("*") if recursive else path.glob("*")
    files = [
        f for f in entries
        if f.is_file()
        and not f.name.startswith(".")
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files)
