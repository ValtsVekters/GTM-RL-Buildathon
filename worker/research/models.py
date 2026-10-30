"""Data passed between the research agents."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    """One line for the "Agent thinking" panel."""

    agent: str
    kind: str  # tool | model | drop | flag | budget | error | done
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


@dataclass
class Person:
    name: str
    title: str
    email: str = ""
    email_status: str = "unknown"  # valid | risky | unknown
    email_confidence: int = 0


@dataclass
class Signal:
    signal: str
    quote: str
    verified: bool = False


@dataclass
class Lead:
    company: str
    domain: str
    source_url: str
    industry: str
    why_fit: str
    people: list[Person] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    fit_score: int = 0
    tier: str = "C"
    enrichment: str = "pending"  # pending | enriched | skipped | no_credits | failed
    review: str = "pending"  # pending | awaiting_approval | dropped
    review_notes: list[str] = field(default_factory=list)
