"""QQ Music credential extraction and response-to-cookie mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CredentialError(ValueError):
    pass


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is not None and str(value) != "":
            return str(value)
    return ""


def _uin(cookies: dict[str, Any], state: dict[str, Any]) -> str:
    value = _first_non_empty(
        cookies.get("uin"),
        cookies.get("wxuin"),
        state.get("uin"),
        state.get("musicid"),
    )
    return value[1:] if value.startswith("o") else value


@dataclass(frozen=True)
class Credentials:
    uin: str
    token: str
    open_id: str
    access_token: str
    refresh_token: str
    refresh_key: str

    def updated_state(self, data: dict[str, Any]) -> dict[str, str]:
        return {
            "uin": _first_non_empty(data.get("musicid"), self.uin),
            "token": _first_non_empty(data.get("musickey"), self.token),
            "open_id": _first_non_empty(data.get("openid"), self.open_id),
            "access_token": _first_non_empty(
                data.get("access_token"), self.access_token
            ),
            "refresh_token": _first_non_empty(
                data.get("refresh_token"), self.refresh_token
            ),
            "refresh_key": _first_non_empty(
                data.get("refresh_key"), self.refresh_key
            ),
        }


def validate_refresh_credentials(credentials: Credentials) -> None:
    """Reject cookies that can be checked but do not contain a refresh credential."""
    if credentials.refresh_token or credentials.refresh_key:
        return
    raise CredentialError(
        "missing QQ Music refresh credential: refresh_token or refresh_key; "
        "the current Cookie can be checked but cannot be force-refreshed"
    )


def credentials_from_sources(
    cookies: dict[str, Any],
    state: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Credentials:
    state = state or {}
    overrides = overrides or {}

    credentials = Credentials(
        uin=_uin(cookies, state),
        token=_first_non_empty(
            cookies.get("qqmusic_key"),
            cookies.get("qm_keyst"),
            state.get("token"),
        ),
        open_id=_first_non_empty(
            cookies.get("psrf_qqopenid"),
            cookies.get("openid"),
            state.get("open_id"),
            overrides.get("open_id"),
        ),
        access_token=_first_non_empty(
            cookies.get("psrf_qqaccess_token"),
            cookies.get("access_token"),
            state.get("access_token"),
            overrides.get("access_token"),
        ),
        refresh_token=_first_non_empty(
            cookies.get("psrf_qqrefresh_token"),
            cookies.get("refresh_token"),
            state.get("refresh_token"),
            overrides.get("refresh_token"),
        ),
        refresh_key=_first_non_empty(
            cookies.get("psrf_qqrefresh_key"),
            cookies.get("refresh_key"),
            state.get("refresh_key"),
            overrides.get("refresh_key"),
        ),
    )

    missing = [
        name
        for name, value in (
            ("uin", credentials.uin),
            ("token", credentials.token),
        )
        if not value
    ]
    if missing:
        raise CredentialError("missing QQ Music fields: " + ", ".join(missing))
    return credentials
