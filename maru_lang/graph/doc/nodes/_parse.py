"""Shared JSON parsing for LLM canvas output (mirrors rag memory._parse_items)."""
import json
import re


def parse_json_array(text: str) -> list[dict]:
    """Robustly parse a JSON array from LLM output (tolerates fences/extra text)."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def parse_json_object(text: str) -> dict:
    """Robustly parse a JSON object from LLM output (tolerates fences/extra text)."""
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
