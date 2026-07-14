"""Validated contracts for weekly recap facts and generated narrative."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class MatchupTakeaway(BaseModel):
    """One matchup's writeup in the newsroom's three-voice + insight format.

    The factual header (who beat whom, the category score) comes from the
    deterministic snapshot, not here -- these are the opinionated takes."""

    matchup_id: str
    woj: str = Field(min_length=1)        # insider / measured
    barkley: str = Field(min_length=1)    # blunt / funny
    stephen_a: str = Field(min_length=1)  # dramatic / hot take
    insight: str = Field(min_length=1)    # grounded analytical line


class AwardExplanation(BaseModel):
    award_id: str
    text: str = Field(min_length=1)


class RecapGeneratedContent(BaseModel):
    headline: str = Field(min_length=1)   # title / theme line
    intro: str = Field(min_length=1)      # 1-3 punchy sentences
    matchup_takeaways: list[MatchupTakeaway] = Field(default_factory=list)
    award_explanations: list[AwardExplanation] = Field(default_factory=list)
    # Assembled server-side by sharing.format_share_text (not produced by the
    # LLM): the full group-chat-ready recap text for the Copy button.
    share_text: str = ""


class DataQualityReport(BaseModel):
    ready: bool
    warnings: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)
    transaction_quality: str = "counts_only"


class PlayoffContext(BaseModel):
    """Bracket facts for a playoff week, derived from league settings and this
    week's decided matchups. Absent entirely for a regular-season week."""

    round_label: str
    round_index: int
    total_rounds: int
    is_championship: bool
    advancing_teams: list[str] = Field(default_factory=list)
    eliminated_teams: list[str] = Field(default_factory=list)
    # Only populated once every advancing team appears in ESPN's own schedule
    # for the next round -- never guessed from seeding rules.
    next_round_matchups: list[dict[str, Any]] = Field(default_factory=list)


class WeeklyFactSnapshot(BaseModel):
    schema_version: str = "recap-facts-v1"
    league: dict[str, Any]
    season: int
    week: int
    week_dates: dict[str, str]
    matchups: list[dict[str, Any]]
    standings: list[dict[str, Any]]
    power_rankings: list[dict[str, Any]]
    transactions: list[dict[str, Any]]
    season_stats: list[dict[str, Any]]
    award_candidates: list[dict[str, Any]]
    data_quality: DataQualityReport
    playoff_context: Optional[PlayoffContext] = None


def validate_generated_content(value: Any) -> RecapGeneratedContent:
    if hasattr(RecapGeneratedContent, "model_validate"):
        return RecapGeneratedContent.model_validate(value)
    return RecapGeneratedContent.parse_obj(value)


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
