from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps


DEFAULT_ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets"


def asset_root() -> Path:
    configured = os.getenv("AUTOCARD_ASSET_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ASSET_ROOT.resolve()


@lru_cache(maxsize=1)
def _icon_map() -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for filename in ("generated-icon-map.json", "icon-map.json"):
        path = asset_root() / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        for category, values in payload.items():
            if isinstance(values, dict):
                merged.setdefault(category, {}).update({str(key): str(value) for key, value in values.items()})
    return merged


def icon_path(category: str, name: object) -> Path | None:
    value = str(name or "").strip()
    category_map = _icon_map().get(category, {})
    relative = category_map.get(value)
    if not relative:
        candidates = [part.strip() for part in re.split(r"\s+[—–]\s+|\s*\|\s*", value) if part.strip()]
        for candidate in (candidates[0:1] + candidates[-1:]):
            relative = category_map.get(candidate)
            if relative:
                break
    if not relative and category in {"item", "weapon", "armor", "feat", "feature"}:
        for label in sorted(category_map, key=len, reverse=True):
            if label and label in value:
                relative = category_map[label]
                break
    if not relative:
        relative = category_map.get("__default__")
    if not relative:
        return None
    root = asset_root()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() and candidate.suffix.lower() == ".png" else None


@lru_cache(maxsize=512)
def _load_icon(category: str, name: str, size: int) -> Image.Image | None:
    path = icon_path(category, name)
    if not path:
        return None
    try:
        with Image.open(path) as source:
            icon = source.convert("RGBA")
            return ImageOps.contain(icon, (size, size), method=Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None


def load_icon(category: str, name: object, size: int) -> Image.Image | None:
    icon = _load_icon(category, str(name or "").strip(), size)
    return icon.copy() if icon else None
