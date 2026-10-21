from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bomb_backend", ROOT / "backend" / "bomb_defusal_backend.py")
backend = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(backend)

payload = {
    "kind": "bomb",
    "player_name": "演示玩家",
    "status": "active",
    "status_label": "拆弹进行中",
    "safe_count": 2,
    "pending_reward": 80,
    "balance": 3789,
    "revealed_color": "",
    "wires": [
        {"id": "red", "name": "红线", "color": "#ef4444", "cut": False},
        {"id": "blue", "name": "蓝线", "color": "#3b82f6", "cut": True},
        {"id": "yellow", "name": "黄线", "color": "#facc15", "cut": False},
        {"id": "green", "name": "绿线", "color": "#22c55e", "cut": True},
        {"id": "purple", "name": "紫线", "color": "#a855f7", "cut": False},
        {"id": "white", "name": "白线", "color": "#f8fafc", "cut": False},
    ],
}

output = ROOT / "tests" / "bomb-defusal-render-check.png"
backend.render(payload).save(output, format="PNG", optimize=True)
print(output)
