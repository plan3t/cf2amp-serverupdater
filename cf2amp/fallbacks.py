from __future__ import annotations

import fnmatch
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .curseforge import CurseForgeError, ModpackFile


USER_AGENT = "plan3t/cf2amp-serverupdater/0.1"


@dataclass(frozen=True)
class FallbackContext:
    curseforge_project_id: int
    curseforge_file_id: int
    minecraft_version: str | None
    loader: str | None


class FallbackResolver:
    def __init__(self, sources: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ()) -> None:
        self.sources = list(sources)
        self.modrinth = ModrinthClient()
        self.github = GitHubReleaseClient()

    def resolve(self, context: FallbackContext) -> ModpackFile | None:
        for source in self.sources:
            if not self._matches(source, context):
                continue
            provider = str(source.get("provider") or source.get("type") or "").lower()
            if provider in {"ignore", "skip", "client-only", "clientonly"}:
                return None
            if provider == "modrinth":
                return self._resolve_modrinth(source, context)
            if provider in {"github", "githubrelease", "github-releases", "github_release"}:
                return self._resolve_github_release(source, context)
            if provider in {"url", "direct"}:
                return self._resolve_direct_url(source, context)
        return None

    def is_ignored(self, context: FallbackContext) -> bool:
        for source in self.sources:
            if not self._matches(source, context):
                continue
            provider = str(source.get("provider") or source.get("type") or "").lower()
            if provider in {"ignore", "skip", "client-only", "clientonly"}:
                return True
        return False

    @staticmethod
    def _matches(source: dict[str, Any], context: FallbackContext) -> bool:
        project_id = source.get("curseforgeProjectId", source.get("curseforge_project_id"))
        if project_id is None:
            project_id = source.get("projectID", source.get("projectId"))
        file_id = source.get("curseforgeFileId", source.get("curseforge_file_id"))
        if file_id is None:
            file_id = source.get("fileID", source.get("fileId"))
        if project_id is not None and int(project_id) != context.curseforge_project_id:
            return False
        if file_id is not None and int(file_id) != context.curseforge_file_id:
            return False
        return project_id is not None or file_id is not None

    def _resolve_modrinth(self, source: dict[str, Any], context: FallbackContext) -> ModpackFile | None:
        project = str(source.get("project") or source.get("slug") or source.get("projectId") or "")
        if not project:
            raise CurseForgeError("Modrinth fallback requires 'project' or 'slug'")
        version = self.modrinth.latest_project_version(
            project,
            minecraft_version=str(source.get("minecraftVersion") or context.minecraft_version or ""),
            loader=str(source.get("loader") or context.loader or ""),
        )
        if version is None:
            return None
        file = self.modrinth.primary_file(version, str(source.get("assetPattern") or "*.jar"))
        if file is None:
            return None
        return self._modpack_file_from_url(
            context,
            file_name=file["filename"],
            url=file["url"],
            display_name=f"{version.get('name') or version.get('version_number')} via Modrinth",
            game_versions=list(version.get("game_versions") or []),
        )

    def _resolve_github_release(self, source: dict[str, Any], context: FallbackContext) -> ModpackFile | None:
        repo = str(source.get("repo") or source.get("repository") or "")
        if not repo:
            raise CurseForgeError("GitHub fallback requires 'repo' in owner/name form")
        pattern = str(source.get("assetPattern") or source.get("asset_pattern") or "*.jar")
        release = self.github.release(repo, tag=source.get("tag"))
        asset = self.github.match_asset(release, pattern)
        if asset is None:
            return None
        return self._modpack_file_from_url(
            context,
            file_name=asset["name"],
            url=asset["browser_download_url"],
            display_name=f"{release.get('name') or release.get('tag_name')} via GitHub",
            game_versions=[context.minecraft_version] if context.minecraft_version else [],
        )

    def _resolve_direct_url(self, source: dict[str, Any], context: FallbackContext) -> ModpackFile | None:
        url = str(source.get("url") or "")
        file_name = str(source.get("fileName") or source.get("file_name") or url.rsplit("/", 1)[-1])
        if not url or not file_name:
            raise CurseForgeError("URL fallback requires 'url' and a downloadable file name")
        return self._modpack_file_from_url(
            context,
            file_name=file_name,
            url=url,
            display_name=f"{file_name} via URL",
            game_versions=[context.minecraft_version] if context.minecraft_version else [],
        )

    @staticmethod
    def _modpack_file_from_url(
        context: FallbackContext,
        file_name: str,
        url: str,
        display_name: str,
        game_versions: list[str],
    ) -> ModpackFile:
        return ModpackFile(
            id=context.curseforge_file_id,
            display_name=display_name,
            file_name=file_name,
            download_url=url,
            release_type=1,
            game_versions=game_versions,
            server_pack_file_id=None,
            file_date=None,
        )


class ModrinthClient:
    def __init__(self, base_url: str = "https://api.modrinth.com/v2") -> None:
        self.base_url = base_url.rstrip("/")

    def latest_project_version(
        self,
        project: str,
        minecraft_version: str,
        loader: str,
    ) -> dict[str, Any] | None:
        params: dict[str, str] = {}
        if minecraft_version:
            params["game_versions"] = json.dumps([minecraft_version])
        if loader:
            params["loaders"] = json.dumps([loader])
        path = f"/project/{urllib.parse.quote(project)}/version"
        versions = self._request_json("GET", path, params=params)
        if not versions:
            return None
        for version in versions:
            if self.primary_file(version, "*.jar") is not None:
                return version
        return None

    @staticmethod
    def primary_file(version: dict[str, Any], pattern: str) -> dict[str, Any] | None:
        files = [item for item in version.get("files", []) if str(item.get("filename", "")).endswith(".jar")]
        if not files:
            return None
        matches = [item for item in files if fnmatch.fnmatch(item.get("filename", ""), pattern)]
        candidates = matches or files
        for item in candidates:
            if item.get("primary"):
                return item
        return candidates[0]

    def _request_json(self, method: str, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            method=method,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        return _request_json(req, "Modrinth")


class GitHubReleaseClient:
    def release(self, repo: str, tag: Any = None) -> dict[str, Any]:
        safe_repo = "/".join(urllib.parse.quote(part) for part in str(repo).split("/", 1))
        path = f"/repos/{safe_repo}/releases/latest" if not tag else f"/repos/{safe_repo}/releases/tags/{urllib.parse.quote(str(tag))}"
        req = urllib.request.Request(
            f"https://api.github.com{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        return _request_json(req, "GitHub")

    @staticmethod
    def match_asset(release: dict[str, Any], pattern: str) -> dict[str, Any] | None:
        assets = release.get("assets", [])
        matches = [
            item
            for item in assets
            if item.get("browser_download_url")
            and str(item.get("name", "")).endswith(".jar")
            and fnmatch.fnmatch(str(item.get("name", "")), pattern)
        ]
        if matches:
            return matches[0]
        return None


def _request_json(req: urllib.request.Request, service_name: str, retries: int = 2) -> Any:
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1 + attempt)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise CurseForgeError(f"{service_name} API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            raise CurseForgeError(f"{service_name} API request failed: {exc}") from exc
    raise CurseForgeError(f"{service_name} API request failed")
