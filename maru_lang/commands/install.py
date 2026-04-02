"""
Installation command - Initialize configuration directories and sample files
"""
import os
import shutil
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

console = Console()


def create_config_directories(base_path: Path, force: bool = False) -> bool:
    """
    Create configuration directories and sample files

    Args:
        base_path: Base directory to create config folders in
        force: If True, overwrite existing files

    Returns:
        True if successful
    """
    try:
        # Ensure base_path exists first
        base_path.mkdir(parents=True, exist_ok=True)

        # Configuration directories to create
        config_dirs = ['llms']

        # Create root-level config files first
        # 1. maru_config.yaml (unified configuration)
        maru_config_path = base_path / "maru_config.yaml"
        if not maru_config_path.exists() or force:
            maru_config_content = get_sample_content("maru_config")
            if maru_config_content:
                maru_config_path.write_text(maru_config_content)
                console.print(f"  ✅ Created maru_config.yaml")

        # 2. build_selector.yaml
        build_selector_path = base_path / "build_selector.yaml"
        if not build_selector_path.exists() or force:
            build_selector_content = get_sample_content("agents_build_selector")
            if build_selector_content:
                build_selector_path.write_text(build_selector_content)
                console.print(f"  ✅ Created build_selector.yaml")

        # 3. rag_config.yaml (replaces group_config.yaml)
        rag_config_path = base_path / "rag_config.yaml"
        if not rag_config_path.exists() or force:
            rag_config_content = get_sample_content("rag_config")
            if rag_config_content:
                rag_config_path.write_text(rag_config_content)
                console.print(f"  ✅ Created rag_config.yaml")

        for dir_name in config_dirs:
            dir_path = base_path / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)

            # Create sample files based on directory
            if dir_name == "llms":
                # Create sample LLM config files with .sample extension
                for sample_file in ["openai.yaml.sample", "local.yaml.sample"]:
                    sample_path = dir_path / sample_file
                    if not sample_path.exists() or force:
                        base_name = sample_file.replace('.yaml.sample', '')
                        sample_content = get_sample_content(
                            f"llms_{base_name}")
                        sample_path.write_text(sample_content)
                        console.print(f"  ✅ Created {dir_name}/{sample_file}")
            elif dir_name == "embedders":
                # Create embedder_config.yaml
                config_path = dir_path / "embedder_config.yaml"
                if not config_path.exists() or force:
                    config_content = get_sample_content("embedders_config")
                    config_path.write_text(config_content)
                    console.print(f"  ✅ Created {dir_name}/embedder_config.yaml")
            elif dir_name == "rerankers":
                # Create reranker_config.yaml
                config_path = dir_path / "reranker_config.yaml"
                if not config_path.exists() or force:
                    config_content = get_sample_content("rerankers_config")
                    config_path.write_text(config_content)
                    console.print(f"  ✅ Created {dir_name}/reranker_config.yaml")

                # Create example LLM reranker agent files
                llm_reranker_py = dir_path / "llm_reranker.py"
                if not llm_reranker_py.exists() or force:
                    py_content = get_sample_content("rerankers_llm_py")
                    if py_content:
                        llm_reranker_py.write_text(py_content)
                        console.print(f"  ✅ Created {dir_name}/llm_reranker.py")

                llm_reranker_yaml = dir_path / "llm_reranker.yaml"
                if not llm_reranker_yaml.exists() or force:
                    yaml_content = get_sample_content("rerankers_llm_yaml")
                    if yaml_content:
                        llm_reranker_yaml.write_text(yaml_content)
                        console.print(f"  ✅ Created {dir_name}/llm_reranker.yaml (auto-registered as agent)")
            elif dir_name == "agents":
                # Dynamically discover agent templates (including builtin)
                agent_templates = discover_agent_templates()

                # Create subdirectories for agent types (mcps and builtin)
                subdirs = {'mcps', 'builtin'}
                for subdir in subdirs:
                    subdir_path = dir_path / subdir
                    subdir_path.mkdir(parents=True, exist_ok=True)

                # Create agent configuration files
                for agent_info in agent_templates['yaml']:
                    if agent_info['target_subdir']:
                        target_dir = dir_path / agent_info['target_subdir']
                        target_dir.mkdir(parents=True, exist_ok=True)
                        sample_path = target_dir / agent_info['output_name']
                        relative_path = f"{dir_name}/{agent_info['target_subdir']}/{agent_info['output_name']}"
                    else:
                        sample_path = dir_path / agent_info['output_name']
                        relative_path = f"{dir_name}/{agent_info['output_name']}"

                    if not sample_path.exists() or force:
                        sample_content = get_sample_content_from_path(
                            agent_info['template_path'])
                        if sample_content:
                            sample_path.write_text(sample_content)
                            console.print(f"  ✅ Created {relative_path}")

                # Create Python implementation files for agents
                for agent_info in agent_templates['python']:
                    if agent_info['target_subdir']:
                        target_dir = dir_path / agent_info['target_subdir']
                        target_dir.mkdir(parents=True, exist_ok=True)
                        py_path = target_dir / agent_info['output_name']
                        relative_path = f"{dir_name}/{agent_info['target_subdir']}/{agent_info['output_name']}"
                    else:
                        py_path = dir_path / agent_info['output_name']
                        relative_path = f"{dir_name}/{agent_info['output_name']}"

                    if not py_path.exists() or force:
                        py_content = get_sample_content_from_path(
                            agent_info['template_path'])
                        if py_content:
                            py_path.write_text(py_content)
                            console.print(f"  ✅ Created {relative_path}")

        # Create main.py
        main_py = base_path / "main.py"
        if main_py.exists() and not force:
            console.print(
                f"[red]❌ Error: main.py already exists. Use --force to overwrite.[/red]")
            return False
        else:
            main_py.write_text(get_main_py_content())
            console.print(f"  ✅ Created main.py")

        return True

    except Exception as e:
        console.print(f"[red]❌ Error creating directories: {e}[/red]")
        return False


