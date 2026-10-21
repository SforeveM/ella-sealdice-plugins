from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = Path(os.environ.get("BOMB_CACHE_DIR", str(ROOT / "backend" / "cache"))).resolve()
PUBLIC_CACHE_VALUE = os.environ.get("BOMB_PUBLIC_CACHE_DIR", "").strip()
PUBLIC_CACHE_DIR = Path(PUBLIC_CACHE_VALUE).resolve() if PUBLIC_CACHE_VALUE else None
PUBLIC_BASE_URL = os.environ.get("BOMB_PUBLIC_BASE_URL", "https://game-api.example.com").rstrip("/")
API_TOKEN = os.environ.get("BOMB_API_TOKEN", "bomb-local").strip()
MAX_BODY = 512 * 1024

C = {
    "background": "#07101d",
    "panel": "#101b2d",
    "panel_alt": "#16243a",
    "line": "#33445f",
    "text": "#eef4ff",
    "muted": "#a9b7cc",
    "cyan": "#50d7e8",
    "green": "#4ade80",
    "gold": "#f5c451",
    "red": "#fb5d64",
}


def safe(value: Any, limit: int = 80) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("msyhbd.ttc" if bold else "msyh.ttc"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("simhei.ttf" if bold else "simsun.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], radius: int, fill: str, outline: Optional[str] = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def gradient_background(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), C["background"])
    pixels = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        for x in range(width):
            glow = max(0.0, 1.0 - (((x - width * 0.5) / width) ** 2 + ((y - height * 0.45) / height) ** 2) * 5.0)
            pixels[x, y] = (
                int(6 + 10 * ratio + 8 * glow),
                int(14 + 11 * ratio + 16 * glow),
                int(27 + 18 * ratio + 26 * glow),
            )
    return image


def draw_bomb(draw: ImageDraw.ImageDraw, status: str) -> None:
    cx, cy, radius = 350, 510, 205
    if status == "exploded":
        for ring, alpha_color in [(285, "#51212a"), (245, "#7f2930"), (218, "#aa353a")]:
            draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), fill=alpha_color)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill="#111827", outline="#65748b", width=8)
    draw.ellipse((cx - 166, cy - 166, cx + 166, cy + 166), fill="#172235", outline="#2b3a51", width=5)
    rounded(draw, (cx - 110, cy - 72, cx + 110, cy + 72), 18, "#05090f", "#485971", 4)
    timer = "BOOM" if status == "exploded" else ("SAFE" if status == "cashed" else "00:??")
    timer_color = C["red"] if status == "exploded" else (C["green"] if status == "cashed" else C["cyan"])
    bbox = draw.textbbox((0, 0), timer, font=font(52, True))
    draw.text((cx - (bbox[2] - bbox[0]) // 2, cy - 34), timer, font=font(52, True), fill=timer_color)
    draw.line((cx + 85, cy - 176, cx + 152, cy - 258), fill="#78879c", width=18)
    draw.line((cx + 152, cy - 258, cx + 218, cy - 238), fill="#78879c", width=18)
    draw.arc((cx + 182, cy - 294, cx + 252, cy - 224), 200, 330, fill=C["gold"], width=8)


def render(payload: Dict[str, Any]) -> Image.Image:
    width, height = 1400, 980
    image = gradient_background(width, height)
    draw = ImageDraw.Draw(image)
    status = safe(payload.get("status"), 20) or "idle"
    player_name = safe(payload.get("player_name"), 30) or "拆弹员"
    status_label = safe(payload.get("status_label"), 30) or "等待开始"
    pending = max(0, int(payload.get("pending_reward") or 0))
    safe_count = max(0, min(5, int(payload.get("safe_count") or 0)))
    balance = int(payload.get("balance") or 0)
    revealed = safe(payload.get("revealed_color"), 20)

    rounded(draw, (38, 30, width - 38, 138), 26, "#0b1525", C["line"], 3)
    draw.text((72, 55), "六色拆弹 · 风险结算", font=font(42, True), fill=C["text"])
    draw.text((width - 430, 60), player_name, font=font(28, True), fill=C["cyan"])
    draw.text((width - 430, 100), status_label, font=font(22), fill=C["muted"])

    rounded(draw, (38, 160, width - 38, 835), 30, C["panel"], C["line"], 3)
    draw_bomb(draw, status)
    wires = payload.get("wires") if isinstance(payload.get("wires"), list) else []
    start_x, end_x = 525, 1240
    for index, wire in enumerate(wires[:6]):
        wire_id = safe(wire.get("id"), 20)
        name = safe(wire.get("name"), 16)
        color = safe(wire.get("color"), 16) or "#94a3b8"
        cut = bool(wire.get("cut"))
        y = 255 + index * 91
        points_left = [(start_x, 390 + index * 34), (650, y), (825, y)]
        points_right = [(885, y), (1060, y), (end_x, y)]
        if cut:
            draw.line(points_left, fill=color, width=16, joint="curve")
            draw.line(points_right, fill="#46546a", width=10, joint="curve")
            draw.line((817, y - 17, 838, y + 17), fill="#e2e8f0", width=5)
            draw.line((838, y - 17, 817, y + 17), fill="#e2e8f0", width=5)
        else:
            draw.line(points_left + points_right, fill=color, width=16, joint="curve")
            draw.line(points_left + points_right, fill="#ffffff", width=3, joint="curve")
        terminal_fill = "#3b1820" if revealed == wire_id else C["panel_alt"]
        terminal_outline = C["red"] if revealed == wire_id else color
        rounded(draw, (end_x - 10, y - 34, end_x + 108, y + 34), 14, terminal_fill, terminal_outline, 4)
        draw.text((end_x + 15, y - 20), name, font=font(25, True), fill=C["text"])
        if cut:
            draw.text((930, y - 18), "已剪断", font=font(22, True), fill=C["muted"])
        elif revealed == wire_id:
            draw.text((930, y - 18), "错误线路", font=font(22, True), fill=C["red"])

    rounded(draw, (55, 855, width - 55, 945), 22, "#0b1525", C["line"], 2)
    draw.text((83, 878), f"安全剪线  {safe_count}/5", font=font(27, True), fill=C["green"])
    if status == "exploded":
        summary = f"爆炸扣款  -{int(payload.get('penalty') or 0)} 宝可元"
        summary_color = C["red"]
    elif status == "cashed":
        summary = f"安全结算  +{int(payload.get('payout') or 0)} 宝可元"
        summary_color = C["green"]
    else:
        summary = f"现在收手  +{pending} 宝可元"
        summary_color = C["gold"]
    draw.text((480, 878), summary, font=font(27, True), fill=summary_color)
    draw.text((1040, 878), f"余额 {balance}", font=font(27, True), fill=C["cyan"])
    return image


def cleanup(directory: Path) -> None:
    if not directory.exists():
        return
    cutoff = time.time() - 7 * 86400
    for item in directory.glob("bomb-defusal-*.png"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            pass


def save_image(image: Image.Image, payload: Dict[str, Any]) -> Tuple[Path, Optional[str]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    name = f"bomb-defusal-{digest}.png"
    local = CACHE_DIR / name
    compact = image.quantize(colors=192, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).convert("RGB")
    compact.save(local, format="PNG", optimize=True, compress_level=9)
    url = None
    if PUBLIC_CACHE_DIR:
        PUBLIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        public = PUBLIC_CACHE_DIR / name
        compact.save(public, format="PNG", optimize=True, compress_level=9)
        url = f"{PUBLIC_BASE_URL}/images/{name}"
        cleanup(PUBLIC_CACHE_DIR)
    cleanup(CACHE_DIR)
    return local, url


class Handler(BaseHTTPRequestHandler):
    server_version = "EllaBombDefusal/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)

    def respond(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self.respond(200, {"ok": True, "service": "ella-bomb-defusal", "version": VERSION, "pid": os.getpid(), "public_image_enabled": PUBLIC_CACHE_DIR is not None})
            return
        self.respond(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/api/v1/render":
            self.respond(404, {"ok": False, "error": "not_found"})
            return
        if API_TOKEN and self.headers.get("X-API-Key", "") != API_TOKEN:
            self.respond(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY:
                raise ValueError("invalid body size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
            image = render(payload)
            path, url = save_image(image, payload)
            self.respond(200, {"ok": True, "image_path": str(path), "image_url": url or "", "image_width": image.width, "image_height": image.height})
        except Exception as error:
            self.respond(400, {"ok": False, "error": safe(error, 300)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12152)
    args = parser.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Ella Bomb Defusal backend {VERSION} listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
