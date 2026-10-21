from __future__ import annotations

import math
import json
import re
from collections import OrderedDict
from typing import Iterable

from .errors import InvalidWorkbookError
from .models import Character, Number, PokemonCompanion, PokemonMove, Weapon
from .ooxml import Cell, Workbook, split_coordinate
from .templates import (
    COC_SIMPLIFIED_SHEET_NAMES,
    GENERIC_NAME_LABELS,
    GENERIC_STORY_LABELS,
    POKEMON_COMPANION_ABILITY_LABELS,
    Template,
    identify_template,
)


DND_ABILITIES = ("力量", "敏捷", "体质", "智力", "感知", "魅力")
DND_SKILLS = (
    "运动", "体操", "特技", "巧手", "隐匿", "调查", "奥秘", "历史", "自然", "宗教",
    "察觉", "洞悉", "驯兽", "驯养", "医疗", "医药", "求生", "生存", "游说",
    "说服", "欺瞒", "欺诈", "威吓", "表演",
)
DND_SKILL_PARENTS = {
    "运动": "力量", "体操": "敏捷", "巧手": "敏捷", "隐匿": "敏捷",
    "调查": "智力", "奥秘": "智力", "历史": "智力", "自然": "智力", "宗教": "智力",
    "察觉": "感知", "洞悉": "感知", "驯兽": "感知", "医药": "感知", "求生": "感知",
    "游说": "魅力", "欺瞒": "魅力", "威吓": "魅力", "表演": "魅力",
}
DND_SKILL_ALIASES = {
    "特技": "体操", "驯养": "驯兽", "医疗": "医药", "生存": "求生",
    "说服": "游说", "欺诈": "欺瞒",
}
CORE_STATS = {"hp", "hpmax", "ac", "dc", "pp", "pw", "先攻", "熟练", *DND_ABILITIES}
COC_CORE = {
    "STR": "力量", "DEX": "敏捷", "POW": "意志", "CON": "体质", "APP": "外貌",
    "EDU": "教育", "SIZ": "体型", "INT": "智力", "LUCK": "幸运",
}
COC_ALIASES = {
    "str": "力量", "dex": "敏捷", "pow": "意志", "con": "体质", "app": "外貌", "edu": "教育",
    "siz": "体型", "int": "智力", "luck": "幸运", "运气": "幸运", "灵感": "智力", "san值": "san",
    "理智": "san", "理智值": "san", "魔法": "mp", "体力": "hp", "信誉": "信用评级", "信用": "信用评级",
    "克苏鲁": "克苏鲁神话", "cm": "克苏鲁神话", "计算机使用": "计算机", "电脑": "计算机",
    "汽车": "汽车驾驶", "驾驶": "汽车驾驶", "图书馆使用": "图书馆", "撬锁": "开锁", "锁匠": "开锁",
    "自然学": "博物学", "领航": "导航", "重型操作": "操作重型机械", "重型机械": "操作重型机械", "重型": "操作重型机械",
}
EMPTY_TEXT = {
    "", "0", "无", "none", "请选择", "请选择类型", "×", "-", "——", "#REF!", "#NAME?", "#N/A",
    "子职", "lv", "自定义背景", "工具熟练",
}
POKEMON_ABILITIES = ("力量", "体魄", "智识", "意念", "机敏", "魅力", "幸运")
POKEMON_SKILLS = (
    "探查", "采集", "矿物", "植物", "传说", "宝可梦", "制球", "制香", "制药", "锻造",
    "医疗", "机械", "垂钓", "驾驶", "烹调", "运动", "对战", "协调", "骑乘", "表演",
    "声乐", "舞蹈", "绘画", "写作", "格斗术", "忍术", "超能力", "魔术", "潜伏",
    "妙手", "话术", "战斗术",
)
POKEMON_RECORD_NAMES = (
    "hpmax", "hp", "旅行点", "物资点", *POKEMON_ABILITIES, *POKEMON_SKILLS,
)


def _number(value: object) -> Number | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return int(value) if float(value).is_integer() else float(value)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*", value)
        if match:
            parsed = float(match.group(1))
            return int(parsed) if parsed.is_integer() else parsed
    return None


def _canonical_coc_skill_name(name: object) -> str:
    text = _text(name).rstrip("：:").strip()
    # Some COC automatic-card templates append Ω (or a similar glyph) as a
    # proficiency/category marker. It is presentation metadata, not part of
    # the SealDice attribute name.
    text = re.sub(r"\s*[ΩΩ○●◎★☆※✓√✔]+\s*$", "", text).strip()
    return COC_ALIASES.get(text.lower(), COC_ALIASES.get(text, text))


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _clean_identity(value: object) -> str:
    if isinstance(value, (int, float)) and float(value) == 0:
        return ""
    text = _text(value)
    return "" if text.lower() in EMPTY_TEXT or text in {"0.0", "0%"} or text.startswith("请选择") else text


def _story_sheet(workbook: Workbook) -> tuple[str, object] | tuple[None, None]:
    """Find a worksheet containing both identity and story anchors."""
    for sheet_name, sheet in workbook.sheets.items():
        if not hasattr(sheet, "iter_cells"):
            continue
        labels = {
            _text(_effective(cell))
            for cell in sheet.iter_cells()
            if _effective(cell) not in (None, "")
        }
        if labels.intersection(GENERIC_NAME_LABELS) and labels.intersection(GENERIC_STORY_LABELS):
            return sheet_name, sheet
    return None, None


def _label_value(sheet: object, labels: Iterable[str], *, max_distance: int = 8) -> str:
    if not hasattr(sheet, "iter_cells"):
        return ""
    wanted = {str(label).strip() for label in labels}
    all_labels = GENERIC_NAME_LABELS | GENERIC_STORY_LABELS | {
        "玩家ID", "玩家", "行动代号", "代号", "年龄", "性别", "本业", "身份", "血统",
        "症候系统", "出身", "经历", "邂逅", "觉醒", "冲动", "角色名",
    }
    cells = list(sheet.iter_cells())
    by_position = {split_coordinate(cell.address): cell for cell in cells}
    for cell in cells:
        if _text(_effective(cell)) not in wanted:
            continue
        row, column = split_coordinate(cell.address)
        for distance in range(1, max_distance + 1):
            candidate = by_position.get((row, column + distance))
            if candidate is None:
                continue
            value = _clean_identity(_effective(candidate))
            if value and value not in all_labels and not value.startswith("#") and not value.startswith("="):
                return value
    return ""


def _background_value(sheet: object) -> str:
    """Read story text beside/below a story label without sweeping the workbook."""
    if not hasattr(sheet, "iter_cells"):
        return ""
    cells = list(sheet.iter_cells())
    by_position = {split_coordinate(cell.address): cell for cell in cells}
    labels = GENERIC_NAME_LABELS | GENERIC_STORY_LABELS | {
        "玩家ID", "玩家", "行动代号", "代号", "年龄", "性别", "本业", "身份", "血统",
        "症候系统", "出身", "经历", "邂逅", "觉醒", "冲动",
    }

    def usable(cell: Cell | None) -> str:
        value = _clean_identity(_effective(cell)) if cell else ""
        if not value or value in labels or value.startswith(("#", "=")):
            return ""
        return value

    for anchor in cells:
        if _text(_effective(anchor)) not in GENERIC_STORY_LABELS:
            continue
        row, column = split_coordinate(anchor.address)
        # Some templates place the whole story in a merged cell to the right.
        for distance in range(1, 22):
            value = usable(by_position.get((row, column + distance)))
            if value:
                return value
        # DX3rd and many form-style sheets put a large merged writing area
        # directly below the label.  Prefer its top-left value.
        values: list[str] = []
        for row_offset in range(1, 19):
            for column_offset in range(0, 10):
                value = usable(by_position.get((row + row_offset, column + column_offset)))
                if value and value not in values:
                    values.append(value)
            if values and sum(len(value) for value in values) >= 16:
                break
        if values:
            return "\n".join(values[:8])
    return ""


def _extract_story_only(workbook: Workbook, template: Template) -> Character:
    sheet_name, sheet = _story_sheet(workbook)
    if not sheet_name or sheet is None:
        raise InvalidWorkbookError("人物卡缺少可可靠定位的角色名或背景故事字段")

    identity: dict[str, str] = OrderedDict()
    if template.id == "dx3rd-pc-v136":
        # These are the editable top-left cells of the merged input regions in
        # the supplied V1.36 sheet.  Fixed addresses are safer than wandering
        # into the rule tables that begin at column M.
        name = _clean_identity(sheet.get("C11")) or "未命名角色"
        player = _clean_identity(sheet.get("C13"))
        fields = {
            "行动代号": "C12", "年龄": "C15", "性别": "E15", "本业": "G15", "身份": "I15",
            "血统": "B19", "症候系统": "D19", "候选症候": "H19",
            "出身": "D34", "经历": "D35", "邂逅": "D36", "觉醒": "C37", "冲动": "C38",
        }
        for label, address in fields.items():
            value = _clean_identity(sheet.get(address))
            if value:
                identity[label] = value
        backstory = _clean_identity(sheet.get("B80"))
    else:
        name = _label_value(sheet, GENERIC_NAME_LABELS) or "未命名角色"
        player = _label_value(sheet, ("玩家ID", "玩家"), max_distance=6)
        for label in ("行动代号", "年龄", "性别", "本业", "身份", "血统", "症候系统", "出身", "经历", "邂逅", "觉醒", "冲动"):
            value = _label_value(sheet, (label,), max_distance=6)
            if value:
                identity[label] = value
        backstory = _background_value(sheet)
    portrait = workbook.best_portrait((sheet_name, "角色卡"))
    warnings = ["此模板仅支持背景故事评审，不支持一键写入规则属性"]
    if name == "未命名角色":
        warnings.append("人物卡未填写角色名")
    if not backstory:
        warnings.append("人物卡未填写背景故事")
    return Character(
        source_filename=workbook.filename,
        source_format=workbook.format,
        rule=template.rule,
        seal_system=template.seal_system,
        template_id=template.id,
        template_name=template.name,
        layout=template.layout,
        name=name,
        player=player,
        identity=identity,
        backstory=backstory,
        portrait=portrait.data if portrait else None,
        portrait_mime=portrait.mime if portrait else "",
        warnings=warnings,
    )


def _effective(cell: Cell) -> object:
    return cell.effective


