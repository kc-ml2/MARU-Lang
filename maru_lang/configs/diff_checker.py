"""
Configuration Diff Checker - Compares user configs with templates
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import yaml

logger = logging.getLogger(__name__)


class ConfigDiffChecker:
    """Checks differences between user configs and template configs"""

    def __init__(self):
        """Initialize diff checker with template and user directories"""
        self.template_dir = Path(__file__).parent.parent / "templates" / "yaml"
        self.user_dir = Path.cwd() / "maru_app"

    def _load_yaml(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Load YAML file safely"""
        try:
            if not file_path.exists():
                return None
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return None

    def _compare_dicts(
        self,
        user_data: Dict[str, Any],
        template_data: Dict[str, Any],
        path: str = ""
    ) -> List[str]:
        """
        Recursively compare two dictionaries and return differences

        Returns list of formatted difference strings
        """
        differences = []

        # Get all keys from both dicts
        all_keys = set(user_data.keys()) | set(template_data.keys())

        for key in sorted(all_keys):
            current_path = f"{path}.{key}" if path else key

            user_value = user_data.get(key)
            template_value = template_data.get(key)

            # Key only in template (new in default)
            if key not in user_data:
                differences.append(
                    f"  + {current_path}: {self._format_value(template_value)} "
                    f"(new in default)"
                )
                continue

            # Key only in user file (removed from default)
            if key not in template_data:
                differences.append(
                    f"  - {current_path}: {self._format_value(user_value)} "
                    f"(removed from default)"
                )
                continue

            # Both have the key - check if values differ
            if isinstance(user_value, dict) and isinstance(template_value, dict):
                # Recursively compare nested dicts
                nested_diffs = self._compare_dicts(
                    user_value, template_value, current_path
                )
                differences.extend(nested_diffs)
            elif user_value != template_value:
                # Values differ
                differences.append(
                    f"  ~ {current_path}: {self._format_value(user_value)} "
                    f"(default: {self._format_value(template_value)})"
                )

        return differences

    def _format_value(self, value: Any, show_keys: bool = True) -> str:
        """
        Format a value for display

        Args:
            value: The value to format
            show_keys: If True, show dict keys for better readability
        """
        if isinstance(value, str):
            # Truncate long strings
            if len(value) > 50:
                return f'"{value[:47]}..."'
            return f'"{value}"'
        elif isinstance(value, dict):
            # Show dict keys for better visibility
            if show_keys and len(value) > 0:
                keys = list(value.keys())
                if len(keys) <= 5:
                    keys_str = ", ".join(str(k) for k in keys)
                    return f"{{dict: {keys_str}}}"
                else:
                    keys_str = ", ".join(str(k) for k in keys[:5])
                    return f"{{dict: {keys_str}, ... ({len(value)} keys total)}}"
            return f"{{dict with {len(value)} keys}}"
        elif isinstance(value, list):
            # Show list length
            return f"[list with {len(value)} items]"
        elif value is None:
            return "null"
        return str(value)

    def check_file(self, filename: str) -> Tuple[bool, List[str]]:
        """
        Check differences for a specific config file

        Returns:
            Tuple of (has_differences, list_of_difference_strings)
        """
        template_path = self.template_dir / filename
        user_path = self.user_dir / filename

        template_data = self._load_yaml(template_path)
        user_data = self._load_yaml(user_path)

        # If template doesn't exist, skip
        if template_data is None:
            return False, []

        # If user file doesn't exist, show all template keys as new
        if user_data is None:
            return True, [f"  ! User file not found (using defaults)"]

        # Compare the two
        differences = self._compare_dicts(user_data, template_data)

        return len(differences) > 0, differences

    def check_file_pair(
        self,
        template_filename: str,
        user_filename: str,
        display_name: str
    ) -> Tuple[bool, List[str]]:
        """
        Check differences between template and user file with different paths

        Args:
            template_filename: Filename in template directory
            user_filename: Filename in user directory (may include subdirectory)
            display_name: Name to display in report

        Returns:
            Tuple of (has_differences, list_of_difference_strings)
        """
        template_path = self.template_dir / template_filename
        user_path = self.user_dir / user_filename

        template_data = self._load_yaml(template_path)
        user_data = self._load_yaml(user_path)

        # If template doesn't exist, skip
        if template_data is None:
            return False, []

        # If user file doesn't exist, skip silently
        if user_data is None:
            return False, []

        # Compare the two
        differences = self._compare_dicts(user_data, template_data)

        return len(differences) > 0, differences

    def check_all_configs(self) -> str:
        """
        Check all configuration files and return formatted report

        Only checks system configs and builtin agent configs for detailed differences.
        User-customizable files (LLMs, custom agents) are not checked.

        Returns:
            Formatted string showing all differences
        """
        # System and component config files to check (detailed comparison)
        system_config_files = [
            # Root level configs
            ("system_config.yaml", "system_config.yaml", "system_config.yaml"),
            ("rag_config.yaml", "rag_config.yaml", "rag_config.yaml"),
            ("agents_build_selector.yaml", "build_selector.yaml", "build_selector.yaml"),

            # Component configs in subdirectories
            ("loader_config.yaml", "loaders/loader_config.yaml", "loaders/loader_config.yaml"),
            ("chunker_config.yaml", "chunkers/chunker_config.yaml", "chunkers/chunker_config.yaml"),
            ("embedder_config.yaml", "embedders/embedder_config.yaml", "embedders/embedder_config.yaml"),
            ("reranker_config.yaml", "rerankers/reranker_config.yaml", "rerankers/reranker_config.yaml"),
        ]

        report_lines = []
        has_any_differences = False

        # Check system configs
        for template_file, user_file, display_name in system_config_files:
            has_diff, differences = self.check_file_pair(template_file, user_file, display_name)

            if has_diff:
                has_any_differences = True
                report_lines.append(f"\n{display_name}:")
                report_lines.extend(differences)

        # Check builtin agent configs
        builtin_diffs = self._check_builtin_agents()
        if builtin_diffs:
            has_any_differences = True
            report_lines.append(f"\n[Builtin Agents]")
            report_lines.extend(builtin_diffs)

        if not has_any_differences:
            return "✓ All configurations match templates (no differences found)"

        header = "Configuration Differences (User vs Default):"
        legend = """
Legend:
  + : New key in default (not in user file)
  - : Key in user file but removed from default
  ~ : Different value between user and default
"""

        return header + "\n" + legend + "\n" + "\n".join(report_lines)

    def _check_builtin_agents(self) -> List[str]:
        """
        Check builtin agent configurations for changes

        Returns:
            List of difference strings for builtin agents
        """
        differences = []
        template_builtin_dir = self.template_dir / "agents"
        user_builtin_dir = self.user_dir / "agents" / "builtin"

        if not template_builtin_dir.exists():
            return differences

        # Find all builtin agent yaml files in template
        for template_file in template_builtin_dir.glob("agents_*.yaml"):
            # Extract agent name (e.g., agents_group_classifier.yaml -> group_classifier.yaml)
            agent_name = template_file.name.replace("agents_", "")
            user_file = user_builtin_dir / agent_name

            template_data = self._load_yaml(template_file)
            user_data = self._load_yaml(user_file)

            # Skip if template doesn't exist or is not builtin type
            if template_data is None:
                continue

            if template_data.get('type') != 'builtin':
                continue

            # Skip if user file doesn't exist
            if user_data is None:
                continue

            # Compare the two
            file_diffs = self._compare_dicts(user_data, template_data)

            if file_diffs:
                differences.append(f"\n  agents/builtin/{agent_name}:")
                differences.extend(f"  {line}" for line in file_diffs)

        return differences


def check_config_differences() -> str:
    """
    Convenience function to check all config differences

    Returns:
        Formatted report string
    """
    checker = ConfigDiffChecker()
    return checker.check_all_configs()
