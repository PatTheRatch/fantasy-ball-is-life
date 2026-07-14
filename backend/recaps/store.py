"""Small PostgREST client for recap persistence.

Supabase is storage and auth only. Keeping the client here makes FastAPI the
single runtime boundary and keeps the service-role key out of the browser.
"""
from __future__ import annotations

from typing import Any

import requests

from backend import config


class RecapStoreError(RuntimeError):
    """Raised when Supabase cannot satisfy a recap persistence request."""


class RecapStore:
    def __init__(
        self,
        *,
        url: str | None = None,
        service_role_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.url = (url if url is not None else config.SUPABASE_URL).rstrip("/")
        self.service_role_key = (
            service_role_key
            if service_role_key is not None
            else config.SUPABASE_SERVICE_ROLE_KEY
        )
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        if not self.url or not self.service_role_key:
            raise RecapStoreError(
                "Supabase is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY."
            )

        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer

        try:
            response = requests.request(
                method,
                f"{self.url}/rest/v1/{path.lstrip('/')}",
                params=params,
                json=json,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RecapStoreError(f"Supabase request failed: {exc}") from exc

        if not response.ok:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise RecapStoreError(
                f"Supabase returned {response.status_code}: {detail}"
            )

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get_league_by_slug(self, slug: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "leagues",
            params={
                "slug": f"eq.{slug}",
                "select": (
                    "id,slug,name,logo_url,accent_color,visibility,recap_voice,"
                    "owner_user_id,admin_user_id,espn_league_id"
                ),
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def is_league_admin(self, league: dict[str, Any], user_id: str) -> bool:
        if user_id in {league.get("owner_user_id"), league.get("admin_user_id")}:
            return True
        rows = self._request(
            "GET",
            "league_memberships",
            params={
                "league_id": f"eq.{league['id']}",
                "user_id": f"eq.{user_id}",
                "role": "in.(owner,admin)",
                "select": "user_id",
                "limit": "1",
            },
        )
        return bool(rows)

    def next_version(
        self,
        table: str,
        *,
        league_id: str,
        season: int,
        week: int,
    ) -> int:
        if table not in {"league_week_snapshots", "recap_editions"}:
            raise ValueError(f"Unsupported versioned table: {table}")
        rows = self._request(
            "GET",
            table,
            params={
                "league_id": f"eq.{league_id}",
                "season": f"eq.{season}",
                "week": f"eq.{week}",
                "select": "version",
                "order": "version.desc",
                "limit": "1",
            },
        )
        return int(rows[0]["version"]) + 1 if rows else 1

    def insert_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "league_week_snapshots",
            json=payload,
            prefer="return=representation",
        )
        return rows[0]

    def insert_edition(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "recap_editions",
            json=payload,
            prefer="return=representation",
        )
        return rows[0]

    def get_power_rankings(
        self, *, league_id: str, season: int, week: int
    ) -> dict[str, Any] | None:
        """The persisted power-rankings blurbs for one week, or ``None`` if
        this week hasn't been generated yet. One row per (league, season,
        week) -- no versioning, since the point is to never redo it."""
        rows = self._request(
            "GET",
            "power_ranking_editions",
            params={
                "league_id": f"eq.{league_id}",
                "season": f"eq.{season}",
                "week": f"eq.{week}",
                "select": "id,ranking_explanations_json,created_at",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def insert_power_rankings(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "power_ranking_editions",
            json=payload,
            prefer="return=representation",
        )
        return rows[0]

    _EDITION_WITH_SNAPSHOT_SELECT = (
        "*,league_week_snapshots("
        "schema_version,matchups_json,standings_json,power_rankings_json,"
        "transactions_json,season_stats_json,award_candidates_json,"
        "data_quality_json)"
    )

    def get_edition(
        self,
        *,
        league_id: str,
        season: int,
        week: int,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        params = {
            "league_id": f"eq.{league_id}",
            "season": f"eq.{season}",
            "week": f"eq.{week}",
            "select": self._EDITION_WITH_SNAPSHOT_SELECT,
            "order": "version.desc",
            "limit": "1",
        }
        if status:
            params["status"] = f"eq.{status}"
        rows = self._request("GET", "recap_editions", params=params)
        return rows[0] if rows else None

    def list_published(
        self, league_id: str, season: int
    ) -> list[dict[str, Any]]:
        """Return all published editions for a league/season, ordered by week.

        Each row: ``{week, headline, published_at}``. Unpublished weeks are
        absent. Used by the public archive navigation.
        """
        rows = self._request(
            "GET",
            "recap_editions",
            params={
                "league_id": f"eq.{league_id}",
                "season": f"eq.{season}",
                "status": "eq.published",
                "select": "week,structured_content_json->headline,published_at",
                "order": "week.asc",
            },
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "week": r["week"],
                "published_at": r.get("published_at"),
            }
            headline = r.get("headline")
            if headline and isinstance(headline, str):
                entry["headline"] = headline
            out.append(entry)
        return out

    def get_edition_by_id(self, edition_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "recap_editions",
            params={
                "id": f"eq.{edition_id}",
                "select": "id,league_id,season,week,status",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_edition_with_content_by_id(self, edition_id: str) -> dict[str, Any] | None:
        """Full content (structured narrative + snapshot) for one specific
        edition, regardless of its status -- lets an admin preview any past
        draft/superseded/published version, not just the latest."""
        rows = self._request(
            "GET",
            "recap_editions",
            params={
                "id": f"eq.{edition_id}",
                "select": self._EDITION_WITH_SNAPSHOT_SELECT,
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def get_history(
        self,
        *,
        league_id: str,
        season: int,
        week: int,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "recap_editions",
            params={
                "league_id": f"eq.{league_id}",
                "season": f"eq.{season}",
                "week": f"eq.{week}",
                "select": (
                    "id,version,status,data_warnings_json,created_by,created_at,"
                    "published_at"
                ),
                "order": "version.desc",
            },
        )

    def publish(self, edition_id: str, actor_user_id: str) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "rpc/publish_recap_edition",
            json={
                "target_edition_id": edition_id,
                "actor_user_id": actor_user_id,
            },
        )
        if isinstance(rows, list):
            return rows[0]
        return rows

    def rollback(
        self,
        edition_id: str,
        *,
        league_id: str,
        season: int,
        week: int,
    ) -> dict[str, Any]:
        edition = self.get_edition_by_id(edition_id)
        if (
            not edition
            or edition.get("league_id") != league_id
            or int(edition.get("season", -1)) != season
            or int(edition.get("week", -1)) != week
        ):
            raise RecapStoreError("Recap edition not found.")

        rows = self._request(
            "PATCH",
            "recap_editions",
            params={
                "id": f"eq.{edition_id}",
                "league_id": f"eq.{league_id}",
                "season": f"eq.{season}",
                "week": f"eq.{week}",
            },
            json={"status": "draft", "published_at": None},
            prefer="return=representation",
        )
        if not rows:
            raise RecapStoreError("Recap edition could not be rolled back.")
        return rows[0]
