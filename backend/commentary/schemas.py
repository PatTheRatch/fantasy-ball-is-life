"""Validated contracts for weekly recap facts and generated narrative."""
from __future__ import annotations

from typing import Any

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


class RecapGeneratedContent(BaseModel):
    headline: str = Field(min_length=1)
    dek: str = Field(min_length=1)
    lead_story: list[str] = Field(min_length=1)
    matchup_takeaways: list[MatchupTakeaway] = Field(default_factory=list)
    ranking_explanations: list[RankingExplanation] = Field(default_factory=list)
    award_explanations: list[AwardExplanation] = Field(default_factory=list)
    whatsapp_summary: str = Field(min_length=1)
    whatsapp_full: str = Field(min_length=1)


class DataQualityReport(BaseModel):
    ready: bool
    warnings: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)
    transaction_quality: str = "counts_only"


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


def validate_generated_content(value: Any) -> RecapGeneratedContent:
    if hasattr(RecapGeneratedContent, "model_validate"):
        return RecapGeneratedContent.model_validate(value)
    return RecapGeneratedContent.parse_obj(value)


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
