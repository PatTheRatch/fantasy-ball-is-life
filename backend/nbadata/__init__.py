"""
FCP Projections M-1 — NBA data ingest layer (shared infrastructure).

Fed by the ``nba_api`` package. Deliberately built as shared infrastructure:
the projection model (M-3+) and the Streaming Advisor's future enrichment
adapter (S-5) both read these tables.

Tables:
  - nba_player_seasons  — one row per player per season (~15 seasons back)
  - nba_player_bio      — DOB, height, weight, draft info, experience

Global tables (not league-scoped): public-read, service-role-write RLS.
"""
