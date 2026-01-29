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
    # Metadata management
    # ------------------------------------------------------------------

    def refresh_item(self, item_id: str, replace_all_metadata: bool = True,
                     replace_all_images: bool = True) -> None:
        """Trigger a metadata refresh for a single item.

        POST /Items/{itemId}/Refresh
        """
        params = {
            "metadataRefreshMode": "FullRefresh",
            "imageRefreshMode": "FullRefresh",
            "replaceAllMetadata": str(replace_all_metadata).lower(),
            "replaceAllImages": str(replace_all_images).lower(),
        }
        resp = self.session.post(
            f"{self.url}/Items/{item_id}/Refresh", params=params,
        )
        resp.raise_for_status()

    def search_remote(self, item_id: str, media_type: str,
                      provider_id: str, provider_name: str) -> list[dict]:
        """Search remote metadata providers for matches.

        POST /Items/RemoteSearch/{Type}
        Returns a list of search result dicts.
        """
        type_map = {"tv": "Series", "movie": "Movie"}
        search_type = type_map.get(media_type, media_type)
        provider_ids = {provider_name: provider_id}
        body = {"SearchInfo": {"ProviderIds": provider_ids}, "ItemId": item_id}
        resp = self.session.post(
            f"{self.url}/Items/RemoteSearch/{search_type}", json=body,
        )
        resp.raise_for_status()
        return resp.json()

    def apply_search_result(self, item_id: str,
                            replace_all_images: bool = True) -> None:
        """Apply a remote search result to re-identify an item.

        POST /Items/RemoteSearch/Apply/{itemId}
        """
        params = {}
        if replace_all_images:
            params["ReplaceAllImages"] = "true"
        resp = self.session.post(
            f"{self.url}/Items/RemoteSearch/Apply/{item_id}", params=params,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if the server responds to a system ping."""
        resp = self.session.get(f"{self.url}/System/Ping")
        return resp.status_code == 200
