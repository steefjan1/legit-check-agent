# I Built a Scam-Checking Agent on Azure Functions. Then I Removed the Agency.

Is that webshop legit? Most of us have pasted a URL into a reputation checker at least once. The signals those sites use are not magic: domain age, HTTPS, policy pages, archive history, reviews. That looked like a perfect weekend project for the Azure Functions serverless agents runtime, the same runtime I used for my [weather agents sample](https://sjwiggers.com/azure-functions-serverless-agents-runtime). Give an agent a set of verification tools, let it gather evidence, and let the model form an opinion.

I built exactly that. It fell over in an instructive way. The fix was not a bugfix. It was an architecture decision: take the orchestration away from the model. This post walks through both versions, the failure in between, and why "evidence in code, judgment in the model" is the pattern I will reach for first from now on.

The full sample is on GitHub: [legit-check-agent](https://github.com/steefjan1/legit-check-agent). Deploy it with `azd up`.

## The signal design

I made one decision early that shaped everything: no scraping and no per-provider review APIs. The Trustpilot content API needs a paid business account. Scraping review sites violates their terms. Instead, the agent uses two tiers of signals.

The first tier is keyless and verifiable. RDAP gives the domain registration date, registrar, and age. A direct HTTPS fetch confirms the site is reachable and checks whether it links the pages a real shop has: contact, about, terms, privacy, returns. The Internet Archive CDX API shows when the site first appeared and whether it has a continuous history. A shop that claims ten years of trading but has a three-month-old domain and no archive footprint tells you something no review score can.

The second tier is reputation through web search grounding. A Tavily search runs targeted queries: `site:trustpilot.com <domain>`, the business name plus "reviews", and the business name plus "scam OR fraud OR oplichting" for Dutch shops. The model sees result titles, URLs, and snippets. It never invents a rating. If no key is configured, the tier reports itself as unavailable and the agent says so in its verdict. Graceful degradation was a design goal, and it mattered more than I expected.

Here is the RDAP helper. Nothing clever, which is the point:

```python
def _domain_info(domain: str) -> dict[str, Any]:
    response = httpx.get(f"https://rdap.org/domain/{domain}",
                         headers={"User-Agent": USER_AGENT},
                         follow_redirects=True, timeout=15.0)
    if response.status_code == 404:
        return {"registered": False, "note": "No RDAP record found."}
    response.raise_for_status()
    data = response.json()
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
    ...
    return {"registered": True, "registration_date": registered_at,
            "age_days": age_days, "registrar": registrar}
```

## Version 1: the agentic loop

The first version followed the textbook. Four `@tool` functions: `check_domain`, `check_website`, `check_archive_history`, `web_search`. The agent instructions told the model to run them in order and issue several search queries. The model orchestrated freely, the way agent demos do.

It worked in the sense that it compiled and deployed. Then the errors started.

First: "Model deployment rate limit exceeded" on gpt-4.1. I switched models, since gpt-4.1 is marked legacy in the catalog anyway, and moved to gpt-5.6-terra. Same error. I bumped the deployment capacity to 500K TPM. Then a new error: "Your input exceeds the context window of this model." A single question about a single webshop exceeded the context window of a frontier model.

Application Insights had the smoking gun. The runtime logs an `agent_token_usage` event per turn, and one line told the whole story:

```
"input_tokens": 47004, "output_tokens": 280
```

Forty-seven thousand tokens in, to produce a 280-token answer.

Here is the mechanism, and it is worth internalizing. Every tool call in an agentic loop is a full model round trip that carries the entire conversation: system prompt, tool schemas, chat history, and every previous tool result. The built-in chat UI stores the thread server-side, so failed turns and retries stay in it forever. And when a tool fails, the model retries. My `web_search` returned an error when no Tavily key was set, so the model helpfully tried again with a different query. Each retry compounded the history. The loop turned a missing API key into a quota problem, and the quota problem into a context overflow. Not one line of my tool code was wrong.

## Version 2: evidence in code, judgment in the model

The redesign fits in one sentence. One deterministic tool gathers every signal in plain Python; the model calls it exactly once and writes the verdict. Two model turns per check, and the evidence pack is hard-capped at 8 KB.

```python
@tool
def gather_business_check(args: dict[str, Any]) -> dict[str, Any]:
    business = str(args["business"])
    domain = _domain_of(business)
    evidence = {
        "domain": domain,
        "domain_registration": _safe(_domain_info, domain),
        "website": _safe(_website_info, domain),
        "archive_history": _safe(_archive_info, domain),
        "reputation_search": _safe(_review_search, domain, business),
    }
    text = json.dumps(evidence, default=str)
    if len(text) > 8000:
        evidence = {"truncated": True, "data": text[:8000]}
    return evidence
```

The `_safe` wrapper is the other half of the fix. A failed signal becomes a short error string inside the evidence, never an exception and never a retry:

```python
def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
```

The agent instructions shrank to match: call the tool once, never retry it, treat missing signals as reported facts, then write a verdict with a 0 to 100 score and cite the sources. The model does the one thing it is uniquely good at here, which is weighing mixed evidence and writing a calibrated judgment. Everything else is boring code, and boring code does not blow up context windows.

## The validation moment

I tested with thenewsound.nl, a Dutch audio webshop. The agent came back with "Mixed signals, be careful" and a 68/100 trust score: positive on the 2.5-year domain age, the full set of trust pages, and a continuous archive history since 2024, with the review search adding independent customer feedback on top. Out of curiosity I ran the same site through a commercial reputation checker. It scored 76/100, "Trusted but Verify", on essentially the same signal categories.

A weekend-size sample with honest signals landed in the same neighborhood as a commercial product. That is not because my code is special. It is because the signals do the work, and the LLM's job is only to weigh them and explain.

## Where this is the wrong answer

Be careful before generalizing this into "agent loops are bad". When the task genuinely needs dynamic tool selection, open-ended research for example, the loop earns its cost. My task was a fixed checklist, and for a fixed checklist the loop was pure overhead with failure modes attached.

The verdicts themselves also deserve a caveat, and the agent states it in every answer: this is a signal-based assessment, not a guarantee. Sophisticated scams fake signals. Legitimate young shops look thin. The agent recommends buyer-protected payment methods whenever it is unsure, and its instructions explicitly refuse the reverse use case of making a site look more legitimate than it is.

## Takeaways

Five things I would tell my past self from two days ago. Give the model judgment, not orchestration, when the workflow is a fixed checklist. Bound every tool result, because the model will see it on every subsequent turn, not once. Watch `agent_token_usage` in Application Insights from day one; input tokens per turn is the health metric of any agent. Model quota is per subscription, region, and model, and legacy models sit in crowded pools. And make every failing tool say "do not retry me", because otherwise the loop will.

The runtime made all of this pleasantly small. The whole sample is a `main.agent.md`, one tools file, and trimmed Bicep. The lesson was never about the runtime. It was about deciding where the agency belongs.