def _nearest_right(
    workbook: Workbook,
    sheet_name: str,
    labels: Iterable[str],
    max_distance: int = 18,
    bounds: tuple[int, int, int, int] | None = None,
) -> str:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return ""
    wanted = {label.strip().lower() for label in labels}
    by_position = {split_coordinate(cell.address): cell for cell in sheet.iter_cells()}
    for cell in sheet.iter_cells():
        if _text(_effective(cell)).lower() not in wanted:
            continue
        row, column = split_coordinate(cell.address)
        if bounds:
            min_row, min_column, max_row, max_column = bounds
            if not (min_row <= row <= max_row and min_column <= column <= max_column):
                continue
        for distance in range(1, max_distance + 1):
            candidate = by_position.get((row, column + distance))
            if candidate is None:
                continue
            text = _clean_identity(_effective(candidate))
            if text and text.lower() not in wanted and not text.startswith("="):
                return text
    return ""


def _parse_dnd_command(
    command: str,
) -> tuple[dict[str, Number], dict[str, Number], dict[str, str], dict[str, Number]]:
    attributes: dict[str, Number] = OrderedDict()
    skills: dict[str, Number] = OrderedDict()
    skill_formulas: dict[str, str] = OrderedDict()
    saving_throw_factors: dict[str, Number] = OrderedDict()
    command = command.replace("\n", " ").replace(".dst", " ").replace(".st", " ")
    token = re.compile(r"([^\s:=]+?)\s*[:=]\s*([+-]?\d+(?:\.\d+)?)")
    for match in token.finditer(command):
        raw_name = match.group(1).strip()
        name = re.sub(r"(?:\*2|\*0\.5|\*)$", "", raw_name)
        factor_match = re.search(r"\*(2|0\.5)?$", raw_name)
        factor: Number = 0
        if factor_match:
            factor = _number(factor_match.group(1) or "1") or 0
        value = _number(match.group(2))
        if value is None:
            continue
        lower = name.lower()
        canonical = {"hp": "hp", "hpmax": "hpmax", "ac": "ac", "dc": "dc", "pp": "pp", "pw": "pp"}.get(lower, name)
        canonical = DND_SKILL_ALIASES.get(canonical, canonical)
        if canonical in DND_SKILL_PARENTS:
            parent = DND_SKILL_PARENTS[canonical]
            skill_formulas[canonical] = f"pbCalc({value},{factor},{parent})"
            parent_score = _number(attributes.get(parent))
            proficiency = _number(attributes.get("熟练")) or 0
            if parent_score is None:
                skills[canonical] = value
            else:
                skills[canonical] = math.floor(value + math.floor((parent_score - 10) / 2) + proficiency * factor)
        elif canonical in CORE_STATS:
            attributes[canonical] = value
            if canonical in DND_ABILITIES and factor_match:
                saving_throw_factors[canonical] = factor
        elif len(canonical) <= 12:
            skills[canonical] = value
    # Commands often place 熟练/abilities after skills. Recompute display totals once all values exist.
    proficiency = _number(attributes.get("熟练")) or 0
    for name, formula in skill_formulas.items():
        numbers = re.fullmatch(r"pbCalc\(([-+\d.]+),([-+\d.]+),(.+)\)", formula)
        if not numbers:
            continue
        base = _number(numbers.group(1)) or 0
        factor = _number(numbers.group(2)) or 0
        parent_score = _number(attributes.get(numbers.group(3)))
        if parent_score is not None:
            skills[name] = math.floor(base + math.floor((parent_score - 10) / 2) + proficiency * factor)
    return attributes, skills, skill_formulas, saving_throw_factors


def _parse_coc_command(command: str) -> tuple[dict[str, Number], dict[str, Number]]:
    attributes: dict[str, Number] = OrderedDict()
    skills: dict[str, Number] = OrderedDict()
    text = command.replace(".st", " ")
    for match in re.finditer(r"([A-Za-z\u4e00-\u9fff]+?)(-?\d+(?:\.\d+)?)", text):
        raw = match.group(1)
        value = _number(match.group(2))
        if value is None:
            continue
        canonical = _canonical_coc_skill_name(raw)
        if canonical in {"力量", "敏捷", "意志", "体质", "外貌", "教育", "体型", "智力", "幸运", "hp", "san", "mp"}:
            attributes.setdefault(canonical, value)
        elif 1 <= len(canonical) <= 20:
            skills.setdefault(canonical, value)
    return attributes, skills


