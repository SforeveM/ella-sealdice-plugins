from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

from .errors import DownloadRejectedError


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator):
        super().__init__()
        self.validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url: str, allow_private: bool = False) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadRejectedError("文件链接必须是 http/https 地址")
    if parsed.username or parsed.password:
        raise DownloadRejectedError("文件链接不能包含账号密码")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as exc:
        raise DownloadRejectedError("无法解析文件下载地址") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved):
            raise DownloadRejectedError("出于安全原因，不能从内网地址下载人物卡")


def download(url: str, *, max_bytes: int = 25 * 1024 * 1024, timeout: int = 20, allow_private: bool = False) -> bytes:
    _validate_url(url, allow_private)
    opener = urllib.request.build_opener(SafeRedirectHandler(lambda value: _validate_url(value, allow_private)))
    request = urllib.request.Request(url, headers={"User-Agent": "SealDice-Autocard/0.1", "Accept": "*/*"})
    try:
        with opener.open(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise DownloadRejectedError("人物卡文件超过大小限制")
            data = response.read(max_bytes + 1)
    except DownloadRejectedError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DownloadRejectedError(f"下载人物卡失败：{exc}") from exc
    if len(data) > max_bytes:
        raise DownloadRejectedError("人物卡文件超过大小限制")
    return data
