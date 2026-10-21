from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

from PIL import Image

from autocard.assets import icon_path, load_icon
from autocard.extractors import (
    _canonical_coc_skill_name, _coc_profile, _dnd5r_equipment,
    _dnd5r_359_equipment, _dnd5r_359_feats_and_features,
    _dnd5e_359_equipment, _dnd5e_359_feats_and_features, _dnd5e_359_identity,
    _dnd5e_359_spells,
    _dnd5r_feats_and_features, _dnd5r_identity, _dnd_main_spells,
    _extract_pokemon_companion, _pokemon_attribute_scores,
    _fff_equipment, _fff_feats_and_features, _fff_identity_extras,
    _collapse_pokemon_forms, _parse_coc_command, _parse_dnd_command, _parse_pokemon_command,
    extract_character,
)
from autocard.models import Character, PokemonCompanion, PokemonMove, Weapon
from autocard.ooxml import Cell, load_workbook
from autocard.onebot import fetch_file, onebot_bases
from autocard.render import Flow, _portrait_fit, render_file_list, render_png, render_pngs
from autocard.render_review import ReviewFlow, render_review_png
from autocard.review import calculate_pokecoin_charge, review_character
from autocard.service import AutocardServer, Handler
from autocard.templates import identify_template


class CommandParsingTests(unittest.TestCase):
    def test_autocard_review_pokecoin_charge_matches_logai_policy(self) -> None:
        self.assertEqual(calculate_pokecoin_charge(0), 100)
        self.assertEqual(calculate_pokecoin_charge(1), 100)
        self.assertEqual(calculate_pokecoin_charge(50000), 100)
        self.assertEqual(calculate_pokecoin_charge(50001), 200)
        self.assertEqual(calculate_pokecoin_charge(100000), 200)

    def test_pokemon_alternate_forms_are_collapsed_without_losing_stats(self) -> None:
        story = "同一只伙伴的共同经历"
        normal = PokemonCompanion(
            name="巨金怪", species="巨金怪", ability="恒净之躯",
            stats={"攻击": 20}, moves=[PokemonMove(name="彗星拳")], backstory=story,
        )
        mega = PokemonCompanion(
            name="巨金怪", species="超级巨金怪", ability="硬爪", held_item="巨金怪进化石",
            hp=43, hpmax=43, stats={"攻击": 31}, moves=[PokemonMove(name="子弹拳")],
            backstory=story,
        )
        collapsed = _collapse_pokemon_forms([normal, mega])
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed[0].held_item, "巨金怪进化石")
        self.assertIn("超级巨金怪", collapsed[0].features[-1])
        self.assertIn("攻击31", collapsed[0].features[-1])
        self.assertIn("子弹拳", collapsed[0].features[-1])

    def test_dnd_command(self) -> None:
        attributes, skills, formulas, saves = _parse_dnd_command(
            ".st 力量*:14 敏捷:11 体质:14 智力:9 感知:18 魅力:10 hp:10 hpmax:10 ac:18 熟练:2 运动*:4 察觉:6"
        )
        self.assertEqual(attributes["力量"], 14)
        self.assertEqual(attributes["hpmax"], 10)
        self.assertEqual(skills["运动"], 8)
        self.assertEqual(skills["察觉"], 10)
        self.assertEqual(formulas["运动"], "pbCalc(4,1,力量)")
        self.assertEqual(formulas["察觉"], "pbCalc(6,0,感知)")
        self.assertEqual(saves["力量"], 1)

    def test_dx3rd_story_only_card_uses_fixed_input_regions(self) -> None:
        values = {
            "B11": "角色名", "C11": "雨宫凛", "B12": "行动代号", "C12": "夜航者",
            "B13": "玩家ID", "C13": "PL-A", "B15": "年龄", "C15": 17,
            "B35": "经历", "D35": "失去家人", "B79": "人物背景设定",
            "B80": "雨宫凛在事故中觉醒。她一面寻找失踪的姐姐，一面害怕自己的力量再次伤害同伴。",
            # Rule-table labels to prove they are not mistaken for profile text.
            "M11": "正面感情", "M83": "合计", "M85": "纹章",
        }

        class FakeSheet:
            def __init__(self, cells=None):
                self.values = cells or {}

            def get(self, address, default=None):
                return self.values.get(address, default)

            def iter_cells(self):
                return iter([Cell(address, value, None, value) for address, value in self.values.items()])

        class FakeWorkbook:
            filename = "雨宫凛.xlsx"
            format = "xlsx"

            def __init__(self):
                self.sheets = {
                    "角色卡": FakeSheet(values), "真实身份": FakeSheet(), "D露易丝": FakeSheet(),
                    "觉醒表和冲动表": FakeSheet(),
                }

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

            def best_portrait(self, preferred_sheets):
                return None

        character = extract_character(FakeWorkbook())
        self.assertEqual(character.rule, "DX3RD")
        self.assertEqual(character.seal_system, "story")
        self.assertEqual(character.name, "雨宫凛")
        self.assertEqual(character.identity["行动代号"], "夜航者")
        self.assertIn("失踪的姐姐", character.backstory)
        self.assertEqual(character.attributes, {})

    def test_generic_niche_card_extracts_story_but_not_rule_data(self) -> None:
        values = {
            "B2": "角色名", "C2": "灰烬", "B8": "背景故事",
            "B9": "他从一座每天都会改变街道的城镇出发，寻找只有自己还记得的故乡。",
        }

        class FakeSheet:
            def get(self, address, default=None):
                return values.get(address, default)

            def iter_cells(self):
                return iter([Cell(address, value, None, value) for address, value in values.items()])

        class FakeWorkbook:
            filename = "未知规则卡.xlsx"
            format = "xlsx"
            sheets = {"人物": FakeSheet()}

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

            def best_portrait(self, preferred_sheets):
                return None

        character = extract_character(FakeWorkbook())
        self.assertEqual(character.template_id, "story-generic")
        self.assertEqual(character.name, "灰烬")
        self.assertIn("改变街道", character.backstory)
        self.assertEqual(character.preview()["core_attributes"], {})

    def test_dnd_alias_uses_computed_skill(self) -> None:
        _, skills, formulas, _ = _parse_dnd_command(".st 敏捷:14 熟练:2 特技*:1")
        self.assertEqual(skills["体操"], 5)
        self.assertEqual(formulas["体操"], "pbCalc(1,1,敏捷)")

    def test_coc_command_deduplicates_aliases(self) -> None:
        attributes, skills = _parse_coc_command(".st 力量55str55敏捷60dex60意志70pow70侦查65图书馆50")
        self.assertEqual(attributes["力量"], 55)
        self.assertEqual(attributes["敏捷"], 60)
        self.assertEqual(attributes["意志"], 70)
        self.assertEqual(skills["侦查"], 65)
        self.assertEqual(skills["图书馆"], 50)

    def test_coc_skill_aliases_share_one_canonical_name(self) -> None:
        self.assertEqual(_canonical_coc_skill_name("图书馆使用"), "图书馆")
        self.assertEqual(_canonical_coc_skill_name("计算机使用"), "计算机")
        self.assertEqual(_canonical_coc_skill_name("计算机使用 Ω"), "计算机")
        self.assertEqual(_canonical_coc_skill_name("电子学 Ω"), "电子学")
        self.assertEqual(_canonical_coc_skill_name("科学（化学）Ω"), "科学（化学）")

    def test_pokemon_command_recovers_blank_current_hp_without_losing_tp(self) -> None:
        attributes, skills = _parse_pokemon_command(
            ".pst HPmax27HP旅行点21物资点15力量3体魄1智识1意念0机敏2魅力0幸运0探查4战斗术5"
        )
        self.assertNotIn("hp", attributes)
        self.assertEqual(attributes["hpmax"], 27)
        self.assertEqual(attributes["旅行点"], 21)
        self.assertEqual(attributes["物资点"], 15)
        self.assertEqual(attributes["力量"], 3)
        self.assertEqual(skills["探查"], 4)
        self.assertEqual(skills["战斗术"], 5)

    def test_pokemon_command_keeps_template_specific_branch_skills(self) -> None:
        attributes, skills = _parse_pokemon_command(
            ".pst HPmax17HP旅行点10物资点10力量-1体魄-1智识5意念0机敏0魅力2幸运0"
            "探查-2宝可梦6分支②3分支3分支①-2战斗-5话术3"
        )
        self.assertEqual(attributes["旅行点"], 10)
        self.assertEqual(skills["宝可梦"], 6)
        self.assertEqual(skills["分支②"], 3)
        self.assertEqual(skills["分支"], 3)
        self.assertEqual(skills["分支①"], -2)
        self.assertEqual(skills["战斗"], -5)

    def test_pokemon_v13_current_uses_strength_alias_without_composite_skills(self) -> None:
        attributes, skills = _parse_pokemon_command(
            ".pst HPmax20HP20旅行点7TP物资点11IP力气-1体魄0智识2意念3机敏2魅力1幸运0探查4战斗-5"
        )
        self.assertEqual(attributes["力量"], -1)
        self.assertEqual(attributes["旅行点"], 7)
        self.assertEqual(attributes["物资点"], 11)
        self.assertEqual(skills["探查"], 4)
        self.assertEqual(skills["战斗"], -5)
        self.assertNotIn("力气", skills)
        self.assertNotIn("TP物资点", skills)
        self.assertNotIn("IP力气", skills)

    def test_pokemon_v13_current_companion_layout(self) -> None:
        values = {
            "A1": "宝可梦基础能力值", "A2": "战斗招式", "A3": "背景与经历",
            "F3": "闪闪", "H5": "皮卡丘", "F7": "电",
            "J4": "体力", "M4": 22, "N4": 1,
            "J6": "攻击", "M6": 15, "N6": 2,
            "J8": "防御", "M8": 11, "N8": 0,
            "J10": "特攻", "M10": 12, "N10": 1,
            "J12": "特防", "M12": 13, "N12": 1,
            "J14": "速度", "M14": 20, "N14": 5,
            "E11": "当前HP", "F11": 18, "G11": "当前EP", "H11": 88,
            "E13": "牵绊等级", "F13": 3,
            "H7": "第二特性", "H8": "避雷针", "C19": "吸引电属性招式。",
            "B22": "携带物：", "C22": "电气球", "D22": "皮卡丘专用道具。",
            "J20": "闪避", "N20": 6, "J22": "命中", "N22": 1,
            "C27": "电光一闪", "F27": "一般", "H27": "物理", "J27": "临近",
            "C28": "1D8", "F28": "D20+6", "H28": 4, "J28": 1, "C29": "快速冲向目标。",
            "C49": "圆滚滚", "C52": "陪伴训练家", "C55": "认真", "C58": "从小一起长大",
        }

        class FakeSheet:
            def get(self, address, default=None):
                return values.get(address, default)

            def iter_cells(self):
                return iter([Cell(address, value, None, value) for address, value in values.items()])

        class FakeWorkbook:
            def get_sheet(self, name):
                return FakeSheet() if name == "伙伴" else None

            def embedded_images(self):
                return []

        companion = _extract_pokemon_companion(FakeWorkbook(), "伙伴")
        self.assertIsNotNone(companion)
        assert companion is not None
        self.assertEqual(companion.hp, 18)
        self.assertEqual(companion.ep, 88)
        self.assertEqual(companion.bond, 3)
        self.assertEqual(companion.held_item, "电气球")
        self.assertEqual(companion.accuracy, 1)
        self.assertEqual(companion.evasion, 6)
        self.assertEqual(companion.moves[0].name, "电光一闪")
        self.assertEqual(companion.moves[0].damage, "1D8")
        self.assertIn("经历：从小一起长大", companion.backstory)
        self.assertIn("道具效果 — 皮卡丘专用道具。", companion.features)

    def test_pokemon_companion_reads_combat_values_and_stat_modifiers(self) -> None:
        values = {
            "A1": "宝可梦能力值", "A2": "战斗招式", "A3": "背景与经历",
            "F3": "锻珑", "H5": "巨锻匠", "F7": "妖精", "F8": "钢",
            "J4": "体力", "M4": 42, "N4": 8,
            "J6": "攻击", "M6": 20, "N6": 5,
            "J8": "防御", "M8": 20, "N8": 5,
            "J10": "特攻", "M10": 17, "N10": 3,
            "J12": "特防", "M12": 23, "N12": 6,
            "J14": "速度", "M14": 22, "N14": 6,
            "J19": "闪避", "N19": 7, "J21": "命中", "N21": 1,
            "H15": 5, "S18": 97, "C42": "守护同伴",
            "H4": "力量", "I4": 16, "H6": "体魄", "I6": 12,
        }

        class FakeSheet:
            def get(self, address, default=None):
                return values.get(address, default)

            def iter_cells(self):
                return iter([Cell(address, value, None, value) for address, value in values.items()])

        class FakeWorkbook:
            def get_sheet(self, name):
                return FakeSheet() if name == "伙伴" else None

            def embedded_images(self):
                return []

        companion = _extract_pokemon_companion(FakeWorkbook(), "伙伴")
        self.assertIsNotNone(companion)
        assert companion is not None
        self.assertEqual(companion.accuracy, 1)
        self.assertEqual(companion.evasion, 7)
        self.assertEqual(companion.stat_modifiers["体力"], 8)
        self.assertEqual(companion.stat_modifiers["速度"], 6)
        self.assertEqual(_pokemon_attribute_scores(FakeSheet()), {"力量": 16, "体魄": 12})

    def test_coc_profile_is_read_by_labels(self) -> None:
        values = {
            "B3": "姓名", "E3": "W.D. Yu", "B4": "玩家", "E4": "SNOM",
            "B5": "职业", "E5": "警探", "J4": "时代", "M4": "现代",
            "B6": "年龄", "E6": 45, "J6": "性别", "M6": "男",
            "B7": "住地", "E7": "科特兰市", "J7": "故乡", "M7": "美国纽约州",
        }

        class FakeSheet:
            def iter_cells(self):
                return iter([Cell(address, value, None, None) for address, value in values.items()])

        class FakeWorkbook:
            def get_sheet(self, name):
                return FakeSheet() if name == "人物卡" else None

        name, player, identity = _coc_profile(FakeWorkbook())
        self.assertEqual(name, "W.D. Yu")
        self.assertEqual(player, "SNOM")
        self.assertEqual(identity["职业"], "警探")
        self.assertEqual(identity["性别"], "男")

    def test_empty_coc_name_does_not_leak_from_attribute_panel(self) -> None:
        values = {"B3": "姓名", "S3": "力量\nSTR"}

        class FakeSheet:
            def iter_cells(self):
                return iter([Cell(address, value, None, None) for address, value in values.items()])

        class FakeWorkbook:
            def get_sheet(self, name):
                return FakeSheet() if name == "人物卡" else None

        name, player, identity = _coc_profile(FakeWorkbook())
        self.assertEqual(name, "未命名角色")
        self.assertEqual(player, "")
        self.assertEqual(identity, {})

    def test_coc_1961_legacy_sheet_name_records_and_combines_background_fields(self) -> None:
        simplified_values = {
            "C3": 55, "F3": 60, "I3": 70, "L3": 65,
            "C5": 50, "F5": 45, "I5": 75, "L5": 60,
            "I9": 50, "C7": 11, "F7": 70, "I7": 14,
            "B40": ".st 力量55敏捷60意志70智力65体质50外貌45教育75体型60侦查65图书馆55",
            "N13": "侦查", "Q13": 65,
            "B12": "旧左轮", "C12": "射击", "D12": "手枪", "E12": 50, "H12": "1D10",
            "B22": "记者证",
            "H28": "她来到雾港追查一封由失踪父亲寄出的新信。",
            "C28": "总把帽檐压得很低，袖口沾着冲洗药水。",
            "C29": "真相应当被记录，但未必应当立刻公开。",
            "C30": "失踪的父亲，也是她最不愿怀疑的人。",
            "C31": "父亲最后出现的雾港暗房。",
            "C32": "一张曝光过度的家庭合照。",
            "C33": "越害怕时，提问反而越直接。",
            "C34": "她烧掉过一张可能救下同伴的底片。",
            "C35": "左手食指有显影液灼伤。",
            "C36": "害怕没有倒影的镜子。",
        }
        main_values = {
            "B3": "姓名", "C3": "林雾", "B4": "玩家", "C4": "PL-A",
            "B5": "职业", "C5": "调查记者", "E4": "时代", "G4": "现代",
            "B6": "年龄", "C6": 29, "E6": "性别/性取向", "G6": "女",
            "B7": "住地", "C7": "雾港", "E7": "故乡", "G7": "北城",
        }

        class FakeSheet:
            def __init__(self, values=None):
                self.values = values or {}

            def get(self, address, default=None):
                return self.values.get(address, default)

            def iter_cells(self):
                return iter([Cell(address, value, None, value) for address, value in self.values.items()])

        class FakeWorkbook:
            filename = "COC七版规则空白卡19.6.1.xlsx"
            format = "xlsx"

            def __init__(self):
                self.sheets = {
                    "人物卡": FakeSheet(main_values),
                    "简化卡": FakeSheet(simplified_values),
                    "更新说明": FakeSheet({"A1": "2019.6.22更新 版本号：19.6.1"}),
                }

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

            def best_portrait(self, preferred_sheets):
                return None

        character = extract_character(FakeWorkbook())
        self.assertEqual(character.template_id, "coc7-1961")
        self.assertEqual(character.name, "林雾")
        self.assertEqual(character.identity["性别"], "女")
        self.assertEqual(character.attributes["力量"], 55)
        self.assertEqual(character.skills["侦查"], 65)
        self.assertEqual(character.weapons[0].name, "旧左轮")
        self.assertIn("背景故事：她来到雾港", character.backstory)
        self.assertIn("思想与信念：真相应当被记录", character.backstory)
        self.assertIn("小秘密：她烧掉过一张", character.backstory)
        self.assertIn("恐惧症和狂躁症：害怕没有倒影", character.backstory)


