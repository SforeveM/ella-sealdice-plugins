from __future__ import annotations

import io
import hashlib
import math
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .assets import load_icon
from .extractors import DND_SKILL_ALIASES, DND_SKILL_PARENTS
from .models import Character


WIDTH = 1600
MARGIN = 70
CARD_WIDTH = WIDTH - MARGIN * 2
BACKGROUND = "#F3F0E8"
INK = "#20242A"
MUTED = "#667085"
WHITE = "#FFFFFF"
DND = "#8F2938"
COC = "#245B59"
POKEMON = "#C43B3B"
POKEMON_BLUE = "#315E9E"
HEALTH = "#2F8F4E"
HEALTH_LIGHT = "#DCEFE1"
DND_GOLD = "#D6B267"


def _portrait_fit(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Crop a character portrait with an upper-body bias for tall artwork."""
    width, height = source.size
    aspect = height / max(1, width)
    if aspect <= 1.1:
        vertical_focus = 0.5
    else:
        vertical_focus = max(0.08, 0.34 - (aspect - 1.1) * 0.48)
    return ImageOps.fit(
        source,
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, vertical_focus),
    )


def _font_path(*, bold: bool = False) -> str | None:
    candidates = (
        os.getenv("AUTOCARD_FONT", ""),
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else "",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    return next((path for path in candidates if path and Path(path).exists()), None)


FONT_PATH = _font_path()
FONT_BOLD_PATH = _font_path(bold=True)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_BOLD_PATH if bold else FONT_PATH
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _lines(draw: ImageDraw.ImageDraw, text: str, face, width: int, max_lines: int | None = None) -> list[str]:
    text = str(text or "").replace("\r", "")
    result: list[str] = []
    for paragraph in text.split("\n") or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textlength(candidate, font=face) > width:
                result.append(current)
                current = char
            else:
                current = candidate
        result.append(current)
    result = result or [""]
    if max_lines and len(result) > max_lines:
        result = result[:max_lines]
        result[-1] = result[-1][:-1] + "…"
    return result


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str = WHITE, outline: str = "#D7D4CC", radius: int = 28) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


class Flow:
    def __init__(self, character: Character) -> None:
        self.character = character
        self.accent = COC if character.rule == "COC7" else (POKEMON if character.rule == "POKEMON-TRPG" else DND)
        self.image = Image.new("RGB", (WIDTH, 20000), BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self.y = 0

    def icon_chip(self, category: str, name: object, x: int, y: int, size: int = 44, *, header: bool = False) -> bool:
        icon = load_icon(category, name, size - 8)
        if icon is None:
            return False
        fill = "#762330" if header else "#F7EFE8"
        outline = DND_GOLD if header else "#D8B9AC"
        self.draw.ellipse((x, y, x + size, y + size), fill=fill, outline=outline, width=2)
        icon_x = x + (size - icon.width) // 2
        icon_y = y + (size - icon.height) // 2
        self.image.paste(icon, (icon_x, icon_y), icon)
        return True

    def header(self) -> None:
        header_height = 400
        self.draw.rectangle((0, 0, WIDTH, header_height), fill=self.accent)
        if self.character.rule not in {"COC7", "POKEMON-TRPG"}:
            # A subtle d20 watermark keeps the base theme D&D-like before custom art is supplied.
            center = (WIDTH - 185, 195)
            radius = 145
            points = [
                (center[0] + math.cos(-math.pi / 2 + index * math.tau / 10) * radius,
                 center[1] + math.sin(-math.pi / 2 + index * math.tau / 10) * radius)
                for index in range(10)
            ]
            self.draw.polygon(points, outline="#A94A58", width=5)
            for index in range(0, 10, 2):
                self.draw.line((points[index], center, points[(index + 3) % 10]), fill="#A94A58", width=3)
            self.draw.line((MARGIN + 300, 340, WIDTH - MARGIN, 340), fill=DND_GOLD, width=3)
        self.y = 48
        portrait_box = (MARGIN, 54, MARGIN + 250, 304)
        mask = Image.new("L", (250, 250), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 249, 249), fill=255)
        if self.character.portrait:
            try:
                source = Image.open(io.BytesIO(self.character.portrait)).convert("RGB")
                source = _portrait_fit(source, (250, 250))
            except Exception:
                source = Image.new("RGB", (250, 250), "#D9DEE6")
        else:
            source = Image.new("RGB", (250, 250), "#E4D7D9" if self.accent == DND else "#CFE0DF")
            initials = (self.character.name[:2] or "PC").upper()
            temp = ImageDraw.Draw(source)
            bbox = temp.textbbox((0, 0), initials, font=font(68))
            temp.text(((250 - (bbox[2] - bbox[0])) / 2, (250 - (bbox[3] - bbox[1])) / 2 - 8), initials, font=font(68), fill=self.accent)
        self.image.paste(source, portrait_box[:2], mask)
        self.draw.ellipse(portrait_box, outline=WHITE, width=9)
        title_x = MARGIN + 300
        alignment = self.character.identity.get("阵营", "") if self.character.rule not in {"COC7", "POKEMON-TRPG"} else ""
        display_name = self.character.name + ((" · " + alignment) if alignment else "")
        name_width = WIDTH - title_x - MARGIN - (250 if self.character.rule not in {"COC7", "POKEMON-TRPG"} else 0)
        name_lines = _lines(self.draw, display_name, font(64, bold=True), name_width, 2)
        self.draw.multiline_text((title_x, 58), "\n".join(name_lines), font=font(64, bold=True), fill=WHITE, spacing=8)
        if self.character.rule not in {"COC7", "POKEMON-TRPG"}:
            identity_line = " · ".join(filter(None, (
                self.character.identity.get("职业", ""), self.character.identity.get("子职", ""),
                self.character.identity.get("等级", ""),
            )))
            if identity_line:
                identity_x = title_x
                for category, key in (("class", "职业"), ("subclass", "子职")):
                    value = self.character.identity.get(key, "")
                    if value and self.icon_chip(category, value, identity_x, 166, 48, header=True):
                        identity_x += 58
                self.draw.text((identity_x, 176), identity_line, font=font(35, bold=True), fill="#FFF2D5")
        rule_label = (
            "COC 7th 调查员" if self.character.rule == "COC7"
            else ("门版宝可梦TRPG · 训练家与同行伙伴" if self.character.rule == "POKEMON-TRPG"
                  else ("D&D 5E 2024" if self.character.rule.endswith("2024") else "D&D 5E 2014"))
        )
        self.draw.text((title_x, 238), rule_label, font=font(34, bold=True), fill="#F8EDEF")
        self.draw.text((title_x, 292), self.character.template_name, font=font(25), fill="#F0DADD" if self.accent == DND else "#D7ECEA")
        if self.character.rule not in {"COC7", "POKEMON-TRPG"}:
            proficiency = self.character.attributes.get("熟练", 0)
            badge_x = WIDTH - MARGIN - 186
            self.draw.text((badge_x, 61), "熟练加值", font=font(27, bold=True), fill="#F6DFAE")
            proficiency_text = f"{proficiency:+g}" if isinstance(proficiency, (int, float)) else str(proficiency)
            bbox = self.draw.textbbox((0, 0), proficiency_text, font=font(84, bold=True))
            self.draw.text((badge_x + 72 - (bbox[2] - bbox[0]) / 2, 102), proficiency_text, font=font(84, bold=True), fill=WHITE)
        self.y = header_height + 45

    def section_title(self, title: str) -> None:
        self.draw.rounded_rectangle((MARGIN, self.y, MARGIN + 13, self.y + 48), radius=6, fill=self.accent)
        self.draw.text((MARGIN + 30, self.y - 4), title, font=font(40, bold=True), fill=INK)
        self.y += 70

    def identity(self) -> None:
        self.section_title("人物档案")
        items = [(key, value) for key, value in self.character.identity.items() if value and key != "阵营"]
        if self.character.player:
            items.insert(0, ("玩家", self.character.player))
        if not items:
            items = [("资料", "未填写")]
        columns = 3
        cell_w = (CARD_WIDTH - 24) // columns
        rows = (len(items) + columns - 1) // columns
        height = rows * 104 + 28
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height))
        for index, (key, value) in enumerate(items):
            row, column = divmod(index, columns)
            x = MARGIN + 24 + column * cell_w
            y = self.y + 20 + row * 104
            self.draw.text((x, y), key, font=font(26, bold=True), fill=MUTED)
            self.draw.text((x, y + 39), str(value)[:24], font=font(34, bold=True), fill=INK)
        self.y += height + 34

    def attributes(self) -> None:
        self.section_title("核心属性")
        if self.character.rule == "COC7":
            keys = ["外貌", "体质", "敏捷", "教育", "智力", "幸运", "意志", "体型", "力量"]
        elif self.character.rule == "POKEMON-TRPG":
            keys = ["力量", "体魄", "智识", "意念", "机敏", "魅力", "幸运"]
        else:
            keys = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
        cols = 3 if len(keys) == 9 else (7 if self.character.rule == "POKEMON-TRPG" else 6)
        gap = 16
        box_w = (CARD_WIDTH - gap * (cols - 1)) // cols
        rows = (len(keys) + cols - 1) // cols
        row_h = 148
        for index, key in enumerate(keys):
            row, column = divmod(index, cols)
            x = MARGIN + column * (box_w + gap)
            y = self.y + row * row_h
            _rounded(self.draw, (x, y, x + box_w, y + 128), fill=WHITE, radius=22)
            icon_size = 48 if box_w >= 220 else 44
            has_icon = self.icon_chip("attribute", key, x + 14, y + 52, icon_size)
            self.draw.text((x + 18, y + 12), key, font=font(28, bold=True), fill=MUTED)
            value = self.character.attributes.get(key, 0)
            value_x = x + (72 if has_icon else 18)
            self.draw.text((value_x, y + 48), str(value), font=font(56, bold=True), fill=self.accent)
        self.y += rows * row_h + 18
        if self.character.rule == "POKEMON-TRPG":
            self._pokemon_trainer_vitals()
            return
        if self.character.rule != "COC7":
            self._dnd_combat_vitals(keys)
            return
        vitals = [(key.upper(), value) for key, value in self.character.attributes.items() if key not in keys]
        if vitals:
            text = "   ".join(f"{key} {value}" for key, value in vitals[:12])
            _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + 78), fill="#FAFAF8")
            self.draw.text((MARGIN + 24, self.y + 18), text, font=font(30, bold=True), fill=INK)
            self.y += 108

    def _pokemon_trainer_vitals(self) -> None:
        hp = self.character.attributes.get("hp", 0)
        hpmax = self.character.attributes.get("hpmax", 0)
        hp_number = float(hp) if isinstance(hp, (int, float)) else 0
        hpmax_number = float(hpmax) if isinstance(hpmax, (int, float)) else 0
        ratio = max(0.0, min(1.0, hp_number / hpmax_number)) if hpmax_number > 0 else 0
        height = 156
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height), fill="#FCFCF9", radius=26)
        self.draw.text((MARGIN + 28, self.y + 18), "训练家体力", font=font(28, bold=True), fill=MUTED)
        self.draw.text((MARGIN + 220, self.y + 8), f"{hp} / {hpmax}", font=font(48, bold=True), fill=HEALTH)
        bar = (MARGIN + 28, self.y + 80, MARGIN + 760, self.y + 126)
        self.draw.rounded_rectangle(bar, radius=23, fill=HEALTH_LIGHT, outline="#A4CFAE", width=2)
        if ratio > 0:
            self.draw.rounded_rectangle((bar[0], bar[1], bar[0] + max(46, int((bar[2] - bar[0]) * ratio)), bar[3]), radius=23, fill=HEALTH)
        for index, (label, key, color) in enumerate((
            ("旅行点 TP", "旅行点", POKEMON_BLUE),
            ("物资点 IP", "物资点", "#B47B20"),
        )):
            x = MARGIN + 850 + index * 285
            self.draw.text((x, self.y + 22), label, font=font(25, bold=True), fill=MUTED)
            self.draw.text((x, self.y + 62), str(self.character.attributes.get(key, 0)), font=font(57, bold=True), fill=color)
        self.y += height + 34

    def _dnd_combat_vitals(self, ability_keys: list[str]) -> None:
        height = 190
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height), fill="#FCFCF9", radius=26)
        hp = self.character.attributes.get("hp", 0)
        hpmax = self.character.attributes.get("hpmax", 0)
        hp_number = float(hp) if isinstance(hp, (int, float)) else 0.0
        hpmax_number = float(hpmax) if isinstance(hpmax, (int, float)) else 0.0
        ratio = max(0.0, min(1.0, hp_number / hpmax_number)) if hpmax_number > 0 else 0.0
        hp_x = MARGIN + 28
        hp_width = 690
        self.draw.text((hp_x, self.y + 20), "生命值  HP", font=font(29, bold=True), fill=MUTED)
        hp_text = f"{hp:g} / {hpmax:g}" if isinstance(hp, (int, float)) and isinstance(hpmax, (int, float)) else f"{hp} / {hpmax}"
        self.draw.text((hp_x + 205, self.y + 5), hp_text, font=font(50, bold=True), fill=HEALTH)
        bar_box = (hp_x, self.y + 88, hp_x + hp_width, self.y + 136)
        self.draw.rounded_rectangle(bar_box, radius=24, fill=HEALTH_LIGHT, outline="#A4CFAE", width=2)
        fill_width = int(hp_width * ratio)
        if fill_width > 0:
            self.draw.rounded_rectangle((bar_box[0], bar_box[1], bar_box[0] + max(48, fill_width), bar_box[3]), radius=24, fill=HEALTH)
        self.draw.text((hp_x, self.y + 145), f"当前 HP {hp}    最大 HP {hpmax}", font=font(22), fill=MUTED)

        def circle_badge(center_x: int, label: str, value: object) -> None:
            center_y = self.y + 91
            self.draw.ellipse((center_x - 73, center_y - 73, center_x + 73, center_y + 73), fill=WHITE, outline=self.accent, width=7)
            self.draw.text((center_x - 25, center_y - 59), label, font=font(26, bold=True), fill=MUTED)
            value_text = str(value)
            value_face = font(57, bold=True)
            bbox = self.draw.textbbox((0, 0), value_text, font=value_face)
            self.draw.text((center_x - (bbox[2] - bbox[0]) / 2, center_y - 20), value_text, font=value_face, fill=self.accent)

        circle_badge(MARGIN + 835, "AC", self.character.attributes.get("ac", 0))
        circle_badge(MARGIN + 1015, "DC", self.character.attributes.get("dc", 0))
        extras = [("先攻", self.character.attributes.get("先攻", 0)), ("被动察觉", self.character.attributes.get("pp", 0))]
        extra_x = MARGIN + 1120
        for index, (label, value) in enumerate(extras):
            y = self.y + 32 + index * 72
            self.draw.text((extra_x, y), label, font=font(24, bold=True), fill=MUTED)
            value_text = f"{value:+g}" if label == "先攻" and isinstance(value, (int, float)) else str(value)
            self.draw.text((extra_x + 135, y - 9), value_text, font=font(42, bold=True), fill=INK)
        self.y += height + 34

    def alignment(self) -> None:
        if self.character.rule == "COC7":
            return
        self.section_title("阵营九宫格")
        alignment = self.character.identity.get("阵营", "")
        cells = (("守序善良", "中立善良", "混乱善良"), ("守序中立", "绝对中立", "混乱中立"), ("守序邪恶", "中立邪恶", "混乱邪恶"))
        cell_w = CARD_WIDTH // 3
        cell_h = 74
        for row in range(3):
            for column in range(3):
                x = MARGIN + column * cell_w
                y = self.y + row * cell_h
                label = cells[row][column]
                selected = alignment and (alignment in label or label in alignment or (alignment == "中立" and label == "绝对中立"))
                self.draw.rounded_rectangle((x + 5, y + 5, x + cell_w - 5, y + cell_h - 5), radius=16,
                                            fill=self.accent if selected else WHITE, outline="#D7D4CC", width=2)
                face = font(28 if selected else 25)
                bbox = self.draw.textbbox((0, 0), label, font=face)
                self.draw.text((x + (cell_w - (bbox[2] - bbox[0])) / 2, y + 20), label, font=face, fill=WHITE if selected else INK)
        self.y += 248

    def skills(self) -> None:
        title = "技能" if self.character.rule in {"COC7", "POKEMON-TRPG"} else "技能与熟练"
        self.section_title(title)
        items = list(self.character.skills.items())
        if not items:
            items = [("未填写", "—")]
        columns = 2
        rows = (len(items) + columns - 1) // columns
        row_h = 82
        height = rows * row_h + 24
        col_gap = 18
        col_w = (CARD_WIDTH - col_gap) // columns
        for index, (name, value) in enumerate(items):
            column = index // rows
            row = index % rows
            x = MARGIN + column * (col_w + col_gap)
            y = self.y + row * row_h
            display = f"{value:+g}" if isinstance(value, (int, float)) and self.character.rule != "COC7" else str(value)
            factor, parent = self._skill_proficiency(name)
            proficient = self.character.rule not in {"COC7", "POKEMON-TRPG"} and factor >= 1
            expertise = self.character.rule not in {"COC7", "POKEMON-TRPG"} and factor >= 2
            fill = "#F1EAF8" if expertise else ("#FFF3D2" if proficient else WHITE)
            outline = "#8560A8" if expertise else (DND_GOLD if proficient else "#D7D4CC")
            self.draw.rounded_rectangle((x, y, x + col_w, y + 70), radius=20, fill=fill, outline=outline, width=3 if proficient else 2)
            name_x = x + 16
            if self.icon_chip("skill", name, x + 12, y + 9, 52):
                name_x += 62
            self.draw.text((name_x, y + 11), str(name)[:16], font=font(31, bold=True), fill=INK)
            if parent:
                tag = "专精" if expertise else ("熟练" if proficient else parent)
                tag_color = "#68438C" if expertise else ("#936B16" if proficient else MUTED)
                self.draw.text((name_x, y + 44), tag, font=font(19, bold=proficient), fill=tag_color)
            value_face = font(39, bold=True)
            value_box = self.draw.textbbox((0, 0), display, font=value_face)
            value_w = value_box[2] - value_box[0]
            self.draw.text((x + col_w - value_w - 20, y + 12), display, font=value_face, fill=self.accent)
        self.y += height + 34

    def pokemon_roster(self) -> None:
        self.section_title(f"同行宝可梦 · {len(self.character.pokemon)} 只")
        for companion in self.character.pokemon:
            start = self.y
            card_x1, card_x2 = MARGIN, WIDTH - MARGIN
            portrait_size = 300
            top_height = 350
            _rounded(self.draw, (card_x1, start, card_x2, start + top_height), fill="#FFFDF8", outline="#D6C7B8", radius=30)
            portrait_box = (card_x1 + 24, start + 24, card_x1 + 24 + portrait_size, start + 24 + portrait_size)
            mask = Image.new("L", (portrait_size, portrait_size), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, portrait_size - 1, portrait_size - 1), radius=34, fill=255)
            try:
                source = Image.open(io.BytesIO(companion.portrait)).convert("RGB") if companion.portrait else Image.new("RGB", (portrait_size, portrait_size), "#E7E8EC")
                source = ImageOps.fit(source, (portrait_size, portrait_size), method=Image.Resampling.LANCZOS)
            except Exception:
                source = Image.new("RGB", (portrait_size, portrait_size), "#E7E8EC")
            self.image.paste(source, portrait_box[:2], mask)
            self.draw.rounded_rectangle(portrait_box, radius=34, outline=POKEMON_BLUE, width=5)

            info_x = card_x1 + 355
            self.draw.text((info_x, start + 24), companion.name, font=font(50, bold=True), fill=INK)
            subtitle = " · ".join(filter(None, (companion.species, companion.gender, "/".join(companion.types))))
            self.draw.text((info_x, start + 88), subtitle, font=font(28, bold=True), fill=POKEMON_BLUE)
            detail = "  ".join(filter(None, (
                f"特性 {companion.ability}" if companion.ability else "",
                f"携带 {companion.held_item}" if companion.held_item else "",
                f"羁绊 {companion.bond:g}" if isinstance(companion.bond, (int, float)) else "",
            )))
            self.draw.text((info_x, start + 132), detail, font=font(25), fill=MUTED)
            self.draw.text((info_x, start + 178), f"HP {companion.hp}/{companion.hpmax}    EP {companion.ep if companion.ep is not None else '—'}", font=font(34, bold=True), fill=HEALTH)

            stats = list(companion.stats.items())
            stat_x, stat_y = info_x, start + 235
            stat_w = 166
            for index, (name, value) in enumerate(stats[:6]):
                x = stat_x + index * stat_w
                self.draw.text((x, stat_y), name, font=font(21, bold=True), fill=MUTED)
                self.draw.text((x, stat_y + 30), str(value), font=font(35, bold=True), fill=self.accent)
            self.y = start + top_height + 18

            if companion.moves:
                rows = (len(companion.moves) + 1) // 2
                col_gap = 16
                col_w = (CARD_WIDTH - col_gap) // 2
                move_h = 116
                for index, move in enumerate(companion.moves):
                    row, column = divmod(index, 2)
                    x = MARGIN + column * (col_w + col_gap)
                    y = self.y + row * (move_h + 10)
                    self.draw.rounded_rectangle((x, y, x + col_w, y + move_h), radius=18, fill=WHITE, outline="#D9DDE5", width=2)
                    self.draw.text((x + 18, y + 12), move.name, font=font(29, bold=True), fill=INK)
                    tags = " · ".join(filter(None, (move.element, move.category, move.range)))
                    self.draw.text((x + 18, y + 52), tags, font=font(21, bold=True), fill=POKEMON_BLUE)
                    mechanics = "  ".join(filter(None, (
                        f"命中 {move.accuracy}" if move.accuracy else "",
                        f"威力 {move.damage}" if move.damage else "",
                        f"EP {move.ep_cost:g}" if isinstance(move.ep_cost, (int, float)) else "",
                    )))
                    self.draw.text((x + 18, y + 82), mechanics, font=font(20), fill=MUTED)
                self.y += rows * (move_h + 10) + 12

            if companion.features:
                feature_text = "\n".join(f"• {value}" for value in dict.fromkeys(companion.features))
                lines = _lines(self.draw, feature_text, font(23), CARD_WIDTH - 52, 8)
                feature_h = len(lines) * 36 + 34
                _rounded(
                    self.draw,
                    (MARGIN, self.y, WIDTH - MARGIN, self.y + feature_h),
                    fill="#FFF8E8",
                    outline="#E0C98C",
                    radius=22,
                )
                self.draw.multiline_text(
                    (MARGIN + 26, self.y + 17),
                    "\n".join(lines),
                    font=font(23),
                    fill=INK,
                    spacing=6,
                )
                self.y += feature_h + 14

            if companion.backstory:
                lines = _lines(self.draw, companion.backstory, font(25), CARD_WIDTH - 52, 10)
                story_h = len(lines) * 39 + 34
                _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + story_h), fill="#F8FAFD", outline="#CBD8EA", radius=24)
                self.draw.multiline_text((MARGIN + 26, self.y + 17), "\n".join(lines), font=font(25), fill=INK, spacing=7)
                self.y += story_h + 18
            self.y += 30

    def _skill_proficiency(self, name: object) -> tuple[float, str]:
        skill_name = DND_SKILL_ALIASES.get(str(name), str(name))
        formula = str(self.character.skill_formulas.get(skill_name, ""))
        match = re.search(r"pbCalc\([^,]*,\s*([0-9.]+)\s*,\s*([^,)]+)", formula)
        if match:
            try:
                factor = float(match.group(1))
            except ValueError:
                factor = 0.0
            return factor, match.group(2).strip()
        parent = DND_SKILL_PARENTS.get(skill_name, "")
        value = self.character.skills.get(str(name))
        score = self.character.attributes.get(parent)
        proficiency = self.character.attributes.get("熟练")
        if not parent or not isinstance(value, (int, float)) or not isinstance(score, (int, float)):
            return 0.0, parent
        base = math.floor((float(score) - 10) / 2)
        if isinstance(proficiency, (int, float)) and float(proficiency) > 0:
            factor = (float(value) - base) / float(proficiency)
            if abs(factor - 2) < 0.15:
                return 2.0, parent
            if abs(factor - 1) < 0.15:
                return 1.0, parent
        return 0.0, parent

    def icon_list_section(self, title: str, values: list[str], *, category: str, columns: int = 2) -> None:
        self.section_title(title)
        values = values or ["—"]
        rows = (len(values) + columns - 1) // columns
        row_h = 84
        height = max(94, rows * row_h + 28)
        col_w = (CARD_WIDTH - 48) // columns
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height))
        for index, value in enumerate(values):
            column = index // rows
            row = index % rows
            x = MARGIN + 24 + column * col_w
            y = self.y + 18 + row * row_h
            text_x = x
            if self.icon_chip(category, value, x, y - 2, 58):
                text_x += 70
            lines = _lines(self.draw, str(value), font(31, bold=True), col_w - (text_x - x) - 24, 2)
            self.draw.multiline_text((text_x, y + 5), "\n".join(lines), font=font(31, bold=True), fill=INK, spacing=5)
        self.y += height + 34

    def mixed_icon_section(self, title: str, values: list[tuple[str, str]], *, columns: int = 1) -> None:
        self.section_title(title)
        rows = (len(values) + columns - 1) // columns
        row_h = 88
        height = max(98, rows * row_h + 20)
        col_w = (CARD_WIDTH - 48) // columns
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height))
        for index, (category, value) in enumerate(values):
            column = index // rows
            row = index % rows
            x = MARGIN + 24 + column * col_w
            y = self.y + 16 + row * row_h
            text_x = x + (70 if self.icon_chip(category, value, x, y - 3, 58) else 0)
            lines = _lines(self.draw, value, font(31, bold=True), col_w - (text_x - x) - 24, 2)
            self.draw.multiline_text((text_x, y + 4), "\n".join(lines), font=font(31, bold=True), fill=INK, spacing=5)
        self.y += height + 34

    def detail_section(self, title: str, values: list[str], *, category: str, max_desc_lines: int = 5) -> None:
        self.section_title(title)
        cards: list[tuple[str, list[str]]] = []
        body_face = font(30)
        for raw in values:
            text = str(raw).strip()
            name, separator, description = text.partition(" — ")
            if not separator:
                name, separator, description = text.partition("—")
            if not separator:
                name, description = text, ""
            lines = _lines(self.draw, description, body_face, CARD_WIDTH - 150, max_desc_lines) if description else []
            cards.append((name.strip(), lines))
        total = sum(max(88, 70 + len(lines) * 41) for _, lines in cards) + 24
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + max(100, total)), fill="#FFFDF8")
        cursor = self.y + 18
        for index, (name, lines) in enumerate(cards):
            item_h = max(88, 70 + len(lines) * 41)
            self.icon_chip(category, name, MARGIN + 22, cursor + 5, 60)
            self.draw.text((MARGIN + 96, cursor + 5), name, font=font(34, bold=True), fill=INK)
            if lines:
                self.draw.multiline_text((MARGIN + 96, cursor + 49), "\n".join(lines), font=body_face, fill="#3E4650", spacing=9)
            if index < len(cards) - 1:
                self.draw.line((MARGIN + 96, cursor + item_h - 8, WIDTH - MARGIN - 24, cursor + item_h - 8), fill="#E5DED3", width=2)
            cursor += item_h
        self.y += max(100, total) + 34

    def list_section(self, title: str, values: list[str], *, columns: int = 1, max_item_lines: int = 8) -> None:
        self.section_title(title)
        values = values or ["—"]
        col_w = (CARD_WIDTH - 48) // columns
        face = font(26)
        wrapped: list[list[str]] = []
        for value in values:
            wrapped.append(_lines(self.draw, "• " + str(value), face, col_w - 22, max_item_lines))
        column_lines = [[] for _ in range(columns)]
        heights = [0] * columns
        for item in wrapped:
            target = min(range(columns), key=lambda i: heights[i])
            column_lines[target].extend(item + [""])
            heights[target] += len(item) + 1
        max_lines = max(heights) if heights else 1
        height = max(88, max_lines * 39 + 28)
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height))
        for column, lines in enumerate(column_lines):
            self.draw.multiline_text((MARGIN + 24 + column * col_w, self.y + 18), "\n".join(lines), font=face, fill=INK, spacing=8)
        self.y += height + 34

    def weapons(self) -> None:
        values: list[tuple[str, str]] = []
        for weapon in self.character.weapons:
            pieces = [weapon.name]
            if weapon.skill:
                pieces.append(weapon.skill)
            if weapon.value is not None:
                pieces.append(str(weapon.value))
            if weapon.damage:
                pieces.append("伤害 " + weapon.damage)
            if weapon.notes:
                pieces.append(weapon.notes)
            values.append(("weapon", " | ".join(pieces)))
        if self.character.armor:
            values.extend(("armor", "护甲 | " + item) for item in self.character.armor)
        self.mixed_icon_section("武器与护甲", values, columns=1)

    def story(self) -> None:
        self.section_title("角色背景")
        text = self.character.backstory or "—"
        face = font(30)
        lines = _lines(self.draw, text, face, CARD_WIDTH - 54, 24)
        height = max(108, len(lines) * 47 + 38)
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height), fill="#FFFDF8")
        self.draw.multiline_text((MARGIN + 26, self.y + 20), "\n".join(lines), font=face, fill=INK, spacing=10)
        self.y += height + 36

    def footer(self) -> None:
        self.draw.text((MARGIN, self.y), f"由一键录卡生成 · {self.character.source_filename}", font=font(22), fill=MUTED)
        self.y += 70

    def finish(self) -> Image.Image:
        return self.image.crop((0, 0, WIDTH, min(self.y, self.image.height)))


class CompactSheet:
    """A dark, table-side reference sheet inspired by VTT character panels."""

    BG = "#101118"
    HEADER = "#171821"
    PANEL = "#1B1D27"
    PANEL_ALT = "#232631"
    LINE = "#353844"
    TEXT = "#F5F2EA"
    SUBTLE = "#AEB2BE"
    DIM = "#777C89"
    PROF = "#D7B86D"
    EXPERT = "#B98AE6"
    GOOD = "#42A663"
    GOOD_DARK = "#203D2B"

    def __init__(self, character: Character, *, variant_offset: int = 0) -> None:
        self.character = character
        self.accent = COC if character.rule == "COC7" else (POKEMON if character.rule == "POKEMON-TRPG" else DND)
        self.accent_light = "#76B9B5" if character.rule == "COC7" else ("#72A7E8" if character.rule == "POKEMON-TRPG" else DND_GOLD)
        if character.rule == "POKEMON-TRPG":
            self.BG = "#F1EBDD"
            self.HEADER = "#FFFDF4"
            self.PANEL = "#FFFDF4"
            self.PANEL_ALT = "#CCFF00"
            self.LINE = "#0A0A0C"
            self.TEXT = "#0A0A0C"
            self.SUBTLE = "#303038"
            self.DIM = "#67636B"
            self.accent_light = "#006FE8"
        self.image = Image.new("RGB", (WIDTH, 12000), self.BG)
        self.background_variant = self._place_background(variant_offset)
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.y = 0

    def _place_background(self, variant_offset: int) -> int:
        if self.character.rule == "COC7":
            prefix = "coc-glass"
            veil = (4, 12, 24, 75)
        elif self.character.rule == "POKEMON-TRPG":
            prefix = "pokemon-brutal"
            veil = (255, 255, 255, 0)
        else:
            prefix = "dnd-epic"
            veil = (5, 6, 12, 105)
        digest = hashlib.sha256(
            f"{self.character.rule}|{self.character.source_filename}".encode("utf-8")
        ).digest()
        variant = (digest[0] + variant_offset) % 3 + 1
        path = Path(__file__).resolve().parent.parent / "assets" / "backgrounds" / f"{prefix}-{variant:02d}.jpg"
        if path.exists():
            try:
                source = Image.open(path).convert("RGB")
                background = ImageOps.fit(source, (WIDTH, 2800), method=Image.Resampling.LANCZOS)
                self.image.paste(background, (0, 0))
                if veil[3]:
                    overlay = Image.new("RGBA", (WIDTH, 2800), veil)
                    self.image.paste(overlay, (0, 0), overlay)
            except Exception:
                pass
        return variant

    @staticmethod
    def _number(value: object, *, signed: bool = False) -> str:
        if isinstance(value, (int, float)):
            return f"{value:+g}" if signed else f"{value:g}"
        return str(value if value not in (None, "") else "—")

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    def _panel(self, box: tuple[int, int, int, int], *, fill: str | None = None, outline: str | None = None, radius: int = 18) -> None:
        if self.character.rule == "POKEMON-TRPG":
            x1, y1, x2, y2 = box
            self.draw.rectangle((x1 + 8, y1 + 8, x2 + 8, y2 + 8), fill=(10, 10, 12, 235))
            self.draw.rectangle(box, fill=fill or (255, 253, 244, 248), outline=outline or self.LINE, width=4)
            return
        panel_fill = fill or ((20, 31, 44, 178) if self.character.rule == "COC7" else (18, 19, 28, 220))
        panel_outline = outline or ((166, 202, 211, 115) if self.character.rule == "COC7" else (104, 92, 76, 185))
        self.draw.rounded_rectangle(box, radius=radius, fill=panel_fill, outline=panel_outline, width=2)

    def _panel_title(self, x: int, y: int, width: int, title: str, subtitle: str = "") -> int:
        if self.character.rule == "POKEMON-TRPG":
            self.draw.rectangle((x, y, x + width, y + 58), fill="#CCFF00", outline=self.LINE, width=4)
            self.draw.rectangle((x, y, x + 12, y + 58), fill="#FF1978")
        else:
            title_fill = (29, 45, 61, 170) if self.character.rule == "COC7" else (35, 36, 47, 230)
            self.draw.rounded_rectangle((x, y, x + width, y + 58), radius=16, fill=title_fill)
            self.draw.rectangle((x, y + 17, x + 8, y + 43), fill=self.accent_light)
        self.draw.text((x + 24, y + 11), title, font=font(29, bold=True), fill=self.TEXT)
        if subtitle:
            face = font(19)
            box = self.draw.textbbox((0, 0), subtitle, font=face)
            self.draw.text((x + width - (box[2] - box[0]) - 20, y + 19), subtitle, font=face, fill=self.DIM)
        return y + 66

    def _icon(self, category: str, name: object, x: int, y: int, size: int = 38) -> int:
        icon = load_icon(category, name, size)
        if icon is None:
            return 0
        self.draw.ellipse((x, y, x + size + 8, y + size + 8), fill="#282A34", outline=self.LINE, width=1)
        self.image.paste(icon, (x + 4 + (size - icon.width) // 2, y + 4 + (size - icon.height) // 2), icon)
        return size + 16

    def _portrait(self, data: bytes | None, box: tuple[int, int, int, int], *, circular: bool = True) -> None:
        x1, y1, x2, y2 = box
        size = (x2 - x1, y2 - y1)
        try:
            source = Image.open(io.BytesIO(data)).convert("RGB") if data else Image.new("RGB", size, "#292B36")
            source = _portrait_fit(source, size)
        except Exception:
            source = Image.new("RGB", size, "#292B36")
        if not data:
            initials = (self.character.name[:2] or "PC").upper()
            painter = ImageDraw.Draw(source)
            face = font(min(size) // 4, bold=True)
            bbox = painter.textbbox((0, 0), initials, font=face)
            painter.text(((size[0] - (bbox[2] - bbox[0])) / 2, (size[1] - (bbox[3] - bbox[1])) / 2 - 8), initials, font=face, fill=self.accent_light)
        mask = Image.new("L", size, 0)
        mask_draw = ImageDraw.Draw(mask)
        if circular:
            mask_draw.ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
        else:
            mask_draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=22, fill=255)
        self.image.paste(source, (x1, y1), mask)
        if circular:
            self.draw.ellipse(box, outline=self.accent_light, width=5)
        else:
            self.draw.rounded_rectangle(box, radius=22, outline=self.accent_light, width=4)

    def _hp_bar(self, x: int, y: int, width: int, hp: object, hpmax: object, *, label: str = "HP") -> None:
        hp_value = float(hp) if isinstance(hp, (int, float)) else 0.0
        max_value = float(hpmax) if isinstance(hpmax, (int, float)) else 0.0
        ratio = max(0.0, min(1.0, hp_value / max_value)) if max_value > 0 else 0.0
        radius = 0 if self.character.rule == "POKEMON-TRPG" else 21
        self.draw.rounded_rectangle((x, y, x + width, y + 42), radius=radius, fill=self.GOOD_DARK, outline=self.LINE if self.character.rule == "POKEMON-TRPG" else "#37694A", width=4 if self.character.rule == "POKEMON-TRPG" else 2)
        if ratio:
            self.draw.rounded_rectangle((x, y, x + max(42, int(width * ratio)), y + 42), radius=radius, fill=self.GOOD)
        text = f"{label}  {self._number(hp)} / {self._number(hpmax)}"
        face = font(24, bold=True)
        bbox = self.draw.textbbox((0, 0), text, font=face)
        self.draw.text((x + (width - (bbox[2] - bbox[0])) / 2, y + 6), text, font=face, fill=WHITE)

    def _round_stat(self, center_x: int, center_y: int, label: str, value: object, *, diameter: int = 112) -> None:
        radius = diameter // 2
        badge_box = (center_x - radius, center_y - radius, center_x + radius, center_y + radius)
        if self.character.rule == "POKEMON-TRPG":
            self.draw.rectangle((badge_box[0] + 7, badge_box[1] + 7, badge_box[2] + 7, badge_box[3] + 7), fill="#0A0A0C")
            self.draw.rectangle(badge_box, fill="#FFFDF4", outline="#0A0A0C", width=4)
        else:
            badge_fill = (25, 38, 52, 180) if self.character.rule == "COC7" else self.PANEL_ALT
            self.draw.ellipse(badge_box, fill=badge_fill, outline=self.accent_light, width=4)
        label_face = font(19, bold=True)
        value_face = font(40, bold=True)
        label_box = self.draw.textbbox((0, 0), label, font=label_face)
        value_text = self._number(value, signed=label in {"先攻", "熟练", "命中"})
        value_box = self.draw.textbbox((0, 0), value_text, font=value_face)
        self.draw.text((center_x - (label_box[2] - label_box[0]) / 2, center_y - 42), label, font=label_face, fill=self.SUBTLE)
        self.draw.text((center_x - (value_box[2] - value_box[0]) / 2, center_y - 13), value_text, font=value_face, fill=self.TEXT)

    def _header(self) -> None:
        header_h = 340
        if self.character.rule == "POKEMON-TRPG":
            self.draw.rectangle((43, 33, WIDTH - 27, header_h - 7), fill="#0A0A0C")
            self.draw.rectangle((35, 25, WIDTH - 35, header_h - 15), fill="#FFFDF4", outline="#0A0A0C", width=5)
            self.draw.rectangle((35, header_h - 30, WIDTH - 35, header_h - 15), fill="#FF1978")
        elif self.character.rule == "COC7":
            self.draw.rounded_rectangle((25, 20, WIDTH - 25, header_h - 15), radius=34, fill=(14, 27, 42, 150), outline=(173, 207, 215, 125), width=2)
            self.draw.rectangle((MARGIN, header_h - 6, WIDTH - MARGIN, header_h - 3), fill=self.accent_light)
        else:
            self.draw.rectangle((0, 0, WIDTH, header_h), fill=(12, 12, 18, 205))
            self.draw.rectangle((0, header_h - 5, WIDTH, header_h), fill=DND_GOLD)
        self._portrait(self.character.portrait, (MARGIN, 45, MARGIN + 245, 290))
        title_x = MARGIN + 285
        identity = self.character.identity
        alignment = identity.get("阵营", "") if self.character.rule not in {"COC7", "POKEMON-TRPG"} else ""
        display_name = self.character.name + (f" · {alignment}" if alignment else "")
        title_face = font(53, bold=True)
        title_lines = _lines(self.draw, display_name, title_face, 670, 1)
        self.draw.text((title_x, 44), title_lines[0], font=title_face, fill=self.TEXT)

        if self.character.rule == "COC7":
            line1 = " · ".join(filter(None, (identity.get("职业", "") or identity.get("职业/身份", ""), identity.get("年龄", ""), identity.get("性别", ""))))
            line2 = " · ".join(filter(None, (identity.get("住地", "") or identity.get("住所", ""), identity.get("故乡", ""))))
            label = "COC 7th 调查员速查卡"
        elif self.character.rule == "POKEMON-TRPG":
            line1 = " · ".join(filter(None, (identity.get("年龄", ""), identity.get("风格", ""), identity.get("方向", ""))))
            line2 = f"{len(self.character.pokemon)} 位同行伙伴 · 训练家与队伍速查卡"
            label = "门版宝可梦TRPG"
        else:
            class_line = " ".join(filter(None, (identity.get("职业", ""), identity.get("子职", ""))))
            level = identity.get("等级", "")
            line1 = " · ".join(filter(None, (class_line, level)))
            line2 = " · ".join(filter(None, (identity.get("种族", ""), identity.get("背景", ""))))
            label = "D&D 5E 2024" if self.character.rule.endswith("2024") else "D&D 5E 2014"
        self.draw.text((title_x, 118), line1 or label, font=font(30, bold=True), fill=self.accent_light)
        if line2:
            self.draw.text((title_x, 163), line2, font=font(25), fill=self.SUBTLE)
        self.draw.text((title_x, 204), label, font=font(21, bold=True), fill=self.DIM)

        hp = self.character.attributes.get("hp", self.character.attributes.get("HP", 0))
        hpmax = self.character.attributes.get("hpmax", self.character.attributes.get("HPmax", hp))
        self._hp_bar(title_x, 244, 610, hp, hpmax)

        if self.character.rule == "COC7":
            badges = [
                ("MP", self.character.attributes.get("mp", self.character.attributes.get("MP", "—"))),
                ("SAN", self.character.attributes.get("san", self.character.attributes.get("SAN", "—"))),
                ("幸运", self.character.attributes.get("幸运", "—")),
            ]
        elif self.character.rule == "POKEMON-TRPG":
            badges = [
                ("TP", self.character.attributes.get("旅行点", "—")),
                ("IP", self.character.attributes.get("物资点", "—")),
                ("伙伴", len(self.character.pokemon)),
            ]
        else:
            badges = [
                ("AC", self.character.attributes.get("ac", "—")),
                ("DC", self.character.attributes.get("dc", "—")),
                ("先攻", self.character.attributes.get("先攻", "—")),
                ("熟练", self.character.attributes.get("熟练", "—")),
            ]
        start_x = 1075 if len(badges) == 4 else 1125
        gap = 118 if len(badges) == 4 else 132
        for index, (badge, value) in enumerate(badges):
            self._round_stat(start_x + index * gap, 178, badge, value, diameter=104)
        self.y = header_h + 28

    def _ability_row(self, keys: list[str], *, dnd_modifiers: bool = False) -> None:
        gap = 14
        box_w = (CARD_WIDTH - gap * (len(keys) - 1)) // len(keys)
        height = 132
        for index, key in enumerate(keys):
            x = MARGIN + index * (box_w + gap)
            self._panel((x, self.y, x + box_w, self.y + height), fill=self.PANEL_ALT, radius=16)
            icon_offset = self._icon("attribute", key, x + 15, self.y + 42, 38)
            self.draw.text((x + 16, self.y + 13), key, font=font(23, bold=True), fill=self.SUBTLE)
            value = self.character.attributes.get(key, 0)
            if dnd_modifiers and isinstance(value, (int, float)):
                modifier = math.floor((float(value) - 10) / 2)
                value_text = self._number(value)
                mod_text = self._number(modifier, signed=True)
                self.draw.text((x + 15 + icon_offset, self.y + 47), value_text, font=font(42, bold=True), fill=self.TEXT)
                mod_box = self.draw.textbbox((0, 0), mod_text, font=font(25, bold=True))
                self.draw.text((x + box_w - (mod_box[2] - mod_box[0]) - 15, self.y + 58), mod_text, font=font(25, bold=True), fill=self.accent_light)
                factor = self.character.saving_throw_factors.get(key, 0)
                if isinstance(factor, (int, float)) and factor > 0:
                    self.draw.ellipse((x + box_w - 27, self.y + 14, x + box_w - 13, self.y + 28), fill=self.PROF)
            elif self.character.rule == "POKEMON-TRPG":
                score = self.character.attribute_scores.get(key)
                if score is not None:
                    self.draw.text((x + 15 + icon_offset, self.y + 47), self._number(score), font=font(42, bold=True), fill=self.TEXT)
                    modifier_text = "加值 " + self._number(value, signed=True)
                    self.draw.text((x + 16, self.y + 99), modifier_text, font=font(22, bold=True), fill=self.accent_light)
                else:
                    self.draw.text((x + 15 + icon_offset, self.y + 47), self._number(value), font=font(42, bold=True), fill=self.TEXT)
            else:
                self.draw.text((x + 15 + icon_offset, self.y + 47), self._number(value), font=font(42, bold=True), fill=self.TEXT)
        self.y += height + 22

    def _skill_proficiency(self, name: object) -> tuple[float, str]:
        skill_name = DND_SKILL_ALIASES.get(str(name), str(name))
        formula = str(self.character.skill_formulas.get(skill_name, ""))
        match = re.search(r"pbCalc\([^,]*,\s*([0-9.]+)\s*,\s*([^,)]+)", formula)
        if match:
            try:
                return float(match.group(1)), match.group(2).strip()
            except ValueError:
                pass
        parent = DND_SKILL_PARENTS.get(skill_name, "")
        value = self.character.skills.get(str(name))
        score = self.character.attributes.get(parent)
        proficiency = self.character.attributes.get("熟练")
        if not parent or not isinstance(value, (int, float)) or not isinstance(score, (int, float)):
            return 0.0, parent
        base = math.floor((float(score) - 10) / 2)
        if isinstance(proficiency, (int, float)) and float(proficiency) > 0:
            factor = (float(value) - base) / float(proficiency)
            if abs(factor - 2) < 0.15:
                return 2.0, parent
            if abs(factor - 1) < 0.15:
                return 1.0, parent
        return 0.0, parent

    def _dnd_skills_panel(self, x: int, y: int, width: int) -> int:
        skills = list(self.character.skills.items())
        row_h = 51
        height = 68 + max(1, len(skills)) * row_h + 12
        self._panel((x, y, x + width, y + height))
        cursor = self._panel_title(x, y, width, "技能", "金色＝熟练 · 紫色＝专精")
        for index, (name, value) in enumerate(skills or [("未填写", "—")]):
            factor, parent = self._skill_proficiency(name)
            color = self.EXPERT if factor >= 2 else (self.PROF if factor >= 1 else self.DIM)
            row_y = cursor + index * row_h
            if index % 2:
                stripe = (240, 233, 218, 230) if self.character.rule == "POKEMON-TRPG" else (30, 32, 42, 205)
                self.draw.rectangle((x + 8, row_y, x + width - 8, row_y + row_h), fill=stripe)
            self.draw.ellipse((x + 18, row_y + 17, x + 31, row_y + 30), fill=color if factor >= 1 else None, outline=color, width=2)
            self.draw.text((x + 43, row_y + 8), str(name), font=font(25, bold=factor >= 1), fill=self.TEXT)
            if parent:
                short = {"力量": "力", "敏捷": "敏", "体质": "体", "智力": "智", "感知": "感", "魅力": "魅"}.get(parent, parent[:1])
                self.draw.text((x + width - 118, row_y + 13), short, font=font(20, bold=True), fill=self.SUBTLE)
            display = self._number(value, signed=True)
            box = self.draw.textbbox((0, 0), display, font=font(27, bold=True))
            self.draw.text((x + width - (box[2] - box[0]) - 18, row_y + 8), display, font=font(27, bold=True), fill=color if factor >= 1 else self.TEXT)
        return height

    def _weapons_panel(self, x: int, y: int, width: int, *, coc: bool = False) -> int:
        weapons = self.character.weapons[:8]
        armor = self.character.armor[:4]
        rows = max(1, len(weapons) + len(armor))
        row_h = 72
        height = 68 + rows * row_h + 10
        self._panel((x, y, x + width, y + height))
        cursor = self._panel_title(x, y, width, "武器与护甲")
        entries: list[tuple[str, str, str]] = []
        for weapon in weapons:
            attack = self._number(weapon.value, signed=not coc) if weapon.value is not None else (weapon.skill or "—")
            detail = " · ".join(filter(None, (f"伤害 {weapon.damage}" if weapon.damage else "", weapon.notes)))
            entries.append((weapon.name, attack, detail))
        entries.extend((item, "AC", "护甲") for item in armor)
        for index, (name, attack, detail) in enumerate(entries or [("未填写", "—", "")]):
            row_y = cursor + index * row_h
            if index % 2:
                stripe = (240, 233, 218, 230) if self.character.rule == "POKEMON-TRPG" else (30, 32, 42, 205)
                self.draw.rectangle((x + 8, row_y, x + width - 8, row_y + row_h), fill=stripe)
            icon_offset = self._icon("armor" if detail == "护甲" else "weapon", name, x + 16, row_y + 12, 36)
            self.draw.text((x + 20 + icon_offset, row_y + 7), str(name)[:18], font=font(25, bold=True), fill=self.TEXT)
            if detail:
                lines = _lines(self.draw, detail, font(18), width - 205 - icon_offset, 1)
                self.draw.text((x + 20 + icon_offset, row_y + 41), lines[0], font=font(18), fill=self.SUBTLE)
            attack_box = self.draw.textbbox((0, 0), attack, font=font(27, bold=True))
            self.draw.text((x + width - (attack_box[2] - attack_box[0]) - 18, row_y + 18), attack, font=font(27, bold=True), fill=self.accent_light)
        return height

    def _chips_panel(self, x: int, y: int, width: int, title: str, values: list[str], category: str, *, limit: int = 24) -> int:
        values = self._unique(values)
        shown = values[:limit]
        chip_h = 49
        columns = 2 if width >= 700 else 1
        rows = max(1, (len(shown) + columns - 1) // columns)
        height = 68 + rows * chip_h + 18
        self._panel((x, y, x + width, y + height))
        cursor = self._panel_title(x, y, width, title, f"{len(values)} 项" if values else "")
        col_w = (width - 28) // columns
        for index, value in enumerate(shown or ["—"]):
            row, column = divmod(index, columns)
            item_x = x + 14 + column * col_w
            item_y = cursor + row * chip_h
            icon_offset = self._icon(category, value, item_x, item_y + 3, 30)
            lines = _lines(self.draw, value, font(21, bold=True), col_w - 20 - icon_offset, 1)
            self.draw.text((item_x + icon_offset, item_y + 10), lines[0], font=font(21, bold=True), fill=self.TEXT)
        if len(values) > limit:
            self.draw.text((x + width - 150, y + height - 34), f"另有 {len(values) - limit} 项", font=font(18), fill=self.DIM)
        return height

    def _details_panel(self, x: int, y: int, width: int, title: str, values: list[str], category: str, *, limit: int = 10) -> int:
        values = self._unique(values)[:limit]
        prepared: list[tuple[str, list[str]]] = []
        for value in values or ["—"]:
            name, separator, description = value.partition(" — ")
            if not separator:
                name, separator, description = value.partition("—")
            if not separator:
                name, description = value, ""
            prepared.append((name.strip(), _lines(self.draw, description.strip(), font(18), width - 105, 1) if description else []))
        row_heights = [68 if lines else 52 for _, lines in prepared]
        height = 68 + sum(row_heights) + 14
        self._panel((x, y, x + width, y + height))
        cursor = self._panel_title(x, y, width, title)
        for index, ((name, lines), row_h) in enumerate(zip(prepared, row_heights)):
            if index % 2:
                stripe = (240, 233, 218, 230) if self.character.rule == "POKEMON-TRPG" else (30, 32, 42, 205)
                self.draw.rectangle((x + 8, cursor, x + width - 8, cursor + row_h), fill=stripe)
            icon_offset = self._icon(category, name, x + 16, cursor + 6, 32)
            self.draw.text((x + 20 + icon_offset, cursor + 6), name[:22], font=font(22, bold=True), fill=self.TEXT)
            if lines:
                self.draw.text((x + 20 + icon_offset, cursor + 36), lines[0], font=font(18), fill=self.SUBTLE)
            cursor += row_h
        return height

    def _render_dnd(self) -> None:
        self._header()
        self._ability_row(["力量", "敏捷", "体质", "智力", "感知", "魅力"], dnd_modifiers=True)
        left_x, gap = MARGIN, 22
        left_w = 520
        right_x = left_x + left_w + gap
        right_w = WIDTH - MARGIN - right_x
        start_y = self.y
        left_h = self._dnd_skills_panel(left_x, start_y, left_w)
        right_y = start_y
        if self.character.weapons or self.character.armor:
            right_y += self._weapons_panel(right_x, right_y, right_w) + 18
        if self.character.spells:
            right_y += self._chips_panel(right_x, right_y, right_w, "法术", self.character.spells, "spell", limit=28) + 18
        feature_values = [*self.character.feats, *self.character.features]
        if feature_values:
            right_y += self._details_panel(right_x, right_y, right_w, "专长与特性", feature_values, "feature", limit=12) + 18
        if self.character.items:
            right_y += self._chips_panel(right_x, right_y, right_w, "关键装备", self.character.items, "item", limit=10) + 18
        self.y = max(start_y + left_h, right_y) + 28

    def _coc_skill_panel(self, x: int, y: int, width: int) -> int:
        skills = [(name, value) for name, value in self.character.skills.items() if value not in (None, "")]
        skills.sort(key=lambda pair: float(pair[1]) if isinstance(pair[1], (int, float)) else -1, reverse=True)
        shown = skills[:30]
        columns = 3
        rows = max(1, (len(shown) + columns - 1) // columns)
        row_h = 55
        height = 68 + rows * row_h + 14
        self._panel((x, y, x + width, y + height))
        cursor = self._panel_title(x, y, width, "常用技能", "按数值排序 · 最多显示 30 项")
        col_w = (width - 28) // columns
        for index, (name, value) in enumerate(shown or [("未填写", "—")]):
            row, column = divmod(index, columns)
            item_x = x + 14 + column * col_w
            item_y = cursor + row * row_h
            if row % 2:
                self.draw.rectangle((item_x, item_y, item_x + col_w - 8, item_y + row_h), fill=(25, 41, 55, 125))
            self.draw.text((item_x + 12, item_y + 10), str(name)[:14], font=font(23, bold=True), fill=self.TEXT)
            display = self._number(value)
            box = self.draw.textbbox((0, 0), display, font=font(26, bold=True))
            self.draw.text((item_x + col_w - (box[2] - box[0]) - 18, item_y + 8), display, font=font(26, bold=True), fill=self.accent_light)
        return height

    def _render_coc(self) -> None:
        self._header()
        self._ability_row(["外貌", "体质", "敏捷", "教育", "智力", "幸运", "意志", "体型", "力量"])
        skills_h = self._coc_skill_panel(MARGIN, self.y, CARD_WIDTH)
        self.y += skills_h + 20
        gap = 22
        left_w = 810
        right_w = CARD_WIDTH - left_w - gap
        left_y = right_y = self.y
        if self.character.weapons or self.character.armor:
            left_y += self._weapons_panel(MARGIN, left_y, left_w, coc=True) + 18
        if self.character.items:
            left_y += self._chips_panel(MARGIN, left_y, left_w, "随身物品", self.character.items, "item", limit=16) + 18
        identity_values = [
            f"{key} — {value}" for key, value in self.character.identity.items()
            if value and key not in {"职业", "职业/身份", "年龄", "性别", "住地", "住所", "故乡"}
        ]
        if identity_values:
            right_y += self._details_panel(MARGIN + left_w + gap, right_y, right_w, "调查员备注", identity_values, "feature", limit=8) + 18
        self.y = max(left_y, right_y) + 28

    def _pokemon_skills_panel(self, x: int, y: int, width: int) -> int:
        items = list(self.character.skills.items())[:14]
        row_h = 52
        height = 68 + max(1, len(items)) * row_h + 12
        self._panel((x, y, x + width, y + height))
        cursor = self._panel_title(x, y, width, "训练家技能")
        for index, (name, value) in enumerate(items or [("未填写", "—")]):
            row_y = cursor + index * row_h
            if index % 2:
                self.draw.rectangle((x + 8, row_y, x + width - 8, row_y + row_h), fill=(240, 233, 218, 230))
            self.draw.text((x + 18, row_y + 9), str(name), font=font(24, bold=True), fill=self.TEXT)
            display = self._number(value, signed=True)
            box = self.draw.textbbox((0, 0), display, font=font(27, bold=True))
            self.draw.text((x + width - (box[2] - box[0]) - 18, row_y + 7), display, font=font(27, bold=True), fill=self.accent_light)
        return height

    def _pokemon_card(self, companion, x: int, y: int, width: int) -> int:
        moves = companion.moves[:6]
        move_rows = max(1, len(moves))
        height = 285 + move_rows * 54
        self._panel((x, y, x + width, y + height), outline="#39465A")
        self._portrait(companion.portrait, (x + 18, y + 18, x + 168, y + 168), circular=False)
        info_x = x + 190
        self.draw.text((info_x, y + 17), companion.name or companion.species or "未命名伙伴", font=font(32, bold=True), fill=self.TEXT)
        subtitle = " · ".join(filter(None, (companion.species, "/".join(companion.types), companion.gender)))
        self.draw.text((info_x, y + 61), subtitle, font=font(20, bold=True), fill=self.accent_light)
        detail = " · ".join(filter(None, (
            f"特性 {companion.ability}" if companion.ability else "",
            f"携带 {companion.held_item}" if companion.held_item else "",
            f"羁绊 {self._number(companion.bond)}" if companion.bond is not None else "",
            f"命中 {self._number(companion.accuracy, signed=True)}" if companion.accuracy is not None else "",
            f"闪避 {self._number(companion.evasion)}" if companion.evasion is not None else "",
        )))
        detail_lines = _lines(self.draw, detail, font(18), width - 210, 2)
        self.draw.multiline_text((info_x, y + 94), "\n".join(detail_lines), font=font(18), fill=self.SUBTLE, spacing=4)
        self._hp_bar(info_x, y + 145, width - 210, companion.hp, companion.hpmax, label="HP")

        stats = list(companion.stats.items())[:6]
        stat_y = y + 184
        stat_w = (width - 36) // max(1, len(stats))
        for index, (name, value) in enumerate(stats):
            stat_x = x + 18 + index * stat_w
            self.draw.text((stat_x, stat_y), name[:2], font=font(16, bold=True), fill=self.DIM)
            self.draw.text((stat_x, stat_y + 23), self._number(value), font=font(22, bold=True), fill=self.TEXT)
            modifier = companion.stat_modifiers.get(name)
            if modifier is not None:
                self.draw.text((stat_x, stat_y + 48), self._number(modifier, signed=True), font=font(16, bold=True), fill=self.accent_light)
        self.draw.line((x + 18, y + 260, x + width - 18, y + 260), fill=self.LINE, width=2)
        move_y = y + 273
        for index, move in enumerate(moves or [None]):
            row_y = move_y + index * 54
            if move is None:
                self.draw.text((x + 20, row_y + 9), "未填写招式", font=font(21), fill=self.DIM)
                continue
            self.draw.text((x + 20, row_y + 7), move.name[:14], font=font(23, bold=True), fill=self.TEXT)
            tags = " · ".join(filter(None, (move.element, move.category)))
            self.draw.text((x + 235, row_y + 11), tags[:16], font=font(18, bold=True), fill=self.accent_light)
            mechanic = "  ".join(filter(None, (
                f"命中 {move.accuracy}" if move.accuracy else "",
                f"伤害 {move.damage}" if move.damage else "",
                f"EP {self._number(move.ep_cost)}" if move.ep_cost is not None else "",
            )))
            mechanic_box = self.draw.textbbox((0, 0), mechanic, font=font(17))
            self.draw.text((x + width - (mechanic_box[2] - mechanic_box[0]) - 18, row_y + 13), mechanic, font=font(17), fill=self.SUBTLE)
        return height

    def _render_pokemon_trainer(self) -> None:
        self._header()
        self._ability_row(["力量", "体魄", "智识", "意念", "机敏", "魅力", "幸运"])
        gap = 22
        left_w = 560
        right_w = CARD_WIDTH - left_w - gap
        skills_h = self._pokemon_skills_panel(MARGIN, self.y, left_w)
        items_h = self._chips_panel(MARGIN + left_w + gap, self.y, right_w, "背包与旅行装备", self.character.items, "item", limit=20)
        self.y += max(skills_h, items_h) + 24
        if self.character.pokemon:
            names = [
                " · ".join(filter(None, (companion.name, companion.species)))
                for companion in self.character.pokemon
            ]
            self.y += self._chips_panel(MARGIN, self.y, CARD_WIDTH, "同行伙伴索引", names, "feature", limit=12) + 12

    def render_pokemon_companion(self, companion, index: int) -> Image.Image:
        self.draw.rectangle((0, 0, WIDTH, 315), fill=self.HEADER)
        self.draw.rectangle((0, 310, WIDTH, 315), fill=POKEMON)
        self._portrait(companion.portrait, (MARGIN, 38, MARGIN + 235, 273), circular=False)
        info_x = MARGIN + 280
        title = companion.name or companion.species or f"伙伴 {index}"
        self.draw.text((info_x, 42), title, font=font(54, bold=True), fill=self.TEXT)
        subtitle = " · ".join(filter(None, (companion.species, "/".join(companion.types), companion.gender)))
        self.draw.text((info_x, 116), subtitle or "宝可梦伙伴速查卡", font=font(28, bold=True), fill=self.accent_light)
        detail = " · ".join(filter(None, (
            f"特性 {companion.ability}" if companion.ability else "",
            f"携带 {companion.held_item}" if companion.held_item else "",
            f"状态 {companion.status}" if companion.status else "",
        )))
        self.draw.text((info_x, 164), detail, font=font(23), fill=self.SUBTLE)
        self._hp_bar(info_x, 219, 640, companion.hp, companion.hpmax, label="HP")
        badge_values = (
            ("命中", companion.accuracy),
            ("闪避", companion.evasion),
            ("EP", companion.ep),
            ("羁绊", companion.bond),
        )
        for center_x, (label, value) in zip((1050, 1190, 1330, 1470), badge_values):
            self._round_stat(center_x, 162, label, value if value is not None else "—", diameter=106)
        self.y = 344

        stat_keys = list(companion.stats)[:6]
        if stat_keys:
            gap = 14
            box_w = (CARD_WIDTH - gap * (len(stat_keys) - 1)) // len(stat_keys)
            for stat_index, key in enumerate(stat_keys):
                stat_x = MARGIN + stat_index * (box_w + gap)
                self._panel((stat_x, self.y, stat_x + box_w, self.y + 148), fill=self.PANEL_ALT, radius=16)
                self.draw.text((stat_x + 16, self.y + 13), key, font=font(23, bold=True), fill=self.SUBTLE)
                self.draw.text((stat_x + 16, self.y + 53), self._number(companion.stats.get(key, 0)), font=font(42, bold=True), fill=self.TEXT)
                modifier = companion.stat_modifiers.get(key)
                if modifier is not None:
                    modifier_text = "加值 " + self._number(modifier, signed=True)
                    self.draw.text((stat_x + 16, self.y + 105), modifier_text, font=font(21, bold=True), fill=self.accent_light)
            self.y += 170

        moves = companion.moves[:10]
        row_h = 78
        move_h = 68 + max(1, len(moves)) * row_h + 14
        self._panel((MARGIN, self.y, WIDTH - MARGIN, self.y + move_h))
        cursor = self._panel_title(MARGIN, self.y, CARD_WIDTH, "战斗招式", f"{len(companion.moves)} 项")
        for move_index, move in enumerate(moves or [None]):
            row_y = cursor + move_index * row_h
            if move_index % 2:
                self.draw.rectangle((MARGIN + 8, row_y, WIDTH - MARGIN - 8, row_y + row_h), fill=(240, 233, 218, 230))
            if move is None:
                self.draw.text((MARGIN + 22, row_y + 20), "未填写招式", font=font(24), fill=self.DIM)
                continue
            icon_offset = self._icon("spell", move.name, MARGIN + 18, row_y + 15, 38)
            self.draw.text((MARGIN + 22 + icon_offset, row_y + 8), move.name[:18], font=font(27, bold=True), fill=self.TEXT)
            tags = " · ".join(filter(None, (move.element, move.category, move.range)))
            self.draw.text((MARGIN + 390, row_y + 12), tags[:28], font=font(21, bold=True), fill=self.accent_light)
            mechanics = "  ".join(filter(None, (
                f"命中 {move.accuracy}" if move.accuracy else "",
                f"伤害 {move.damage}" if move.damage else "",
                f"EP {self._number(move.ep_cost)}" if move.ep_cost is not None else "",
                f"优先度 {self._number(move.priority, signed=True)}" if move.priority is not None else "",
            )))
            mechanic_box = self.draw.textbbox((0, 0), mechanics, font=font(21))
            self.draw.text((WIDTH - MARGIN - (mechanic_box[2] - mechanic_box[0]) - 20, row_y + 12), mechanics, font=font(21), fill=self.SUBTLE)
            if move.effect:
                effect = _lines(self.draw, move.effect, font(17), CARD_WIDTH - 430, 1)[0]
                self.draw.text((MARGIN + 390, row_y + 44), effect, font=font(17), fill=self.DIM)
        self.y += move_h + 20
        if companion.features:
            self.y += self._details_panel(MARGIN, self.y, CARD_WIDTH, "特性与战斗备注", companion.features, "feature", limit=10) + 18
        self.draw.text((MARGIN, self.y), f"{self.character.name}的同行伙伴 · 第 {index} 张伙伴卡", font=font(19), fill=self.DIM)
        self.draw.text((WIDTH - MARGIN - 255, self.y), "由一键录卡生成", font=font(19), fill=self.DIM)
        self.y += 55
        return self.image.crop((0, 0, WIDTH, min(self.y, self.image.height)))

    def render(self) -> Image.Image:
        if self.character.rule == "COC7":
            self._render_coc()
        elif self.character.rule == "POKEMON-TRPG":
            self._render_pokemon_trainer()
        else:
            self._render_dnd()
        footer = f"跑团速查卡 · {self.character.source_filename}"
        self.draw.text((MARGIN, self.y), footer, font=font(19), fill=self.DIM)
        self.draw.text((WIDTH - MARGIN - 255, self.y), "由一键录卡生成", font=font(19), fill=self.DIM)
        self.y += 55
        return self.image.crop((0, 0, WIDTH, min(self.y, self.image.height)))


def render_character(character: Character) -> Image.Image:
    return CompactSheet(character).render()


def render_png(character: Character) -> bytes:
    output = io.BytesIO()
    render_character(character).save(output, format="PNG", optimize=True)
    return output.getvalue()


POKEMON_ROSTER_SUMMARY_THRESHOLD = 12


def render_pokemon_roster(character: Character) -> Image.Image:
    """One complete, compact roster; no biographies or move effect paragraphs."""
    count = len(character.pokemon)
    columns = max(2, min(6, math.ceil(math.sqrt(count / 3))))
    tile_width, gap, margin = 760, 24, 40
    width = margin * 2 + columns * tile_width + (columns - 1) * gap
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_font, body_font = font(29, bold=True), font(23)
    entries = []
    for index, pokemon in enumerate(character.pokemon, 1):
        stats = []
        for label, value in (("HP", pokemon.hp), ("HP上限", pokemon.hpmax), ("EP", pokemon.ep),
                             ("命中", pokemon.accuracy), ("闪避", pokemon.evasion), ("羁绊", pokemon.bond)):
            if value is not None:
                stats.append(f"{label} {value:g}")
        for label in dict.fromkeys([*pokemon.stats, *pokemon.stat_modifiers]):
            value = pokemon.stats.get(label)
            modifier = pokemon.stat_modifiers.get(label)
            text = f"{label} {value:g}" if value is not None else label
            if modifier is not None:
                text += f"（{modifier:+g}）"
            stats.append(text)
        title_lines = _lines(measure, f"{index:02d}  {pokemon.name or pokemon.species}", title_font, tile_width - 220)
        species_lines = _lines(measure, "种族：" + (pokemon.species or "未填写") +
                               (" · " + "/".join(pokemon.types) if pokemon.types else ""), body_font, tile_width - 220)
        info_height = max(168, len(title_lines) * 39 + len(species_lines) * 32 + 12)
        stat_lines = []
        current = ""
        for stat in stats or ["属性未填写"]:
            candidate = (current + "   " + stat).strip()
            if current and measure.textlength(candidate, font=body_font) > tile_width - 40:
                stat_lines.extend(_lines(measure, current, body_font, tile_width - 40))
                current = stat
            else:
                current = candidate
        stat_lines.extend(_lines(measure, current, body_font, tile_width - 40))
        move_lines = _lines(measure, "招式：" + ("、".join(move.name for move in pokemon.moves if move.name) or "未填写"),
                            body_font, tile_width - 40)
        height = 40 + info_height + (len(stat_lines) + len(move_lines)) * 34 + 28
        entries.append((pokemon, title_lines, species_lines, stat_lines, move_lines, info_height, height))
    rows = [entries[start:start + columns] for start in range(0, count, columns)]
    height = 160 + sum(max(entry[-1] for entry in row) + gap for row in rows) + 24
    image = Image.new("RGB", (width, height), "#F1EBDD")
    draw = ImageDraw.Draw(image)
    draw.text((margin, 28), "同行宝可梦", font=font(48, bold=True), fill=INK)
    draw.text((margin, 94), f"{character.name} · 共 {count} 只 · 属性与招式速查", font=font(25), fill=MUTED)
    y = 150
    for row in rows:
        row_height = max(entry[-1] for entry in row)
        for column, (pokemon, titles, species, stats, moves, info_height, _) in enumerate(row):
            x = margin + column * (tile_width + gap)
            _rounded(draw, (x, y, x + tile_width, y + row_height), fill="#FFFDF4", outline="#303038", radius=12)
            draw.rectangle((x + 18, y + 18, x + 182, y + 182), fill="#E3DFD4")
            if pokemon.portrait:
                try:
                    with Image.open(io.BytesIO(pokemon.portrait)) as source:
                        portrait = ImageOps.contain(source.convert("RGBA"), (164, 164), Image.Resampling.LANCZOS)
                    image.paste(portrait, (x + 18 + (164 - portrait.width) // 2, y + 18 + (164 - portrait.height) // 2), portrait)
                except (OSError, ValueError):
                    draw.text((x + 32, y + 82), "图片不可用", font=font(20), fill=MUTED)
            else:
                draw.text((x + 42, y + 82), "未附图片", font=font(20), fill=MUTED)
            cursor = y + 18
            for line in titles:
                draw.text((x + 202, cursor), line, font=title_font, fill=INK)
                cursor += 39
            for line in species:
                draw.text((x + 202, cursor + 8), line, font=body_font, fill=POKEMON_BLUE)
                cursor += 32
            cursor = y + 26 + info_height
            for line in stats + moves:
                draw.text((x + 20, cursor), line, font=body_font, fill=INK)
                cursor += 34
        y += row_height + gap
    return image


def render_pngs(character: Character) -> list[bytes]:
    """Encode each image before rendering the next to bound peak memory."""
    def images():
        yield render_character(character)
        if character.rule == "POKEMON-TRPG":
            if len(character.pokemon) > POKEMON_ROSTER_SUMMARY_THRESHOLD:
                yield render_pokemon_roster(character)
            else:
                for index, companion in enumerate(character.pokemon, 1):
                    yield CompactSheet(character, variant_offset=index).render_pokemon_companion(companion, index)

    payloads: list[bytes] = []
    for image in images():
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        payloads.append(output.getvalue())
        image.close()
    return payloads


FILE_LIST_WIDTH = 1400
FILE_LIST_BASE_HEIGHT = 510
FILE_LIST_ROW_HEIGHT = 112
FILE_LIST_MAX_ROWS = 12


def file_list_dimensions(file_count: int) -> tuple[int, int]:
    """Return the exact metadata-list canvas size used by the renderer."""
    rows = max(1, min(FILE_LIST_MAX_ROWS, int(file_count)))
    return FILE_LIST_WIDTH, FILE_LIST_BASE_HEIGHT + rows * FILE_LIST_ROW_HEIGHT


def render_file_list(files: list[dict], group_name: str = "") -> bytes:
    """Render a metadata-only group file browser. This never opens workbook data."""
    width = FILE_LIST_WIDTH
    margin = 56
    rows = files[:FILE_LIST_MAX_ROWS]
    row_h = FILE_LIST_ROW_HEIGHT
    _, height = file_list_dimensions(len(rows))
    image = Image.new("RGB", (width, height), "#09101D")
    draw = ImageDraw.Draw(image, "RGBA")

    # A restrained aurora gradient gives the list its own neutral, premium UI.
    for y in range(height):
        progress = y / max(1, height - 1)
        red = int(9 + 10 * progress)
        green = int(16 + 7 * progress)
        blue = int(29 + 18 * progress)
        draw.line((0, y, width, y), fill=(red, green, blue, 255))
    draw.ellipse((-220, -310, 650, 560), fill=(39, 196, 210, 28))
    draw.ellipse((880, -270, 1580, 470), fill=(150, 83, 235, 30))

    draw.rounded_rectangle(
        (margin, 42, width - margin, 194),
        radius=30,
        fill=(19, 30, 49, 205),
        outline=(139, 184, 209, 90),
        width=2,
    )
    draw.text((margin + 34, 68), "群内角色卡文件", font=font(43, bold=True), fill="#F7F9FC")
    scope = group_name or "当前会话"
    scope_lines = _lines(draw, scope, font(22), 580, 1)
    draw.text((margin + 36, 132), scope_lines[0], font=font(22), fill="#8DD9DF")
    list_y = 218
    for index, item in enumerate(rows, 1):
        y = list_y + (index - 1) * row_h
        draw.rounded_rectangle(
            (margin, y, width - margin, y + 94),
            radius=22,
            fill=(22, 34, 54, 188),
            outline=(112, 143, 176, 75),
            width=2,
        )
        draw.rounded_rectangle((margin + 16, y + 17, margin + 82, y + 77), radius=17, fill="#18A7B6")
        number = str(index)
        number_box = draw.textbbox((0, 0), number, font=font(30, bold=True))
        draw.text(
            (margin + 49 - (number_box[2] - number_box[0]) / 2, y + 28),
            number,
            font=font(30, bold=True),
            fill="#FFFFFF",
        )
        file_name = str(item.get("filename") or "未命名文件")
        name_lines = _lines(draw, file_name, font(27, bold=True), 690, 1)
        draw.text((margin + 106, y + 16), name_lines[0], font=font(27, bold=True), fill="#F7F9FC")
        meta = " · ".join(filter(None, (
            str(item.get("format") or "").upper(),
            str(item.get("size_text") or ""),
            str(item.get("uploader") or ""),
            str(item.get("time_text") or ""),
        )))
        meta_lines = _lines(draw, meta, font(19), 790, 1)
        draw.text((margin + 108, y + 57), meta_lines[0], font=font(19), fill="#9BA9BC")
        command = f".一键录卡 导入 {index}"
        command_box = draw.textbbox((0, 0), command, font=font(22, bold=True))
        command_w = command_box[2] - command_box[0]
        draw.rounded_rectangle(
            (width - margin - command_w - 40, y + 22, width - margin - 18, y + 72),
            radius=14,
            fill=(98, 64, 170, 175),
            outline=(174, 138, 242, 115),
            width=2,
        )
        draw.text((width - margin - command_w - 29, y + 34), command, font=font(22, bold=True), fill="#F5EEFF")

    footer_y = list_y + max(1, len(rows)) * row_h + 12
    draw.rounded_rectangle(
        (margin, footer_y, width - margin, footer_y + 194),
        radius=28,
        fill=(18, 28, 46, 215),
        outline=(128, 164, 198, 85),
        width=2,
    )
    draw.text((margin + 30, footer_y + 22), "怎么使用", font=font(29, bold=True), fill="#F7F9FC")
    commands = (
        "读取指定文件并识别： .一键录卡 导入 1\n"
        "读取最近上传的文件： .一键录卡 导入 最新\n"
        "刷新本群文件列表：   .一键录卡 列表"
    )
    draw.multiline_text((margin + 30, footer_y + 67), commands, font=font(22, bold=True), fill="#C7D2E1", spacing=13)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
