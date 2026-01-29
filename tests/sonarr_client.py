"""Sonarr API client for YAMS integration tests."""

import requests

from . import config


class SonarrClient:
    """Minimal client for the Sonarr v3 REST API."""

    def __init__(self, url: str = "", api_key: str = ""):
        self.url = (url or config.SONARR_URL).rstrip("/")
        self.api_key = api_key or config.SONARR_API_KEY
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": self.api_key})

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = self.session.get(f"{self.url}/api/v3{path}", **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Series endpoints
    # ------------------------------------------------------------------

    def get_series(self) -> list[dict]:
        """Return all series in the Sonarr library."""
        return self._get("/series").json()

    def get_series_by_id(self, series_id: int) -> dict:
        """Return a single series by its Sonarr ID."""
        return self._get(f"/series/{series_id}").json()

    # ------------------------------------------------------------------
    # Episode endpoints
    # ------------------------------------------------------------------

    def get_episodes(self, series_id: int) -> list[dict]:
        """Return all episodes for a given series."""
        return self._get("/episode", params={"seriesId": series_id}).json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if Sonarr responds to a health check."""
        resp = self.session.get(f"{self.url}/api/v3/system/status")
        return resp.status_code == 200
