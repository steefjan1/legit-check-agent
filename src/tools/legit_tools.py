"""
Legitimacy-signal tools for the business legitimacy check agent.

Design: ONE agent-facing tool (gather_business_check) runs every check
deterministically in code and returns a single compact evidence pack.
The model calls it once, then writes its assessment — no multi-step
tool loop, so a check costs exactly two model turns.

All signals are keyless except the review searches, which use the Tavily
API when TAVILY_API_KEY is set.
"""
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from azure_functions_agents import tool

USER_AGENT = "legit-check-agent/1.0 (business legitimacy demo)"


def _domain_of(value: str) -> str:
    """Normalise a URL or bare domain to its registrable hostname."""
    value = value.strip().lower()
    if "://" not in value:
        value = "https://" + value
    host = urlparse(value).hostname or ""
    return host.removeprefix("www.")


def _safe(fn, *args):
    """Run one signal check; a failure becomes a short error string, never an exception."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — evidence gathering must not abort
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _domain_info(domain: str) -> dict[str, Any]:
    response = httpx.get(f"https://rdap.org/domain/{domain}",
                         headers={"User-Agent": USER_AGENT},
                         follow_redirects=True, timeout=15.0)
    if response.status_code == 404:
        return {"registered": False, "note": "No RDAP record found."}
    response.raise_for_status()
    data = response.json()
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
    registrar = None
    for entity in data.get("entities", []):
        if "registrar" in entity.get("roles", []):
            for item in entity.get("vcardArray", [None, []])[1]:
                if item and item[0] == "fn":
                    registrar = item[3]
    registered_at = events.get("registration")
    age_days = None
    if registered_at:
        try:
            reg = datetime.fromisoformat(registered_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - reg).days
        except ValueError:
            pass
    return {
        "registered": True,
        "registration_date": registered_at,
        "age_days": age_days,
        "registrar": registrar,
    }


def _website_info(domain: str) -> dict[str, Any]:
    url = f"https://{domain}/"
    response = httpx.get(url, headers={"User-Agent": USER_AGENT},
                         follow_redirects=True, timeout=20.0)
    html = response.text[:200_000].lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
    trust_pages = [
        page for page, pattern in {
            "contact": r"contact",
            "about": r"about",
            "terms": r"terms|conditions|algemene voorwaarden",
            "privacy": r"privacy",
            "returns": r"return|refund|retour",
        }.items() if re.search(pattern, html)
    ]
    return {
        "reachable": True,
        "status_code": response.status_code,
        "redirected_offsite": _domain_of(str(response.url)) != domain,
        "title": title_match.group(1).strip()[:150] if title_match else None,
        "trust_pages_linked": trust_pages,
    }


def _archive_info(domain: str) -> dict[str, Any]:
    def snapshot(limit: int) -> str | None:
        response = httpx.get(
            "https://web.archive.org/cdx/search/cdx",
            params={"url": domain, "output": "json", "limit": limit,
                    "fl": "timestamp", "filter": "statuscode:200"},
            headers={"User-Agent": USER_AGENT}, timeout=20.0)
        response.raise_for_status()
        rows = response.json()
        return rows[1][0] if len(rows) > 1 else None

    fmt = lambda ts: f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}" if ts else None  # noqa: E731
    first = snapshot(1)
    return {"first_snapshot": fmt(first), "latest_snapshot": fmt(snapshot(-1)),
            "has_history": first is not None}


def _review_search(domain: str, business: str) -> dict[str, Any]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return {"available": False,
                "note": "Review search disabled (no TAVILY_API_KEY configured)."}
    queries = [
        f"site:trustpilot.com {domain}",
        f"{business} reviews rating",
        f"{business} scam OR fraud OR oplichting",
    ]
    all_results = []
    for query in queries:
        try:
            response = httpx.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": 3,
                      "search_depth": "basic", "include_answer": False},
                headers={"User-Agent": USER_AGENT}, timeout=30.0)
            response.raise_for_status()
            for r in response.json().get("results", []):
                all_results.append({
                    "query": query,
                    "title": (r.get("title") or "")[:120],
                    "url": r.get("url"),
                    "snippet": (r.get("content") or "")[:250],
                })
        except httpx.HTTPError as exc:
            all_results.append({"query": query, "error": str(exc)[:150]})
    return {"available": True, "results": all_results}


@tool
def gather_business_check(args: dict[str, Any]) -> dict[str, Any]:
    """Run ALL legitimacy checks for an online business in one call and return a compact evidence pack: domain registration/age (RDAP), website reachability and trust pages, Internet Archive history, and review/reputation search results (Trustpilot, reviews, scam reports) when search is configured. Call this exactly ONCE per business, then write the assessment from the returned evidence. Args: business (str) — the business name or website URL."""
    business = str(args["business"])
    domain = _domain_of(business)
    evidence = {
        "domain": domain,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "domain_registration": _safe(_domain_info, domain),
        "website": _safe(_website_info, domain),
        "archive_history": _safe(_archive_info, domain),
        "reputation_search": _safe(_review_search, domain, business),
    }
    # absolute size guard: the evidence pack can never flood the model context
    text = json.dumps(evidence, default=str)
    if len(text) > 8000:
        evidence = {"truncated": True, "data": text[:8000]}
    return evidence
