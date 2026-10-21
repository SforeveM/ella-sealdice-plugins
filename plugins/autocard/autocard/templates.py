from __future__ import annotations

from dataclasses import dataclass

from .errors import UnsupportedTemplateError
from .ooxml import Workbook


GENERIC_NAME_LABELS = {
    "角色名", "角色姓名", "姓名", "名字", "人物名", "调查员姓名", "训练家姓名",
}
GENERIC_STORY_LABELS = {
    "人物背景设定", "背景故事", "背景与经历", "角色背景", "人物背景",
    "角色设定", "人物设定", "背景设定", "个人经历",
}

COC_SIMPLIFIED_SHEET_NAMES = ("简化卡 骰娘导入", "简化卡")

POKEMON_COMPANION_ABILITY_LABELS = {"宝可梦能力值", "宝可梦基础能力值"}


def _sheet_labels(sheet: object) -> set[str]:
    if not hasattr(sheet, "iter_cells"):
        return set()
    return {
        str(cell.effective).strip()
        for cell in sheet.iter_cells()
        if cell.effective not in (None, "")
    }


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    name: str
    rule: str
    seal_system: str
    layout: str
    family: str


def identify_template(workbook: Workbook) -> Template:
    sheets = set(workbook.sheets)

    pokemon_trainer = None
    pokemon_sheet_count = 0
    pokemon_current_sheet_count = 0
    for sheet_name, sheet in workbook.sheets.items():
        if not hasattr(sheet, "iter_cells"):
            continue
        labels = {
            str(cell.effective).strip()
            for cell in sheet.iter_cells()
            if cell.effective not in (None, "")
        }
        trainer_structure = (
            {"基础设定", "基础属性", "技能列表", "训练家卡导入"}.issubset(labels)
            or {"基础信息", "基础能力", "技能列表", "训练家卡导入"}.issubset(labels)
        )
        if trainer_structure:
            pokemon_trainer = sheet_name
        if (
            {"战斗招式", "背景与经历"}.issubset(labels)
            and POKEMON_COMPANION_ABILITY_LABELS.intersection(labels)
        ):
            pokemon_sheet_count += 1
            if "宝可梦基础能力值" in labels:
                pokemon_current_sheet_count += 1
    if pokemon_trainer and pokemon_sheet_count:
        version = str(workbook.get(pokemon_trainer, "A1", "")).replace("版本：", "").strip()
        suffix = f"（{version}）" if version else ""
        is_v13 = pokemon_trainer == "训练家" and "基础信息" in {
            str(cell.effective).strip()
            for cell in workbook.sheets[pokemon_trainer].iter_cells()
            if cell.effective not in (None, "")
        }
        is_current = pokemon_current_sheet_count > 0
        template_id = (
            "pokemon-men-v1.3-current"
            if is_current
            else "pokemon-men-v1.3" if is_v13 else "pokemon-men-semi-auto"
        )
        version_name = " V1.3（新版布局）" if is_current else " V1.3" if is_v13 else ""
        return Template(
            template_id,
            f"门版宝可梦TRPG 半自动卡{version_name}{suffix}",
            "POKEMON-TRPG",
            "pokemon",
            "训练家与宝可梦队伍长卡",
            "pokemon",
        )

    coc_simplified_sheet = next(
        (name for name in COC_SIMPLIFIED_SHEET_NAMES if name in sheets),
        "",
    )
    if coc_simplified_sheet and "人物卡" in sheets:
        if "审卡" in sheets:
            return Template("coc7-reviewed", "COC7 空白卡（审卡版）", "COC7", "coc7", "COC 调查员长卡", "coc7")
        if "建卡" in sheets:
            return Template("coc7-2023", "COC7版人物卡 2023ver", "COC7", "coc7", "COC 调查员长卡", "coc7")
        update_marker = str(workbook.get("更新说明", "A1", ""))
        if coc_simplified_sheet == "简化卡" and "19.6.1" in update_marker:
            return Template(
                "coc7-1961", "COC七版规则空白卡 19.6.1",
                "COC7", "coc7", "COC 调查员长卡", "coc7",
            )
        return Template("coc7-cy21", "COC7 CY21.1 空白卡", "COC7", "coc7", "COC 调查员长卡", "coc7")

    title_2024 = str(workbook.get("主要", "A1", ""))
    if "2024" in title_2024 and "5.5E" in title_2024.upper():
        return Template(
            "dnd5r-beiling-359-2024",
            "DND 5E2024 人物卡〈悲灵 v3.5.9〉",
            "DND5E2024", "dnd5e", "DND 冒险者长卡", "dnd",
        )
    if "5E2024" in title_2024.upper():
        return Template("dnd5r-beiling-100", "DND 5E2024 人物卡〈悲灵 v1.0.0〉", "DND5E2024", "dnd5e", "DND 冒险者长卡", "dnd")

    gray_title = str(workbook.get("主要情况", "O1", "") or workbook.get("主状况", "O1", ""))
    if "灰灰" in gray_title and "0.60" in gray_title:
        return Template("dnd5e-gray-060", "DND 5E 人物卡〈灰灰 v0.60〉", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")
    if "灰灰" in gray_title:
        return Template("dnd5e-gray-057", "DND 5E 人物卡〈灰灰 v0.57〉", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")

    tragic_title = str(workbook.get("主要", "A1", ""))
    if "悲灵" in tragic_title:
        if "2014" in tragic_title:
            return Template("dnd5e-beiling-359-2014", "DND 5E 人物卡〈悲灵 v3.5.9·2014〉", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")
        if "网页导入" in sheets:
            return Template("dnd5e-beiling-owlbear", "DND 5E 人物卡〈悲灵·枭熊适配版〉", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")
        return Template("dnd5e-beiling-359", "DND 5E 人物卡〈悲灵 v3.5.9〉", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")

    if "导入海豹骰或梨骰" in sheets:
        update_dimension = workbook.sheets.get("更新日志&在线更新").xml.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension")
        dimension = update_dimension.attrib.get("ref", "") if update_dimension is not None else ""
        v184_marker = str(workbook.get("更新日志&在线更新", "R144", ""))
        version = "v1.84α" if v184_marker or "144" in dimension else "v1.83γ"
        return Template(f"dnd5e-fff-{version}", f"dnd5e人物卡模板 {version}", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")

    if {"角色", "主要情况", "施法", "图表"}.issubset(sheets):
        return Template("dnd5e-fff-v1.82g", "dnd5e人物卡模板 v1.82γ", "DND5E2014", "dnd5e", "DND 冒险者长卡", "dnd")

    # Double Cross sheets are intentionally story-only for now.  The marker
    # combination is stable across the supplied V1.36 workbook and avoids
    # confusing its many rule-data worksheets with ordinary character cards.
    dx_sheet = workbook.sheets.get("角色卡")
    dx_labels = _sheet_labels(dx_sheet) if dx_sheet else set()
    if (
        {"真实身份", "D露易丝", "觉醒表和冲动表"}.issubset(sheets)
        and {"角色名", "人物背景设定"}.issubset(dx_labels)
    ):
        return Template(
            "dx3rd-pc-v136", "Double Cross 3rd PC 半自动卡 V1.36",
            "DX3RD", "story", "背景故事评审卡", "story",
        )

    # Conservative fallback for future niche systems: both a character-name
    # label and an unambiguous story label must occur on the same worksheet.
    # Such cards may be reviewed, but are never exposed as rule-data imports.
    for sheet in workbook.sheets.values():
        labels = _sheet_labels(sheet)
        if labels.intersection(GENERIC_NAME_LABELS) and labels.intersection(GENERIC_STORY_LABELS):
            return Template(
                "story-generic", "小众规则通用背景故事卡",
                "OTHER-TRPG", "story", "背景故事评审卡", "story",
            )

    raise UnsupportedTemplateError(
        "没有识别出受支持的人物卡模板，也未找到可可靠读取的角色名与背景故事字段"
    )
