"""QQ Music mobile login RPC and its request signature."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from .credentials import Credentials
from .device import load_or_create
from .qimei import get_qimei

LOGIN_URL = "https://u.y.qq.com/cgi-bin/musics.fcg"
MOBILE_VERSION = "14.9.0.8"
PART_1_INDEXES = [23, 14, 6, 36, 16, 7, 19]
PART_2_INDEXES = [16, 1, 32, 12, 19, 27, 8, 5]
SCRAMBLE_VALUES = [
    89, 39, 179, 150, 218, 82, 58, 252, 177, 52,
    186, 123, 120, 64, 242, 133, 143, 161, 121, 179,
]


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sign_payload(payload: str) -> str:
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest().upper()
    part1 = "".join(digest[index] for index in PART_1_INDEXES)
    part2 = "".join(digest[index] for index in PART_2_INDEXES)
    part3 = bytes(
        value ^ int(digest[index * 2 : index * 2 + 2], 16)
        for index, value in enumerate(SCRAMBLE_VALUES)
    )
    encoded = base64.b64encode(part3).decode("ascii")
    encoded = encoded.translate(str.maketrans("", "", "\\/+="))
    return f"zzc{part1}{encoded}{part2}".lower()


def build_common(credentials: Credentials, qimei: dict[str, str], device) -> dict[str, Any]:
    common = {
        "v": 14090008,
        "ct": 11,
        "cv": 14090008,
        "chid": "2005000982",
        "QIMEI": qimei["q16"],
        "QIMEI36": qimei["q36"],
        "tmeAppID": "qqmusic",
        "format": "json",
        "inCharset": "utf-8",
        "outCharset": "utf-8",
        "qq": credentials.uin,
        "authst": credentials.token,
        "tmeLoginType": 1 if credentials.token.startswith("W_X_") else 2,
        "OpenUDID": "ffffffffbff94f7d000000000033c587",
        "udid": "ffffffffbff94f7d000000000033c587",
        "os_ver": device.version.release,
        "aid": "d2550265db4ce5c4",
        "phonetype": device.model,
        "devicelevel": device.version.sdk,
        "newdevicelevel": device.version.sdk,
        "nettype": "1030",
        "rom": device.fingerprint,
        "OpenUDID2": "ffffffffbff94f7d000001999ff7d5bf",
    }
    return common


def build_login_payload(
    credentials: Credentials, qimei: dict[str, str], device
) -> dict[str, Any]:
    return {
        "comm": build_common(credentials, qimei, device),
        "req": {
            "module": "music.login.LoginServer",
            "method": "Login",
            "param": {
                "openid": credentials.open_id,
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
                "expired_in": 0,
                "musicid": int(credentials.uin),
                "musickey": credentials.token,
                "refresh_key": credentials.refresh_key,
                "loginMode": 2,
            },
        },
    }


def refresh_login(
    credentials: Credentials, device_file: Path, timeout: int = 20
) -> dict[str, Any]:
    import requests

    device = load_or_create(device_file)
    qimei = get_qimei(device, device_file, MOBILE_VERSION, timeout)
    body = compact_json(build_login_payload(credentials, qimei, device))
    response = requests.post(
        f"{LOGIN_URL}?sign={sign_payload(body)}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "QQMusic"},
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    req = result.get("req", {})
    code = req.get("code")
    if code != 0:
        raise RuntimeError(f"QQ Music login refresh returned code {code}")
    data = req.get("data")
    if not isinstance(data, dict) or not data.get("musickey"):
        raise RuntimeError("QQ Music login refresh returned no musickey")
    return data
