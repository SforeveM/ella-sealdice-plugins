from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from . import __version__
from .downloader import download
from .errors import AutocardError
from .extractors import extract_character
from .ooxml import load_workbook
from .onebot import fetch_file as fetch_onebot_file
from .render import file_list_dimensions, render_file_list, render_pngs
from .render_review import render_review_png
from .portrait_archive import (
    portrait_archive_dir,
    save_character_portrait,
    setpic_portrait_dir,
)
from .review import calculate_pokecoin_charge, review_ai_status, review_character
from .store import PendingStore


TOKEN_PATH = re.compile(r"^/api/v1/pending/([A-Za-z0-9_-]+)$")
RENDER_PATH = re.compile(r"^/api/v1/render/([A-Za-z0-9_-]+)$")
REVIEW_PATH = re.compile(r"^/api/v1/review/([A-Za-z0-9_-]+)$")
CARD_PATH = re.compile(r"^/cards/([A-Za-z0-9_-]+?)(?:-pokemon-([1-9][0-9]*))?\.png$")
REVIEW_CARD_PATH = re.compile(r"^/cards/([A-Za-z0-9_-]+)-review\.png$")
FILE_LIST_CARD_PATH = re.compile(r"^/cards/file-list-([A-Za-z0-9_-]+)\.png$")
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


