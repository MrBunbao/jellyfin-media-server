"""Jellyfin API client for YAMS integration tests."""

import requests

from . import config


class JellyfinClient:
    """Minimal client for the Jellyfin REST API."""

    def __init__(self, url: str = "", api_key: str = ""):
        self.url = (url or config.JELLYFIN_URL).rstrip("/")
        self.api_key = api_key or config.JELLYFIN_API_KEY
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f'MediaBrowser Token="{self.api_key}"'})

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = self.session.get(f"{self.url}{path}", **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Library endpoints
    # ------------------------------------------------------------------

    def get_libraries(self) -> list[dict]:
        """Return all media libraries (virtual folders)."""
        return self._get("/Library/VirtualFolders").json()

    def get_items(self, parent_id: str = "", **params) -> dict:
        """Return items, optionally filtered by parent library ID.

        Returns the full Jellyfin paged result with 'Items' and 'TotalRecordCount'.
        """
        if parent_id:
            params["ParentId"] = parent_id
        return self._get("/Items", params=params).json()

    def get_item_metadata(self, item_id: str) -> dict:
        """Return full metadata for a single item."""
        return self._get(f"/Items/{item_id}").json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if the server responds to a system ping."""
        resp = self.session.get(f"{self.url}/System/Ping")
        return resp.status_code == 200
