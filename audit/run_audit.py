#!/usr/bin/env python3
"""
AI SEO Readiness Audit -- CLI entry point.

Run manually, one business at a time:

    python -m audit.run_audit \\
        --url https://example-plumbing.com \\
        --business-name "Example Plumbing Co" \\
        --industry "residential plumbing" \\
        --markets "San Diego,Chula Vista,La Mesa" \\
        --competitors "Rapid Rooter Plumbing,ProFlow Plumbing"

Two API passes happen per run:
  1. Research pass -- Claude + web_search tool, gathers live AI-visibility
     test results, off-site trust signals, and a competitor benchmark.
  2. Structuring pass -- Claude + structured outputs, turns the research
     notes and the (locally computed) technical findings into the final
     AuditResult JSON. Split into two calls because the API does not
     allow web-search citations and output_config.format in one request.

Nothing here is scheduled or automatic -- you run this by hand for each
prospect you want to audit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from audit.prompts import (
    build_research_user_message,
    build_structuring_user_message,
    research_system_prompt,
    structuring_system_prompt,
)
from audit.schema import AuditResult
from audit.technical_checks import run_technical_checks

DEFAULT_MODEL = "claude-sonnet-5"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run an AI SEO Readiness Audit for one business.")
    p.add_argument("--url", required=True, help="Business website URL, e.g. https://example.com")
    p.add_argument("--business-name", required=True, help="Business name as it should appear in the report")
    p.add_argument("--industry", required=True, help="Industry/service type, e.g. 'residential plumbing'")
    p.add_argument(
        "--markets", required=True, help="Comma-separated cities/markets served, e.g. 'San Diego,Chula Vista'"
    )
    p.add_argument(
        "--competitors",
        default="",
        help="Comma-separated names of 1-2 known local competitors (optional -- Claude will also try to find its own)",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    p.add_argument("--max-searches", type=int, default=12, help="Cap on web searches for the research pass")
    p.add_argument("--out-dir", default="audits", help="Directory to save results (default: ./audits)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run only the local technical checks, skip both Claude API passes. Useful for testing without spending API credits.",
    )
    return p.parse_args(argv)


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def render_markdown_summary(result: AuditResult) -> str:
    s = result.score
    lines = [
        f"# AI SEO Readiness Audit -- {result.business_name}",
        "",
        f"**Site:** {result.website_url}  ",
        f"**Industry:** {result.industry}  ",
        f"**Markets:** {', '.join(result.markets)}",
        "",
        f"## Score: {s.total}/100",
        "",
        f"> {result.verdict}",
        "",
        "| Pillar | Score |",
        "|---|---|",
        f"| AI & search crawler access | {s.crawler_access.points}/{s.crawler_access.max_points} |",
        f"| Answer-ready, market-specific content | {s.answer_ready_content.points}/{s.answer_ready_content.max_points} |",
        f"| Entity clarity & structured data | {s.entity_clarity.points}/{s.entity_clarity.max_points} |",
        f"| Off-site authority, reviews & citations | {s.offsite_authority.points}/{s.offsite_authority.max_points} |",
        f"| Live AI visibility | {s.ai_visibility.points}/{s.ai_visibility.max_points} |",
        "",
    ]

    if result.whats_working:
        lines.append("## What's already working")
        lines.append("")
        for item in result.whats_working:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## Findings")
    lines.append("")
    for i, f in enumerate(result.findings, 1):
        lines += [
            f"### {i}. {f.title} ({f.effort})",
            "",
            f"**The issue:** {f.issue}",
            "",
            f"**Evidence:** {f.evidence}",
            "",
            f"**The fix:** {f.fix}",
            "",
            f"**Expected outcome:** {f.expected_outcome}",
            "",
        ]

    if result.test_queries:
        lines.append("## Live AI visibility test queries")
        lines.append("")
        lines.append("| Query | Engine | Brand appeared? | Notes |")
        lines.append("|---|---|---|---|")
        for q in result.test_queries:
            lines.append(f"| {q.query} | {q.engine} | {'Yes' if q.brand_appeared else 'No'} | {q.notes} |")
        lines.append("")

    if result.competitor_benchmark:
        lines.append("## Competitor benchmark")
        lines.append("")
        for c in result.competitor_benchmark:
            lines.append(f"- **{c.name}:** {c.notes}")
        lines.append("")

    lines += ["## Why now", "", result.why_now, ""]

    if result.sources:
        lines.append("## Sources")
        lines.append("")
        for src in result.sources:
            lines.append(f"- {src}")
        lines.append("")

    return "\n".join(lines)


def run_research_pass(client, model: str, max_searches: int, business: dict, technical: dict) -> str:
    """Pass A: Claude + web_search. Returns free-form research notes with an
    appended, deduplicated list of every URL Claude cited."""
    messages = [
        {"role": "user", "content": build_research_user_message(business, technical)}
    ]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}]

    all_text_parts: list[str] = []
    cited_urls: list[str] = []

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=research_system_prompt(),
            messages=messages,
            tools=tools,
        )

        for block in response.content:
            if block.type == "text":
                all_text_parts.append(block.text)
                for citation in getattr(block, "citations", None) or []:
                    url = getattr(citation, "url", None)
                    if url and url not in cited_urls:
                        cited_urls.append(url)

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        break

    notes = "\n".join(all_text_parts)
    if cited_urls:
        notes += "\n\nSOURCES CITED (from live search):\n" + "\n".join(f"- {u}" for u in cited_urls)
    return notes


def run_structuring_pass(client, model: str, business: dict, technical: dict, research_notes: str) -> AuditResult:
    """Pass B: Claude + structured outputs (no tools). Returns a validated AuditResult."""
    response = client.messages.parse(
        model=model,
        max_tokens=8192,
        system=structuring_system_prompt(),
        messages=[
            {"role": "user", "content": build_structuring_user_message(business, technical, research_notes)}
        ],
        output_format=AuditResult,
    )
    return response.parsed_output


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]

    business = {
        "name": args.business_name,
        "url": args.url,
        "industry": args.industry,
        "markets": markets,
        "known_competitors": competitors,
    }

    print(f"Running technical checks against {args.url} ...", file=sys.stderr)
    technical = run_technical_checks(args.url, args.business_name, args.industry, markets)

    out_dir = Path(args.out_dir)
    slug = slugify(args.business_name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_name = f"{slug}-{timestamp}"

    save_json(technical, out_dir / f"{base_name}.technical.json")
    print(f"Saved technical findings -> {out_dir / f'{base_name}.technical.json'}", file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run set: skipping Claude API passes. Technical findings only.", file=sys.stderr)
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY is not set. Add it to a .env file or export it, "
            "or re-run with --dry-run to test the technical checks only.",
            file=sys.stderr,
        )
        return 1

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    print("Running research pass (web search) ...", file=sys.stderr)
    research_notes = run_research_pass(client, args.model, args.max_searches, business, technical)
    (out_dir / f"{base_name}.research-notes.txt").parent.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{base_name}.research-notes.txt").write_text(research_notes, encoding="utf-8")

    print("Running structuring pass (structured output) ...", file=sys.stderr)
    result = run_structuring_pass(client, args.model, business, technical, research_notes)

    result_path = out_dir / f"{base_name}.result.json"
    save_json(result.model_dump(), result_path)

    summary_path = out_dir / f"{base_name}.summary.md"
    summary_path.write_text(render_markdown_summary(result), encoding="utf-8")

    print(f"\nDone. Score: {result.score.total}/100", file=sys.stderr)
    print(f"JSON  -> {result_path}", file=sys.stderr)
    print(f"Report -> {summary_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
