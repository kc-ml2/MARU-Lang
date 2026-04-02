"""Installation command - initialize project with config and main.py."""
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console

console = Console()


def install_configs(
    path: Optional[Path] = None,
    force: bool = False,
) -> bool:
    """Install maru_config.yaml and main.py.

    Args:
        path: Custom path (default: cwd/maru_app).
        force: Overwrite existing files.

    Returns:
        True if successful.
    """
    base_path = path or (Path.cwd() / "maru_app")
    console.print(f"Installing to: {base_path}")

    try:
        base_path.mkdir(parents=True, exist_ok=True)

        # 1. maru_config.yaml
        _install_template(base_path / "maru_config.yaml", "maru_config.yaml", force)

        # 2. main.py
        main_py = base_path / "main.py"
        if main_py.exists() and not force:
            console.print("  main.py already exists (use --force to overwrite)")
        else:
            template = _get_template_path("python", "main.py")
            if template:
                main_py.write_text(template.read_text())
                console.print("  Created main.py")

        console.print("\nInstallation complete!")
        console.print("\nNext steps:")
        console.print("  1. Edit maru_config.yaml (add LLM API keys, etc.)")
        console.print("  2. Run 'maru serve' to start the server")

        return True

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return False


def _install_template(target: Path, template_name: str, force: bool) -> None:
    """Copy a YAML template to the target path."""
    if target.exists() and not force:
        console.print(f"  {target.name} already exists")
        return

    template = _get_template_path("yaml", template_name)
    if template:
        target.write_text(template.read_text())
        console.print(f"  Created {target.name}")


def _get_template_path(subdir: str, filename: str) -> Optional[Path]:
    """Locate a template file."""
    path = Path(__file__).parent.parent / "templates" / subdir / filename
    return path if path.exists() else None
