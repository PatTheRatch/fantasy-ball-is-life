"""Validated contracts for weekly recap facts and generated narrative."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class EvidenceNarrative(BaseModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class MatchupTakeaway(EvidenceNarrative):
    matchup_id: str


class RankingExplanation(EvidenceNarrative):
    team_id: str


class AwardExplanation(EvidenceNarrative):
    award_id: str


class PlayoffMatchupRecap(EvidenceNarrative):
    matchup_id: str
    result_summary: str = Field(min_length=1)


class PlayoffOutlook(EvidenceNarrative):
    team: str


class PlayoffStoryline(EvidenceNarrative):
    title: str = Field(min_length=1)


class RecapGeneratedContent(BaseModel):
    headline: str = Field(min_length=1)
    dek: str = Field(min_length=1)
    lead_story: list[str] = Field(min_length=1)
    matchup_takeaways: list[MatchupTakeaway] = Field(default_factory=list)
    ranking_explanations: list[RankingExplanation] = Field(default_factory=list)
    award_explanations: list[AwardExplanation] = Field(default_factory=list)
    whatsapp_summary: str = Field(min_length=1)
    whatsapp_full: str = Field(min_length=1)
    # Playoff weeks only (see WeeklyFactSnapshot.playoff_context) -- empty/omitted
    # for a regular-season week.
    playoff_matchup_recaps: list[PlayoffMatchupRecap] = Field(default_factory=list)
    playoff_outlook: list[PlayoffOutlook] = Field(default_factory=list)
    playoff_storylines: list[PlayoffStoryline] = Field(default_factory=list)
    playoff_final_line: Optional[str] = None


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