def _parse_pokemon_command(command: str) -> tuple[dict[str, Number], dict[str, Number]]:
    attributes: dict[str, Number] = OrderedDict()
    skills: dict[str, Number] = OrderedDict()
    aliases = {
        "HPmax": "hpmax", "HPMAX": "hpmax", "HP": "hp", "TP": "旅行点", "IP": "物资点",
        "知识": "智识", "力气": "力量",
    }
    names = sorted({*POKEMON_RECORD_NAMES, *aliases}, key=len, reverse=True)
    token = re.compile("(" + "|".join(re.escape(name) for name in names) + r")\s*([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
    for match in token.finditer(str(command or "").replace("\n", " ")):
        raw_name = match.group(1)
        canonical = aliases.get(raw_name, aliases.get(raw_name.upper(), raw_name))
        canonical = {"hpmax": "hpmax", "hp": "hp"}.get(canonical.lower(), canonical)
        value = _number(match.group(2))
        if value is None:
            continue
        if canonical in {"hp", "hpmax", "旅行点", "物资点", *POKEMON_ABILITIES}:
            attributes[canonical] = value
        elif canonical in POKEMON_SKILLS:
            skills[canonical] = value
    generic_text = re.sub(r"^\s*\.pst\b", "", str(command or ""), flags=re.IGNORECASE)
    for match in re.finditer(r"([^\d\s+\-]+)\s*([+\-]?\d+(?:\.\d+)?)", generic_text):
        raw_name = match.group(1).strip()
        value = _number(match.group(2))
        if value is None or not raw_name or len(raw_name) > 20:
            continue
        canonical = aliases.get(raw_name, aliases.get(raw_name.upper(), raw_name))
        canonical = {"hpmax": "hpmax", "hp": "hp"}.get(canonical.lower(), canonical)
        if canonical in attributes or canonical in skills:
            continue
        # The compact .pst string has no separators. The generic fallback is
        # only for template-specific skills, so composite fragments such as
        # "TP物资点" and "IP力气" must not become bogus skill names.
        record_markers = ("HPmax", "HP", "TP", "IP", "旅行点", "物资点", "力气", *POKEMON_ABILITIES)
        if any(name.casefold() in raw_name.casefold() for name in record_markers):
            continue
        if canonical in {"hp", "hpmax", "旅行点", "物资点", *POKEMON_ABILITIES}:
            attributes[canonical] = value
        elif not raw_name.startswith("."):
            skills[canonical] = value
    return attributes, skills


def _generic_dnd_values(workbook: Workbook, sheet_name: str) -> tuple[dict[str, Number], dict[str, Number]]:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return {}, {}
    cells = list(sheet.iter_cells())
    positions = {split_coordinate(cell.address): cell for cell in cells}
    abilities: dict[str, Number] = OrderedDict()
    skills: dict[str, Number] = OrderedDict()
    for cell in cells:
        label = _text(_effective(cell))
        parts = label.split()
        if not parts:
            continue
        normalized = parts[0]
        is_ability = normalized in DND_ABILITIES
        is_skill = normalized in DND_SKILLS
        if not is_ability and not is_skill:
            continue
        row, column = split_coordinate(cell.address)
        max_distance = 8 if is_ability else 10
        for distance in range(1, max_distance + 1):
            candidate = positions.get((row, column + distance))
            if candidate is None:
                continue
            value = _number(_effective(candidate))
            if value is None:
                continue
            canonical = DND_SKILL_ALIASES.get(normalized, normalized)
            (abilities if is_ability else skills).setdefault(canonical, value)
            break
    return abilities, skills


def _dnd_command(workbook: Workbook) -> str:
    locations = (
        ("骰娘导入", "B8"), ("导入", "B8"), ("导入海豹骰或梨骰", "B8"),
        ("录卡", "G3"), ("主要", "AV1"), ("主要情况", "AV1"), ("主状况", "AV1"),
    )
    for sheet, address in locations:
        value = _text(workbook.get(sheet, address, ""))
        if (value.startswith(".st") or value.startswith(".dst")) and "#REF!" not in value:
            return value
    return ""


def _complete_dnd_skills(workbook, sheet_name, attributes, skills, formulas, saves, *, owlbear=False):
    """Keep sheet totals while supplying native DND base/proficiency semantics."""
    factors = {}
    sheet = workbook.get_sheet(sheet_name)
    if owlbear and sheet:
        # Owlbear's I column is the final skill total; F is only an extra bonus.
        # Looking for the first number to the right incorrectly picks F when filled.
        half_proficient = _text(sheet.get("H39")) == "是"
        for cell in sheet.iter_cells():
            row, column = split_coordinate(cell.address)
            if column != 3:
                continue
            label = _text(cell.effective)
            name = DND_SKILL_ALIASES.get(label, label)
            marker = _text(sheet.get(f"B{row}"))
            factor = 2 if marker == "🅞" else (1 if marker in {"O", "○", "●"} else 0)
            if name in DND_SKILL_PARENTS:
                total = _number(sheet.get(f"I{row}"))
                if total is not None:
                    skills[name] = total
                    factors[name] = factor or (0.5 if half_proficient else 0)
            elif name in DND_ABILITIES and 13 <= row <= 18:
                saves[name] = factor
    pb = attributes.get("熟练", 2)
    for name, parent in DND_SKILL_PARENTS.items():
        if name in formulas:
            continue
        modifier = math.floor((attributes.get(parent, 10) - 10) / 2)
        total = skills.get(name, modifier)
        factor = factors.get(name, 0)
        base = total - modifier - math.floor(pb * factor)
        skills[name] = total
        formulas[name] = f"pbCalc({base:g},{factor:g},{parent})"
    # A new import must not inherit saving-throw proficiency from the old card.
    for ability in DND_ABILITIES:
        saves.setdefault(ability, 0)


def _collect_plain_inputs(workbook: Workbook, sheet_names: Iterable[str], *, min_length: int = 2, max_items: int = 50) -> list[str]:
    excluded = re.compile(
        r"^(名称|类型|数量|重量|备注|说明|技能|法术|法术名称|职业|种族|角色|玩家|背景|装备|物品|武器|护甲|特性|"
        r"熟练|属性|总值|修正|当前|最大|选择|请|第\d|level|name)$",
        re.IGNORECASE,
    )
    result: list[str] = []
    seen: set[str] = set()
    for name in sheet_names:
        sheet = workbook.get_sheet(name)
        if not sheet:
            continue
        for cell in sheet.iter_cells():
            if cell.formula is not None:
                continue
            value = _clean_identity(cell.value)
            if len(value) < min_length or len(value) > 600 or excluded.match(value):
                continue
            if value in seen or value.startswith(("DND", "人物卡", "角色卡", "作者", "推荐", "右键")):
                continue
            if any(term in value for term in ("点击", "复制", "粘贴", "请选择", "快捷输入", "使用Alt+Enter")):
                continue
            seen.add(value)
            result.append(value)
            if len(result) >= max_items:
                return result
    return result


def _collect_formula_text(workbook: Workbook, sheet_names: Iterable[str], max_items: int = 80) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    excluded = {"法术名称", "法术来源", "职业", "施法时间", "射程", "成分", "持续时间", "专注", "仪式"}
    for name in sheet_names:
        sheet = workbook.get_sheet(name)
        if not sheet:
            continue
        for cell in sheet.iter_cells():
            if cell.formula is None:
                continue
            value = _clean_identity(cell.cached)
            if not value or value in excluded or value in seen or len(value) > 80:
                continue
            if value.startswith(("请选择", "未选择", "说明：", ".st", ".dst", ".nn")):
                continue
            if value.isdigit():
                continue
            seen.add(value)
            result.append(value)
            if len(result) >= max_items:
                return result
    return result


def _collect_region_text(workbook: Workbook, sheet_name: str, top_left: str, bottom_right: str, max_items: int = 60) -> list[str]:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return []
    top, left = split_coordinate(top_left)
    bottom, right = split_coordinate(bottom_right)
    excluded = {
        "名称", "描述", "特性", "特殊能力", "战斗风格专长", "专长", "职业能力", "种族特性", "背景特性",
        "等级", "属性", "熟练", "修正", "调整值", "当前", "最大", "资源", "扩展", "备注", "笔记",
    }
    result: list[str] = []
    seen: set[str] = set()
    for cell in sheet.iter_cells():
        row, column = split_coordinate(cell.address)
        if not (top <= row <= bottom and left <= column <= right):
            continue
        value = _clean_identity(cell.effective)
        if not value or value in excluded or value in seen or re.fullmatch(r"\d+级?", value):
            continue
        if value.startswith(("请选择", "说明：", ".st", ".dst")):
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= max_items:
            break
    return result


def _dnd_items(workbook: Workbook) -> list[str]:
    sheet = workbook.get_sheet("背包")
    if not sheet:
        return []
    addresses: list[str] = []
    for column, start, end in (("B", 5, 14), ("B", 16, 25), ("Y", 5, 25), ("B", 29, 38),
                               ("Y", 29, 38), ("B", 40, 49), ("Y", 40, 49)):
        addresses.extend(f"{column}{row}" for row in range(start, end + 1))
    excluded = {"名称", "工具", "工具速查", "冒险装备", "背包1", "背包2", "次元袋", "无"}
    result: list[str] = []
    for address in addresses:
        value = _clean_identity(sheet.get(address))
        if value and value not in excluded and value not in result:
            result.append(value)
    return result


def _dedupe_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for raw in values:
        value = re.sub(r"\s+", " ", _clean_identity(raw)).strip().replace("_", " ")
        key = value.split(" — ", 1)[0].casefold()
        if not value:
            continue
        if key in seen:
            index = seen[key]
            if " — " in value and " — " not in result[index]:
                result[index] = value
            continue
        seen[key] = len(result)
        result.append(value)
    return result


def _dnd_main_spells(workbook: Workbook, main_sheet: str) -> list[str]:
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return []
    result = _collect_formula_text(workbook, ("法术书",), max_items=100)
    spell_sheet = workbook.get_sheet("施法")
    if spell_sheet:
        excluded = {"", "-", "—", "42", "法术名", "法术名称", "#N/A", "无"}
        for row in range(4, 220):
            value = _clean_identity(spell_sheet.get(f"L{row}"))
            if value not in excluded and not value.startswith("#") and not value.isdigit():
                result.append(value)
    # 悲灵系模板在“主要”页维护无消耗法术、准备法术和已知戏法。
    for column in ("Q", "Y", "AG", "AO"):
        for row in (*range(66, 75), *range(77, 83)):
            value = _clean_identity(sheet.get(f"{column}{row}"))
            if value and value not in {"法术名称", "无消耗法术", "准备法术", "已知戏法"}:
                result.append(value)
    return _dedupe_text(result)


def _dnd5e_359_spells(workbook: Workbook, main_sheet: str) -> list[str]:
    """Read selected spells from the original 2014 悲灵 3.5.9 main page."""
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return []
    result = _dnd_main_spells(workbook, main_sheet)
    excluded = {
        "法术名称", "法术名", "已知戏法", "已准备的法术", "准备法术",
        "无消耗法术", "Lv", "等级", "无", "-", "—",
    }
    # BP: known cantrips; BW/CD/CK: prepared spells; BI: no-cost spells.
    for column, start in (("BP", 41), ("BW", 41), ("CD", 41), ("CK", 41), ("BI", 49)):
        for row in range(start, 80):
            value = _clean_identity(sheet.get(f"{column}{row}"))
            if (
                value
                and value not in excluded
                and not value.startswith("#")
                and _number(value) is None
            ):
                result.append(value)
    return _dedupe_text(result)


def _owlbear_main_items(workbook: Workbook) -> tuple[list[str], list[str]]:
    sheet = workbook.get_sheet("主要")
    if not sheet:
        return [], []
    armor = _clean_identity(sheet.get("L40"))
    items = []
    for row in (*range(42, 52), *range(53, 58)):
        value = _clean_identity(sheet.get(f"L{row}"))
        if value and value not in {"奇物", "消耗品", "稀有度"}:
            items.append(value)
    return _dedupe_text(items), ([armor] if armor else [])


def _paired_feature_text(
    workbook: Workbook,
    sheet_name: str,
    name_column: str,
    description_column: str,
    start: int,
    end: int,
    prefix: str = "",
) -> list[str]:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return []
    values: list[str] = []
    for row in range(start, end + 1):
        name = _clean_identity(sheet.get(f"{name_column}{row}"))
        description = _clean_identity(sheet.get(f"{description_column}{row}"))
        if not name or name in {"名称", "Lv", "特性", "专长", "职业能力", "特殊能力"}:
            continue
        text = (prefix + name) if prefix else name
        if description and description != name:
            text += " — " + description
        values.append(text)
    return _dedupe_text(values)


def _dnd5r_identity(workbook: Workbook, main_sheet: str) -> dict[str, str]:
    profession = _clean_identity(workbook.get(main_sheet, "E6"))
    subclass = _clean_identity(workbook.get(main_sheet, "I6"))
    level = _number(workbook.get(main_sheet, "O6"))
    identity = {
        "职业": profession,
        "子职": subclass,
        "等级": f"Lv{level:g}" if isinstance(level, (int, float)) else "",
        # These values are stored in column T; column U is part of the merged
        # display area and has no independent OOXML value.
        "种族": _clean_identity(workbook.get(main_sheet, "T6")),
        "亚种": _clean_identity(workbook.get(main_sheet, "T7")),
        "阵营": _clean_identity(workbook.get(main_sheet, "T8")),
        "信仰": _clean_identity(workbook.get(main_sheet, "T9")),
        "背景": _clean_identity(workbook.get("起源", "E6")),
    }
    return {key: value for key, value in identity.items() if value}


def _dnd5e_359_identity(workbook: Workbook, main_sheet: str) -> dict[str, str]:
    """Read the original 2014 悲灵 3.5.9 compact identity header."""
    level = _number(workbook.get(main_sheet, "O6"))
    identity = {
        "职业": _clean_identity(workbook.get(main_sheet, "E6")),
        "子职": _clean_identity(workbook.get(main_sheet, "I6")),
        "等级": f"Lv{level:g}" if isinstance(level, (int, float)) else "",
        "种族": _clean_identity(workbook.get(main_sheet, "S3")),
        "亚种": _clean_identity(workbook.get(main_sheet, "S4")),
        "阵营": _clean_identity(workbook.get(main_sheet, "U6")),
        "信仰": _clean_identity(workbook.get(main_sheet, "U7")),
    }
    return {key: value for key, value in identity.items() if value}


def _dnd5r_feats_and_features(workbook: Workbook, main_sheet: str) -> tuple[list[str], list[str]]:
    class_features = _paired_feature_text(workbook, main_sheet, "AX", "BC", 17, 40)
    race_features = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 27, 40)
    feats = _paired_feature_text(workbook, main_sheet, "BU", "BZ", 43, 54)
    fighting_styles = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 57, 68)
    return _dedupe_text([*feats, *fighting_styles]), _dedupe_text([*class_features, *race_features])


def _dnd5r_359_feats_and_features(workbook: Workbook, main_sheet: str) -> tuple[list[str], list[str]]:
    """Read the 2024 rules variant that retains the 悲灵 3.5.9 page layout."""
    class_features = _paired_feature_text(workbook, main_sheet, "AX", "BC", 17, 30)
    race_features = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 6, 16)
    feats = _paired_feature_text(workbook, main_sheet, "BU", "BZ", 19, 30)
    fighting_styles = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 32, 37)
    special_features = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 39, 45)
    return _dedupe_text([*feats, *fighting_styles]), _dedupe_text([
        *class_features, *race_features, *special_features,
    ])


def _dnd5e_359_feats_and_features(workbook: Workbook, main_sheet: str) -> tuple[list[str], list[str]]:
    """Read the compact 2014 feature blocks without entering spell quick-reference cells."""
    class_features = _paired_feature_text(workbook, main_sheet, "AX", "BC", 11, 25)
    race_features = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 3, 12)
    feats = _paired_feature_text(workbook, main_sheet, "BU", "BZ", 15, 25)
    special_features = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 28, 38)
    return _dedupe_text(feats), _dedupe_text([
        *class_features, *race_features, *special_features,
    ])


