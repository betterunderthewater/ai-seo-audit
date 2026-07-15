# AI SEO Readiness Audit

A tool that scores a local service business's visibility in AI-driven
search (Google AI Overviews, ChatGPT, Perplexity, Claude, Copilot) and
the traditional local/organic search that feeds those answers. Built for
sales/pitch use: point it at a prospect's website and it returns a
scored, evidence-backed audit you can turn into a report, a deck, or a
dashboard.

You run this yourself, one business at a time, from the command line.
Nothing here is scheduled or automated.

## How it works

Each run does three things:

1. **Technical checks** (`audit/technical_checks.py`, pure Python, no AI) --
   fetches the live site and checks the stuff that's objectively
   verifiable: robots.txt rules for AI crawlers (GPTBot, ClaudeBot,
   PerplexityBot, Google-Extended, etc.), whether `llms.txt` exists,
   whether key content renders without JavaScript, what schema.org
   structured data is present, and whether the site has dedicated pages
   for each service x city combination.

2. **Research pass** (Claude + web search) -- takes the technical
   findings and does everything that needs live information: 3-5 test
   queries a real buyer would ask an AI engine, off-site trust signals
   (Google Business Profile, BBB, Yelp, review counts), and a named
   competitor benchmark.

3. **Structuring pass** (Claude + structured outputs) -- synthesizes both
   of the above into a scored, schema-validated result: a 1-100 AI SEO
   Readiness Score broken down across five pillars, 1-5 ranked findings
   (each with plain-language issue, evidence, fix, effort, and expected
   outcome), and a "why now" close.

Passes 2 and 3 are split into separate API calls because the Claude API
doesn't allow web-search citations and structured JSON output
(`output_config.format`) in the same request.

The output is a validated `AuditResult` (see `audit/schema.py`) saved as
JSON, plus a readable Markdown summary. The JSON is the actual product --
turn it into a slide deck, a one-page teaser, a tracked spreadsheet
across prospects, or a live dashboard without re-running the research.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

## Usage

```bash
python -m audit.run_audit \
  --url "https://example-plumbing.com" \
  --business-name "Example Plumbing Co" \
  --industry "residential plumbing" \
  --markets "San Diego,Chula Vista,La Mesa" \
  --competitors "Rapid Rooter Plumbing,ProFlow Plumbing"
```

Outputs land in `./audits/`:

- `<slug>-<timestamp>.technical.json` -- raw technical check results
- `<slug>-<timestamp>.research-notes.txt` -- Claude's live research notes
- `<slug>-<timestamp>.result.json` -- the final structured `AuditResult`
- `<slug>-<timestamp>.summary.md` -- a readable report

### Options

| Flag | Description |
|---|---|
| `--competitors` | Optional. Names of known local competitors; Claude will also try to find its own. |
| `--model` | Claude model to use. Defaults to `claude-sonnet-5`. |
| `--max-searches` | Cap on web searches for the research pass (default 12). |
| `--out-dir` | Where to save results (default `./audits`). |
| `--dry-run` | Run only the local technical checks and skip both Claude API calls. Useful for testing a site without spending API credits. |

## Scope and honesty about limitations

- The technical checks are genuinely automated and deterministic -- same
  site, same result, no API key required (`--dry-run`).
- "Live AI visibility" test queries are approximated through Claude's web
  search, which reflects what currently ranks and gets cited on the open
  web -- it is not a literal API call to ChatGPT, Perplexity, or Copilot.
  Treat those results as a strong proxy, not a guarantee of what each
  specific engine would say verbatim.
- Off-site trust signals (review counts, GBP category) are pulled via web
  search rather than the Google Business Profile API, so treat exact
  numbers as approximate and verify anything that goes into a client-facing
  deliverable before sending it.
- The audit intentionally skips deep technical SEO (crawl budget, Core Web
  Vitals minutiae, log files) unless it's genuinely the headline finding --
  this is built for a non-technical leadership audience, not a full
  technical SEO audit.

## Project layout

```
audit/
  schema.py            # Pydantic models -- the output contract
  technical_checks.py  # Deterministic site checks, no AI
  prompts.py           # System prompts for both Claude passes
  run_audit.py          # CLI entry point / orchestration
requirements.txt
.env.example
```
