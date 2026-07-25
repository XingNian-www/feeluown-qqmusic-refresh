"""Small, atomic JSON storage helpers for FeelUOwn data files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from feeluown.consts import DATA_DIR
except ImportError:
    DATA_DIR = Path.home() / ".FeelUOwn" / "data"


def _data_dir() -> Path:
    return Path(DATA_DIR)


def default_cookie_file() -> Path:
    return _data_dir() / "qqmusic_user_info.json"


def default_state_file() -> Path:
    return _data_dir() / "fuo_qqmusic_refresh.json"


def default_device_file() -> Path:
    return _data_dir() / "fuo_qqmusic_refresh_device.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def update_cookie_document(document: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    cookies = result.get("cookies")
    if not isinstance(cookies, dict):
        cookies = result
        result = dict(cookies)

    updated = dict(cookies)
    music_key = str(data.get("musickey") or "")
    if music_key:
        updated["qqmusic_key"] = music_key
        if "qm_keyst" in updated:
            updated["qm_keyst"] = music_key

    field_map = {
        "openid": ("psrf_qqopenid", "openid"),
        "access_token": ("psrf_qqaccess_token", "access_token"),
        "refresh_token": ("psrf_qqrefresh_token", "refresh_token"),
        "refresh_key": ("psrf_qqrefresh_key", "refresh_key"),
    }
    for source, targets in field_map.items():
        value = str(data.get(source) or "")
        if not value:
            continue
        existing_targets = [target for target in targets if target in updated]
        write_targets = existing_targets or [targets[0]]
        for target in write_targets:
            updated[target] = value

    if "uin" in updated and data.get("musicid"):
        updated["uin"] = str(data["musicid"])
    elif "uin" not in updated and "wxuin" not in updated and data.get("musicid"):
        updated["uin"] = str(data["musicid"])

    if "cookies" in result:
        result["cookies"] = updated
        return result
    return updated