def _dnd5r_equipment(workbook: Workbook, main_sheet: str) -> tuple[list[Weapon], list[str]]:
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return [], []

    armor: list[str] = []
    armor_base = _clean_identity(sheet.get("L31"))
    armor_name = _clean_identity(sheet.get("R31"))
    if armor_base and armor_base not in {"护甲", "无"}:
        display = armor_name + (f"（{armor_base}）" if armor_name and armor_name != armor_base else "") if armor_name else armor_base
        details = []
        armor_ac = _number(sheet.get("AD31"))
        if armor_ac is not None:
            details.append(f"AC {armor_ac:g}")
        properties = _clean_identity(sheet.get("V31"))
        if properties:
            details.append(properties)
        armor.append(display + ((" | " + " | ".join(details)) if details else ""))

    shield = _clean_identity(sheet.get("AL31"))
    wearing_shield = _clean_identity(sheet.get("AS31"))
    if shield and shield not in {"盾牌", "无"} and wearing_shield not in {"否", "×"}:
        armor.append(shield)

    weapons: list[Weapon] = []
    for row in range(33, 38):
        base_name = _clean_identity(sheet.get(f"L{row}"))
        custom_name = _clean_identity(sheet.get(f"Q{row}"))
        if not base_name or base_name in {"武器", "无"}:
            continue
        display_name = custom_name + (f"（{base_name}）" if custom_name and custom_name != base_name else "") if custom_name else base_name
        attack = _number(sheet.get(f"AF{row}"))
        damage_dice = _clean_identity(sheet.get(f"AH{row}"))
        damage_bonus = _clean_identity(sheet.get(f"AJ{row}"))
        damage_type = _clean_identity(sheet.get(f"AL{row}"))
        damage = damage_dice
        if damage and damage_bonus and damage_bonus not in {"+0", "0"}:
            damage += damage_bonus if damage_bonus.startswith(("+", "-")) else "+" + damage_bonus
        if damage_type:
            damage += (" " if damage else "") + damage_type
        notes = []
        properties = _clean_identity(sheet.get(f"V{row}"))
        mastery = _clean_identity(sheet.get(f"AN{row}"))
        if properties:
            notes.append(properties)
        if mastery:
            notes.append("精通：" + mastery)
        weapons.append(Weapon(display_name, value=attack, damage=damage, notes=" | ".join(notes)))
    return weapons, armor


def _dnd5r_359_equipment(workbook: Workbook, main_sheet: str) -> tuple[list[Weapon], list[str], list[str]]:
    """Read 2024 weapons/armor kept in the older 3.5.9 coordinate layout."""
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return [], [], []

    armor: list[str] = []
    armor_base = _clean_identity(sheet.get("L40"))
    armor_name = _clean_identity(sheet.get("R40"))
    if armor_base and armor_base not in {"护甲", "无", "奇物"}:
        display = armor_name + (f"（{armor_base}）" if armor_name and armor_name != armor_base else "") if armor_name else armor_base
        details = []
        armor_ac = _number(sheet.get("D23"))
        if armor_ac is not None:
            details.append(f"AC {armor_ac:g}")
        properties = _clean_identity(sheet.get("V40"))
        if properties:
            details.append(properties)
        armor.append(display + (" | " + " | ".join(details) if details else ""))

    shield = _clean_identity(sheet.get("AL40"))
    wearing_shield = _clean_identity(sheet.get("AS40"))
    if shield and shield not in {"盾牌", "无"} and wearing_shield not in {"否", "×"}:
        armor.append(shield)

    weapons: list[Weapon] = []
    for row in range(32, 37):
        base_name = _clean_identity(sheet.get(f"B{row}"))
        custom_name = _clean_identity(sheet.get(f"H{row}"))
        if not base_name or base_name in {"武器", "武器类型", "无"}:
            continue
        display_name = custom_name + (f"（{base_name}）" if custom_name and custom_name != base_name else "") if custom_name else base_name
        attack = _number(sheet.get(f"Z{row}"))
        damage = _clean_identity(sheet.get(f"AB{row}"))
        damage_bonus = _clean_identity(sheet.get(f"AD{row}"))
        if damage and damage_bonus and damage_bonus not in {"+0", "0"}:
            damage += damage_bonus if damage_bonus.startswith(("+", "-")) else "+" + damage_bonus
        damage_type = _clean_identity(sheet.get(f"AF{row}"))
        if damage_type:
            damage += (" " if damage else "") + damage_type
        notes = []
        properties = _clean_identity(sheet.get(f"M{row}"))
        mastery = _clean_identity(sheet.get(f"AN{row}"))
        if properties:
            notes.append(properties)
        if mastery:
            notes.append("精通：" + mastery)
        weapons.append(Weapon(display_name, value=attack, damage=damage, notes=" | ".join(notes)))

    equipped_items: list[str] = []
    ammunition = _clean_identity(sheet.get("AK30"))
    ammunition_count = _number(sheet.get("AS30"))
    if ammunition and ammunition not in {"弹药", "无"}:
        equipped_items.append(ammunition + (f" ×{ammunition_count:g}" if ammunition_count is not None else ""))
    return weapons, armor, equipped_items


def _dnd5e_359_equipment(
    workbook: Workbook,
    main_sheet: str,
    attributes: dict[str, Number] | None = None,
) -> tuple[list[Weapon], list[str], list[str]]:
    """Read the original 2014 悲灵 3.5.9 equipment block.

    This layout uses row 32 for armor and rows 34-38 for weapons.  It differs
    from both the 5R page and the 2024 variant that reuses part of the old
    visual layout.
    """
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return [], [], []
    attributes = attributes or {}

    def usable(value: object) -> str:
        text = _clean_identity(value)
        return "" if not text or text.startswith("#") or text in {"-", "—"} else text

    armor: list[str] = []
    armor_base = usable(sheet.get("L32"))
    armor_name = usable(sheet.get("Q32"))
    if armor_base and armor_base not in {"护甲", "无", "奇物"}:
        display = (
            armor_name + (f"（{armor_base}）" if armor_name != armor_base else "")
            if armor_name else armor_base
        )
        details: list[str] = []
        total_ac = _number(attributes.get("ac"))
        armor_ac = total_ac if total_ac is not None else _number(sheet.get("AD32"))
        if armor_ac is not None:
            details.append(f"AC {armor_ac:g}")
        properties = usable(sheet.get("W32"))
        if properties:
            details.append(properties)
        armor.append(display + ((" | " + " | ".join(details)) if details else ""))

    shield = usable(sheet.get("AL32"))
    wearing_shield = usable(sheet.get("AS32"))
    if shield and shield not in {"盾牌", "无"} and wearing_shield not in {"否", "×", "X"}:
        shield_ac = _number(sheet.get("AO32"))
        armor.append(shield + (f" | AC +{shield_ac:g}" if shield_ac is not None else ""))

    weapons: list[Weapon] = []
    equipped_items: list[str] = []
    for row in range(34, 39):
        base_name = usable(sheet.get(f"L{row}"))
        custom_name = usable(sheet.get(f"P{row}"))
        if not base_name or base_name in {"武器", "武器类型", "无"}:
            continue

        reference_row = row - 32
        attack = _number(sheet.get(f"AH{row}"))
        damage_dice = usable(sheet.get(f"AJ{row}")) or usable(workbook.get("装备", f"W{reference_row}"))
        damage_bonus = usable(sheet.get(f"AM{row}")) or usable(workbook.get("装备", f"AB{reference_row}"))
        damage_type = usable(sheet.get(f"AO{row}")) or usable(workbook.get("装备", f"X{reference_row}"))
        properties = usable(sheet.get(f"U{row}")) or usable(workbook.get("装备", f"V{reference_row}"))

        # Spellcasting foci and other non-weapons share the visual block but
        # have no valid damage cache. Preserve them as carried items instead.
        if not damage_dice and not damage_type:
            item_name = custom_name or base_name
            if custom_name and custom_name != base_name:
                item_name += f"（{base_name}）"
            equipped_items.append(item_name)
            continue

        display_name = (
            custom_name + (f"（{base_name}）" if custom_name != base_name else "")
            if custom_name else base_name
        )
        damage = damage_dice
        if damage and damage_bonus and damage_bonus not in {"+0", "0"}:
            damage += damage_bonus if damage_bonus.startswith(("+", "-")) else "+" + damage_bonus
        if damage_type:
            damage += (" " if damage else "") + damage_type

        notes: list[str] = []
        if properties:
            notes.append(properties)
        ammunition = usable(sheet.get(f"AR{row}"))
        ammunition_count = _number(sheet.get(f"AS{row}"))
        if ammunition and ammunition_count is not None and ammunition_count > 0:
            notes.append(f"{ammunition} ×{ammunition_count:g}")
        weapons.append(Weapon(display_name, value=attack, damage=damage, notes=" | ".join(notes)))

    # “其他” equipment rows on the main page are separate from the backpack
    # sheet and otherwise disappear from the rendered card.
    for row in range(40, 50):
        name = usable(sheet.get(f"P{row}"))
        if name and name not in {"名称", "无"}:
            equipped_items.append(name)
    return weapons, armor, _dedupe_text(equipped_items)


def _lookup_nearby_description(workbook: Workbook, sheet_name: str, name: str) -> str:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet or not name:
        return ""
    positions = {split_coordinate(cell.address): cell for cell in sheet.iter_cells()}
    candidates: list[tuple[int, str]] = []
    for cell in sheet.iter_cells():
        if _clean_identity(cell.effective) != name:
            continue
        row, column = split_coordinate(cell.address)
        for distance in range(1, 4):
            candidate = positions.get((row, column + distance))
            description = _clean_identity(candidate.effective) if candidate else ""
            if len(description) >= 16 and description != name:
                # “图表”中背景条目也可能把专长名当作字段值；规则库条目
                # 通常会在说明开头明确写“专长”，应优先于更长的背景文案。
                priority = 1 if "专长" in description[:24] else 0
                candidates.append((priority, description))
    return max(candidates, key=lambda item: (item[0], len(item[1])))[1] if candidates else ""


def _fff_feats_and_features(workbook: Workbook, main_sheet: str) -> tuple[list[str], list[str]]:
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return [], []

    def collect(name_column: str, description_column: str, start: int, end: int) -> list[str]:
        values = []
        for row in range(start, end + 1):
            name = _clean_identity(sheet.get(f"{name_column}{row}"))
            if not name or name in {"名称", "LV", "Lv", "属性值提升/专长", "特殊能力（战技、魔能祈唤等）"}:
                continue
            description = _clean_identity(sheet.get(f"{description_column}{row}"))
            if not description:
                description = _lookup_nearby_description(workbook, "图表", name)
            values.append(name + ((" — " + description) if description and description != name else ""))
        return _dedupe_text(values)

    feats = collect("BN", "BS", 14, 22)
    class_features = collect("AW", "BB", 3, 11)
    race_features = collect("BM", "BS", 3, 11)
    special_features = collect("BN", "BS", 25, 29)
    return feats, _dedupe_text([*class_features, *race_features, *special_features])


