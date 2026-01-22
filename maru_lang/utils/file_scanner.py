from pathlib import Path
from typing import List


def scan_directory(path: Path, recursive: bool = True) -> List[Path]:
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    if recursive:
        files = sorted([f for f in path.rglob("*") if f.is_file()])
    else:
        files = sorted([f for f in path.glob("*") if f.is_file()])

    return files
