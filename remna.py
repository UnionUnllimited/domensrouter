"""Optional read-only Remnawave client: only GET requests, used to avoid paying twice for one device."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)


class Remnawave:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            # Required by Remnawave when the backend port is called directly over plain HTTP
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "127.0.0.1",
        }
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(headers=self._headers, timeout=aiohttp.ClientTimeout(total=15))

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def _get(self, path: str) -> Any:
        assert self._session is not None, "call start() first"
        async with self._session.get(self.base_url + path) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        return data.get("response") if isinstance(data, dict) else data

    async def hwids_by_username(self, username: str) -> list[str]:
        """HWIDs of the panel user; empty list if unknown or the panel is unreachable."""
        try:
            user = await self._get(f"/api/users/by-username/{quote(username, safe='')}")
            if not isinstance(user, dict) or not user.get("uuid"):
                return []
            data = await self._get(f"/api/hwid/devices/{user['uuid']}")
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("Remnawave lookup failed for %s: %s", username, exc)
            return []
        devices = data.get("devices", []) if isinstance(data, dict) else (data or [])
        return [str(d["hwid"]) for d in devices if isinstance(d, dict) and d.get("hwid")]