def _fff_identity_extras(workbook: Workbook, main_sheet: str) -> dict[str, str]:
    identity: dict[str, str] = {}
    level = _number(workbook.get(main_sheet, "W3"))
    if level is not None:
        identity["等级"] = f"Lv{level:g}"
    gender = _clean_identity(workbook.get("角色", "E7"))
    if gender:
        identity["性别"] = gender
    age_or_alignment = _clean_identity(workbook.get("角色", "M7"))
    if age_or_alignment:
        if any(word in age_or_alignment for word in ("守序", "中立", "混乱", "善良", "邪恶")):
            identity["第二阵营"] = age_or_alignment
        else:
            identity["年龄"] = age_or_alignment
    faith = _clean_identity(workbook.get("角色", "M8"))
    if faith:
        identity["信仰"] = faith
    return identity


def _fff_equipment(workbook: Workbook, main_sheet: str) -> tuple[list[Weapon], list[str], list[str]]:
    sheet = workbook.get_sheet(main_sheet)
    if not sheet:
        return [], [], []
    armor: list[str] = []
    armor_base = _clean_identity(sheet.get("L23"))
    armor_name = _clean_identity(sheet.get("O23"))
    if armor_base or armor_name:
        display = armor_name or armor_base
        if armor_name and armor_base and armor_name != armor_base:
            display += f"（{armor_base}）"
        details = []
        armor_ac = _number(sheet.get("AD23"))
        if armor_ac is not None:
            details.append(f"AC {armor_ac:g}")
        properties = _clean_identity(sheet.get("V23"))
        if properties:
            details.append(properties)
        disadvantage = _clean_identity(sheet.get("AJ23"))
        if disadvantage in {"是", "√", "O"}:
            details.append("隐匿劣势")
        armor.append(display + ((" | " + " | ".join(details)) if details else ""))

    weapons: list[Weapon] = []
    for row in range(25, 30):
        slot = _clean_identity(sheet.get(f"L{row}"))
        name = _clean_identity(sheet.get(f"O{row}"))
        if not name or name in {"名称", "无", "—"}:
            continue
        attack = _number(sheet.get(f"AF{row}"))
        damage = _clean_identity(sheet.get(f"AI{row}"))
        damage_type = _clean_identity(sheet.get(f"AM{row}"))
        if damage_type and damage_type not in {"—", "-"}:
            damage += (" " if damage else "") + damage_type
        notes = []
        properties = _clean_identity(sheet.get(f"U{row}"))
        mastery = _clean_identity(sheet.get(f"Y{row}"))
        if slot and slot not in {"X", "—"}:
            notes.append(slot)
        if properties and properties not in {"—", "-"}:
            notes.append(properties)
        if mastery and mastery not in {"—", "-"}:
            notes.append("精通：" + mastery)
        weapons.append(Weapon(name, value=attack, damage=damage, notes=" | ".join(notes)))

    equipped_items = []
    for row in range(31, 41):
        name = _clean_identity(sheet.get(f"O{row}"))
        if name and name not in {"名称", "无", "—"}:
            equipped_items.append(name)
    return weapons, armor, _dedupe_text(equipped_items)


def _sheet_labels(workbook: Workbook, sheet_name: str) -> set[str]:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return set()
    return {_clean_identity(cell.effective) for cell in sheet.iter_cells() if _clean_identity(cell.effective)}


def _pokemon_trainer_sheet(workbook: Workbook) -> str:
    for sheet_name in workbook.sheet_order:
        labels = _sheet_labels(workbook, sheet_name)
        if (
            {"基础设定", "基础属性", "技能列表", "训练家卡导入"}.issubset(labels)
            or {"基础信息", "基础能力", "技能列表", "训练家卡导入"}.issubset(labels)
        ):
            return sheet_name
    raise InvalidWorkbookError("宝可梦模板缺少训练家工作表")


def _pokemon_command(workbook: Workbook, trainer_sheet: str) -> str:
    sheet = workbook.get_sheet(trainer_sheet)
    if not sheet:
        return ""
    candidates = [
        _text(cell.effective)
        for cell in sheet.iter_cells()
        if _text(cell.effective).lower().startswith(".pst")
    ]
    return max(candidates, key=len) if candidates else ""


def _image_for_sheet(
    workbook: Workbook,
    sheet_name: str,
    *,
    max_row: int | None = None,
    max_column: int | None = None,
):
    candidates = [
        image for image in workbook.embedded_images()
        if image.sheet == sheet_name and image.width >= 120 and image.height >= 120
        and (max_row is None or image.row < max_row)
        and (max_column is None or image.column < max_column)
    ]
    return max(candidates, key=lambda image: image.width * image.height) if candidates else None


def _lookup_table_row(workbook: Workbook, sheet_name: str, key_column: str, key: object) -> dict[str, object]:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet or key in (None, ""):
        return {}
    wanted = str(key).strip()
    row_number = None
    for cell in sheet.iter_cells():
        if not cell.address.startswith(key_column):
            continue
        if str(cell.effective).strip() == wanted:
            row_number = split_coordinate(cell.address)[0]
            break
        number = _number(cell.effective)
        wanted_number = _number(key)
        if number is not None and wanted_number is not None and number == wanted_number:
            row_number = split_coordinate(cell.address)[0]
            break
    if row_number is None:
        return {}
    return {
        re.match(r"[A-Z]+", cell.address).group(): cell.effective
        for cell in sheet.iter_cells()
        if split_coordinate(cell.address)[0] == row_number
    }


def _pokemon_move_reference(workbook: Workbook, name: str) -> dict[str, object]:
    row = _lookup_table_row(workbook, "招式表", "C", name)
    if not row:
        return {}
    return {
        "element": row.get("D"),
        "category": row.get("E"),
        "damage": row.get("G"),
        "accuracy": row.get("I"),
        "ep_cost": row.get("K"),
        "range": row.get("L"),
        "priority": row.get("M"),
        "effect": row.get("N"),
    }


def _valid_formula_result(value: object) -> bool:
    return bool(_clean_identity(value))


def _pokemon_move(
    workbook: Workbook,
    sheet_name: str,
    row: int,
    *,
    right: bool = False,
    current_layout: bool = False,
) -> PokemonMove | None:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return None
    if current_layout and right:
        name = _clean_identity(sheet.get(f"L{row}"))
        element, category, distance = (
            _clean_identity(sheet.get(f"O{row}")),
            _clean_identity(sheet.get(f"Q{row}")),
            _clean_identity(sheet.get(f"S{row}")),
        )
        damage, accuracy = _clean_identity(sheet.get(f"L{row + 1}")), _clean_identity(sheet.get(f"O{row + 1}"))
        ep_cost, priority, effect = _number(sheet.get(f"Q{row + 1}")), _number(sheet.get(f"S{row + 1}")), _clean_identity(sheet.get(f"L{row + 2}"))
    elif current_layout:
        name = _clean_identity(sheet.get(f"C{row}"))
        element, category, distance = (
            _clean_identity(sheet.get(f"F{row}")),
            _clean_identity(sheet.get(f"H{row}")),
            _clean_identity(sheet.get(f"J{row}")),
        )
        damage, accuracy = _clean_identity(sheet.get(f"C{row + 1}")), _clean_identity(sheet.get(f"F{row + 1}"))
        ep_cost, priority, effect = _number(sheet.get(f"H{row + 1}")), _number(sheet.get(f"J{row + 1}")), _clean_identity(sheet.get(f"C{row + 2}"))
    elif right:
        name, accuracy, damage = _clean_identity(sheet.get(f"L{row}")), _clean_identity(sheet.get(f"N{row}")), _clean_identity(sheet.get(f"P{row}"))
        category, element, distance = _clean_identity(sheet.get(f"L{row + 1}")), _clean_identity(sheet.get(f"N{row + 1}")), _clean_identity(sheet.get(f"P{row + 1}"))
        ep_cost, priority, effect = _number(sheet.get(f"S{row + 1}")), _number(sheet.get(f"S{row}")), _clean_identity(sheet.get(f"L{row + 2}"))
    else:
        name, accuracy, damage = _clean_identity(sheet.get(f"C{row}")), _clean_identity(sheet.get(f"E{row}")), _clean_identity(sheet.get(f"G{row}"))
        category, element, distance = _clean_identity(sheet.get(f"C{row + 1}")), _clean_identity(sheet.get(f"E{row + 1}")), _clean_identity(sheet.get(f"G{row + 1}"))
        ep_cost, priority, effect = _number(sheet.get(f"J{row + 1}")), _number(sheet.get(f"J{row}")), _clean_identity(sheet.get(f"C{row + 2}"))
    if not name or name in {"招式", "名称", "名称："}:
        return None
    reference = _pokemon_move_reference(workbook, name)
    category = category if _valid_formula_result(category) and category in {"物理", "特殊", "变化"} else _clean_identity(reference.get("category"))
    element = element if _valid_formula_result(element) else _clean_identity(reference.get("element"))
    accuracy = accuracy if _valid_formula_result(accuracy) else _clean_identity(reference.get("accuracy"))
    damage = damage if _valid_formula_result(damage) else _clean_identity(reference.get("damage"))
    distance = distance if _valid_formula_result(distance) else _clean_identity(reference.get("range"))
    effect = effect if _valid_formula_result(effect) else _clean_identity(reference.get("effect"))
    ep_cost = ep_cost if ep_cost is not None else _number(reference.get("ep_cost"))
    priority = priority if priority is not None else _number(reference.get("priority"))
    return PokemonMove(
        name=name, category=category, element=element, accuracy=accuracy, damage=damage,
        range=distance, ep_cost=ep_cost, priority=priority, effect=effect,
    )


def _pokemon_reference_profile(workbook: Workbook, number: object) -> dict[str, object]:
    return _lookup_table_row(workbook, "编号表", "A", number)


