from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from autocard.models import Character
from autocard.portrait_archive import (
    normalize_character_name,
    save_character_portrait,
    setpic_portrait_dir,
)


class PortraitArchiveTests(unittest.TestCase):
    def test_save_character_portrait(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tmp_path = Path(folder)
            image = Image.new("RGB", (240, 320), "#7aa7d9")
            payload = io.BytesIO()
            image.save(payload, format="PNG")
            pending_root = tmp_path / "pending"
            pending_root.mkdir()
            character = Character(
                source_filename="艾拉.xlsx",
                source_format="XLSX",
                rule="DND5E2014",
                seal_system="dnd5e",
                template_id="test",
                template_name="测试卡",
                layout="DND",
                name="艾拉·诺恩",
                portrait=payload.getvalue(),
                portrait_mime="image/png",
            )

            record = save_character_portrait(character, pending_root)

            self.assertIsNotNone(record)
            archive = tmp_path / "portraits"
            self.assertTrue((archive / record["file"]).is_file())
            index = json.loads((archive / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index[normalize_character_name(character.name)]["name"], character.name)

    def test_save_character_portrait_to_setpic_folder_and_replace(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tmp_path = Path(folder)
            pending_root = tmp_path / "autocard" / "data" / "pending"
            pending_root.mkdir(parents=True)
            setpic_root = tmp_path / "shared-portraits"

            def make_character(color: str) -> Character:
                image = Image.new("RGB", (80, 100), color)
                payload = io.BytesIO()
                image.save(payload, format="PNG")
                return Character(
                    source_filename="艾拉.xlsx",
                    source_format="XLSX",
                    rule="DND5E2014",
                    seal_system="dnd5e",
                    template_id="test",
                    template_name="测试卡",
                    layout="DND",
                    name="艾拉·诺恩",
                    portrait=payload.getvalue(),
                    portrait_mime="image/png",
                )

            with patch.dict(
                "os.environ",
                {"AUTOCARD_SETPIC_DIR": str(setpic_root)},
                clear=False,
            ):
                first = save_character_portrait(make_character("#ff0000"), pending_root)
                second = save_character_portrait(make_character("#0000ff"), pending_root)

            target = setpic_root / "艾拉·诺恩.png"
            self.assertTrue(target.is_file())
            self.assertEqual(first["setpic_file"], str(target))
            self.assertEqual(second["setpic_file"], str(target))
            with Image.open(target) as saved:
                self.assertEqual(saved.convert("RGB").getpixel((0, 0)), (0, 0, 255))

    def test_default_setpic_folder_uses_standard_core_layout(self) -> None:
        pending_root = Path("C:/SealDice/自动读卡绘制角色卡面/data/pending")
        with patch.dict(
            "os.environ",
            {"AUTOCARD_SETPIC_DIR": "", "LOGAI_PORTRAIT_DIR": ""},
            clear=False,
        ):
            self.assertEqual(
                setpic_portrait_dir(pending_root),
                Path("C:/SealDice/base64-api/portraits"),
            )
