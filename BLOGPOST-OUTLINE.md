# Blog post outline: I Built a Scam-Checking Agent, Then Removed the Agency

Working title options:
- I Built a Scam-Checking Agent on Azure Functions. Then I Removed the Agency.
- Evidence in Code, Judgment in the Model: Lessons from a Legitimacy-Check Agent
- When Your Agent Should Stop Being Agentic

Target: sjwiggers.com (Cloud Perspectives). Voice: practitioner honesty, active voice, short sentences, include a "where this is the wrong answer" section, no em dashes. Blog length flexible; this has enough material for 1,200 to 1,500 words or a two-parter.

---

## 1. The idea (short setup)

- Everyday problem: is this webshop legit? People paste URLs into reputation checkers such as ScamAdviser-style sites.
- Goal: a chat agent that does the same with verifiable signals plus an LLM opinion.
- Built on the Azure Functions serverless agents runtime, same pattern as the weather agents samples (link back to that post).
- Repo: github.com/steefjan1/legit-check-agent (publish the repo first).

## 2. The signal design (what makes it credible)

Key decision: no scraping, no per-provider review APIs. Signals in two tiers:

- Keyless technical signals: RDAP registration date and age (rdap.org), HTTPS reachability plus trust pages (contact, terms, privacy, retour), Internet Archive first/latest snapshot.
- Web search grounding via Tavily for reputation: Trustpilot results, reviews, "scam OR fraud OR oplichting", optionally KVK for Dutch shops.
- One paragraph on why search grounding beats the Trustpilot API here (no paid account, no ToS gray zone, degrades gracefully without a key).

Code snippet: the `_domain_info` RDAP helper (compact, self-explanatory).

## 3. Version 1: the agentic loop (and how it failed)

The honest middle of the post. Four @tool functions, model orchestrates freely.

Failure timeline, with the actual evidence:
- Rate limit exceeded on gpt-4.1 (legacy model, shared regional quota, tool-call fan-out).
- Model swap detour: gpt-4.1 is marked legacy; moved to gpt-5.6-terra. Sidebar: the truncated version string gotcha ("2026-03-1") and why name/version must match the catalog verbatim.
- Rate limit again on terra. Capacity was not the root cause.
- The smoking gun: App Insights `agent_token_usage` showing input_tokens 47,004 for a 280-token answer. Screenshot this log line.
- Finally: "Your input exceeds the context window of this model."

Root cause explanation (the teachable part): every tool call is a full round trip carrying the entire thread; failed turns and retries stay in the server-side thread; a model facing a failing tool (missing search key) retries with new queries, and each retry compounds. Agentic loops turn small inefficiencies into quota and context blowups.

## 4. Version 2: evidence in code, judgment in the model

The redesign in one sentence: one deterministic tool gathers everything; the model calls it once and writes the verdict. Two model turns per check, bounded at ~8 KB of evidence.

Code snippets:
- `gather_business_check` (the aggregator with `_safe` wrapper: a failed signal becomes an error string, never an exception, never a retry).
- The size guard (json dump, truncate at 8,000 chars).
- The agent instructions excerpt: "Call it exactly ONCE... missing signals are simply reported as missing."

Architecture diagram: user -> Functions chat endpoint -> gather (RDAP, HTTPS, Wayback, Tavily in parallel-ish code) -> single evidence pack -> one LLM call -> verdict. Contrast with the v1 diagram (model in the loop, N round trips).

## 5. The validation moment

- Real test: thenewsound.nl. Agent verdict: Mixed signals, 68/100, positive on domain age, trust pages, archive history, unknown on reviews (no key yet).
- A commercial reputation checker scored the same site 76/100 "Trusted but Verify" on essentially the same signal categories.
- Point: a weekend-size sample with honest signals lands in the same neighborhood as a commercial product. Screenshot both side by side.

## 6. Where this is the wrong answer

- When you genuinely need dynamic tool selection (open-ended research), the loop earns its cost; this task has a fixed checklist, so the loop was pure overhead.
- Signal-based verdicts are not guarantees: sophisticated scams fake signals, young legitimate shops look thin. The agent says so in every answer by design.
- Do not extend this into helping a site look more legitimate; the agent instructions refuse that direction explicitly.

## 7. Takeaways (short list)

1. Give the model judgment, not orchestration, when the workflow is a fixed checklist.
2. Bound every tool result; assume the model will see it N times, not once.
3. Watch `agent_token_usage` in App Insights from day one; input tokens per turn is the health metric.
4. Model quota is per subscription/region/model; legacy models share crowded pools.
5. A failing tool must say "do not retry me" or the loop will.

## Assets checklist

- [ ] Publish repo to GitHub (scrub .azure/, local.settings.json)
- [ ] Screenshot: App Insights token usage line (47K input tokens)
- [ ] Screenshot: chat UI verdict for thenewsound.nl
- [ ] Screenshot: commercial checker's 76/100 for the same site
- [ ] SVG diagrams: v1 loop vs v2 pipeline
- [ ] Before/after tools code side by side
- [ ] Run TAVILY_API_KEY version and capture the richer verdict for the post
- [ ] Yoast: keyphrase candidates "serverless agents runtime", "azure functions ai agent", "llm tool calling patterns"