def _pokemon_computed_stats(workbook: Workbook, sheet_name: str, reference: dict[str, object]) -> dict[str, Number]:
    sheet = workbook.get_sheet(sheet_name)
    if not sheet or not reference:
        return {}
    grade_sheet = workbook.get_sheet("其它")
    grade_values: dict[str, Number] = {}
    if grade_sheet:
        for row in range(22, 29):
            label = _clean_identity(grade_sheet.get(f"G{row}"))
            value = _number(grade_sheet.get(f"H{row}"))
            if label and value is not None:
                grade_values[label] = value
    current_layout = "宝可梦基础能力值" in _sheet_labels(workbook, sheet_name)
    bond = _number(sheet.get("F13" if current_layout else "H15")) or 0
    stats: dict[str, Number] = OrderedDict()
    rows = (4, 6, 8, 10, 12, 14)
    reference_columns = ("J", "K", "L", "M", "N", "O")
    grade_rows = (3, 5, 7, 9, 11, 13)
    for index, row in enumerate(rows):
        stat_name = _clean_identity(sheet.get(f"J{row}"))
        base = _number(reference.get(reference_columns[index]))
        if not stat_name or base is None:
            continue
        grade = _clean_identity(sheet.get(f"Q{grade_rows[index]}"))
        grade_adjustment = _number(grade_values.get(grade)) or 0
        normalized = base / (1 + 0.01 * (max(0.0, base - 120) + 0.1) ** 0.8)
        result = normalized * (1 + grade_adjustment / 12) / 6 + 2.2 + bond
        value = math.floor(result * 2 if index == 0 else result)
        change = _number(sheet.get(f"L{row}")) or 0
        stats[stat_name] = value + change
    return stats


def _pokemon_combat_value(sheet: object, label: str) -> Number | None:
    """Read a partner's final accuracy/evasion value from the combat panel.

    Current cards put the final value in column N, while older copies may leave
    that formula blank and expose the base/change/base-bonus columns instead.
    Scanning the J labels keeps this compatible with small row shifts between
    template revisions.
    """
    if not hasattr(sheet, "iter_cells"):
        return None
    for cell in sheet.iter_cells():
        try:
            row, column = split_coordinate(cell.address)
        except ValueError:
            continue
        if column != 10 or _clean_identity(cell.effective) != label:
            continue
        final = _number(sheet.get(f"N{row}"))
        if final is not None:
            return final
        parts = [_number(sheet.get(f"{column_letter}{row}")) for column_letter in ("K", "L", "M")]
        if any(part is not None for part in parts):
            return sum(part or 0 for part in parts)
    return None


def _extract_pokemon_companion(workbook: Workbook, sheet_name: str) -> PokemonCompanion | None:
    labels = _sheet_labels(workbook, sheet_name)
    if not (
        {"战斗招式", "背景与经历"}.issubset(labels)
        and POKEMON_COMPANION_ABILITY_LABELS.intersection(labels)
    ):
        return None
    sheet = workbook.get_sheet(sheet_name)
    if not sheet:
        return None
    current_layout = "宝可梦基础能力值" in labels
    name = _clean_identity(sheet.get("F3"))
    species = _clean_identity(sheet.get("H5"))
    portrait = _image_for_sheet(workbook, sheet_name)
    if not species or species in {"种族", "请选择"} or (not name and portrait is None):
        return None
    name = name if name not in {"名称", "宝可梦"} else ""
    name = name or species
    reference = _pokemon_reference_profile(workbook, sheet.get("F5"))

    types = _dedupe_text([
        _clean_identity(sheet.get("F7")) or _clean_identity(reference.get("C")),
        _clean_identity(sheet.get("F8")) or _clean_identity(reference.get("D")),
    ])
    stats: dict[str, Number] = OrderedDict()
    stat_modifiers: dict[str, Number] = OrderedDict()
    for row in (4, 6, 8, 10, 12, 14):
        stat_name = _clean_identity(sheet.get(f"J{row}"))
        value = _number(sheet.get(f"M{row}"))
        if stat_name and value is not None:
            stats[stat_name] = value
            modifier = _number(sheet.get(f"N{row}"))
            if modifier is not None:
                stat_modifiers[stat_name] = modifier
    for stat_name, value in _pokemon_computed_stats(workbook, sheet_name, reference).items():
        stats.setdefault(stat_name, value)
    hpmax = stats.get("体力")
    hp = _number(sheet.get("F11" if current_layout else "H13"))
    if hp is None:
        hp = hpmax
    move_rows = (27, 33, 40) if current_layout else (26, 30, 35)
    moves = [
        move for row in move_rows
        for move in (
            _pokemon_move(workbook, sheet_name, row, current_layout=current_layout),
            _pokemon_move(workbook, sheet_name, row, right=True, current_layout=current_layout),
        )
        if move is not None
    ]
    story_parts = []
    story_cells = (
        (("形象", "C49"), ("信念", "C52"), ("性格", "C55"), ("经历", "C58"))
        if current_layout
        else (("形象", "C42"), ("信念", "C45"), ("性格", "C48"), ("经历", "C51"))
    )
    for label, address in story_cells:
        value = _clean_identity(sheet.get(address))
        if value and value not in {"效果", "说明"}:
            story_parts.append(f"{label}：{value}")
    features = []
    ability_selector = _clean_identity(sheet.get("H7"))
    ability_index = int(_number(ability_selector) or {
        "第一特性": 1, "第二特性": 2, "隐藏特性": 3, "梦特性": 3,
    }.get(ability_selector, 1))
    ability = _clean_identity(sheet.get("H8")) or _clean_identity(reference.get({1: "E", 2: "F", 3: "G"}.get(ability_index, "E")))
    ability_effect = _clean_identity(sheet.get("C19"))
    if not ability_effect and ability:
        ability_effect = _clean_identity(_lookup_table_row(workbook, "特性表", "B", ability).get("C"))
    item_effect = _clean_identity(sheet.get("D22" if current_layout else "C21"))
    if ability_effect:
        features.append("特性效果 — " + ability_effect)
    if item_effect and item_effect != "效果":
        features.append("道具效果 — " + item_effect)
    held_item = _clean_identity(sheet.get("C22" if current_layout else "H17"))
    if held_item in {"物品", "道具", "请选择"}:
        held_item = ""
    return PokemonCompanion(
        name=name,
        species=species,
        gender=_clean_identity(sheet.get("H3")),
        types=types,
        ability=ability,
        held_item=held_item,
        status="" if current_layout else _clean_identity(sheet.get("F13")),
        bond=_number(sheet.get("F13" if current_layout else "H15")),
        hp=hp,
        hpmax=hpmax,
        ep=_number(sheet.get("H11" if current_layout else "S18")),
        accuracy=_pokemon_combat_value(sheet, "命中"),
        evasion=_pokemon_combat_value(sheet, "闪避"),
        stats=stats,
        stat_modifiers=stat_modifiers,
        moves=moves,
        features=features,
        backstory="\n".join(story_parts),
        portrait=portrait.data if portrait else None,
        portrait_mime=portrait.mime if portrait else "",
    )


def _collapse_pokemon_forms(pokemon: list[PokemonCompanion]) -> list[PokemonCompanion]:
    """Combine alternate-form sheets that describe the same named partner."""
    result: list[PokemonCompanion] = []
    by_name: dict[str, PokemonCompanion] = {}
    for companion in pokemon:
        key = companion.name.strip().casefold()
        base = by_name.get(key)
        same_story = bool(
            base
            and base.backstory.strip()
            and companion.backstory.strip()
            and base.backstory.strip() == companion.backstory.strip()
        )
        if (
            base is None
            or base.species.strip() == companion.species.strip()
            or not same_story
        ):
            result.append(companion)
            by_name.setdefault(key, companion)
            continue

        if not base.held_item and companion.held_item:
            base.held_item = companion.held_item
        if base.accuracy is None and companion.accuracy is not None:
            base.accuracy = companion.accuracy
        if base.evasion is None and companion.evasion is not None:
            base.evasion = companion.evasion
        for stat_name, modifier in companion.stat_modifiers.items():
            base.stat_modifiers.setdefault(stat_name, modifier)
        stat_text = "、".join(
            f"{name}{value:g}" if isinstance(value, (int, float)) else f"{name}{value}"
            for name, value in companion.stats.items()
        )
        detail_parts = [
            f"特性 {companion.ability}" if companion.ability else "",
            f"HP {companion.hp}/{companion.hpmax}" if companion.hpmax is not None else "",
            f"命中 {companion.accuracy}" if companion.accuracy is not None else "",
            f"闪避 {companion.evasion}" if companion.evasion is not None else "",
            stat_text,
        ]
        base_move_names = {move.name for move in base.moves}
        different_moves = [move.name for move in companion.moves if move.name not in base_move_names]
        if different_moves:
            detail_parts.append("差异招式 " + "、".join(different_moves))
        base.features.append(
            f"替换形态·{companion.species or companion.name}："
            + "；".join(part for part in detail_parts if part)
        )
    return result


def _pokemon_attribute_scores(sheet: object) -> dict[str, Number]:
    """Read raw trainer ability scores without replacing writable modifiers."""
    if not hasattr(sheet, "get"):
        return {}
    scores: dict[str, Number] = OrderedDict()
    # The supplied trainer layout uses H/I/J for label, raw score and
    # modifier. Restricting the scan to the top panel avoids matching the
    # similarly shaped skill table farther down the sheet.
    for row in range(1, 20):
        raw_label = _clean_identity(sheet.get(f"H{row}"))
        label = "力量" if raw_label == "力气" else raw_label
        if label not in POKEMON_ABILITIES:
            continue
        value = _number(sheet.get(f"I{row}"))
        if value is not None:
            scores[label] = value
    return scores