class RenderTests(unittest.TestCase):
    def test_group_file_list_renders_without_workbook_data(self) -> None:
        data = render_file_list([
            {
                "filename": "艾拉的角色卡.xlsx",
                "format": "xlsx",
                "size_text": "820 KB",
                "uploader": "玩家A",
                "time_text": "07-26 18:30",
            },
            {
                "filename": "调查员.xls",
                "format": "xls",
                "size_text": "340 KB",
                "uploader": "玩家B",
                "time_text": "07-26 18:42",
            },
        ], "测试群（QQ-Group:123456）")
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.width, 1400)
            self.assertGreater(image.height, 650)
            self.assertLess(image.height, 1100)

    def test_file_list_api_uses_metadata_only_and_serves_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {
            "AUTOCARD_DATA_DIR": str(Path(temp_dir) / "pending"),
            "AUTOCARD_API_TOKEN": "test-token",
            "AUTOCARD_PUBLIC_BASE_URL": "http://list.test",
        }):
            server = AutocardServer(("127.0.0.1", 0), Handler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps({
                    "group_name": "测试群",
                    "files": [{
                        "filename": "安全候选.xlsx",
                        "size_text": "1.2 MB",
                        "uploader": "玩家",
                        "time_text": "07-26 19:00",
                    }, {
                        "filename": "e33ceb90eff90e73d6a04753d1bdafb05fe5c3f53d684720",
                        "format": "xlsx",
                        "size_text": "2.4 MB",
                        "uploader": "官方QQ用户",
                        "time_text": "08-04 15:00",
                    }],
                }, ensure_ascii=False).encode("utf-8")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/v1/file-list",
                    data=body,
                    headers={
                        "Authorization": "Bearer test-token",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertTrue(result["ok"])
                self.assertEqual(result["count"], 2)
                self.assertEqual(result["image_width"], 1400)
                self.assertEqual(result["image_height"], 734)
                image_path = urlsplit(result["image_url"]).path
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}{image_path}",
                    timeout=5,
                ) as response:
                    payload = response.read()
                self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertFalse(any(Path(temp_dir).rglob("source.bin")))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_tall_character_portrait_prefers_upper_part(self) -> None:
        source = Image.new("RGB", (100, 300), "blue")
        source.paste("red", (0, 0, 100, 100))
        cropped = _portrait_fit(source, (100, 100))
        red, _, blue = cropped.getpixel((50, 50))
        self.assertGreater(red, blue)

    def test_render_is_valid_png(self) -> None:
        character = Character(
            source_filename="test.xlsx",
            source_format="xlsx",
            rule="DND5E2014",
            seal_system="dnd5e",
            template_id="test",
            template_name="测试模板",
            layout="DND 冒险者长卡",
            name="测试角色",
            identity={"职业": "战士 Lv3", "种族": "人类", "阵营": "中立善良"},
            attributes={"力量": 16, "敏捷": 12, "体质": 14, "智力": 10, "感知": 11, "魅力": 8, "hp": 28, "hpmax": 28, "ac": 18},
            skills={"运动": 5, "察觉": 2},
            weapons=[Weapon("长剑", value=5, damage="1d8+3")],
            armor=["链甲"],
            items=["冒险者套组"],
            backstory="来自边境的守卫。",
        )
        data = render_png(character)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.width, 1600)
            self.assertGreater(image.height, 900)
            self.assertLess(image.height, 2400)

    def test_skill_proficiency_can_be_inferred_from_totals(self) -> None:
        character = Character(
            source_filename="test.xlsx", source_format="xlsx", rule="DND5E2014",
            seal_system="dnd5e", template_id="test", template_name="测试模板",
            layout="DND 冒险者长卡", name="测试角色",
            attributes={"力量": 14, "感知": 18, "熟练": 2},
            skills={"运动": 2, "察觉": 6},
        )
        flow = Flow(character)
        self.assertEqual(flow._skill_proficiency("运动"), (0.0, "力量"))
        self.assertEqual(flow._skill_proficiency("察觉"), (1.0, "感知"))

    def test_review_scores_background_only_and_renders_png(self) -> None:
        character = Character(
            source_filename="cleric.xlsx", source_format="xlsx", rule="DND5E2014",
            seal_system="dnd5e", template_id="test", template_name="测试模板",
            layout="DND 冒险者长卡", name="艾莫斯·卡罗", player="SNOM",
            identity={"职业": "牧师", "子职": "暮光领域", "等级": "Lv1", "种族": "人类", "背景": "银毫学生", "阵营": "中立善良"},
            attributes={"力量": 14, "敏捷": 11, "体质": 14, "智力": 9, "感知": 18, "魅力": 10,
                        "hp": 10, "hpmax": 10, "ac": 18, "dc": 10, "pp": 16, "熟练": 2},
            skills={name: value for name, value in zip(
                ("运动", "体操", "巧手", "隐匿", "调查", "奥秘", "历史", "自然", "宗教", "察觉", "洞悉", "驯兽", "医药", "求生", "游说", "欺瞒", "威吓", "表演"),
                (2, 0, 0, 0, -1, -1, -1, -1, -1, 6, 6, 4, 6, 4, 2, 0, 2, 0),
            )},
            weapons=[Weapon("战锤", value=4, damage="1d8+2", notes="军用武器")],
            armor=["链甲"], items=["探索套组", "圣徽", "墨水"], spells=["神导术", "治愈真言"],
            feats=["魔法学徒"], features=["施法", "黑夜明目", "警觉赐福"],
            backstory=(
                "艾莫斯在银毫学院学习神学与奥术，平日温柔却很怕自己无法救下重要的人。"
                "为了治愈生病的发小，他循着一封没有署名的信踏上旅途；但信中要求他在真相与朋友的安全之间选择。"
                "离校那夜，他对发小说：“等我回来，我们再一起看晨光。”他至今不知道寄信者为什么了解两人的秘密。"
            ),
            warnings=["模板没有可用的骰娘导入缓存，已按字段位置读取"],
        )
        review = review_character(character)
        self.assertGreaterEqual(review.total_score, 85)
        self.assertEqual([section.title for section in review.sections], [
            "背景故事梗概", "原文细读与人物拆解",
            "人物呈现与扮演抓手", "故事趣味与成长空间",
        ])
        self.assertIn("银毫学院", review.sections[0].body)
        self.assertIn("治愈生病的发小", review.sections[1].body)
        self.assertGreaterEqual(review.sections[1].body.count("“"), 3)
        self.assertTrue(any("“" in item and "”" in item for item in review.highlights))
        self.assertGreaterEqual(review.clarity_score, 80)
        self.assertGreaterEqual(review.interest_score, 80)
        self.assertFalse(any("施法" in item or "法术 DC" in item or "武器" in item for item in review.suggestions))
        self.assertLessEqual(len(review.ella_comment), 20)
        self.assertNotIn("艾拉说", review.ella_comment)
        flow = ReviewFlow(character, review)
        self.assertIn(flow.background_variant, (1, 2, 3))
        data = render_review_png(character, review)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.width, 1600)
            self.assertGreater(image.height, 1500)

    def test_ai_review_uses_configured_temperature_and_persona_contract(self) -> None:
        character = Character(
            source_filename="story.xlsx", source_format="xlsx", rule="COC7",
            seal_system="coc7", template_id="test", template_name="测试模板",
            layout="调查员卡", name="林雾",
            backstory="林雾为了寻找失踪的姐姐来到港城，却发现姐姐可能主动加入了调查组织。她必须在信任与追问之间选择。",
        )
        result = {
            "clarity_score": 88,
            "completeness_score": 84,
            "interest_score": 91,
            "verdict": "人物关系与两难都很鲜明",
            "sections": [
                {"title": "故事梗概", "body": "林雾循着姐姐的失踪来到港城。"},
                {"title": "原文细读", "body": "“信任与追问之间选择”让亲情成为会影响行动的矛盾。"},
            ],
            "highlights": ["姐姐既是目标，也是冲突来源。"],
            "suggestions": ["补充姐妹最后一次正常交谈的细节。"],
            "ella_comment": "艾拉说：这份牵挂很真，我想继续听下去呀",
        }
        envelope = {
            "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500},
        }
        seen = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(envelope, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout):
            seen["timeout"] = timeout
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        environment = {
            "AUTOCARD_REVIEW_AI_URL": "http://127.0.0.1:9999/v1",
            "AUTOCARD_REVIEW_AI_MODEL": "review-model",
            "AUTOCARD_REVIEW_AI_KEY": "secret",
            "AUTOCARD_REVIEW_TEMPERATURE": "1.15",
        }
        with patch.dict(os.environ, environment, clear=False), patch(
            "autocard.review.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            review = review_character(character)

        self.assertEqual(seen["body"]["temperature"], 1.15)
        self.assertIn("15厘米", seen["body"]["messages"][0]["content"])
        self.assertEqual(review.total_score, 88)
        self.assertLessEqual(len(review.ella_comment), 20)
        self.assertNotIn("艾拉说", review.ella_comment)
        self.assertEqual(review.sections[1].title, "原文细读")
        self.assertEqual(review.review_source, "ai")
        self.assertEqual(review.prompt_tokens, 1200)
        self.assertEqual(review.completion_tokens, 300)
        self.assertEqual(review.total_tokens, 1500)
        self.assertFalse(review.token_usage_estimated)

    def test_ai_review_estimates_usage_when_provider_omits_usage(self) -> None:
        character = Character(
            source_filename="story.xlsx", source_format="xlsx", rule="COC7",
            seal_system="coc7", template_id="test", template_name="测试模板",
            layout="调查员卡", name="林雾", backstory="为了寻找姐姐，她来到港城调查真相。",
        )
        result = {
            "clarity_score": 80, "completeness_score": 80, "interest_score": 80,
            "verdict": "故事已有清楚方向",
            "sections": [
                {"title": "故事梗概", "body": "林雾寻找姐姐。"},
                {"title": "人物拆解", "body": "行动目标清楚。"},
            ],
            "highlights": ["目标明确"], "suggestions": ["补充关系"], "ella_comment": "继续追下去吧",
        }
        envelope = {"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(envelope, ensure_ascii=False).encode("utf-8")

        environment = {
            "AUTOCARD_REVIEW_AI_URL": "http://127.0.0.1:9999/v1",
            "AUTOCARD_REVIEW_AI_MODEL": "review-model",
            "AUTOCARD_REVIEW_AI_KEY": "secret",
        }
        with patch.dict(os.environ, environment, clear=False), patch(
            "autocard.review.urllib.request.urlopen", return_value=FakeResponse()
        ):
            review = review_character(character)
        self.assertEqual(review.review_source, "ai")
        self.assertTrue(review.token_usage_estimated)
        self.assertGreater(review.total_tokens, 0)

    def test_ai_review_accepts_sealdice_request_config(self) -> None:
        character = Character(
            source_filename="story.xlsx", source_format="xlsx", rule="COC7",
            seal_system="coc7", template_id="test", template_name="测试模板",
            layout="调查员卡", name="林雾", backstory="为了寻找姐姐，她来到港城调查真相。",
        )
        result = {
            "clarity_score": 80, "completeness_score": 80, "interest_score": 80,
            "verdict": "故事已有清楚方向",
            "sections": [
                {"title": "故事梗概", "body": "林雾寻找姐姐。"},
                {"title": "人物拆解", "body": "行动目标清楚。"},
            ],
            "highlights": ["目标明确"], "suggestions": ["补充关系"], "ella_comment": "继续追下去吧",
        }
        envelope = {
            "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
        seen = {}

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit): return json.dumps(envelope, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["authorization"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch.dict(os.environ, {}, clear=True), patch(
            "autocard.review.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            review = review_character(character, {
                "api_url": "https://ai.example.com/v1",
                "api_key": "sk-from-sealdice",
                "model": "review-from-sealdice",
            })
        self.assertEqual(seen["url"], "https://ai.example.com/v1/chat/completions")
        self.assertEqual(seen["authorization"], "Bearer sk-from-sealdice")
        self.assertEqual(seen["body"]["model"], "review-from-sealdice")
        self.assertEqual(review.review_source, "ai")
        self.assertEqual(review.total_tokens, 120)

    def test_review_does_not_score_by_background_length(self) -> None:
        story = "为了寻找失踪的朋友，他循着神秘传闻踏上旅途，但始终没有找到真相。"
        character = Character(
            source_filename="long.xlsx", source_format="xlsx", rule="DND5E2014",
            seal_system="dnd5e", template_id="test", template_name="测试模板",
            layout="DND 冒险者长卡", name="长故事角色",
            identity={"职业": "游侠", "等级": "Lv1", "种族": "人类", "背景": "向导", "阵营": "中立善良"},
            attributes={"力量": 10, "敏捷": 16, "体质": 14, "智力": 10, "感知": 16, "魅力": 10,
                        "hp": 12, "hpmax": 12, "ac": 15, "dc": 13, "pp": 15, "熟练": 2},
            backstory=story * 40,
        )
        review = review_character(character)
        character.backstory = story
        short_review = review_character(character)
        self.assertGreater(review.story_length, 1000)
        self.assertEqual(review.total_score, short_review.total_score)
        self.assertEqual(review.clarity_score, short_review.clarity_score)
        self.assertFalse(any("1000" in item or "字数" in item or "压缩" in item for item in review.suggestions))

    def test_template_like_story_gets_only_a_personal_voice_reminder(self) -> None:
        character = Character(
            source_filename="story.xlsx", source_format="xlsx", rule="COC7",
            seal_system="coc7", template_id="test", template_name="测试模板",
            layout="调查员卡", name="调查员",
            backstory=(
                "一、角色起源：值得注意的是，他在故乡长大。\n"
                "二、人物成长：综上所述，这一经历使他成长与蜕变。\n"
                "三、主要目标：这不仅让他决定调查真相，也埋下了伏笔。\n"
                "四、未来方向：与此同时，他将在这个过程中承担责任与担当。"
            ),
        )
        review = review_character(character)
        joined = "\n".join(review.suggestions)
        self.assertIn("属于角色自己的细节", joined)
        self.assertNotIn("AI", joined)
        self.assertNotIn("人工智能", joined)
        self.assertNotIn("检测", joined)

    def test_pokemon_team_renders_and_gets_story_first_review(self) -> None:
        portrait = io.BytesIO()
        Image.new("RGB", (320, 320), "#E65A62").save(portrait, format="PNG")
        character = Character(
            source_filename="pokemon.xlsx", source_format="xlsx", rule="POKEMON-TRPG",
            seal_system="pokemon", template_id="pokemon-men-semi-auto",
            template_name="门版宝可梦TRPG 半自动卡", layout="训练家与宝可梦队伍长卡",
            name="叙世", player="玩家", identity={"年龄": "16", "风格": "探索", "方向": "冒险"},
            attributes={"力量": 3, "体魄": 1, "智识": 1, "意念": 0, "机敏": 2, "魅力": 0, "幸运": 0,
                        "hp": 27, "hpmax": 27, "旅行点": 21, "物资点": 15},
            skills={"探查": 4, "采集": -1, "锻造": 1, "战斗术": 5, "妙手": 0, "话术": 0},
            items=["雨衣", "睡袋"],
            backstory="为了和伙伴们成为新的传奇，他离开故乡踏上旅途。虽然总会闯祸，但会为每一次选择负责，并想守护所有同伴。" * 4,
            portrait=portrait.getvalue(), portrait_mime="image/png",
            pokemon=[PokemonCompanion(
                name="锻珑", species="巨锻匠", gender="♀", types=["妖精", "钢"], ability="我行我素",
                bond=5, hp=42, hpmax=42, ep=97,
                stats={"体力": 42, "攻击": 20, "防御": 20, "特攻": 17, "特防": 23, "速度": 22},
                moves=[PokemonMove("金属爪", "物理", "钢", "d20+5", "1d10", "近身1", 4, 0)],
                backstory="她希望用自己的锤子守护同伴，也想改变族群中欺压弱者的传统。与训练家相遇后，她决定一起寻找传说之锤。" * 3,
                portrait=portrait.getvalue(), portrait_mime="image/png",
            )],
        )
        character.pokemon.append(PokemonCompanion(
            name="走路草", species="走路草", held_item="花朵香薰",
            stats={"体力": 20, "攻击": 8, "防御": 10, "特攻": 12, "特防": 11, "速度": 7},
            moves=[PokemonMove("溶解液")],
        ))
        card = render_png(character)
        with Image.open(io.BytesIO(card)) as image:
            self.assertEqual(image.width, 1600)
            self.assertGreater(image.height, 900)
            self.assertLess(image.height, 2200)
        team_cards = render_pngs(character)
        self.assertEqual(len(team_cards), 3)
        for payload in team_cards:
            with Image.open(io.BytesIO(payload)) as image:
                self.assertEqual(image.width, 1600)
                self.assertLess(image.height, 2200)
        review = review_character(character)
        self.assertEqual([section.title for section in review.sections[:5]], [
            "训练家故事梗概", "训练家原文细读", "伙伴故事逐只点评",
            "队伍关系与共同故事", "人物呈现与成长空间",
        ])
        companion_section = next(section for section in review.sections if section.title == "伙伴故事逐只点评")
        self.assertIn("锻珑", companion_section.body)
        self.assertIn("力量如何用来守护而非欺压", companion_section.body)
        self.assertIn("走路草", companion_section.body)
        self.assertIn("花朵香薰", companion_section.body)
        self.assertTrue(any("走路草尚未填写独立背景" in item for item in review.suggestions))
        self.assertLessEqual(review.total_score, 98)
        self.assertTrue(any("伙伴" in item or "锻珑" in item for item in review.highlights))
        review_card = render_review_png(character, review)
        self.assertTrue(review_card.startswith(b"\x89PNG\r\n\x1a\n"))


class Dnd5rLayoutTests(unittest.TestCase):
    def test_identity_features_feats_and_equipment(self) -> None:
        main_values = {
            "E6": "战士", "I6": "灵能武士", "O6": 5,
            "T6": "龙裔", "T7": "红龙", "T8": "混乱中立", "T9": "提亚马特",
            "AX17": "战斗风格", "BC17": "获得一种战斗风格。",
            "BT30": "龙族血统", "BZ30": "你的血脉来自巨龙。",
            "BU43": "凶蛮打手", "BZ43": "每回合一次重掷武器伤害。",
            "BT57": "防御", "BZ57": "着装护甲时AC+1。",
            "L31": "链甲", "AD31": 16, "V31": "隐匿劣势，力量需求13",
            "L33": "巨剑", "Q33": "大剑！", "AF33": "+8", "AH33": "2d6",
            "AJ33": "+5", "AL33": "挥砍", "AN33": "擦掠", "V33": "重型，双手",
        }
        origin_values = {"E6": "骑士团成员"}

        class DictSheet:
            def __init__(self, values):
                self.values = values

            def get(self, address, default=None):
                return self.values.get(address, default)

        class FakeWorkbook:
            def __init__(self):
                self.sheets = {"主要": DictSheet(main_values), "起源": DictSheet(origin_values)}

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

        workbook = FakeWorkbook()
        identity = _dnd5r_identity(workbook, "主要")
        self.assertEqual(identity["职业"], "战士")
        self.assertEqual(identity["等级"], "Lv5")
        self.assertEqual(identity["种族"], "龙裔")
        self.assertEqual(identity["亚种"], "红龙")
        self.assertEqual(identity["阵营"], "混乱中立")
        feats, features = _dnd5r_feats_and_features(workbook, "主要")
        self.assertEqual([item.split(" — ", 1)[0] for item in feats], ["凶蛮打手", "防御"])
        self.assertEqual([item.split(" — ", 1)[0] for item in features], ["战斗风格", "龙族血统"])
        weapons, armor = _dnd5r_equipment(workbook, "主要")
        self.assertEqual(weapons[0].name, "大剑！（巨剑）")
        self.assertEqual(weapons[0].value, 8)
        self.assertEqual(weapons[0].damage, "2d6+5 挥砍")
        self.assertEqual(armor[0], "链甲 | AC 16 | 隐匿劣势，力量需求13")

    def test_359_2024_variant_detection_features_and_equipment(self) -> None:
        main_values = {
            "A1": "DND 5.5E 人物卡<悲灵ver.>（2024）",
            "AX17": "施法", "BC17": "你学会施展游侠法术。",
            "BT6": "黑暗视觉", "BZ6": "你拥有60尺黑暗视觉。",
            "BU19": "魔法学徒", "BZ19": "你习得两道戏法和一道一环法术。",
            "B32": "长弓", "M32": "弹药，重型，双手", "Z32": "+6",
            "AB32": "1d8", "AD32": "+4", "AF32": "穿刺", "AN32": "缓速",
            "L40": "镶钉皮甲", "D23": 16, "AS40": "否",
            "AK30": "箭矢", "AS30": 20,
        }

        class DictSheet:
            def __init__(self, values):
                self.values = values

            def get(self, address, default=None):
                return self.values.get(address, default)

        class FakeWorkbook:
            def __init__(self):
                self.sheets = {"主要": DictSheet(main_values)}

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

        workbook = FakeWorkbook()
        template = identify_template(workbook)
        self.assertEqual(template.id, "dnd5r-beiling-359-2024")
        self.assertEqual(template.rule, "DND5E2024")
        feats, features = _dnd5r_359_feats_and_features(workbook, "主要")
        self.assertEqual([item.split(" — ", 1)[0] for item in feats], ["魔法学徒"])
        self.assertEqual([item.split(" — ", 1)[0] for item in features], ["施法", "黑暗视觉"])
        weapons, armor, items = _dnd5r_359_equipment(workbook, "主要")
        self.assertEqual(weapons[0], Weapon("长弓", value=6, damage="1d8+4 穿刺", notes="弹药，重型，双手 | 精通：缓速"))
        self.assertEqual(armor, ["镶钉皮甲 | AC 16"])
        self.assertEqual(items, ["箭矢 ×20"])


class Dnd5e359LayoutTests(unittest.TestCase):
    def test_original_2014_identity_spells_feats_and_features(self) -> None:
        main_values = {
            "E6": "邪术师", "I6": "至高妖精", "O6": 1,
            "S3": "精灵", "S4": "雅灵", "U6": "中立善良", "U7": "莎罕妮",
            "BP41": "魔能爆", "BP42": "次级幻影",
            "BW41": "妖火", "BW42": "睡眠术",
            "BI48": "法术名称", "BI49": "迷踪步",
            "AX11": "妖精仪态", "BC11": "你散发出妖精荒野的超然气质。",
            "BT3": "生物种类", "BZ3": "你是类人生物。",
            "BU15": "幸运（受宠者）", "BZ15": "命运会在关键时刻眷顾你。",
            # This spell quick-reference text must not leak into features.
            "AX54": "法术简易速查", "BC54": "法术效果",
        }
        background_values = {"E6": "受宠者"}

        class DictSheet:
            def __init__(self, values):
                self.values = values

            def get(self, address, default=None):
                return self.values.get(address, default)

        class FakeWorkbook:
            def __init__(self):
                self.sheets = {
                    "主要": DictSheet(main_values),
                    "背景": DictSheet(background_values),
                }

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

        workbook = FakeWorkbook()
        identity = {"背景": "受宠者"}
        identity.update(_dnd5e_359_identity(workbook, "主要"))
        self.assertEqual(identity, {
            "背景": "受宠者",
            "职业": "邪术师",
            "子职": "至高妖精",
            "等级": "Lv1",
            "种族": "精灵",
            "亚种": "雅灵",
            "阵营": "中立善良",
            "信仰": "莎罕妮",
        })
        spells = _dnd5e_359_spells(workbook, "主要")
        self.assertEqual(spells, ["魔能爆", "次级幻影", "妖火", "睡眠术", "迷踪步"])
        feats, features = _dnd5e_359_feats_and_features(workbook, "主要")
        self.assertEqual([item.split(" — ", 1)[0] for item in feats], ["幸运（受宠者）"])
        self.assertEqual(
            [item.split(" — ", 1)[0] for item in features],
            ["妖精仪态", "生物种类"],
        )

    def test_original_2014_equipment_coordinates(self) -> None:
        main_values = {
            "L32": "镶钉皮甲", "AD32": 12, "AL32": "", "AS32": "否",
            "L34": "匕首", "AE34": "O", "AH34": "+5",
            "AJ34": "1d4", "AM34": "+3", "AO34": "穿刺",
            "L37": "奥术法器", "P37": "水晶",
            "P40": "窃贼套组", "P41": "水袋*5", "P42": "治疗药水",
        }
        equipment_values = {
            "V2": "灵巧，轻型，投掷（射程20/60）",
            "W2": "1d4", "X2": "穿刺", "AB2": "+3",
        }

        class DictSheet:
            def __init__(self, values):
                self.values = values

            def get(self, address, default=None):
                return self.values.get(address, default)

        class FakeWorkbook:
            def __init__(self):
                self.sheets = {
                    "主要": DictSheet(main_values),
                    "装备": DictSheet(equipment_values),
                }

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

        weapons, armor, items = _dnd5e_359_equipment(
            FakeWorkbook(),
            "主要",
            {"ac": 15},
        )
        self.assertEqual(weapons, [
            Weapon(
                "匕首",
                value=5,
                damage="1d4+3 穿刺",
                notes="灵巧，轻型，投掷（射程20/60）",
            ),
        ])
        self.assertEqual(armor, ["镶钉皮甲 | AC 15"])
        self.assertEqual(items, ["水晶（奥术法器）", "窃贼套组", "水袋*5", "治疗药水"])


class FffLayoutTests(unittest.TestCase):
    def test_legacy_fff_identity_spells_feats_and_equipment(self) -> None:
        main_values = {
            "W3": 1,
            "BN14": "健壮", "BN15": "幸运",
            "L23": "无甲", "O23": "自定义护甲", "AD23": 18, "AJ23": "否",
            "L26": "左手", "O26": "长剑", "U26": "两用（1d10）", "Y26": "削弱",
            "AF26": 7, "AI26": "1d8+5", "AM26": "挥砍",
        }
        role_values = {"E7": "女", "M7": "中立守序", "M8": "月神"}
        casting_values = {"L4": "轰雷剑", "L5": "辉石魔法", "L17": "护盾术", "L18": "法术ADS"}
        chart_values = {
            "DD39": "健壮", "DE39": "起源专长：你的生命值上限获得显著提升，并会随等级继续成长。",
            "DD20": "幸运", "DE20": "你拥有不可思议的好运气。",
        }

        class DictSheet:
            def __init__(self, values):
                self.values = values

            def get(self, address, default=None):
                return self.values.get(address, default)

            def iter_cells(self):
                return iter([Cell(address, value, None, None) for address, value in self.values.items()])

        class FakeWorkbook:
            def __init__(self):
                self.sheets = {
                    "主要情况": DictSheet(main_values), "角色": DictSheet(role_values),
                    "施法": DictSheet(casting_values), "图表": DictSheet(chart_values),
                }

            def get_sheet(self, name):
                return self.sheets.get(name)

            def get(self, sheet, address, default=None):
                target = self.get_sheet(sheet)
                return target.get(address, default) if target else default

        workbook = FakeWorkbook()
        self.assertEqual(_fff_identity_extras(workbook, "主要情况"), {
            "等级": "Lv1", "性别": "女", "第二阵营": "中立守序", "信仰": "月神",
        })
        self.assertEqual(_dnd_main_spells(workbook, "主要情况"), ["轰雷剑", "辉石魔法", "护盾术", "法术ADS"])
        feats, features = _fff_feats_and_features(workbook, "主要情况")
        self.assertEqual([item.split(" — ", 1)[0] for item in feats], ["健壮", "幸运"])
        self.assertIn("生命值上限", feats[0])
        self.assertEqual(features, [])
        weapons, armor, items = _fff_equipment(workbook, "主要情况")
        self.assertEqual(weapons[0], Weapon("长剑", value=7, damage="1d8+5 挥砍", notes="左手 | 两用（1d10） | 精通：削弱"))
        self.assertEqual(armor, ["自定义护甲（无甲） | AC 18"])
        self.assertEqual(items, [])


@unittest.skipUnless((Path(__file__).resolve().parents[1] / "assets" / "icon-map.json").exists(), "Optional third-party icon pack is not bundled in the public source edition")
class AssetTests(unittest.TestCase):
    def test_curated_icons_and_item_aliases(self) -> None:
        self.assertIsNotNone(icon_path("class", "牧师"))
        self.assertIsNotNone(icon_path("item", "圣徽—镶嵌在盾牌上"))
        icon = load_icon("spell", "神导术", 48)
        self.assertIsNotNone(icon)
        self.assertLessEqual(icon.width, 48)
        self.assertLessEqual(icon.height, 48)

    def test_generated_rule_vocabulary_icons(self) -> None:
        for category, name in (
            ("spell", "火球术"), ("feat", "警觉"), ("weapon", "电锯"),
            ("attribute", "力量"), ("armor", "链甲"),
        ):
            path = icon_path(category, name)
            self.assertIsNotNone(path, f"missing {category}:{name}")
            self.assertTrue(path.is_file())


class RichDataPortraitTests(unittest.TestCase):
    def test_excel_rich_data_local_image_is_attached_to_cell(self) -> None:
        """Excel in-cell images must be visible to the portrait selector."""
        image_buffer = io.BytesIO()
        Image.new("RGBA", (237, 229), (35, 120, 210, 255)).save(image_buffer, format="PNG")
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
        rich_data = "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata"
        rich_value_rel = "http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel"
        files = {
            "[Content_Types].xml": f'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
                <Default Extension="xml" ContentType="application/xml"/>
                <Default Extension="png" ContentType="image/png"/>
            </Types>''',
            "xl/workbook.xml": f'''<workbook xmlns="{main}" xmlns:r="{rel}">
                <sheets><sheet name="训练家" sheetId="1" r:id="rId1"/></sheets>
            </workbook>''',
            "xl/_rels/workbook.xml.rels": f'''<Relationships xmlns="{package_rel}">
                <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
            </Relationships>''',
            "xl/worksheets/sheet1.xml": f'''<worksheet xmlns="{main}">
                <sheetData><row r="3"><c r="B3" vm="1" t="e"><v>#VALUE!</v></c></row></sheetData>
            </worksheet>''',
            "xl/metadata.xml": f'''<metadata xmlns="{main}">
                <valueMetadata count="1"><bk><rc t="1" v="0"/></bk></valueMetadata>
            </metadata>''',
            "xl/richData/rdrichvaluestructure.xml": f'''<rvStructures xmlns="{rich_data}" count="1">
                <s t="_localImage"><k n="_rvRel:LocalImageIdentifier" t="i"/><k n="CalcOrigin" t="i"/></s>
            </rvStructures>''',
            "xl/richData/rdrichvalue.xml": f'''<rvData xmlns="{rich_data}" count="1">
                <rv s="0"><v>0</v><v>5</v></rv>
            </rvData>''',
            "xl/richData/richValueRel.xml": f'''<richValueRels xmlns="{rich_value_rel}" xmlns:r="{rel}">
                <rel r:id="rId1"/>
            </richValueRels>''',
            "xl/richData/_rels/richValueRel.xml.rels": f'''<Relationships xmlns="{package_rel}">
                <Relationship Id="rId1" Target="../media/image1.png"/>
            </Relationships>''',
            "xl/media/image1.png": image_buffer.getvalue(),
        }
        data = io.BytesIO()
        with ZipFile(data, "w", ZIP_DEFLATED) as archive:
            for path, content in files.items():
                archive.writestr(path, content if isinstance(content, bytes) else content.encode("utf-8"))

        workbook = load_workbook(data.getvalue(), "rich-data.xlsx")
        cell = workbook.get_sheet("训练家").cell("B3")
        self.assertEqual(cell.metadata_index, 1)
        images = workbook.embedded_images()
        self.assertEqual(len(images), 1)
        self.assertEqual((images[0].sheet, images[0].row, images[0].column), ("训练家", 2, 1))
        self.assertEqual((images[0].width, images[0].height, images[0].mime), (237, 229, "image/png"))
        self.assertEqual(workbook.best_portrait(("训练家",)), images[0])


class OneBotFileTests(unittest.TestCase):
    def test_configured_onebot_base_has_priority(self) -> None:
        bases = onebot_bases("http://127.0.0.1:4567,http://127.0.0.1:8096")
        self.assertEqual(bases[0], "http://127.0.0.1:4567")
        self.assertEqual(bases.count("http://127.0.0.1:8096"), 1)

    def test_fetch_file_reads_path_returned_by_get_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "人物卡.xlsx"
            source.write_bytes(b"fake workbook bytes")

            class GetFileHandler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def do_POST(self):
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    self.server.seen_file_id = body.get("file_id")
                    self.server.seen_file = body.get("file")
                    self.server.seen_download = body.get("download")
                    payload = json.dumps({
                        "status": "ok",
                        "data": {"file": str(source)},
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            server = ThreadingHTTPServer(("127.0.0.1", 0), GetFileHandler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                data = fetch_file("/file-id", configured_bases=base)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            self.assertEqual(data, b"fake workbook bytes")
            self.assertEqual(server.seen_file_id, "/file-id")
            self.assertEqual(server.seen_file, "/file-id")
            self.assertIs(server.seen_download, True)

    def test_group_file_falls_back_to_group_download_url(self) -> None:
        class GroupFileHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.path == "/get_file":
                    payload = json.dumps({
                        "status": "failed",
                        "retcode": 200,
                        "message": "不支持的文件类型: 3",
                    }, ensure_ascii=False).encode("utf-8")
                elif self.path == "/get_group_file_url":
                    self.server.seen_group_body = body
                    url = f"http://127.0.0.1:{self.server.server_address[1]}/download"
                    payload = json.dumps({
                        "status": "ok",
                        "retcode": 0,
                        "data": {"url": url},
                    }).encode("utf-8")
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                if self.path != "/download":
                    self.send_error(404)
                    return
                payload = b"group workbook bytes"
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), GroupFileHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            data = fetch_file(
                "/group-file-id",
                group_id="1234567890",
                busid=3,
                configured_bases=base,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(data, b"group workbook bytes")
        self.assertEqual(server.seen_group_body["group_id"], 1234567890)
        self.assertEqual(server.seen_group_body["file_id"], "/group-file-id")
        self.assertEqual(server.seen_group_body["busid"], 3)


if __name__ == "__main__":
    unittest.main()
