from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from .errors import AutocardError
from .extractors import extract_character
from .models import Character
from .ooxml import load_workbook


TOKEN = re.compile(r"^[A-Za-z0-9_-]{24,64}$")


class PendingNotFound(AutocardError):
    pass


class PendingStore:
    def __init__(self, root: str | Path, ttl_seconds: int = 1800) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def create(self, data: bytes, character: Character) -> str:
        token = secrets.token_urlsafe(24)
        folder = self.root / token
        folder.mkdir(parents=False, exist_ok=False)
        (folder / "source.bin").write_bytes(data)
        (folder / "meta.json").write_text(
            json.dumps(
                {
                    "created_at": int(time.time()),
                    "filename": character.source_filename,
                    "character": character.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return token

    def _folder(self, token: str) -> Path:
        if not TOKEN.fullmatch(token):
            raise PendingNotFound("待确认人物卡不存在或已过期")
        folder = self.root / token
        meta = folder / "meta.json"
        if not meta.exists():
            raise PendingNotFound("待确认人物卡不存在或已过期")
        data = json.loads(meta.read_text(encoding="utf-8"))
        if int(time.time()) - int(data.get("created_at", 0)) > self.ttl_seconds:
            raise PendingNotFound("待确认人物卡已过期，请重新上传")
        return folder

    def metadata(self, token: str) -> dict:
        return json.loads((self._folder(token) / "meta.json").read_text(encoding="utf-8"))

    def character(self, token: str) -> Character:
        folder = self._folder(token)
        metadata = self.metadata(token)
        workbook = load_workbook((folder / "source.bin").read_bytes(), metadata["filename"])
        return extract_character(workbook)

    def card_path(self, token: str, index: int = 0) -> Path:
        filename = "card.png" if index == 0 else f"card-pokemon-{index}.png"
        return self._folder(token) / filename

    def review_path(self, token: str) -> Path:
        return self._folder(token) / "review.png"

    def cleanup(self) -> int:
        removed = 0
        now = int(time.time())
        for folder in self.root.iterdir():
            if not folder.is_dir():
                continue
            try:
                metadata = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
                expired = now - int(metadata.get("created_at", 0)) > self.ttl_seconds
            except Exception:
                expired = True
            if not expired:
                continue
            for file in folder.iterdir():
                if file.is_file():
                    file.unlink()
            folder.rmdir()
            removed += 1
        return removed