def _extract_pokemon(workbook: Workbook, template: Template) -> Character:
    trainer_sheet = _pokemon_trainer_sheet(workbook)
    sheet = workbook.get_sheet(trainer_sheet)
    command = _pokemon_command(workbook, trainer_sheet)
    attributes, skills = _parse_pokemon_command(command)
    attribute_scores = _pokemon_attribute_scores(sheet)
    warnings: list[str] = []
    hpmax = attributes.get("hpmax")
    if "hp" not in attributes and hpmax is not None:
        attributes["hp"] = hpmax
        warnings.append("训练家当前 HP 未填写，录卡时已按满血处理")

    name = _nearest_right(workbook, trainer_sheet, ("姓名：", "姓名"), 4) or trainer_sheet
    player = _nearest_right(workbook, trainer_sheet, ("玩家：", "玩家"), 4)
    identity = {
        "年龄": _nearest_right(workbook, trainer_sheet, ("年龄：", "年龄"), 4),
        "性别": _nearest_right(workbook, trainer_sheet, ("性别：", "性别"), 4),
        "身高": _nearest_right(workbook, trainer_sheet, ("身高：", "身高"), 4),
        "体重": _nearest_right(workbook, trainer_sheet, ("体重：", "体重"), 4),
        "风格": _nearest_right(workbook, trainer_sheet, ("风格：", "风格"), 4),
        "方向": _nearest_right(workbook, trainer_sheet, ("方向：", "方向"), 4),
    }
    identity = {key: value for key, value in identity.items() if value}
    backstory_parts = []
    for label in ("形象描述", "梦想/信念", "性格/特质", "背景/经历"):
        value = _nearest_right(workbook, trainer_sheet, (label,), 6)
        if value:
            backstory_parts.append(f"{label}：{value}")

    excluded_items = {
        "背包", "旅行纪念", "特殊道具", "资金", "携带队伍", "名称：", "种族：", "状态：",
        "正常", "物资点上限", "TXT中转区", "备注栏", "如选开规则相关",
    }
    items: list[str] = []
    for cell in sheet.iter_cells():
        row, column = split_coordinate(cell.address)
        if not (3 <= row <= 62 and 15 <= column <= 19):
            continue
        value = _clean_identity(cell.effective)
        if not value or value in excluded_items or value.startswith(("物资点", "旅行点", "宝可元")):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?(?:TP|IP)", value, flags=re.IGNORECASE):
            continue
        if _number(value) is not None:
            continue
        items.append(value)
    items = _dedupe_text(items)

    pokemon = _collapse_pokemon_forms([
        companion for sheet_name in workbook.sheet_order
        if (companion := _extract_pokemon_companion(workbook, sheet_name)) is not None
    ])
    if pokemon:
        identity["队伍"] = "、".join(
            item.name if not item.species or item.name == item.species else f"{item.name}（{item.species}）"
            for item in pokemon
        )
    else:
        warnings.append("没有读取到已填写的宝可梦队伍")
    if not command:
        warnings.append("训练家页没有可用的 .pst 导入结果，无法可靠录入规则插件")
    portrait = _image_for_sheet(workbook, trainer_sheet, max_row=20, max_column=5)
    return Character(
        source_filename=workbook.filename,
        source_format=workbook.format,
        rule=template.rule,
        seal_system=template.seal_system,
        template_id=template.id,
        template_name=template.name,
        layout=template.layout,
        name=name,
        player=player,
        identity=identity,
        attributes=attributes,
        skills=skills,
        items=items,
        pokemon=pokemon,
        backstory="\n".join(backstory_parts),
        portrait=portrait.data if portrait else None,
        portrait_mime=portrait.mime if portrait else "",
        warnings=warnings,
        attribute_scores=attribute_scores,
    )


def _extract_dnd(workbook: Workbook, template: Template) -> Character:
    main_sheet = "主要" if "主要" in workbook.sheets else ("主状况" if "主状况" in workbook.sheets else "主要情况")
    command = _dnd_command(workbook)
    skill_formulas: dict[str, str] = {}
    saving_throw_factors: dict[str, Number] = {}
    if command:
        attributes, skills, skill_formulas, saving_throw_factors = _parse_dnd_command(command)
    else:
        attributes, skills = _generic_dnd_values(workbook, main_sheet)
    if not all(name in attributes for name in DND_ABILITIES):
        fallback_attributes, fallback_skills = _generic_dnd_values(workbook, main_sheet)
        for key, value in fallback_attributes.items():
            attributes.setdefault(key, value)
        for key, value in fallback_skills.items():
            skills.setdefault(key, value)

    if main_sheet == "主要情况" and "hp" not in attributes:
        hp = _number(workbook.get(main_sheet, "Y8"))
        hpmax = _number(workbook.get(main_sheet, "AC8"))
        ac = _number(workbook.get(main_sheet, "P10"))
        for key, value in (("hp", hp), ("hpmax", hpmax), ("ac", ac)):
            if value is not None:
                attributes[key] = value

    if main_sheet == "主要":
        for key, address in (("hp", "R22"), ("hpmax", "V22"), ("先攻", "D22"), ("ac", "D23"),
                             ("dc", "D24"), ("pp", "L23"), ("熟练", "S3")):
            value = _number(workbook.get(main_sheet, address))
            if value is not None:
                attributes.setdefault(key, value)

    if main_sheet in {"主要", "主状况"}:
        name = _clean_identity(workbook.get(main_sheet, "E3"))
        player = _clean_identity(workbook.get(main_sheet, "E4"))
        identity = {
            "职业": _nearest_right(workbook, main_sheet, ("主职业", "主职")),
            "子职": _nearest_right(workbook, main_sheet, ("子职",)),
            "种族": _nearest_right(workbook, main_sheet, ("种族",)),
            "亚种": _nearest_right(workbook, main_sheet, ("亚种",)),
            "背景": _nearest_right(workbook, "起源" if "起源" in workbook.sheets else "背景", ("背景", "人物背景")),
            "阵营": _nearest_right(workbook, main_sheet, ("阵营",)),
        }
        if template.id in {"dnd5r-beiling-100", "dnd5r-beiling-359-2024"}:
            identity = _dnd5r_identity(workbook, main_sheet)
        elif template.id in {"dnd5e-beiling-359", "dnd5e-beiling-359-2014"}:
            # Preserve the legacy background page while filling the compact
            # identity header from this template's exact coordinates.
            identity.update(_dnd5e_359_identity(workbook, main_sheet))
    else:
        name = _clean_identity(workbook.get(main_sheet, "E3")) or _clean_identity(workbook.get("角色", "E3"))
        player = _clean_identity(workbook.get(main_sheet, "E4")) or _clean_identity(workbook.get("角色", "E4"))
        identity = {
            "职业": _nearest_right(workbook, main_sheet, ("主职业", "主职")),
            "种族": _nearest_right(workbook, "角色", ("种族",)),
            "亚种": _nearest_right(workbook, "角色", ("亚种",)),
            "背景": _nearest_right(workbook, "角色", ("背景",)),
            "阵营": _nearest_right(workbook, "角色", ("阵营",)),
        }
        if template.id.startswith("dnd5e-fff"):
            identity.update(_fff_identity_extras(workbook, main_sheet))

    name = _clean_identity(name) or "未命名角色"
    if template.id == "dnd5r-beiling-100" and player == "悲灵":
        player = ""
    identity = {key: value for key, value in identity.items() if value}
    backstory = ""
    for sheet in ("角色", "背景", "起源"):
        backstory = _nearest_right(workbook, sheet, ("背景故事", "角色背景", "故事"), 30)
        if backstory:
            break
    if not backstory and template.id.startswith("dnd5e-fff"):
        backstory = _clean_identity(workbook.get("角色", "R20"))

    portrait = workbook.best_portrait(("角色", "背景", "起源", main_sheet))
    plain_backpack = _dnd_items(workbook)
    spells = (
        _dnd5e_359_spells(workbook, main_sheet)
        if template.id in {"dnd5e-beiling-359", "dnd5e-beiling-359-2014"}
        else _dnd_main_spells(workbook, main_sheet)
    )
    feats: list[str] = []
    if template.id == "dnd5r-beiling-100":
        feats, features = _dnd5r_feats_and_features(workbook, main_sheet)
    elif template.id == "dnd5r-beiling-359-2024":
        feats, features = _dnd5r_359_feats_and_features(workbook, main_sheet)
    elif template.id in {"dnd5e-beiling-359", "dnd5e-beiling-359-2014"}:
        feats, features = _dnd5e_359_feats_and_features(workbook, main_sheet)
    elif template.id.startswith("dnd5e-gray"):
        feature_text = _collect_region_text(workbook, main_sheet, "BS69", "CN106")
    elif template.id.startswith("dnd5e-fff"):
        feats, features = _fff_feats_and_features(workbook, main_sheet)
    else:
        feature_text = _collect_region_text(workbook, main_sheet, "AW54", "CO149")
    if template.id not in {
        "dnd5r-beiling-100",
        "dnd5r-beiling-359-2024",
        "dnd5e-beiling-359",
        "dnd5e-beiling-359-2014",
    } and not template.id.startswith("dnd5e-fff"):
        identity_values = {name, player, *identity.values()}
        features = [item for item in feature_text if item not in identity_values and item != backstory]

    if template.id == "dnd5r-beiling-100":
        weapons, armor_values = _dnd5r_equipment(workbook, main_sheet)
        armor_value = ""
    elif template.id == "dnd5r-beiling-359-2024":
        weapons, armor_values, equipped_items = _dnd5r_359_equipment(workbook, main_sheet)
        plain_backpack = _dedupe_text([*plain_backpack, *equipped_items])
        armor_value = ""
    elif template.id.startswith("dnd5e-fff"):
        weapons, armor_values, equipped_items = _fff_equipment(workbook, main_sheet)
        plain_backpack = _dedupe_text([*plain_backpack, *equipped_items])
        armor_value = ""
    elif template.id in {"dnd5e-beiling-359", "dnd5e-beiling-359-2014"}:
        weapons, armor_values, equipped_items = _dnd5e_359_equipment(workbook, main_sheet, attributes)
        plain_backpack = _dedupe_text([*plain_backpack, *equipped_items])
        armor_value = ""
    else:
        weapons = []
        for label in ("持用武器", "武器"):
            value = _nearest_right(workbook, main_sheet, (label,), 20)
            if value and value not in {"熟练", "同调", "名称", "特性"}:
                weapons.append(Weapon(name=value))
                break
        armor_value = _nearest_right(workbook, main_sheet, ("护甲",), 20)
        armor_values = [armor_value] if armor_value and armor_value not in {"熟练", "同调", "名称", "特性", "基础AC", "最大敏捷"} else []

    warnings = []

    if template.id == "dnd5e-beiling-owlbear":
        raw_json = _text(workbook.get("网页导入", "B8", ""))
        try:
            obr = json.loads(raw_json)
            obr_identity = obr.get("identity", {})
            name = _clean_identity(obr_identity.get("character_name")) or name
            player = _clean_identity(obr_identity.get("player")) or player
            identity.update({
                "种族": _clean_identity(obr_identity.get("race")),
                "亚种": _clean_identity(obr_identity.get("subrace")),
                "阵营": _clean_identity(obr_identity.get("alignment")),
                "信仰": _clean_identity(obr_identity.get("faith")),
            })
            classes = obr.get("classes", [])
            if classes:
                identity["职业"] = " / ".join(str(item.get("name", "")) for item in classes if item.get("name"))
                subclasses = [str(item.get("sub", "")) for item in classes if item.get("sub")]
                levels = [f"Lv{item.get('level')}" for item in classes if item.get("level") not in (None, "")]
                if subclasses:
                    identity["子职"] = " / ".join(subclasses)
                if levels:
                    identity["等级"] = " / ".join(levels)
            for code, canonical in zip(("str", "dex", "con", "int", "wis", "cha"), DND_ABILITIES):
                value = _number(obr.get("abilities", {}).get(code, {}).get("score"))
                if value is not None:
                    attributes[canonical] = value
            core = obr.get("core_stats", {})
            for key, source in (("熟练", "prof_bonus"), ("先攻", "initiative"), ("ac", "ac"), ("dc", "dc"), ("pp", "passive_perception")):
                value = _number(core.get(source))
                if value is not None:
                    attributes[key] = value
            hp = core.get("hp", {})
            for key, source in (("hp", "current"), ("hpmax", "max")):
                value = _number(hp.get(source))
                if value is not None:
                    attributes[key] = value
            obr_weapons = []
            for item in obr.get("combat", {}).get("weapons", []):
                if item.get("name"):
                    obr_weapons.append(Weapon(item["name"], value=_number(str(item.get("atk", "")).lstrip("+")), damage=str(item.get("damage", "")), notes=str(item.get("props", ""))))
            if obr_weapons:
                weapons = obr_weapons
            armor_name = _clean_identity(obr.get("combat", {}).get("armor", {}).get("name"))
            if armor_name:
                armor_value = armor_name
            obr_items = []
            for item in list(obr.get("wondrous", [])) + list(obr.get("consumables", [])):
                item_name = _clean_identity(item.get("name"))
                if item_name and item_name not in {"消耗品", "名字"}:
                    description = _clean_identity(item.get("props"))
                    obr_items.append(item_name + ((" — " + description) if description else ""))
            main_items, main_armor = _owlbear_main_items(workbook)
            plain_backpack = _dedupe_text([*plain_backpack, *main_items, *obr_items])
            if main_armor and armor_value in {"", "熟练", "同调", "名称", "特性", "基础AC", "最大敏捷"}:
                armor_value = main_armor[0]
            obr_features = []
            for item in obr.get("features", {}).get("special_abilities", []):
                item_name = _clean_identity(item.get("name"))
                if item_name and item_name not in {"名字", "体型", "力量"}:
                    description = _clean_identity(item.get("desc"))
                    obr_features.append(item_name + ((" — " + description) if description else ""))
            class_features = _paired_feature_text(workbook, main_sheet, "AX", "BC", 11, 25)
            race_features = _paired_feature_text(workbook, main_sheet, "BT", "BZ", 3, 8)
            feats = _paired_feature_text(workbook, main_sheet, "BU", "BZ", 18, 30)
            features = _dedupe_text([*class_features, *race_features, *obr_features])
        except (json.JSONDecodeError, TypeError, AttributeError):
            warnings.append("枭熊 JSON 缓存无效，已改用表格字段")
    if template.id not in {
        "dnd5r-beiling-100",
        "dnd5r-beiling-359-2024",
        "dnd5e-beiling-359",
        "dnd5e-beiling-359-2014",
    } and not template.id.startswith("dnd5e-fff"):
        armor_values = [armor_value] if armor_value and armor_value not in {
            "熟练", "同调", "名称", "特性", "基础AC", "最大敏捷",
        } else []
    if not command:
        warnings.append("模板没有可用的骰娘导入缓存，已按字段位置读取")
    _complete_dnd_skills(
        workbook, main_sheet, attributes, skills, skill_formulas, saving_throw_factors,
        owlbear=template.id == "dnd5e-beiling-owlbear" and not command,
    )
    if name == "未命名角色":
        warnings.append("人物卡未填写角色名")
    return Character(
        source_filename=workbook.filename,
        source_format=workbook.format,
        rule=template.rule,
        seal_system=template.seal_system,
        template_id=template.id,
        template_name=template.name,
        layout=template.layout,
        name=name,
        player=player,
        identity=identity,
        attributes=attributes,
        skills=skills,
        skill_formulas=skill_formulas,
        saving_throw_factors=saving_throw_factors,
        weapons=weapons,
        armor=armor_values,
        items=plain_backpack,
        spells=spells,
        feats=feats,
        features=features,
        backstory=backstory,
        portrait=portrait.data if portrait else None,
        portrait_mime=portrait.mime if portrait else "",
        warnings=warnings,
    )