def disable_windows_console_quick_edit() -> bool:
    """Prevent legacy Windows console text selection from suspending the server."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel32.GetConsoleMode.restype = ctypes.c_int
        kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.SetConsoleMode.restype = ctypes.c_int

        std_input_handle = ctypes.c_uint32(-10).value
        handle = kernel32.GetStdHandle(std_input_handle)
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in {None, 0, invalid_handle}:
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_quick_edit_mode = 0x0040
        enable_extended_flags = 0x0080
        safe_mode = (mode.value | enable_extended_flags) & ~enable_quick_edit_mode
        if safe_mode == mode.value:
            return True
        return bool(kernel32.SetConsoleMode(handle, safe_mode))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class AutocardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, handler=BaseHTTPRequestHandler):
        super().__init__(address, handler)
        data_dir = Path(os.getenv("AUTOCARD_DATA_DIR", "data/pending"))
        self.store = PendingStore(data_dir, int(os.getenv("AUTOCARD_PENDING_TTL", "1800")))
        self.api_token = os.getenv("AUTOCARD_API_TOKEN", "change-me")
        public_host = address[0] if address[0] not in {"", "0.0.0.0", "::"} else "127.0.0.1"
        self.public_base = os.getenv("AUTOCARD_PUBLIC_BASE_URL", f"http://{public_host}:{address[1]}").rstrip("/")
        self.allow_private = os.getenv("AUTOCARD_ALLOW_PRIVATE_DOWNLOADS", "false").lower() in {"1", "true", "yes"}
        # Official QQ attachments use /discover-url and never reach OneBot.
        # Ordinary QQ attachments use this base; LLBot listens on 4000 here.
        self.onebot_http_base = os.getenv("AUTOCARD_ONEBOT_HTTP_BASE", "http://127.0.0.1:4000")
        self.onebot_access_token = os.getenv("AUTOCARD_ONEBOT_ACCESS_TOKEN", "")
        self.access_log = os.getenv("AUTOCARD_ACCESS_LOG", "false").lower() in {"1", "true", "yes", "on"}
        self.quick_edit_disabled = False
        self.file_list_dir = data_dir.parent / "file-lists"
        self.file_list_dir.mkdir(parents=True, exist_ok=True)

    def handle_error(self, request, client_address) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, CLIENT_DISCONNECT_ERRORS):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server: AutocardServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        if not self.server.access_log:
            return
        try:
            sys.stderr.write(f"{self.client_address[0]} - {format % args}\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass

    def _json(self, status: int, value: dict) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._bytes(status, payload, "application/json; charset=utf-8", "no-store")

    def _bytes(self, status: int, payload: bytes, content_type: str, cache_control: str) -> None:
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except CLIENT_DISCONNECT_ERRORS:
            self.close_connection = True

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.api_token
        if supplied == expected:
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "API token 不正确"})
        return False

    def _body(self, max_bytes: int = 35 * 1024 * 1024) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AutocardError("Content-Length 无效") from exc
        if length <= 0 or length > max_bytes:
            raise AutocardError("请求体为空或超过大小限制")
        return self.rfile.read(length)

    def _body_json(self) -> dict:
        try:
            return json.loads(self._body().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutocardError("请求 JSON 无效") from exc

    def _discover(self, data: bytes, filename: str) -> dict:
        workbook = load_workbook(data, filename)
        character = extract_character(workbook)
        token = self.server.store.create(data, character)
        return {
            "ok": True,
            "token": token,
            "file": character.source_filename,
            "format": character.source_format,
            "rule": character.rule,
            "seal_system": character.seal_system,
            "template": character.template_name,
            "character": character.name,
            "expires_in": self.server.store.ttl_seconds,
            "warnings": character.warnings,
        }

    def _pending(self, token: str) -> dict:
        character = self.server.store.character(token)
        values = dict(character.attributes)
        values.update({name: value for name, value in character.skills.items() if name not in character.skill_formulas})
        values.update({"$stp_" + name: value for name, value in character.saving_throw_factors.items()})
        return {
            "ok": True,
            "token": token,
            "character": character.to_dict(),
            "preview": character.preview(),
            "record": {
                "name": character.name,
                "rule": character.rule,
                "seal_system": character.seal_system,
                "values": values,
                "computed_values": character.skill_formulas,
                "string_values": character.identity,
                "pokemon": character.to_dict().get("pokemon", []),
            },
        }

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/health":
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "service": "sealdice-autocard",
                    "version": __version__,
                    "access_log": self.server.access_log,
                    "windows_quick_edit_disabled": self.server.quick_edit_disabled,
                    "portrait_archive": str(portrait_archive_dir(self.server.store.root)),
                    "setpic_portrait_dir": str(
                        setpic_portrait_dir(self.server.store.root) or ""
                    ),
                    "review_ai": review_ai_status(),
                    "review_billing": {
                        "enabled": True,
                        "token_step": 50000,
                        "step_charge": 100,
                        "minimum_charge": 100,
                        "currency": "宝可元",
                    },
                })
                return
            file_list_match = FILE_LIST_CARD_PATH.fullmatch(path)
            if file_list_match:
                card = self.server.file_list_dir / f"{file_list_match.group(1)}.png"
                if not card.exists():
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "图片不存在"})
                    return
                payload = card.read_bytes()
                self._bytes(HTTPStatus.OK, payload, "image/png", "private, max-age=900")
                return
            review_card_match = REVIEW_CARD_PATH.fullmatch(path)
            if review_card_match:
                card = self.server.store.review_path(review_card_match.group(1))
                if not card.exists():
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "图片不存在"})
                    return
                payload = card.read_bytes()
                self._bytes(HTTPStatus.OK, payload, "image/png", "private, max-age=1800")
                return
            card_match = CARD_PATH.fullmatch(path)
            if card_match:
                card = self.server.store.card_path(card_match.group(1), int(card_match.group(2) or 0))
                if not card.exists():
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "图片不存在"})
                    return
                payload = card.read_bytes()
                self._bytes(HTTPStatus.OK, payload, "image/png", "private, max-age=1800")
                return
            if not self._authorized():
                return
            pending_match = TOKEN_PATH.fullmatch(path)
            if pending_match:
                self._json(HTTPStatus.OK, self._pending(pending_match.group(1)))
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
        except AutocardError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"服务器处理失败：{exc}"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not self._authorized():
            return
        try:
            if path == "/api/v1/file-list":
                body = self._body_json()
                raw_files = body.get("files")
                if not isinstance(raw_files, list) or not raw_files:
                    raise AutocardError("群内没有可展示的角色卡候选文件")
                files: list[dict] = []
                for raw in raw_files[:12]:
                    if not isinstance(raw, dict):
                        continue
                    filename = Path(str(raw.get("filename") or "未命名文件")).name[:120]
                    extension = str(raw.get("format") or "").lower().lstrip(".")
                    if extension not in {"xls", "xlsx", "xlsm"}:
                        extension = Path(filename).suffix.lower().lstrip(".")
                    if extension not in {"xls", "xlsx", "xlsm"}:
                        continue
                    files.append({
                        "filename": filename,
                        "format": extension,
                        "size_text": str(raw.get("size_text") or "")[:30],
                        "uploader": str(raw.get("uploader") or "")[:40],
                        "time_text": str(raw.get("time_text") or "")[:30],
                    })
                if not files:
                    raise AutocardError("没有有效的 Excel 角色卡候选文件")
                token = secrets.token_urlsafe(18)
                card = self.server.file_list_dir / f"{token}.png"
                card.write_bytes(render_file_list(files, str(body.get("group_name") or "")[:80]))
                image_width, image_height = file_list_dimensions(len(files))
                cutoff = time.time() - 3600
                for old_card in self.server.file_list_dir.glob("*.png"):
                    try:
                        if old_card != card and old_card.stat().st_mtime < cutoff:
                            old_card.unlink()
                    except OSError:
                        pass
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "count": len(files),
                    "image_url": f"{self.server.public_base}/cards/file-list-{token}.png",
                    "image_width": image_width,
                    "image_height": image_height,
                })
                return
            if path == "/api/v1/discover-url":
                body = self._body_json()
                filename = Path(str(body.get("filename") or "upload.xlsx")).name
                data = download(str(body.get("url") or ""), allow_private=self.server.allow_private)
                self._json(HTTPStatus.OK, self._discover(data, filename))
                return
            if path == "/api/v1/discover-file-id":
                body = self._body_json()
                filename = Path(str(body.get("filename") or "upload.xlsx")).name
                data = fetch_onebot_file(
                    str(body.get("file_id") or ""),
                    group_id=str(body.get("group_id") or ""),
                    busid=int(body.get("busid") or 3),
                    configured_bases=self.server.onebot_http_base,
                    access_token=self.server.onebot_access_token,
                )
                self._json(HTTPStatus.OK, self._discover(data, filename))
                return
            if path == "/api/v1/discover-base64":
                body = self._body_json()
                filename = Path(str(body.get("filename") or "upload.xlsx")).name
                try:
                    data = base64.b64decode(str(body.get("data") or ""), validate=True)
                except ValueError as exc:
                    raise AutocardError("文件 base64 无效") from exc
                self._json(HTTPStatus.OK, self._discover(data, filename))
                return
            render_match = RENDER_PATH.fullmatch(path)
            if render_match:
                body: dict = {}
                if int(self.headers.get("Content-Length", "0") or "0") > 0:
                    body = self._body_json()
                raw_owner_ids = body.get("owner_ids", []) if isinstance(body, dict) else []
                if isinstance(raw_owner_ids, str):
                    raw_owner_ids = [raw_owner_ids]
                owner_ids = [str(item).strip() for item in raw_owner_ids if str(item).strip()]
                if body.get("owner_id"):
                    owner_ids.insert(0, str(body["owner_id"]).strip())
                owner_ids = list(dict.fromkeys(owner_ids))[:12]
                token = render_match.group(1)
                character = self.server.store.character(token)
                portrait_record = save_character_portrait(
                    character, self.server.store.root, owner_ids=owner_ids
                )
                rendered = render_pngs(character)
                image_urls: list[str] = []
                image_sizes: list[dict] = []
                for index, card_bytes in enumerate(rendered):
                    self.server.store.card_path(token, index).write_bytes(card_bytes)
                    suffix = "" if index == 0 else f"-pokemon-{index}"
                    image_urls.append(f"{self.server.public_base}/cards/{token}{suffix}.png")
                    with Image.open(io.BytesIO(card_bytes)) as card_image:
                        image_sizes.append({"width": card_image.width, "height": card_image.height})
                payload = self._pending(token)
                payload["image_url"] = image_urls[0]
                payload["image_urls"] = image_urls
                payload["image_sizes"] = image_sizes
                payload["portrait_archived"] = bool(portrait_record)
                payload["setpic_portrait_saved"] = bool(
                    portrait_record and portrait_record.get("setpic_file")
                )
                payload["setpic_portrait_error"] = str(
                    portrait_record.get("setpic_error") if portrait_record else ""
                )
                payload["portrait_owner_ids_saved"] = owner_ids
                self._json(HTTPStatus.OK, payload)
                return
            review_match = REVIEW_PATH.fullmatch(path)
            if review_match:
                body: dict = {}
                if int(self.headers.get("Content-Length", "0") or "0") > 0:
                    body = self._body_json()
                review_ai = body.get("review_ai") if isinstance(body, dict) else None
                if review_ai is not None and not isinstance(review_ai, dict):
                    raise AutocardError("AI 评分配置格式无效")
                if isinstance(review_ai, dict):
                    api_url = str(review_ai.get("api_url") or "").strip()
                    api_key = str(review_ai.get("api_key") or "").strip()
                    model = str(review_ai.get("model") or "").strip()
                    if not re.match(r"^https?://", api_url, re.I):
                        raise AutocardError("AI 评分 API 地址无效")
                    if not api_key or len(api_key) > 4096:
                        raise AutocardError("AI 评分 API 密钥无效")
                    if not model or len(model) > 200:
                        raise AutocardError("AI 评分模型名无效")
                    review_ai = {"api_url": api_url, "api_key": api_key, "model": model}
                token = review_match.group(1)
                character = self.server.store.character(token)
                review = review_character(character, review_ai)
                card = self.server.store.review_path(token)
                review_bytes = render_review_png(character, review)
                card.write_bytes(review_bytes)
                with Image.open(io.BytesIO(review_bytes)) as review_image:
                    review_size = {"width": review_image.width, "height": review_image.height}
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "token": token,
                    "review": review.to_dict(),
                    "review_image_url": f"{self.server.public_base}/cards/{token}-review.png",
                    "review_image_size": review_size,
                    "billing": {
                        "ai_used": review.review_source == "ai",
                        "prompt_tokens": review.prompt_tokens,
                        "completion_tokens": review.completion_tokens,
                        "total_tokens": review.total_tokens,
                        "usage_estimated": review.token_usage_estimated,
                        "pokecoin_charge": (
                            calculate_pokecoin_charge(review.total_tokens)
                            if review.review_source == "ai" else 0
                        ),
                        "policy": "minimum-100-plus-100-per-started-50000-tokens",
                    },
                })
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
        except AutocardError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"服务器处理失败：{exc}"})


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    quick_edit_disabled = disable_windows_console_quick_edit()
    server = AutocardServer((host, port), Handler)
    server.quick_edit_disabled = quick_edit_disabled
    print(f"SealDice Autocard listening on http://{host}:{port}", flush=True)
    if os.name == "nt":
        state = "disabled" if quick_edit_disabled else "unavailable"
        print(f"Windows console QuickEdit protection: {state}", flush=True)
    if server.access_log:
        print("Autocard access log: enabled", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
