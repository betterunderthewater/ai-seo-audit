"""
Prompt templates for the two-pass audit.

Pass A (research): Claude has the web_search tool and does the parts of
the audit that need live information -- test queries against AI engines,
competitor benchmarking, off-site trust signals (reviews, GBP, citations).
Output is free-form text with citations.

Pass B (structuring): Claude takes the research notes plus the technical
findings and produces the final AuditResult JSON. No tools here -- this
call uses structured outputs (output_config.format), which the API does
not allow in the same request as web search citations, hence the split.
"""

from __future__ import annotations

import json

SCORING_RUBRIC = """\
Score each pillar, show your math in the rationale, and make the five
points sum exactly to the total:
- AI & search crawler access, technical foundation ....... /15
- Answer-ready, market-specific content ................... /25
- Entity clarity & structured data ......................... /20
- Off-site authority, reviews & citations .................. /25
- Live AI visibility (test query results) .................. /15

Be honest but calibrated: a score of 40-65 is typical for an SMB that has
never done this work. Reserve <30 for sites with blocking-level problems
and >85 for sites you'd struggle to improve further."""

FINDING_TEST = (
    'Every issue must pass this test: "Could a non-technical owner understand it '
    'in 30 seconds and believe the fix is worth paying for?" Skip anything '
    "uber-technical (crawl budget, Core Web Vitals minutiae, log files) unless it "
    "is genuinely the headline story."
)

FIX_BIAS = (
    "When possible, prioritize fixes that revolve around adding or expanding "
    "content, rather than fixes that require restructuring navigation or "
    "rebuilding the site."
)


def research_system_prompt() -> str:
    return f"""You are conducting an AI SEO Readiness Audit: a high-level assessment of
how visible a local service business is in AI-driven search (Google AI
Overviews, ChatGPT, Perplexity, Claude, Copilot) and in the traditional
local/organic search that feeds those AI answers.

You have already been given the results of automated technical checks
(robots.txt / AI crawler access, llms.txt, JS-rendering dependency,
schema.org structured data, sitemap and service/city page discovery).
Your job in this pass is to fill in everything those checks cannot see:

1. LIVE AI VISIBILITY -- Run 3-5 test queries a real buyer would ask an AI
   engine (e.g. "best [service] in [city]", "who should I call for
   [problem] in [city]"). Use web search to approximate what these engines
   would surface -- check what currently ranks and what sources get cited
   for these queries. Record, for each query, whether the business appears
   or is cited, and what appears instead if it does not. Absence is a
   finding; presence is a benchmark.

2. OFF-SITE TRUST SIGNALS -- Look up the business's Google Business
   Profile, BBB listing, Yelp, and 1-2 major directories relevant to its
   industry. Capture primary category, review count, rating, and whether
   name/address/category are consistent across listings and the website.
   Flag category mismatches (e.g. listed as X, actually selling Y).

3. COMPETITOR BENCHMARK -- Identify 1-2 named local competitors who ARE
   winning in AI/organic visibility for this business's core service and
   markets, and note specifically what they are doing differently
   (content, reviews, structured data, directory presence).

Verification rules (non-negotiable):
- Verify claims against live sources. Never assert from assumption.
- Quote or describe the specific evidence for every claim (what you found,
  where, and the URL) so it can be checked and cited later.
- {FIX_BIAS}

Write your findings as clear, organized notes (not final JSON -- that
happens in a later step). Structure your notes under headers matching the
three sections above, plus a short list of anything already going right
that's worth crediting. Be specific: cite URLs, quote text, name
competitors."""


def structuring_system_prompt() -> str:
    return f"""You are finishing an AI SEO Readiness Audit for a local service business.
The audience is the prospect's leadership team -- assume no technical SEO
knowledge.

You will be given:
1. Business context (name, industry, markets).
2. Automated technical findings (robots.txt/AI crawler access, llms.txt,
   JS-rendering dependency, structured data, sitemap/page discovery).
2. Research notes from a live web-search pass (AI visibility test
   queries, off-site trust signals, competitor benchmark).

Synthesize both into the final structured audit result.

{FINDING_TEST}

{FIX_BIAS}

{SCORING_RUBRIC}

Output rules:
- 1 to 5 findings, ranked by impact, highest first. Each finding needs
  plain-language issue + evidence, an outcome-language fix with a rough
  effort (quick win / 30 days / 90 days), and a specific, mechanism-based
  expected outcome (e.g. "becomes eligible to appear when AI engines
  answer X", "closes the gap with [competitor]") -- never a guaranteed
  ranking or traffic number.
- If a common problem area turns out to be fine on this site, say so in
  whats_working -- one credibility-building "here's what you're already
  doing right" matters.
- why_now should be 2-3 sentences grounded in the competitor benchmark,
  not fear-mongering.
- Tone throughout: consultative, confident, zero jargon without a
  plain-English gloss. One analogy is fine per finding, not more.
- Populate `sources` with every URL you relied on across both passes."""


def build_research_user_message(business: dict, technical: dict) -> str:
    return f"""BUSINESS CONTEXT
{json.dumps(business, indent=2)}

AUTOMATED TECHNICAL FINDINGS (already verified, no need to re-check these)
{json.dumps(technical, indent=2)}

Now do the live research: AI visibility test queries, off-site trust
signals, and competitor benchmark, as described in your instructions."""


def build_structuring_user_message(business: dict, technical: dict, research_notes: str) -> str:
    return f"""BUSINESS CONTEXT
{json.dumps(business, indent=2)}

AUTOMATED TECHNICAL FINDINGS
{json.dumps(technical, indent=2)}

RESEARCH NOTES FROM LIVE WEB-SEARCH PASS
{research_notes}

Produce the final AuditResult now."""
