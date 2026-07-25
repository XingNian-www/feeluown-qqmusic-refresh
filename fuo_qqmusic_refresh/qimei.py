"""QIMEI request used by QQ Music's Android client RPC."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

from .device import Device, save

logger = logging.getLogger(__name__)

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDEIxgwoutfwoJxcGQeedgP7FG9qaIuS0qzfR8gWkrkTZKM2iWHn2ajQpBRZjMSoSf6+KJGvar2ORhBfpDXyVtZCKpqLQ+FLkpncClKVIrBwv6PHyUvuCb0rIarmgDnzkfQAqVufEtR64iazGDKatvJ9y6B9NMbHddGSAUmRTCrHQIDAQAB
-----END PUBLIC KEY-----"""
SECRET = "ZdJqM15EeO2zWc08"
APP_KEY = "0AND0HD6FE4HY80F"
QIMEI_FALLBACK = "6c9d3cd110abca9b16311cee10001e717614"


def _md5(*values: str) -> str:
    digest = hashlib.md5()
    for value in values:
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()


def _rsa_encrypt(content: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = serialization.load_pem_public_key(PUBLIC_KEY.encode("ascii"))
    return public_key.encrypt(content, padding.PKCS1v15())


def _aes_encrypt(key: bytes, content: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    cipher = Cipher(algorithms.AES(key), modes.CBC(key))
    pad_size = 16 - len(content) % 16
    encryptor = cipher.encryptor()
    return encryptor.update(content + bytes([pad_size]) * pad_size) + encryptor.finalize()


def _beacon_id() -> str:
    result = []
    month = datetime.now().strftime("%Y-%m-") + "01"
    rand1 = random.randint(100000, 999999)
    rand2 = random.randint(100000000, 999999999)
    timestamp_keys = {1, 2, 13, 14, 17, 18, 21, 22, 25, 26, 29, 30, 33, 34, 37, 38}
    for index in range(1, 41):
        if index in timestamp_keys:
            value = f"{month}{rand1}.{rand2}"
        elif index == 3:
            value = "0000000000000000"
        elif index == 4:
            value = "".join(random.choices("123456789abcdef", k=16))
        else:
            value = str(random.randint(0, 9999))
        result.append(f"k{index}:{value};")
    return "".join(result)


def _payload(device: Device, version: str) -> dict:
    fixed_rand = random.randint(0, 14400)
    reserved = {
        "harmony": "0",
        "clone": "0",
        "containe": "",
        "oz": "UhYmelwouA+V2nPWbOvLTgN2/m8jwGB+yUB5v9tysQg=",
        "oo": "Xecjt+9S1+f8Pz2VLSxgpw==",
        "kelong": "0",
        "uptimes": (datetime.now() - timedelta(seconds=fixed_rand)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "multiUser": "0",
        "bod": device.brand,
        "dv": device.device,
        "firstLevel": "",
        "manufact": device.brand,
        "name": device.model,
        "host": "se.infra",
        "kernel": device.proc_version,
    }
    return {
        "androidId": device.android_id,
        "platformId": 1,
        "appKey": APP_KEY,
        "appVersion": version,
        "beaconIdSrc": _beacon_id(),
        "brand": device.brand,
        "channelId": "10003505",
        "cid": "",
        "imei": device.imei,
        "imsi": "",
        "mac": "",
        "model": device.model,
        "networkType": "unknown",
        "oaid": "",
        "osVersion": f"Android {device.version.release},level {device.version.sdk}",
        "qimei": "",
        "qimei36": "",
        "sdkVersion": "1.2.13.6",
        "targetSdkVersion": "33",
        "audit": "",
        "userId": "{}",
        "packageId": "com.tencent.qqmusic",
        "deviceType": "Phone",
        "sdkName": "",
        "reserved": json.dumps(reserved, separators=(",", ":")),
    }


def get_qimei(device: Device, path: Path, version: str, timeout: int) -> dict[str, str]:
    if device.qimei and device.qimei.get("q36"):
        return device.qimei

    try:
        import requests

        crypt_key = "".join(random.choices("adbcdef1234567890", k=16))
        nonce = "".join(random.choices("adbcdef1234567890", k=16))
        timestamp = int(time.time())
        key = base64.b64encode(_rsa_encrypt(crypt_key.encode("ascii"))).decode("ascii")
        params = base64.b64encode(
            _aes_encrypt(
                crypt_key.encode("ascii"),
                json.dumps(_payload(device, version), separators=(",", ":")).encode(),
            )
        ).decode("ascii")
        extra = '{"appKey":"' + APP_KEY + '"}'
        request_sign = _md5(key, params, str(timestamp * 1000), nonce, SECRET, extra)
        response = requests.post(
            "https://api.tencentmusic.com/tme/trpc/proxy",
            headers={
                "Host": "api.tencentmusic.com",
                "method": "GetQimei",
                "service": "trpc.tme_datasvr.qimeiproxy.QimeiProxy",
                "appid": "qimei_qq_android",
                "sign": _md5(
                    "qimei_qq_androidpzAuCmaFAaFaHrdakPjLIEqKrGnSOOvH", str(timestamp)
                ),
                "User-Agent": "QQMusic",
                "timestamp": str(timestamp),
            },
            json={
                "app": 0,
                "os": 1,
                "qimeiParams": {
                    "key": key,
                    "params": params,
                    "time": str(timestamp),
                    "nonce": nonce,
                    "sign": request_sign,
                    "extra": extra,
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        encoded_data = body["data"]
        if isinstance(encoded_data, str):
            encoded_data = json.loads(encoded_data)
        result = encoded_data["data"]
        qimei = {"q16": str(result["q16"]), "q36": str(result["q36"])}
        device.qimei = qimei
        save(path, device)
        return qimei
    except Exception:
        logger.warning("QIMEI request failed; using fallback QIMEI", exc_info=True)
        return {"q16": "", "q36": QIMEI_FALLBACK}
