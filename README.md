# Legit Check Agent — Azure Functions Serverless Agents Runtime

A business-legitimacy chat agent built on the [Azure Functions serverless agents runtime](https://learn.microsoft.com/en-us/azure/azure-functions/functions-serverless-agents-runtime), following the same structure as the weather-agents and weather-briefing-agent samples.

Give the agent the name or URL of an online business and it assesses how trustworthy it looks, combining keyless technical signals with web search grounding over Trustpilot, Google reviews, scam databases, and news coverage.

## What it does

> **You:** Is shop.example-deals.com legit?
>
> **Agent:** **Verdict: Strong scam indicators.** The domain was registered 47 days ago, there is no Internet Archive history, the homepage links no contact or terms pages, and search results show a 1.6 Trustpilot rating with recent reports of undelivered orders. …

## Tools

| Tool | Source | Key needed |
|---|---|---|
| `check_domain` | RDAP (rdap.org) — registration date, registrar, domain age | No |
| `check_website` | Direct HTTPS fetch — reachability, redirects, title, trust pages | No |
| `check_archive_history` | Internet Archive Wayback CDX — first/latest snapshot | No |
| `web_search` | Tavily search API — Trustpilot, Google reviews, scam reports, KVK | `TAVILY_API_KEY` (optional) |

Review content is reached through web search grounding rather than scraping or per-provider APIs, so no Trustpilot or Google Places accounts are required. Without a Tavily key the agent still works, using the technical signals only.

## Architecture

The agent is defined in `src/main.agent.md`; the serverless agents runtime discovers it at startup, registers the HTTP trigger and built-in chat UI endpoint, and runs it through Microsoft Agent Framework. The tools in `src/tools/legit_tools.py` are plain Python functions decorated with `@tool`.

Compared to the weather samples, the Bicep template is trimmed: no ACA session pool (no code-interpreter needed) and no connector gateway.

## Prerequisites

- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- An Azure subscription with permissions to create Azure AI Foundry resources and model deployments
- Optional: a [Tavily](https://tavily.com) API key for the review/search grounding tool

## Quick start

```bash
cd legit-check-agent
azd env new legit-check-dev
azd env set TAVILY_API_KEY <your-key>   # optional but recommended
azd up
```

When prompted:
- **Location:** Select **Central US** (`centralus`) — the serverless agents runtime requires this region during preview
- **Subscription:** Select your Azure subscription

## Access the chat UI

```
https://<function-app-name>.azurewebsites.net/api/agents/main/
```

On first visit, a connection settings dialog appears. The Base URL is pre-filled. Get the Function key from the Azure portal: **portal.azure.com → \<function-app\> → App keys → default**, paste it, and click **Save**.

## Environment variables set by deployment

| Setting | Purpose |
|---|---|
| `AZURE_FUNCTIONS_AGENTS_PROVIDER` | `foundry` |
| `FOUNDRY_PROJECT_ENDPOINT` | Microsoft Foundry project endpoint |
| `FOUNDRY_MODEL` | Model deployment name (default `gpt-4.1`) |
| `TAVILY_API_KEY` | Optional web search grounding key |

## Local development

```bash
cd src
cp local.settings.json.example local.settings.json   # fill in endpoint + model
pip install -r requirements.txt
func start
```

## A note on scope

The verdicts are signal-based assessments, not guarantees. Sophisticated scams can fake many signals and legitimate new businesses can look thin; the agent says so in its answers and cites the sources it used.
