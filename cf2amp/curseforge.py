from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


MINECRAFT_GAME_ID = 432
MODPACK_CLASS_ID = 4471


class CurseForgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModpackFile:
    id: int
    display_name: str
    file_name: str
    download_url: str | None
    release_type: int
    game_versions: list[str]
    server_pack_file_id: int | None
    file_date: str | None


class CurseForgeClient:
    def __init__(self, api_key: str, base_url: str = "https://api.curseforge.com/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def search_modpacks(self, query: str, page_size: int = 10) -> list[dict[str, Any]]:
        params = {
            "gameId": MINECRAFT_GAME_ID,
            "classId": MODPACK_CLASS_ID,
            "searchFilter": query,
            "pageSize": page_size,
            "sortField": 6,
            "sortOrder": "desc",
        }
        payload = self._request_json("GET", "/mods/search", params=params)
        return payload.get("data", [])

    def get_mod(self, mod_id: int) -> dict[str, Any]:
        payload = self._request_json("GET", f"/mods/{mod_id}")
        return payload["data"]

    def get_files(
        self,
        mod_id: int,
        minecraft_version: str | None = None,
        page_size: int = 50,
    ) -> list[ModpackFile]:
        params: dict[str, Any] = {"pageSize": page_size}
        if minecraft_version:
            params["gameVersion"] = minecraft_version
        payload = self._request_json("GET", f"/mods/{mod_id}/files", params=params)
        files = payload.get("data", [])
        return [self._parse_file(item) for item in files]

    def get_file(self, mod_id: int, file_id: int) -> ModpackFile:
        payload = self._request_json("GET", f"/mods/{mod_id}/files/{file_id}")
        return self._parse_file(payload["data"])

    def get_download_url(self, mod_id: int, file_id: int) -> str:
        payload = self._request_json("GET", f"/mods/{mod_id}/files/{file_id}/download-url")
        url = payload.get("data")
        if not url:
            raise CurseForgeError(f"No download URL for project {mod_id} file {file_id}")
        return url

    def download(self, url: str, destination: str) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "cf2amp-serverupdater/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                with open(destination, "wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
        except urllib.error.URLError as exc:
            raise CurseForgeError(f"Download failed: {url}: {exc}") from exc

    def _request_json(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            method=method,
            headers={
                "Accept": "application/json",
                "x-api-key": self.api_key,
                "User-Agent": "cf2amp-serverupdater/0.1",
            },
        )

        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise CurseForgeError(f"CurseForge API error {exc.code}: {body}") from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                raise CurseForgeError(f"CurseForge API request failed: {exc}") from exc

        raise CurseForgeError("CurseForge API request failed")

    @staticmethod
    def _parse_file(item: dict[str, Any]) -> ModpackFile:
        return ModpackFile(
            id=int(item["id"]),
            display_name=item.get("displayName") or item.get("fileName") or str(item["id"]),
            file_name=item.get("fileName") or str(item["id"]),
            download_url=item.get("downloadUrl"),
            release_type=int(item.get("releaseType") or 0),
            game_versions=list(item.get("gameVersions") or []),
            server_pack_file_id=item.get("serverPackFileId"),
            file_date=item.get("fileDate"),
        )
