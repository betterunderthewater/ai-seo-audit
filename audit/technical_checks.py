"""
Deterministic technical checks for the AI SEO Readiness Audit.

These are the things that don't need judgment: can a crawler read this
site, is structured data present, does the sitemap have the pages it
should. Everything here is verifiable by fetching a URL, so it runs
without an LLM in the loop and produces the same result every time.

The output of run_technical_checks() is a plain dict that gets handed
to Claude as evidence for the parts of the audit that DO need judgment
(live AI visibility, competitor benchmarking, scoring).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; AISEOReadinessAudit/1.0; +https://github.com/)"
TIMEOUT = 15

AI_BOTS = [
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
]

JS_FRAMEWORK_ROOT_IDS = ["root", "app", "__next", "__nuxt", "___gatsby"]


def _get(url: str, **kwargs) -> requests.Response | None:
    try:
        return requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, allow_redirects=True, **kwargs
        )
    except requests.RequestException:
        return None


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ---------------------------------------------------------------------------
# 1. AI crawler access (robots.txt + llms.txt)
# ---------------------------------------------------------------------------


def _parse_robots_txt(text: str) -> dict[str, list[str]]:
    """Very small robots.txt parser: returns {user-agent: [directive lines]}."""
    groups: dict[str, list[str]] = {}
    current_agents: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            # A run of consecutive User-agent lines belongs to the same group.
            if current_agents and groups.get(current_agents[-1]) not in (None, []):
                current_agents = [value]
            else:
                current_agents.append(value)
            for agent in current_agents:
                groups.setdefault(agent, [])
        elif current_agents:
            for agent in current_agents:
                groups[agent].append(f"{key}: {value}")
    return groups


def _bot_status(groups: dict[str, list[str]], bot: str) -> dict:
    """Determine whether a specific bot is blocked, based on its own group or the wildcard group."""
    directives = groups.get(bot)
    matched_agent = bot
    if directives is None:
        directives = groups.get("*", [])
        matched_agent = "*" if "*" in groups else None

    blocked = False
    disallow_rules = []
    for d in directives:
        if d.lower().startswith("disallow:"):
            path = d.split(":", 1)[1].strip()
            disallow_rules.append(path)
            if path == "/":
                blocked = True

    return {
        "matched_group": matched_agent,
        "blocked_entirely": blocked,
        "disallow_rules": disallow_rules,
        "explicit_group_found": bot in groups,
    }


def check_robots_txt(base_url: str) -> dict:
    url = urljoin(base_url, "/robots.txt")
    resp = _get(url)
    if resp is None or resp.status_code >= 400:
        return {
            "fetched": False,
            "url": url,
            "status_code": getattr(resp, "status_code", None),
            "note": "robots.txt not found or unreachable. Default assumption: no bots are blocked.",
            "bots": {bot: {"blocked_entirely": False, "explicit_group_found": False} for bot in AI_BOTS},
        }

    groups = _parse_robots_txt(resp.text)
    bots = {bot: _bot_status(groups, bot) for bot in AI_BOTS}
    return {
        "fetched": True,
        "url": url,
        "status_code": resp.status_code,
        "raw_text": resp.text[:5000],
        "groups_found": list(groups.keys()),
        "bots": bots,
    }


def check_llms_txt(base_url: str) -> dict:
    url = urljoin(base_url, "/llms.txt")
    resp = _get(url)
    present = resp is not None and resp.status_code == 200 and len(resp.text.strip()) > 0
    return {
        "present": present,
        "url": url,
        "status_code": getattr(resp, "status_code", None),
        "excerpt": resp.text[:500] if present else None,
    }


# ---------------------------------------------------------------------------
# 2. Content extractability (JS dependency heuristic)
# ---------------------------------------------------------------------------


def check_js_dependency(url: str) -> dict:
    resp = _get(url)
    if resp is None or resp.status_code >= 400:
        return {
            "fetched": False,
            "status_code": getattr(resp, "status_code", None),
            "likely_js_dependent": None,
            "note": "Could not fetch page for JS-dependency check.",
        }

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible_text = soup.get_text(separator=" ", strip=True)
    word_count = len(visible_text.split())

    signals = []
    for root_id in JS_FRAMEWORK_ROOT_IDS:
        el = soup.find(id=root_id)
        if el is not None and len(el.get_text(strip=True)) < 40:
            signals.append(f"Empty or near-empty root element found: #{root_id}")

    likely_js_dependent = word_count < 150 or len(signals) > 0

    return {
        "fetched": True,
        "status_code": resp.status_code,
        "raw_html_word_count": word_count,
        "signals": signals,
        "likely_js_dependent": likely_js_dependent,
        "sample_text": visible_text[:300],
    }


# ---------------------------------------------------------------------------
# 3. Structured data (schema.org JSON-LD)
# ---------------------------------------------------------------------------


def extract_schema(url: str) -> dict:
    resp = _get(url)
    if resp is None or resp.status_code >= 400:
        return {"fetched": False, "status_code": getattr(resp, "status_code", None), "types_found": []}

    soup = BeautifulSoup(resp.text, "html.parser")
    blocks = soup.find_all("script", {"type": "application/ld+json"})

    types_found: set[str] = set()
    parsed_blocks = []
    errors = 0
    for block in blocks:
        try:
            data = json.loads(block.string or "")
        except (json.JSONDecodeError, TypeError):
            errors += 1
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            nodes = graph if isinstance(graph, list) else [item]
            for node in nodes:
                if isinstance(node, dict) and "@type" in node:
                    t = node["@type"]
                    if isinstance(t, list):
                        types_found.update(t)
                    else:
                        types_found.add(str(t))
        parsed_blocks.append(item)

    return {
        "fetched": True,
        "status_code": resp.status_code,
        "ld_json_block_count": len(blocks),
        "unparseable_blocks": errors,
        "types_found": sorted(types_found),
        "has_local_business_or_org": any(
            t in types_found for t in ("LocalBusiness", "Organization", "ProfessionalService")
        )
        or any(t.endswith("Business") for t in types_found),
        "has_service_type": "Service" in types_found,
        "has_faq_type": "FAQPage" in types_found,
    }


# ---------------------------------------------------------------------------
# 4. Sitemap / service x city page discovery
# ---------------------------------------------------------------------------


def _fetch_sitemap_urls(base_url: str, seen: set[str] | None = None) -> list[str]:
    if seen is None:
        seen = set()
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    if sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    resp = _get(sitemap_url)
    if resp is None or resp.status_code >= 400:
        return []

    try:
        soup = BeautifulSoup(resp.content, "xml")
    except Exception:
        soup = BeautifulSoup(resp.content, "html.parser")

    locs = [loc.get_text(strip=True) for loc in soup.find_all("loc")]

    # If this is a sitemap index, recurse one level into child sitemaps.
    if soup.find("sitemapindex") is not None:
        urls: list[str] = []
        for child in locs[:20]:  # cap to avoid runaway recursion on huge sites
            if child not in seen:
                seen.add(child)
                child_resp = _get(child)
                if child_resp is not None and child_resp.status_code < 400:
                    try:
                        child_soup = BeautifulSoup(child_resp.content, "xml")
                    except Exception:
                        child_soup = BeautifulSoup(child_resp.content, "html.parser")
                    urls.extend([loc.get_text(strip=True) for loc in child_soup.find_all("loc")])
        return urls

    return locs


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def discover_service_city_pages(base_url: str, industry: str, markets: list[str]) -> dict:
    urls = _fetch_sitemap_urls(base_url)
    sitemap_found = len(urls) > 0

    if not sitemap_found:
        # Fallback: crawl the homepage for internal links.
        resp = _get(base_url)
        if resp is not None and resp.status_code < 400:
            soup = BeautifulSoup(resp.text, "html.parser")
            domain = urlparse(base_url).netloc
            urls = list(
                {
                    urljoin(base_url, a["href"])
                    for a in soup.find_all("a", href=True)
                    if urlparse(urljoin(base_url, a["href"])).netloc == domain
                }
            )

    industry_slug = _slugify(industry)
    industry_words = set(industry_slug.split("-"))

    matched_pages: dict[str, list[str]] = {}
    for city in markets:
        city_slug = _slugify(city)
        city_words = set(city_slug.split("-"))
        matches = [
            u
            for u in urls
            if city_slug in _slugify(u)
            or (city_words and city_words.issubset(set(_slugify(u).split("-"))))
        ]
        matched_pages[city] = matches[:5]

    missing_cities = [city for city, pages in matched_pages.items() if not pages]

    # Rough count of pages that look like dedicated service pages (contain an industry keyword).
    service_like_pages = [
        u for u in urls if industry_words & set(_slugify(u).split("-"))
    ]

    return {
        "sitemap_found": sitemap_found,
        "total_urls_discovered": len(urls),
        "matched_city_pages": matched_pages,
        "missing_cities": missing_cities,
        "service_like_page_count": len(service_like_pages),
        "sample_service_like_pages": service_like_pages[:10],
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_technical_checks(url: str, business_name: str, industry: str, markets: list[str]) -> dict:
    base = _base_url(url)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "url": url,
            "business_name": business_name,
            "industry": industry,
            "markets": markets,
        },
        "robots_txt": check_robots_txt(base),
        "llms_txt": check_llms_txt(base),
        "js_dependency": check_js_dependency(url),
        "structured_data": extract_schema(url),
        "service_city_pages": discover_service_city_pages(base, industry, markets),
    }


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = run_technical_checks(target, "Example Co", "plumbing", ["San Diego", "Chula Vista"])
    print(json.dumps(result, indent=2))