def get_readme_content(dir_name: str) -> str:
    """Get README content for each configuration directory"""
    template_dir = Path(__file__).parent.parent / "templates" / "readme"

    template_map = {
        "llms": "llms.md",
        "agents": "agents.md",
        "loaders": "parsers.md",  # Reuse parsers.md content for loaders
        "chunkers": "chunkers.md",
        "embedders": "embedders.md"
    }

    if not template_dir.exists():
        console.print(
            "[yellow]⚠️ Warning: README template directory is missing. Skipping README content.[/yellow]"
        )
        return ""

    if dir_name in template_map:
        template_file = template_dir / template_map[dir_name]
        if template_file.exists():
            return template_file.read_text()

    return ""


def discover_agent_templates():
    """Dynamically discover all agent templates and organize by type (excluding builtin)"""
    import yaml as yaml_lib

    template_base = Path(__file__).parent.parent / "templates"
    yaml_dir = template_base / "yaml" / "agents"
    python_dir = template_base / "python"

    result = {
        'yaml': [],
        'python': []
    }

    # Discover YAML agent templates
    for yaml_file in yaml_dir.rglob("agents_*.yaml"):
        try:
            # Read YAML to get agent type
            with open(yaml_file, 'r', encoding='utf-8') as f:
                agent_config = yaml_lib.safe_load(f)

            agent_type = agent_config.get('type', '')
            agent_name = yaml_file.name.replace("agents_", "")

            # Determine target directory based on agent type
            if agent_type == 'builtin':
                # Builtin agents go to agents/builtin/
                target_subdir = 'builtin'
            elif agent_type == 'mcp_client':
                target_subdir = 'mcps'
            else:  # All other types - place directly in agents/
                target_subdir = ''

            result['yaml'].append({
                'template_path': yaml_file,
                'output_name': agent_name,
                'agent_type': agent_type,
                'target_subdir': target_subdir
            })
        except Exception as e:
            console.print(f"[yellow]⚠️ Warning: Could not parse {yaml_file}: {e}[/yellow]")
            continue

    # Discover Python agent implementations
    # Match Python files with their corresponding YAML configs to get correct type
    # Create a mapping from Python filename to agent type from YAML configs
    yaml_to_type_map = {}
    for yaml_agent in result['yaml']:
        # Extract agent name from yaml filename (e.g., "response.yaml" -> "response")
        yaml_name = yaml_agent['output_name'].replace('.yaml', '')
        yaml_to_type_map[yaml_name] = yaml_agent['agent_type']

    # Look for specific patterns that indicate agent implementations
    # Excluding builtin agents
    python_patterns = [
        "*_agent.py",  # calculator_agent.py, etc.
        "knowledge_search.py",
    ]

    # Builtin agent files to skip (now in core/agents/builtin/)
    builtin_files = {
        'group_classifier.py',
        'intent_extractor.py',
        'keyword_extractor.py',
        'response_agent.py',
        'knowledge_search.py',
    }

    for pattern in python_patterns:
        for py_file in python_dir.glob(pattern):
            # Skip __init__.py, main.py, and builtin agent files
            if py_file.name in ['__init__.py', 'main.py'] or py_file.name in builtin_files:
                continue

            # Extract agent name from Python filename
            # e.g., "response_agent.py" -> "response", "knowledge_search.py" -> "knowledge_search"
            agent_name = py_file.stem.replace('_agent', '')

            # Try to match with YAML config to get correct type
            agent_type = yaml_to_type_map.get(agent_name, '')

            # Skip builtin types (shouldn't happen but safety check)
            if agent_type == 'builtin':
                continue

            # Determine target directory based on agent type
            if agent_type == 'mcp_client':
                target_subdir = 'mcps'
            else:
                target_subdir = ''  # Place directly in agents/

            result['python'].append({
                'template_path': py_file,
                'output_name': py_file.name,
                'agent_type': agent_type,
                'target_subdir': target_subdir
            })

    return result


