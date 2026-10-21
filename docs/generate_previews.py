"""Generate the README previews from fictional data with the actual renderers."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/autocard"))
from autocard.models import Character, PokemonCompanion, PokemonMove
from autocard.render import render_pngs

images = ROOT / "docs/images"
images.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location(
    "bomb_demo", ROOT / "plugins/bomb-defusal/tests/render_sample.py"
)
demo = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(demo)
demo.backend.render(demo.payload).save(images / "bomb-defusal.png")

trainer = Character(
    source_filename="fictional-demo.xlsx", source_format="xlsx",
    rule="POKEMON-TRPG", seal_system="pokemon", template_id="demo",
    template_name="虚构训练家演示", layout="modern", name="林间旅人",
    player="演示玩家", identity={"年龄": "20", "性别": "女", "职业": "研究员"},
    attributes={"力量": 1, "体魄": 2, "智识": 3, "意念": 2, "机敏": 1,
                "魅力": 2, "幸运": 1, "HP": 30, "HPmax": 30, "旅行点": 5},
    skills={"观察": 4, "自然": 5, "医疗": 3, "运动": 2},
    features=["所有数据均为虚构，仅用于展示插件的绘图效果。"],
    backstory="记录沿途的生态，与伙伴一起探索森林、海岸和新的冒险营地。",
    pokemon=[PokemonCompanion(
        name="同行伙伴", species="伊布", types=["一般"], hp=24, hpmax=24,
        ep=10, bond=3, ability="适应力",
        stats={"攻击": 3, "防御": 2, "特攻": 2, "特防": 3, "速度": 3},
        moves=[PokemonMove(name="撞击", category="物理", element="一般",
                           accuracy="95", damage="1d6+3", ep_cost=1)]
    )],
)
(images / "autocard.png").write_bytes(render_pngs(trainer)[0])
print("Generated fictional previews in", images)
