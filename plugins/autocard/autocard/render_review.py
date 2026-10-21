from __future__ import annotations

import io
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .models import Character
from .render import (
    BACKGROUND, CARD_WIDTH, COC, DND, DND_GOLD, INK, MARGIN, MUTED, POKEMON, WHITE, WIDTH,
    _lines, _portrait_fit, _rounded, font,
)
from .review import CharacterReview, review_character


STORY = "#6847C7"


class ReviewFlow:
    def __init__(self, character: Character, review: CharacterReview) -> None:
        self.character = character
        self.review = review
        self.accent = (
            COC if character.rule == "COC7"
            else (POKEMON if character.rule == "POKEMON-TRPG"
                  else (STORY if character.seal_system == "story" else DND))
        )
        self.image = Image.new("RGB", (WIDTH, 18000), BACKGROUND)
        self.background_variant = self._place_background()
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.heading_color = "#22252B" if character.rule == "POKEMON-TRPG" else "#F7F2E9"
        self.footer_color = "#3B3A40" if character.rule == "POKEMON-TRPG" else "#E6DDD0"
        self.y = 0

    def _place_background(self) -> int:
        if self.character.rule == "COC7":
            prefix = "coc-glass"
            veil = (5, 12, 24, 105)
        elif self.character.rule == "POKEMON-TRPG":
            prefix = "pokemon-brutal"
            veil = (248, 244, 232, 155)
        elif self.character.seal_system == "story":
            prefix = "story-arcana"
            veil = (12, 10, 30, 125)
        else:
            prefix = "dnd-epic"
            veil = (20, 14, 20, 115)
        digest = hashlib.sha256(
            f"review|{self.character.rule}|{self.character.source_filename}".encode("utf-8")
        ).digest()
        variant = digest[0] % 3 + 1
        path = Path(__file__).resolve().parent.parent / "assets" / "backgrounds" / f"{prefix}-{variant:02d}.jpg"
        if path.exists():
            try:
                source = Image.open(path).convert("RGB")
                tile_height = 2400
                tile = ImageOps.fit(source, (WIDTH, tile_height), method=Image.Resampling.LANCZOS)
                for y in range(0, self.image.height, tile_height):
                    current = tile if (y // tile_height) % 2 == 0 else ImageOps.flip(tile)
                    self.image.paste(current, (0, y))
                overlay = Image.new("RGBA", self.image.size, veil)
                self.image.paste(overlay, (0, 0), overlay)
            except Exception:
                pass
        return variant

    def _portrait(self, box: tuple[int, int, int, int]) -> None:
        size = box[2] - box[0]
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        if self.character.portrait:
            try:
                source = Image.open(io.BytesIO(self.character.portrait)).convert("RGB")
                source = _portrait_fit(source, (size, size))
            except Exception:
                source = Image.new("RGB", (size, size), "#E4D7D9")
        else:
            source = Image.new("RGB", (size, size), "#E4D7D9" if self.accent == DND else "#CFE0DF")
            initials = (self.character.name[:2] or "PC").upper()
            face = font(58, bold=True)
            temp = ImageDraw.Draw(source)
            bounds = temp.textbbox((0, 0), initials, font=face)
            temp.text(((size - (bounds[2] - bounds[0])) / 2, (size - (bounds[3] - bounds[1])) / 2 - 8), initials, font=face, fill=self.accent)
        self.image.paste(source, box[:2], mask)
        self.draw.ellipse(box, outline=WHITE, width=8)

    def header(self) -> None:
        height = 410
        header_fill = (
            (58, 28, 39, 224) if self.character.rule.startswith("DND")
            else ((19, 51, 65, 218) if self.character.rule == "COC7"
                  else ((50, 31, 92, 224) if self.character.seal_system == "story" else (196, 49, 56, 225)))
        )
        self.draw.rectangle((0, 0, WIDTH, height), fill=header_fill)
        center = (WIDTH - 220, 205)
        radius = 150
        points = [
            (center[0] + math.cos(-math.pi / 2 + i * math.tau / 10) * radius,
             center[1] + math.sin(-math.pi / 2 + i * math.tau / 10) * radius)
            for i in range(10)
        ]
        watermark = "#A94A58" if self.accent == DND else ("#8870D6" if self.accent == STORY else "#3B7774")
        self.draw.polygon(points, outline=watermark, width=5)
        for index in range(0, 10, 2):
            self.draw.line((points[index], center, points[(index + 3) % 10]), fill=watermark, width=3)

        self._portrait((MARGIN, 70, MARGIN + 220, 290))
        title_x = MARGIN + 260
        review_title = (
            "艾拉的宝可梦队伍故事评审" if self.character.rule == "POKEMON-TRPG"
            else ("艾拉的异能者背景故事评审" if self.character.rule == "DX3RD"
                  else ("艾拉的小众规则背景故事评审" if self.character.seal_system == "story"
                        else "艾拉的背景故事评审"))
        )
        self.draw.text((title_x, 62), review_title, font=font(55 if self.character.rule == "POKEMON-TRPG" else 59, bold=True), fill=WHITE)
        self.draw.text((title_x, 153), self.character.name, font=font(50, bold=True), fill="#FFF2D5")
        if self.character.rule == "POKEMON-TRPG":
            identity = " · ".join(filter(None, (
                self.character.identity.get("风格", ""), self.character.identity.get("方向", ""),
                f"{len(self.character.pokemon)}位同行伙伴",
            )))
        elif self.character.seal_system == "story":
            identity = " · ".join(filter(None, (
                self.character.identity.get("行动代号", ""), self.character.identity.get("本业", ""),
                self.character.identity.get("身份", ""), self.character.identity.get("症候系统", ""),
            )))
        else:
            identity = " · ".join(filter(None, (
                self.character.identity.get("职业", ""), self.character.identity.get("子职", ""),
                self.character.identity.get("等级", ""), self.character.identity.get("阵营", ""),
            )))
        self.draw.text((title_x, 225), identity or self.review.rule, font=font(31, bold=True), fill="#F0DADD" if self.accent == DND else "#D7ECEA")
        rule_label = (
            "COC 7th" if self.character.rule == "COC7"
            else ("门版宝可梦TRPG" if self.character.rule == "POKEMON-TRPG"
                  else ("Double Cross 3rd" if self.character.rule == "DX3RD"
                        else ("小众规则 · 通用故事卡" if self.character.seal_system == "story"
                              else ("D&D 5E 2024" if self.character.rule.endswith("2024") else "D&D 5E 2014"))))
        )
        self.draw.text((title_x, 282), rule_label + " · 人物清晰度 / 故事完整度 / 趣味与可玩性", font=font(26), fill="#F7E7D0")
        self.draw.line((title_x, 344, WIDTH - MARGIN, 344), fill=DND_GOLD, width=3)

        score_text = str(self.review.total_score)
        score_face = font(88, bold=True)
        bounds = self.draw.textbbox((0, 0), score_text, font=score_face)
        self.draw.text((center[0] - (bounds[2] - bounds[0]) / 2, 137), score_text, font=score_face, fill=WHITE)
        label_face = font(25, bold=True)
        label = "背景评分"
        label_bounds = self.draw.textbbox((0, 0), label, font=label_face)
        self.draw.text((center[0] - (label_bounds[2] - label_bounds[0]) / 2, 245), label, font=label_face, fill="#F6DFAE")
        self.y = height + 42

    def score_summary(self) -> None:
        card_gap = 18
        card_w = (CARD_WIDTH - card_gap * 2) // 3
        values = (
            ("人物清晰度", self.review.clarity_score, "是否能看清角色是谁、在乎什么"),
            ("故事完整度", self.review.completeness_score, "来历、关系、动机与当前处境"),
            ("趣味与可玩性", self.review.interest_score, "矛盾、选择、场景与成长空间"),
        )
        for index, (label, value, note) in enumerate(values):
            x = MARGIN + index * (card_w + card_gap)
            fill = self.accent if index == 2 else (255, 253, 248, 238)
            outline = self.accent if index == 2 else "#D7D4CC"
            self.draw.rounded_rectangle((x, self.y, x + card_w, self.y + 190), radius=28, fill=fill, outline=outline, width=2)
            label_color = "#F6DFAE" if index == 2 else MUTED
            value_color = WHITE if index == 2 else self.accent
            self.draw.text((x + 26, self.y + 20), label, font=font(28, bold=True), fill=label_color)
            self.draw.text((x + 26, self.y + 57), str(value), font=font(65, bold=True), fill=value_color)
            lines = _lines(self.draw, note, font(22), card_w - 52, 2)
            self.draw.multiline_text((x + 26, self.y + 137), "\n".join(lines), font=font(22), fill="#F7E7E9" if index == 2 else MUTED, spacing=4)
        self.y += 225

        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + 94), fill=(255, 253, 248, 238))
        info = f"角色：{self.review.name}    年龄：{self.review.age}    规则：{self.review.rule}    模板：{self.character.template_name}"
        self.draw.text((MARGIN + 26, self.y + 26), info, font=font(27, bold=True), fill=INK)
        self.y += 128

    def section(self, title: str, body: str) -> None:
        self.draw.rounded_rectangle((MARGIN, self.y + 5, MARGIN + 13, self.y + 53), radius=6, fill=self.accent)
        self.draw.text((MARGIN + 30, self.y), title, font=font(38, bold=True), fill=self.heading_color)
        self.y += 64
        face = font(29)
        story_section = title in {
            "背景故事梗概", "原文细读与人物拆解", "训练家故事梗概", "训练家原文细读",
            "伙伴故事逐只点评",
            "伙伴关系与队伍叙事", "队伍关系与共同故事", "人物呈现与扮演抓手",
            "人物呈现与成长空间", "故事趣味与成长空间",
        }
        max_lines = 90 if title == "伙伴故事逐只点评" else (36 if story_section else 12)
        lines = _lines(self.draw, body, face, CARD_WIDTH - 58, max_lines)
        height = max(110, len(lines) * 45 + 42)
        _rounded(self.draw, (MARGIN, self.y, WIDTH - MARGIN, self.y + height), fill=(255, 253, 248, 238))
        self.draw.multiline_text((MARGIN + 28, self.y + 20), "\n".join(lines), font=face, fill="#343A42", spacing=10)
        self.y += height + 32

    def bullet_section(self, title: str, values: list[str], *, warning: bool = False) -> None:
        self.draw.rounded_rectangle((MARGIN, self.y + 5, MARGIN + 13, self.y + 53), radius=6, fill="#B47B20" if warning else self.accent)
        self.draw.text((MARGIN + 30, self.y), title, font=font(38, bold=True), fill=self.heading_color)
        self.y += 64
        face = font(29)
        wrapped: list[str] = []
        for index, value in enumerate(values, 1):
            prefix = f"{index}. " if warning else "• "
            wrapped.extend(_lines(self.draw, prefix + value, face, CARD_WIDTH - 62, 8))
            wrapped.append("")
        if wrapped:
            wrapped.pop()
        height = max(110, len(wrapped) * 44 + 40)
        fill = (255, 248, 231, 241) if warning else (255, 253, 248, 238)
        outline = "#E2C98C" if warning else "#D7D4CC"
        self.draw.rounded_rectangle((MARGIN, self.y, WIDTH - MARGIN, self.y + height), radius=28, fill=fill, outline=outline, width=2)
        self.draw.multiline_text((MARGIN + 28, self.y + 20), "\n".join(wrapped), font=face, fill=INK, spacing=9)
        self.y += height + 32

    def ella(self) -> None:
        height_face = font(31, bold=True)
        lines = _lines(self.draw, self.review.ella_comment, height_face, CARD_WIDTH - 120, 7)
        height = max(165, len(lines) * 50 + 72)
        self.draw.rounded_rectangle((MARGIN, self.y, WIDTH - MARGIN, self.y + height), radius=32, fill=self.accent, outline=DND_GOLD, width=3)
        self.draw.text((MARGIN + 28, self.y + 20), "妖精评审官 · 艾拉", font=font(29, bold=True), fill="#F6DFAE")
        self.draw.multiline_text((MARGIN + 42, self.y + 67), "\n".join(lines), font=height_face, fill=WHITE, spacing=12)
        self.y += height + 34

    def footer(self) -> None:
        note = "本评审只依据背景故事：角色是否清晰、完整或有趣；不评价战力、配卡与文字篇幅。"
        self.draw.text((MARGIN, self.y), note, font=font(23), fill=self.footer_color)
        self.draw.text((MARGIN, self.y + 38), f"由一键录卡 · 艾拉评审生成 · {self.character.source_filename}", font=font(21), fill=self.footer_color)
        self.y += 100

    def finish(self) -> Image.Image:
        return self.image.crop((0, 0, WIDTH, min(self.y, self.image.height)))


def render_review(character: Character, review: CharacterReview | None = None) -> Image.Image:
    result = review or review_character(character)
    flow = ReviewFlow(character, result)
    flow.header()
    flow.score_summary()
    for section in result.sections:
        flow.section(section.title, section.body)
    flow.bullet_section("写得好的部分", result.highlights)
    flow.bullet_section("有待提升的部分", result.suggestions, warning=True)
    flow.ella()
    flow.footer()
    return flow.finish()


def render_review_png(character: Character, review: CharacterReview | None = None) -> bytes:
    output = io.BytesIO()
    render_review(character, review).save(output, format="PNG", optimize=True)
    return output.getvalue()
