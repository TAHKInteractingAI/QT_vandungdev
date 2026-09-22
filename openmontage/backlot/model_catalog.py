"""Load the approved Backlot model catalog from provider-owned JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_CATALOG_DIR = Path(__file__).with_name("model_catalog_data") / "approved"


def _load_models() -> tuple[dict[str, Any], ...]:
    models: list[dict[str, Any]] = []
    for path in sorted(_CATALOG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"model catalog must be a JSON list: {path}")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"model catalog entries must be objects: {path}")
            normalized = dict(item)
            normalized["operations"] = tuple(normalized.get("operations", ()))
            normalized["credential_env"] = tuple(normalized.get("credential_env", ()))
            models.append(normalized)
    if not models:
        raise ValueError(f"no model catalog files found in {_CATALOG_DIR}")
    return tuple(models)


_MODELS = _load_models()


def models_for(operation: str | None = None, *, selectable_only: bool = False) -> list[dict[str, Any]]:
    """Return a JSON-safe catalog filtered by operation and lifecycle."""
    result = []
    for item in _MODELS:
        if operation and operation not in item["operations"]:
            continue
        if selectable_only and not item["selectable"]:
            continue
        result.append({key: list(value) if isinstance(value, tuple) else value for key, value in item.items()})
    return result


def default_model(operation: str) -> str:
    """Return the default selectable model for a public creator operation."""
    for item in _MODELS:
        if operation in item["operations"] and item["selectable"] and item["default"]:
            return str(item["id"])
    raise ValueError(f"unsupported generation operation: {operation}")


def is_selectable(operation: str, model: str) -> bool:
    return any(
        item["id"] == model
        and operation in item["operations"]
        and item["selectable"]
        for item in _MODELS
    )
