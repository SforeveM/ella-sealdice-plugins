from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .downloader import download
from .errors import AutocardError


DEFAULT_BASES = (
    # LLBot is the supported non-official QQ adapter in this deployment.
    # Keep the older NapCat/LLOneBot ports as fallbacks for other servers.
    "http://127.0.0.1:4000",
    "http://127.0.0.1:8096",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5700",
)


def onebot_bases(configured: str = "") -> list[str]:
    bases: list[str] = []
    for value in configured.split(","):
        value = value.strip().rstrip("/")
        if value and value not in bases:
            bases.append(value)
    for value in DEFAULT_BASES:
        if value not in bases:
            bases.append(value)
    return bases


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def _find_first(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for child in value.values():
            found = _find_first(child, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first(child, keys)
            if found not in (None, ""):
                return found
    return None


def call_get_file(
    file_id: str,
    *,
    bases: list[str],
    access_token: str = "",
    timeout: int = 30,
) -> Any:
    file_id = str(file_id or "").strip()
    if not file_id:
        raise AutocardError("QQ 文件消息缺少 file_id")

    # NapCat/OneBot 12 commonly reads file_id; LLOneBot's get_file action
    # documents the same identifier under file and needs download=true to
    # materialize a local path. Sending all three is accepted by the known
    # implementations and keeps the endpoint portable.
    body = json.dumps(
        {"file_id": file_id, "file": file_id, "download": True},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if access_token.strip():
        headers["Authorization"] = "Bearer " + access_token.strip()

    last_error = "unknown"
    for base in bases:
        request = urllib.request.Request(
            base.rstrip("/") + "/get_file",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024)
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict) and str(value.get("status", "")).lower() in {"failed", "error"}:
                last_error = str(value.get("msg") or value.get("wording") or value)[:300]
                continue
            return _unwrap(value)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(500).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            last_error = f"{base} 返回 HTTP {exc.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = f"{base}: {exc}"

    raise AutocardError(
        "无法通过 OneBot get_file 取得 QQ 文件。请确认 NapCat/NC 的 HTTP 服务已开启，"
        "并设置 AUTOCARD_ONEBOT_HTTP_BASE。最后错误：" + last_error
    )


def call_get_group_file_url(
    file_id: str,
    group_id: str,
    *,
    bases: list[str],
    busid: int = 3,
    access_token: str = "",
    timeout: int = 30,
) -> Any:
    file_id = str(file_id or "").strip()
    group_id = str(group_id or "").strip()
    if not file_id or not group_id:
        raise AutocardError("获取 QQ 群文件链接时缺少 file_id 或 group_id")

    try:
        normalized_group_id: int | str = int(group_id)
    except ValueError:
        normalized_group_id = group_id
    body = json.dumps(
        {"group_id": normalized_group_id, "file_id": file_id, "busid": int(busid)},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if access_token.strip():
        headers["Authorization"] = "Bearer " + access_token.strip()

    errors: list[str] = []
    for base in bases:
        request = urllib.request.Request(
            base.rstrip("/") + "/get_group_file_url",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024)
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict) and str(value.get("status", "")).lower() in {"failed", "error"}:
                detail = str(value.get("message") or value.get("msg") or value.get("wording") or value)[:300]
                errors.append(f"{base}: {detail}")
                continue
            return _unwrap(value)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(500).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            errors.append(f"{base}: HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"{base}: {exc}")

    raise AutocardError(
        "无法通过 OneBot get_group_file_url 取得 QQ 群文件链接。尝试结果："
        + "；".join(errors)
    )


def _read_local(path_value: str, max_bytes: int) -> bytes:
    path = Path(path_value)
    if not path.is_file():
        raise AutocardError(f"OneBot 返回了本地文件路径，但自动读卡服务无法访问：{path_value}")
    try:
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError as exc:
        raise AutocardError(f"读取 OneBot 本地文件失败：{exc}") from exc
    if len(data) > max_bytes:
        raise AutocardError("人物卡文件超过大小限制")
    return data


def fetch_file(
    file_id: str,
    *,
    group_id: str = "",
    busid: int = 3,
    configured_bases: str = "",
    access_token: str = "",
    max_bytes: int = 25 * 1024 * 1024,
) -> bytes:
    bases = onebot_bases(configured_bases)
    get_file_error: AutocardError | None = None
    try:
        value = call_get_file(
            file_id,
            bases=bases,
            access_token=access_token,
        )
    except AutocardError as exc:
        get_file_error = exc
        if not str(group_id or "").strip():
            raise
        value = call_get_group_file_url(
            file_id,
            group_id,
            bases=bases,
            busid=busid,
            access_token=access_token,
        )

    url = _find_first(value, ("url", "download_url"))
    if url and re.match(r"^https?://", str(url), flags=re.I):
        return download(str(url), max_bytes=max_bytes, timeout=90, allow_private=True)

    local_path = _find_first(
        value,
        ("file", "path", "file_path", "absolute_path", "real_path"),
    )
    if local_path:
        return _read_local(str(local_path), max_bytes)

    if isinstance(value, str):
        if re.match(r"^https?://", value, flags=re.I):
            return download(value, max_bytes=max_bytes, timeout=90, allow_private=True)
        return _read_local(value, max_bytes)

    detail = (
        "；通用 get_file 结果：" + str(get_file_error)
        if get_file_error is not None else ""
    )
    raise AutocardError(
        "OneBot get_file 已成功响应，但没有返回可用的下载地址或本地路径："
        + json.dumps(value, ensure_ascii=False)[:500] + detail
    )
