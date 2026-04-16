"""Auto-update client using the GitHub Releases API.

Uses stdlib ``urllib`` only. Signature verification is a stub that checks
file presence/size; replace with real minisign / cosign before shipping.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

ProgressCB = Callable[[str, float], None] | None


class UpdateInfo(BaseModel):
    current_version: str
    latest_version: str
    available: bool
    release_url: str = ""
    download_url: str = ""
    changelog: str = ""
    published_at: str = ""


def _parse_semver(s: str) -> tuple[int, int, int]:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", s or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


class Updater:
    def __init__(self, repo: str = "openforge/openforge", current_version: str = "0.0.0") -> None:
        self.repo = repo
        self.current_version = current_version

    def check_for_updates(self, timeout: float = 10.0) -> UpdateInfo:
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            logger.warning("update check failed: %s", exc)
            return UpdateInfo(
                current_version=self.current_version,
                latest_version=self.current_version,
                available=False,
            )

        latest = str(data.get("tag_name", "") or data.get("name", "")).lstrip("v")
        available = _parse_semver(latest) > _parse_semver(self.current_version)

        download_url = ""
        for asset in data.get("assets", []) or []:
            name = str(asset.get("name", ""))
            if any(name.endswith(ext) for ext in (".exe", ".dmg", ".AppImage", ".zip", ".tar.gz")):
                download_url = asset.get("browser_download_url", "")
                break

        return UpdateInfo(
            current_version=self.current_version,
            latest_version=latest or self.current_version,
            available=available,
            release_url=data.get("html_url", ""),
            download_url=download_url,
            changelog=data.get("body", "") or "",
            published_at=data.get("published_at", "") or "",
        )

    def download(self, info: UpdateInfo, target: Path, progress: ProgressCB = None) -> Path:
        if not info.download_url:
            raise RuntimeError("no download URL in UpdateInfo")
        target.parent.mkdir(parents=True, exist_ok=True)

        def _hook(block_num: int, block_size: int, total_size: int) -> None:
            if progress and total_size > 0:
                frac = min(0.99, (block_num * block_size) / total_size)
                progress(f"Downloading {target.name}", frac)

        logger.info("downloading update %s -> %s", info.download_url, target)
        urllib.request.urlretrieve(info.download_url, target, reporthook=_hook)  # noqa: S310
        if progress:
            progress("Download complete", 1.0)
        return target

    def verify_signature(self, path: Path) -> bool:
        """Placeholder - real signature check should live here."""
        try:
            return path.exists() and path.stat().st_size > 0
        except OSError:
            return False
