"""Fit score (0-100) and tier for a reviewed lead.

Only tier-A leads spend Hunter credits, so this rule decides where the scarcest
free quota goes.
"""

from .models import Lead


def score_lead(lead: Lead, icp: dict) -> int:
    # Default weights: industry fit 40, each verified trigger signal 15 (max 30),
    # each person whose title matches a target persona 15 (max 30).
    industries = {i.get("name", "").lower() for i in icp.get("industries", [])}
    personas = [p.get("title", "").lower() for p in icp.get("personas", []) if p.get("title")]
    score = 40 if lead.industry.lower() in industries else 0
    score += min(15 * sum(s.verified for s in lead.signals), 30)
    matches = sum(
        1 for person in lead.people
        if person.title and any(p in person.title.lower() or person.title.lower() in p for p in personas)
    )
    return score + min(15 * matches, 30)


def tier_for(score: int) -> str:
    return "A" if score >= 70 else "B" if score >= 40 else "C"
