"""Radarr API client for YAMS integration tests."""

import requests

from . import config


class RadarrClient:
    """Minimal client for the Radarr v3 REST API."""

    def __init__(self, url: str = "", api_key: str = ""):
        self.url = (url or config.RADARR_URL).rstrip("/")
        self.api_key = api_key or config.RADARR_API_KEY
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": self.api_key})

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = self.session.get(f"{self.url}/api/v3{path}", **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Movie endpoints
    # ------------------------------------------------------------------

    def get_movies(self) -> list[dict]:
        """Return all movies in the Radarr library."""
        return self._get("/movie").json()

    def get_movie_by_id(self, movie_id: int) -> dict:
        """Return a single movie by its Radarr ID."""
        return self._get(f"/movie/{movie_id}").json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if Radarr responds to a health check."""
        resp = self.session.get(f"{self.url}/api/v3/system/status")
        return resp.status_code == 200