def get_sample_content_from_path(template_path: Path) -> str:
    """Get content from a template file path"""
    try:
        if template_path.exists():
            return template_path.read_text()
    except Exception as e:
        console.print(
            f"[yellow]⚠️ Warning: Could not read {template_path}: {e}[/yellow]")
    return ""


def get_sample_content(content_type: str) -> str:
    """Get sample YAML content for each configuration type (legacy method for non-agent files)"""
    # Determine template directory based on content type
    if content_type.startswith("loaders_") or content_type.startswith("chunkers_") or content_type.startswith("embedders_") or content_type.startswith("rerankers_"):
        # Handle loaders/chunkers/embedders/rerankers specific files
        if content_type in ["loaders_config", "chunkers_config", "embedders_config", "rerankers_config"]:
            # YAML config files from templates/yaml
            template_dir = Path(__file__).parent.parent / "templates" / "yaml"
            template_map = {
                "loaders_config": "loader_config.yaml",
                "chunkers_config": "chunker_config.yaml",
                "embedders_config": "embedder_config.yaml",
                "rerankers_config": "reranker_config.yaml",
            }
            template_file = template_dir / template_map[content_type]
            if template_file.exists():
                return template_file.read_text()
        elif content_type in ["rerankers_llm_py", "rerankers_llm_yaml"]:
            # Reranker agent examples from templates/
            if content_type == "rerankers_llm_py":
                template_dir = Path(__file__).parent.parent / "templates" / "python"
                template_file = template_dir / "llm_reranker.py"
            else:  # rerankers_llm_yaml
                template_dir = Path(__file__).parent.parent / "templates" / "yaml"
                template_file = template_dir / "llm_reranker.yaml"

            if template_file.exists():
                return template_file.read_text()
        else:
            # Python files from templates/python
            template_dir = Path(__file__).parent.parent / "templates" / "python"
            template_map = {
            }
            if content_type in template_map:
                template_file = template_dir / template_map[content_type]
                if template_file.exists():
                    return template_file.read_text()
    else:
        template_dir = Path(__file__).parent.parent / "templates" / "yaml"
        template_map = {
            "llms_openai": "openai.yaml",
            "llms_local": "local.yaml",
            "rag_config": "rag_config.yaml",
            "agents_build_selector": "agents_build_selector.yaml",
            "maru_config": "maru_config.yaml",
        }
        if content_type in template_map:
            template_file = template_dir / template_map[content_type]
            if template_file.exists():
                return template_file.read_text()

    return ""


def get_main_py_content() -> str:
    """Get main.py content"""
    template_file = Path(__file__).parent.parent / "templates" / "python" / "main.py"
    if template_file.exists():
        return template_file.read_text()
    raise FileNotFoundError(f"main.py not found in {template_file}")


def get_main_readme_content() -> str:
    """Get main README content"""
    template_file = Path(__file__).parent.parent / "templates" / "readme" / "main.md"
    if template_file.exists():
        return template_file.read_text()
    console.print(
        "[yellow]⚠️ Warning: main README template not found. Generating minimal README.[/yellow]"
    )
    return "# README\n\nThis file was generated automatically by the install command.\n"


def install_configs(
    path: Optional[Path] = None,
    force: bool = False,
) -> bool:
    """
    Install configuration directories and sample files

    Args:
        path: Custom path for configs (default: current directory/maru_app)
        force: Overwrite existing files

    Returns:
        True if successful
    """
    # Determine target path
    if path:
        base_path = path
        console.print(f"📁 Installing to: {base_path}")
    else:
        base_path = Path.cwd() / "maru_app"
        console.print(f"📁 Installing to: {base_path}")

    # Create configuration directories
    console.print("\n🔧 Creating configuration directories...")
    success = create_config_directories(base_path, force)

    if success:
        console.print("\n✨ Installation complete!")
        console.print("\n📋 Next steps:")
        console.print(
            "1. Copy the sample.yaml.example files and rename to .yaml")
        console.print(
            "2. Configure your LLM servers, prompts, groups, and tools")
        console.print("3. Run 'maru status' to check your setup")
        console.print("4. Start the server with 'maru serve'")
        console.print(
            "\n💡 The main.py file has been created in maru_app/ for you to customize!")
    else:
        console.print(
            "\n❌ Installation failed. Please check the errors above.")

    return success
