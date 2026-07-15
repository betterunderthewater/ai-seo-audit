"""
Structured output schema for the AI SEO Readiness Audit.

This is the contract between the audit tool and everything downstream
(reports, dashboards, decks, spreadsheets). Every run produces one
AuditResult, saved as JSON, that any renderer can consume without
knowing anything about how the audit was performed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Effort = Literal["quick win", "30 days", "90 days"]


class PillarScore(BaseModel):
    points: int = Field(..., description="Points awarded for this pillar.")
    max_points: int = Field(..., description="Maximum possible points for this pillar.")
    rationale: str = Field(
        ..., description="One to three sentences explaining the score, citing specific evidence."
    )


class ScoreBreakdown(BaseModel):
    crawler_access: PillarScore = Field(
        ..., description="AI & search crawler access, technical foundation. Max 15."
    )
    answer_ready_content: PillarScore = Field(
        ..., description="Answer-ready, market-specific content. Max 25."
    )
    entity_clarity: PillarScore = Field(
        ..., description="Entity clarity & structured data. Max 20."
    )
    offsite_authority: PillarScore = Field(
        ..., description="Off-site authority, reviews & citations. Max 25."
    )
    ai_visibility: PillarScore = Field(
        ..., description="Live AI visibility from test queries. Max 15."
    )
    total: int = Field(..., description="Sum of all five pillars. Must equal the points above.")


class Finding(BaseModel):
    title: str = Field(..., description="Short headline for the issue, e.g. 'No city-specific service pages'.")
    issue: str = Field(
        ...,
        description=(
            "Plain-language description of the problem a non-technical owner could understand in "
            "30 seconds, including the evidence (what was found, where, with URLs quoted)."
        ),
    )
    evidence: str = Field(
        ..., description="The specific proof: quoted text, URL, status code, or robots.txt line."
    )
    fix: str = Field(
        ..., description="What we would do, described in outcome language, not tool or jargon language."
    )
    effort: Effort = Field(..., description="Rough effort to implement the fix.")
    expected_outcome: str = Field(
        ...,
        description=(
            "Specific, mechanism-based expected result, e.g. 'becomes eligible to appear when AI "
            "engines answer X' or 'closes the gap with [competitor]'. Never a guaranteed ranking or "
            "traffic number."
        ),
    )


class TestQueryResult(BaseModel):
    query: str = Field(..., description="The exact query a real buyer would type or ask.")
    engine: str = Field(..., description="Which engine was tested, e.g. 'ChatGPT', 'Perplexity', 'Google AI Overview'.")
    brand_appeared: bool = Field(..., description="Whether the business appeared or was cited in the answer.")
    notes: str = Field(..., description="What was actually said/cited, or what appeared instead of the brand.")


class CompetitorBenchmark(BaseModel):
    name: str = Field(..., description="Competitor business name.")
    notes: str = Field(
        ..., description="What this competitor is doing that this site isn't, with specific evidence."
    )


class AuditResult(BaseModel):
    business_name: str
    website_url: str
    industry: str
    markets: list[str]

    score: ScoreBreakdown
    verdict: str = Field(..., description="One-sentence summary verdict for the top of the report.")

    whats_working: list[str] = Field(
        default_factory=list,
        description="Things already done correctly. At least one if genuinely true, otherwise empty.",
    )

    findings: list[Finding] = Field(
        ..., description="1 to 5 high-impact issues, ranked by impact, highest first."
    )

    test_queries: list[TestQueryResult] = Field(
        default_factory=list, description="Results of the 3-5 live AI test queries."
    )

    competitor_benchmark: list[CompetitorBenchmark] = Field(
        default_factory=list, description="1-2 named local competitors that are winning, with evidence."
    )

    why_now: str = Field(
        ..., description="2-3 sentences on the cost of inaction, grounded in the competitor benchmark."
    )

    sources: list[str] = Field(
        default_factory=list, description="URLs used as evidence across the audit (deduplicated)."
    )
