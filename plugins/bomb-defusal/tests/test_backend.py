from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bomb_backend", ROOT / "backend" / "bomb_defusal_backend.py")
backend = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(backend)

assert backend.VERSION == "1.0.0"

wires = [
    {"id": "red", "name": "红线", "color": "#ef4444", "cut": False},
    {"id": "blue", "name": "蓝线", "color": "#3b82f6", "cut": True},
    {"id": "yellow", "name": "黄线", "color": "#facc15", "cut": False},
    {"id": "green", "name": "绿线", "color": "#22c55e", "cut": True},
    {"id": "purple", "name": "紫线", "color": "#a855f7", "cut": False},
    {"id": "white", "name": "白线", "color": "#f8fafc", "cut": False},
]
active = {"kind": "bomb", "player_name": "WONS", "status": "active", "status_label": "拆弹进行中", "safe_count": 2, "pending_reward": 80, "balance": 1000, "wires": wires, "revealed_color": ""}
exploded = {**active, "status": "exploded", "status_label": "炸弹爆炸", "penalty": 80, "balance": 920, "revealed_color": "red"}

active_image = backend.render(active)
exploded_image = backend.render(exploded)
assert active_image.size == (1400, 980)
assert exploded_image.size == (1400, 980)

with tempfile.TemporaryDirectory(prefix="bomb-defusal-test-") as temporary:
    backend.CACHE_DIR = Path(temporary) / "local"
    backend.PUBLIC_CACHE_DIR = Path(temporary) / "public"
    backend.PUBLIC_BASE_URL = "https://game-api.example.com"
    active_path, active_url = backend.save_image(active_image, active)
    exploded_path, exploded_url = backend.save_image(exploded_image, exploded)
    assert active_path.exists() and exploded_path.exists()
    assert active_path.stat().st_size < 900_000
    assert exploded_path.stat().st_size < 900_000
    assert active_url and active_url.startswith("https://game-api.example.com/images/bomb-defusal-")
    assert exploded_url and exploded_url.startswith("https://game-api.example.com/images/bomb-defusal-")

print("Bomb defusal backend tests passed.")