def _coc_simplified_sheet(workbook: Workbook):
    for sheet_name in COC_SIMPLIFIED_SHEET_NAMES:
        sheet = workbook.get_sheet(sheet_name)
        if sheet:
            return sheet
    return None


def _coc_skill_pairs(workbook: Workbook) -> dict[str, Number]:
    sheet = _coc_simplified_sheet(workbook)
    if not sheet:
        return {}
    result: dict[str, Number] = OrderedDict()
    for row in range(3, 90):
        for name_col, value_col in (("N", "Q"), ("T", "W")):
            name = _clean_identity(sheet.get(f"{name_col}{row}"))
            value = _number(sheet.get(f"{value_col}{row}"))
            if not name or value is None:
                continue
            name = _canonical_coc_skill_name(name)
            if name and name not in {"技能", "当前时间"}:
                result[name] = value
    return result


def _coc_profile(workbook: Workbook) -> tuple[str, str, dict[str, str]]:
    def field(*labels: str) -> str:
        # COC profile values sit three cells to the right. A tight bound prevents an
        # empty profile cell from leaking into the attribute panel later in the row.
        return _nearest_right(
            workbook, "人物卡", labels, max_distance=5,
            bounds=(3, 2, 7, 13),
        )

    name = field("姓名") or "未命名角色"
    player = field("玩家")
    identity = {
        "职业": field("职业"),
        "时代": field("时代"),
        "年龄": field("年龄"),
        "性别": field("性别", "性别/性取向"),
        "住地": field("住地"),
        "故乡": field("故乡"),
    }
    return name, player, {key: value for key, value in identity.items() if value}


COC_BACKSTORY_FIELDS = (
    ("个人描述", "C28", "O61"),
    ("思想与信念", "C29", "O63"),
    ("重要之人", "C30", "O65"),
    ("意义非凡之地", "C31", "O67"),
    ("宝贵之物", "C32", "O69"),
    ("特质", "C33", "O71"),
    ("小秘密", "C34", "O73"),
    ("伤口和疤痕", "C35", "O75"),
    ("恐惧症和狂躁症", "C36", "O77"),
)


def _clean_coc_backstory_value(value: object) -> str:
    text = _clean_identity(value)
    if text.startswith("请务必在此填写背景故事"):
        return ""
    return text


def _coc_backstory(workbook: Workbook, simplified: object) -> str:
    """Combine the free-form story and the official COC background prompts."""
    parts: list[str] = []
    free_story = _clean_coc_backstory_value(simplified.get("H28"))
    if not free_story:
        free_story = _clean_coc_backstory_value(workbook.get("人物卡", "M79", ""))
    if free_story:
        parts.append(f"背景故事：{free_story}")

    for label, simplified_address, main_address in COC_BACKSTORY_FIELDS:
        # Direct input cells are preferred because formula caches on the
        # simplified sheet can be stale after editing with non-Excel tools.
        value = _clean_coc_backstory_value(workbook.get("人物卡", main_address, ""))
        if not value:
            value = _clean_coc_backstory_value(simplified.get(simplified_address))
        if value and all(value not in item for item in parts):
            parts.append(f"{label}：{value}")
    return "\n".join(parts)


def _extract_coc(workbook: Workbook, template: Template) -> Character:
    simplified = _coc_simplified_sheet(workbook)
    if not simplified:
        raise InvalidWorkbookError("COC 模板缺少“简化卡”或“简化卡 骰娘导入”工作表")
    attributes: dict[str, Number] = OrderedDict()
    for address, canonical in (("C3", "力量"), ("F3", "敏捷"), ("I3", "意志"), ("L3", "智力"),
                               ("C5", "体质"), ("F5", "外貌"), ("I5", "教育"), ("L5", "体型"),
                               ("I9", "幸运"), ("C7", "hp"), ("F7", "san"), ("I7", "mp")):
        value = _number(simplified.get(address))
        if value is not None:
            attributes[canonical] = value

    name, player, identity = _coc_profile(workbook)
    command_attributes, command_skills = _parse_coc_command(_text(simplified.get("B40")))
    for key, value in command_attributes.items():
        attributes.setdefault(key, value)
    skills = command_skills
    skills.update(_coc_skill_pairs(workbook))
    weapons: list[Weapon] = []
    for row in range(12, 17):
        values = [simplified.get(f"{column}{row}") for column in ("B", "C", "D", "E", "H", "I", "J")]
        name_value = _clean_identity(values[0])
        if not name_value or name_value in {"武器表", "无"}:
            continue
        weapons.append(
            Weapon(
                name=name_value,
                skill="/".join(filter(None, (_clean_identity(values[1]), _clean_identity(values[2])))),
                value=_number(values[3]),
                damage=_clean_identity(values[4]),
                notes=" ".join(filter(None, (_clean_identity(values[5]), _clean_identity(values[6])))),
            )
        )
    items = []
    for row in range(22, 27):
        for column in ("B", "E", "H", "K"):
            item = _clean_identity(simplified.get(f"{column}{row}"))
            if item and item not in items:
                items.append(item)
    backstory = _coc_backstory(workbook, simplified)
    portrait = workbook.best_portrait(("人物卡",))
    warnings = []
    if name == "未命名角色":
        warnings.append("人物卡未填写调查员姓名")
    if not backstory:
        warnings.append("人物卡未填写背景故事或调查员背景栏目")
    return Character(
        source_filename=workbook.filename,
        source_format=workbook.format,
        rule=template.rule,
        seal_system=template.seal_system,
        template_id=template.id,
        template_name=template.name,
        layout=template.layout,
        name=name,
        player=player,
        identity=identity,
        attributes=attributes,
        skills=skills,
        weapons=weapons,
        items=items,
        backstory=backstory,
        portrait=portrait.data if portrait else None,
        portrait_mime=portrait.mime if portrait else "",
        warnings=warnings,
    )


def extract_character(workbook: Workbook) -> Character:
    template = identify_template(workbook)
    if template.family == "coc7":
        return _extract_coc(workbook, template)
    if template.family == "pokemon":
        return _extract_pokemon(workbook, template)
    if template.family == "story":
        return _extract_story_only(workbook, template)
    return _extract_dnd(workbook, template)
