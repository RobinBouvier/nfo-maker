"""Client IMDb via OMDb API (fallback pour les recherches)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .utils import get_config_dir


OMDB_BASE_URL = "http://www.omdbapi.com/"


class ImdbError(RuntimeError):
    pass


class ImdbClient:
    """Client minimal OMDb: lookup par titre."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = 10, retries: int = 2) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries

    @classmethod
    def from_env(cls, config_path: Optional[Path] = None) -> "ImdbClient":
        """Construit le client depuis variables env ou config.json."""
        config = cls._load_config(config_path)
        api_key = (
            os.environ.get("IMDB_API_KEY")
            or os.environ.get("OMDB_API_KEY")
            or config.get("imdb_api_key")
            or config.get("omdb_api_key")
        )
        return cls(api_key=api_key)

    @staticmethod
    def _load_config(config_path: Optional[Path]) -> Dict[str, Any]:
        """Charge un fichier de configuration JSON si present."""
        if config_path:
            candidates = [config_path]
        else:
            local_candidates = [
                Path.cwd() / "config.json",
                Path(__file__).resolve().parent / "config.json",
            ]
            candidates = local_candidates + [get_config_dir() / "config.json"]
        for candidate in candidates:
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return {}
        return {}

    def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Envoie une requete OMDb avec retries simples."""
        if not self.api_key:
            raise ImdbError("OMDb API key not configured.")
        params = dict(params)
        params["apikey"] = self.api_key
        query = urllib.parse.urlencode(params)
        url = f"{OMDB_BASE_URL}?{query}"
        request = urllib.request.Request(url)

        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8")
                    return json.loads(payload)
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1)
                    continue
                break
        raise ImdbError(f"OMDb request failed: {last_error}")

    def search_title(self, query: str, year: Optional[int] = None) -> Optional[Tuple[str, Optional[int]]]:
        """Recherche un titre (exact puis search)."""
        if not query:
            return None
        params: Dict[str, Any] = {"t": query}
        if year:
            params["y"] = str(year)
        payload = self._request(params)
        if payload.get("Response") == "True":
            title = payload.get("Title") or ""
            year_val = _parse_year(payload.get("Year"))
            if title:
                return title, year_val

        params = {"s": query}
        if year:
            params["y"] = str(year)
        payload = self._request(params)
        items = payload.get("Search") if isinstance(payload, dict) else None
        if not items:
            return None
        if year:
            for item in items:
                year_val = _parse_year(item.get("Year"))
                if year_val == year and item.get("Title"):
                    return item["Title"], year_val
        first = items[0]
        title = first.get("Title") if isinstance(first, dict) else None
        if not title:
            return None
        return title, _parse_year(first.get("Year"))


def _parse_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    parts = value.split("–", 1)[0].split("-", 1)[0]
    return int(parts) if parts.isdigit() else None
