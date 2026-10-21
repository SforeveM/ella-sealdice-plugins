from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps

from .models import Character


_LOCK = threading.Lock()
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def normalize_character_name(value: object) -> str:
    return re.sub(r"[\s·・._\-—]+", "", str(value or "").strip()).casefold()


def normalize_owner_id(value: object) -> str:
    """Normalize a SeaDice account identity without using a display name.

    Official QQ group nicknames are not stable identities.  The caller passes
    the OpenID/uniform ID instead, so this key is deliberately conservative.
    """
    return str(value or "").strip().casefold()


def portrait_archive_dir(pending_root: Path) -> Path:
    configured = os.environ.get("AUTOCARD_PORTRAIT_DIR", "").strip()
    if configured:
        return Path(configured)
    return pending_root.parent / "portraits"


def setpic_portrait_dir(pending_root: Path) -> Path | None:
    """Return the shared portrait folder used by LogAI's ``.setpic`` command.

    An explicit AutoCard setting wins, then LogAI's own setting is honoured when
    both services are launched from the same environment.  For the standard
    SealDice layout we can derive ``<core>/base64-api/portraits`` from
    ``<autocard>/data/pending`` without hard-coding the installation directory.
    """

    configured = (
        os.environ.get("AUTOCARD_SETPIC_DIR", "").strip()
        or os.environ.get("LOGAI_PORTRAIT_DIR", "").strip()
    )
    if configured:
        return Path(configured)

    data_root = pending_root.parent
    if data_root.name.casefold() != "data":
        return None
    return data_root.parent.parent / "base64-api" / "portraits"


def _safe_stem(value: str) -> str:
    value = _INVALID_FILENAME.sub("_", value).strip(" ._")
    return (value or "character")[:80]


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _read_index(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_portrait_index(root: Path, name: str, record: dict, owners: list[str], filename: str) -> None:
    index_path = root / "index.json"
    index = _read_index(index_path)
    name_key = normalize_character_name(name)
    stored = dict(record)
    stored["file"] = filename
    index[name_key] = stored
    for owner in owners:
        index[f"owner:{owner}:{name_key}"] = stored
    _atomic_json(index_path, index)


def _atomic_png(image: Image.Image, target: Path) -> None:
    temporary = target.with_name(target.name + ".tmp")
    image.save(temporary, format="PNG", optimize=True)
    os.replace(temporary, target)


def save_character_portrait(
    character: Character,
    pending_root: Path,
    owner_ids: list[str] | None = None,
) -> dict | None:
    """Persist an imported character portrait after the user confirms recording.

    Pending autocard folders expire quickly, so initiative cards cannot reliably read
    the embedded workbook image from there.  The durable archive keeps its hashed
    copy and index; a second ``<character name>.png`` compatibility copy is written
    to LogAI's shared ``.setpic`` folder so personal-rating cards can use it directly.
    Neither location stores the character sheet itself.
    """

    if not character.portrait or not normalize_character_name(character.name):
        return None

    root = portrait_archive_dir(pending_root)
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(character.portrait).hexdigest()[:16]
    filename = f"{_safe_stem(character.name)}-{digest}.png"
    target = root / filename

    with Image.open(io.BytesIO(character.portrait)) as source:
        normalized = ImageOps.exif_transpose(source).convert("RGBA")
        normalized.thumbnail((1600, 1600), Image.Resampling.LANCZOS)

    owners = []
    for value in owner_ids or []:
        owner = normalize_owner_id(value)
        if owner and owner not in owners:
            owners.append(owner)

    with _LOCK:
        if not target.exists():
            _atomic_png(normalized, target)

        setpic_target: Path | None = None
        setpic_error = ""
        setpic_root = setpic_portrait_dir(pending_root)
        if setpic_root is not None:
            try:
                setpic_root.mkdir(parents=True, exist_ok=True)
                setpic_target = setpic_root / f"{_safe_stem(character.name)}.png"
                # Always replace this file: recording an updated card should also
                # refresh the portrait used by LogAI, comics and other .setpic users.
                _atomic_png(normalized, setpic_target)
            except OSError as exc:
                # The compatibility copy must not make the actual card recording
                # fail when a separately configured shared folder is unavailable.
                setpic_target = None
                setpic_error = str(exc)

        record = {
            "name": character.name,
            "file": filename,
            "rule": character.rule,
            "source_filename": character.source_filename,
            "updated_at": int(time.time()),
            "owner_ids": owners,
        }
        if setpic_target is not None:
            record["setpic_file"] = str(setpic_target)
        if setpic_error:
            record["setpic_error"] = setpic_error
        # Keep a name-only compatibility entry for older readers. New readers
        # prefer the owner+name entry, preventing same-name cards from colliding.
        _write_portrait_index(root, character.name, record, owners, filename)
        if setpic_target is not None and setpic_root is not None and setpic_root != root:
            # The core's .setpic directory is the stable shared location used
            # by the log renderer. Store the same identity metadata beside its
            # compatibility image, so the renderer does not depend on the
            # backend's working directory.
            _write_portrait_index(
                setpic_root,
                character.name,
                record,
                owners,
                setpic_target.name,
            )
        return record
