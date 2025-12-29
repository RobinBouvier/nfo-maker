"""TMDB API client with optional caching."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .utils import ensure_dir, get_cache_dir, get_config_dir


TMDB_BASE_URL = "https://api.themoviedb.org/3"


class TmdbError(RuntimeError):
    pass


@dataclass
class SearchResult:
    tmdb_id: int
    title: str
    original_title: str
    year: Optional[int]
    score: float


class TmdbClient:
    def __init__(
        self,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        timeout: int = 10,
        retries: int = 2,
    ) -> None:
        self.token = token
        self.api_key = api_key
        self.cache_dir = cache_dir or get_cache_dir()
        self.timeout = timeout
        self.retries = retries

    @classmethod
    def from_env(cls, config_path: Optional[Path] = None) -> "TmdbClient":
        config = cls._load_config(config_path)
        token = os.environ.get("TMDB_TOKEN") or config.get("tmdb_token")
        api_key = os.environ.get("TMDB_API_KEY") or config.get("tmdb_api_key")
        return cls(token=token, api_key=api_key)

    @staticmethod
    def _load_config(config_path: Optional[Path]) -> Dict[str, Any]:
        config_path = config_path or (get_config_dir() / "config.json")
        if not config_path.exists():
            return {}
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not (self.token or self.api_key):
            raise TmdbError("TMDB token or API key not configured.")
        params = params or {}
        if self.api_key:
            params["api_key"] = self.api_key
        query = urllib.parse.urlencode(params)
        url = f"{TMDB_BASE_URL}{path}"
        if query:
            url = f"{url}?{query}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)

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
        raise TmdbError(f"TMDB request failed: {last_error}")

    def _cache_path(self, movie_id: int, lang: Optional[str]) -> Path:
        suffix = lang or "default"
        return self.cache_dir / f"tmdb_{movie_id}_{suffix}.json"

    def get_movie(self, movie_id: int, lang: Optional[str] = None) -> Dict[str, Any]:
        cache_path = self._cache_path(movie_id, lang)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        params = {"language": lang} if lang else {}
        payload = self._request(f"/movie/{movie_id}", params=params)
        ensure_dir(self.cache_dir)
        cache_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return payload

    def get_external_ids(self, movie_id: int) -> Dict[str, Any]:
        return self._request(f"/movie/{movie_id}/external_ids")

    def search_movie(
        self, query: str, year: Optional[int] = None, lang: Optional[str] = None
    ) -> List[SearchResult]:
        params: Dict[str, Any] = {"query": query}
        if year:
            params["year"] = year
        if lang:
            params["language"] = lang
        payload = self._request("/search/movie", params=params)
        results = []
        for item in payload.get("results", []):
            release = item.get("release_date") or ""
            year_val = int(release[:4]) if release[:4].isdigit() else None
            score = float(item.get("popularity") or 0)
            results.append(
                SearchResult(
                    tmdb_id=int(item.get("id")),
                    title=item.get("title") or "",
                    original_title=item.get("original_title") or "",
                    year=year_val,
                    score=score,
                )
            )
        return results

    def resolve_movie(
        self,
        tmdb_id: Optional[int],
        title: Optional[str],
        year: Optional[int],
        lang: Optional[str],
        interactive: bool = False,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if tmdb_id:
            return self.get_movie(tmdb_id, lang=lang), None
        if not title:
            return None, None
        results = self.search_movie(title, year=year, lang=lang)
        if not results:
            return None, None
        if interactive:
            print("TMDB matches:")
            for idx, result in enumerate(results[:5], start=1):
                label = f"{result.title} ({result.year or 'N/A'})"
                print(f"  {idx}) {label} [id {result.tmdb_id}]")
            choice = input("Select match (1-5, Enter for 1): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= min(5, len(results)):
                picked = results[int(choice) - 1]
            else:
                picked = results[0]
        else:
            def score(result: SearchResult) -> float:
                boost = 5.0 if year and result.year == year else 0.0
                return result.score + boost
            picked = sorted(results, key=score, reverse=True)[0]
        match_note = f"{picked.tmdb_id} {picked.title} ({picked.year or 'N/A'})"
        return self.get_movie(picked.tmdb_id, lang=lang), match_note
