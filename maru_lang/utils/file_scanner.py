from pathlib import Path
from typing import List

from maru_lang.graph.ingest.loader.langchain import is_supported


def scan_directory(path: Path, recursive: bool = True) -> List[Path]:
    """Collect ingestible files under a directory.

    Only files with a supported extension are returned; hidden files (dotfiles
    like .DS_Store) and unsupported formats are skipped so junk never reaches
    the upload/embed pipeline. Platform-aware: .doc is only offered when
    doc2txt/antiword is available on this platform.
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
        and is_supported(f)
    ]
    return sorted(files)
