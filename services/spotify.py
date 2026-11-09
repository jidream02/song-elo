"""Минимальный клиент Spotify Web API (Client Credentials flow)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"


@dataclass(frozen=True)
class TrackInfo:
    spotify_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    genre: str | None
    cover_url: str | None
    url: str | None


class SpotifyError(RuntimeError):
    pass


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, timeout: float = 10.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.AsyncClient(timeout=timeout)
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    async def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at - 60:
            return self._token
        resp = await self._http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        if resp.status_code != 200:
            raise SpotifyError(f"Spotify auth failed: {resp.status_code} {resp.text[:200]}")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + payload.get("expires_in", 3600)
        return self._token

    async def _get(self, path: str, params: dict | None = None) -> dict:
        token = await self._get_token()
        resp = await self._http.get(
            f"{API_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 401:  # токен протух раньше времени — один повтор
            self._token = None
            token = await self._get_token()
            resp = await self._http.get(
                f"{API_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
        if resp.status_code != 200:
            raise SpotifyError(f"Spotify GET {path} failed: {resp.status_code}")
        return resp.json()

    async def search_track(self, query: str) -> TrackInfo | None:
        data = await self._get("/search", {"q": query, "type": "track", "limit": 1})
        items = data.get("tracks", {}).get("items", [])
        if not items:
            return None
        return await self._to_track_info(items[0])

    async def _to_track_info(self, item: dict) -> TrackInfo:
        album = item.get("album") or {}
        artists = item.get("artists") or []
        images = album.get("images") or []
        release = album.get("release_date") or ""
        year = int(release[:4]) if release[:4].isdigit() else None

        # У трека в Spotify нет жанра — берём жанры первого исполнителя.
        genre = None
        if artists and artists[0].get("id"):
            try:
                artist = await self._get(f"/artists/{artists[0]['id']}")
                genres = artist.get("genres") or []
                genre = ", ".join(genres[:3]) or None
            except (SpotifyError, httpx.HTTPError) as exc:
                log.warning("Не удалось получить жанр исполнителя: %s", exc)

        return TrackInfo(
            spotify_id=item["id"],
            title=item.get("name", "?"),
            artist=", ".join(a.get("name", "?") for a in artists) or "?",
            album=album.get("name"),
            year=year,
            genre=genre,
            cover_url=images[0]["url"] if images else None,
            url=(item.get("external_urls") or {}).get("spotify"),
        )
