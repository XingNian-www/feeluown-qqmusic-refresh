"""A stable synthetic Android device identity used by QQ Music mobile RPC."""

from __future__ import annotations

import binascii
import hashlib
import json
import os
import random
import string
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass
class OSVersion:
    incremental: str = "5891938"
    release: str = "10"
    codename: str = "REL"
    sdk: int = 29


@dataclass
class Device:
    display: str = field(
        default_factory=lambda: f"QMAPI.{random.randint(100000, 999999)}.001"
    )
    product: str = "iarim"
    device: str = "sagit"
    board: str = "eomam"
    model: str = "MI 6"
    fingerprint: str = field(
        default_factory=lambda: (
            "xiaomi/iarim/sagit:10/eomam.200122.001/"
            f"{random.randint(1000000, 9999999)}:user/release-keys"
        )
    )
    boot_id: str = field(default_factory=lambda: str(uuid4()))
    proc_version: str = field(
        default_factory=lambda: (
            "Linux 5.4.0-54-generic-"
            f"{''.join(random.choices(string.ascii_letters + string.digits, k=8))} "
            "(android-build@google.com)"
        )
    )
    imei: str = field(default="")
    brand: str = "Xiaomi"
    bootloader: str = "U-boot"
    base_band: str = ""
    version: OSVersion = field(default_factory=OSVersion)
    sim_info: str = "T-Mobile"
    os_type: str = "android"
    mac_address: str = "00:50:56:C0:00:08"
    wifi_bssid: str = "00:50:56:C0:00:08"
    wifi_ssid: str = "<unknown ssid>"
    imsi_md5: list[int] = field(default_factory=lambda: list(hashlib.md5(os.urandom(16)).digest()))
    android_id: str = field(
        default_factory=lambda: binascii.hexlify(os.urandom(8)).decode("ascii")
    )
    apn: str = "wifi"
    vendor_name: str = "MIUI"
    vendor_os_name: str = "qmapi"
    qimei: dict[str, str] | None = None

    def __post_init__(self):
        if not self.imei:
            self.imei = random_imei()


def random_imei() -> str:
    digits = [random.randint(0, 9) for _ in range(14)]
    checksum = 0
    for index, number in enumerate(digits):
        value = number * 2 if (index + 2) % 2 == 0 else number
        checksum += value // 10 + value % 10
    digits.append((checksum * 9) % 10)
    return "".join(str(number) for number in digits)


def load_or_create(path: Path) -> Device:
    path = path.expanduser()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = OSVersion(**data["version"])
        return Device(**data)
    device = Device()
    save(path, device)
    return device


def save(path: Path, device: Device) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(device), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
