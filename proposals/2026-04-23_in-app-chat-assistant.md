# Proposal — In-App Chat Assistant ("Ask Anunnaki")

**Date:** 2026-04-23
**Author:** SPECTRE
**Status:** Draft — operator review required before any implementation
**Risk tier:** Medium (new user-facing surface, external LLM calls, account data exposure)

---

## 1. Problem / Opportunity

New users land on `/app` and get dropped into a dashboard with ~15 distinct
surfaces (signals feed, copy-trading, trailing SL, liquidation heatmap,
PREDATOR regime, macro gate, referrals, tier management, …). The whitepaper
is thorough but long; tooltips are helpful but scattered. Today a confused
user has three options:

1. Read the whitepaper (friction — most don't).
2. Ask in Telegram ops chat (friction + privacy — they don't).
3. Give up and churn.

A chat assistant that *understands the product* and *can see the user's own
account context* closes this gap. It becomes:

- Onboarding guide ("How do I enable copy-trading?")
- Feature explainer ("What does the trailing SL do after TP1?")
- Live debugger ("Why didn't my NMRUSDT signal fire?")
- Conversion lever ("What does Pro unlock over Free?")

The building blocks are already in the codebase:

| Asset | Current use | Reuse for chat |
|---|---|---|
| `openrouter_intelligence.py` | Signal robustness analysis, systemic fragility checks | Same client, different system prompt |
| `ai_mcp_bridge.py` | MCP tool definitions for Telegram AI tool-calling | Same tools, exposed to dashboard chat |
| `telegram_handler.py` (chat AI) | Telegram chat assistant | Copy the intent router, swap the transport |
| `copy_trading.py`, `performance_tracker.py`, `signal_registry_db.py` | Already expose account/signal state via functions | Wrap as tools |
| `landing.html` roadmap + whitepaper | Documentation source | Chunked → retrieval corpus |

**No new infra required** — just wiring + a well-designed system prompt +
a small retrieval index.

---

## 2. Goals & Non-Goals

### Goals

1. **Answer "how do I" questions** about every documented feature with
   correct, concrete, tier-aware instructions.
2. **Answer account-aware questions** ("show me my open signals", "why
   did this trade close at a loss") using existing MCP tools.
3. **Nudge, never push** — the assistant may surface paid features, but
   never emits unsolicited trade advice or promotional spam.
4. **Safe by construction** — cannot leak API keys, admin endpoints, other
   users' data, or the raw strategy code.
5. **Low operating cost** — free-tier OpenRouter models for education Q&A,
   better models reserved for account-context queries (opt-in).

### 2a. Model choice — why OpenRouter, not a local model

**Decision: reuse `openrouter_intelligence.py`. Do not train or self-host.**

The use case is **retrieval + tool-calling over a slowly-changing product
corpus** — both are solved by frontier models + RAG, neither is improved
by fine-tuning.

| Dimension | OpenRouter (chosen) | Fine-tune local 7–13B | Self-host open-source (no training) |
|---|---|---|---|
| Dev time to working product | **~3 days** | 4–8 weeks | 1–2 weeks |
| Monthly cost @ 500 DAU | **< $10** | $0 infra but... | $0 infra but... |
| RTX 3090 impact | None | Blocks XGBoost/Transformer during fine-tune + permanent VRAM fight | Eats 8–20 GB VRAM 24/7 → starves trading inference |
| Quality on "how do I …" | Excellent (GPT-4o-mini / Claude Haiku / Llama-3.3-70B) | **Worse** than base frontier models | Decent, noticeably below frontier |
| Tool-calling quality | Native, reliable | Requires dataset you don't have | Mediocre on open 8B models |
| Handling a feature shipped tomorrow | Update `chat_knowledge/*.md`, 5 s index rebuild | Re-fine-tune every change | Update corpus, no retrain |
| Failure mode | Graceful fallback to retrieval-only | Hallucinates confidently, hard to debug | OOM → trading inference crashes |

**Specific reasons fine-tuning is wrong for this product:**

1. **Fine-tuning is for style/format, not knowledge.** We need knowledge
   retrieval and tool-calling — both solved by RAG + function-calling.
2. **No labelled dataset exists.** A useful fine-tune needs ~5k curated
   Q/A pairs; synthesising them from an LLM just distils OpenRouter into
   a smaller, worse model.
3. **Docs change weekly.** The roadmap itself advertises multiple ships
   per week. RAG re-indexes in seconds; fine-tunes take hours–days.
4. **GPU is already committed.** The RTX 3090 runs XGBoost + Transformer
   on every scan cycle. Co-hosting an LLM there means scan latency *or*
   chat latency has to lose. OpenRouter keeps them isolated.

**When we'd revisit local hosting (escape hatch):**

- Monthly OpenRouter spend exceeds ~$200 (current projection: <$10).
- A hard privacy mandate requires zero third-party LLM calls on user PII
  (today we already send signal data to OpenRouter — box not checked).
- Latency requirement drops below ~300 ms (irrelevant for chat).

The swap is a one-line change: replace
`openrouter_intelligence.chat_completion(...)` with a local vLLM client
implementing the same interface. The entire rest of the proposal is
unaffected. **No lock-in.**

**Model rotation strategy (for use inside `openrouter_intelligence.py`):**

| Intent | Model | Cost |
|---|---|---|
| Intent classification (20 tokens out) | `meta-llama/llama-3.2-3b-instruct:free` | Free |
| FAQ / retrieval-only (Free + Starter) | `google/gemini-2.0-flash-exp:free` or `deepseek/deepseek-chat:free` | Free |
| LIVE / tool-calling (Pro+) | `openai/gpt-4o-mini` or `anthropic/claude-haiku-4.5` | ~$0.15/$0.60 per M tokens |
| Fallback if free rate-limited | `meta-llama/llama-3.3-70b-instruct` | ~$0.12 per M tokens |

All already reachable through the existing client — zero new code.

---

### Non-Goals

- **Not a trading signal generator.** The assistant never invents or
  recommends entries. If asked, it redirects to the signals feed with a
  disclaimer.
- **Not a replacement for ops/Telegram.** Business-critical requests
  (refunds, KYC, disputes) escalate to a human.
- **Not a voice/image agent** — v1 is text only.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Dashboard UI (/app)                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Floating "Ask Anunnaki" bubble (bottom-right)        │   │
│  │    → click → slide-in panel with chat history         │   │
│  │  Context-aware "?" icons next to every feature card   │   │
│  │    → click → opens panel + pre-fills question         │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼ POST /api/chat/ask                │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 chat_assistant.py (new)                      │
│                                                              │
│  1. Rate-limit + tier-gate (Free: 20/day, Pro: 200/day)     │
│  2. Classify intent:                                         │
│       FAQ  →  retrieval-augmented generation                 │
│       LIVE →  tool-call loop (existing MCP tools)            │
│       MIXED → both                                           │
│  3. Build prompt:                                            │
│       - system: persona + guardrails                         │
│       - context: top-K retrieved doc chunks                  │
│       - user: their message                                  │
│       - (if LIVE) available tools from ai_mcp_bridge         │
│  4. Call OpenRouter via openrouter_intelligence.py          │
│       - Free tier / cheap model for FAQ-only                 │
│       - Better model for LIVE / MIXED                        │
│  5. Stream response via SSE                                  │
│  6. Persist turn in chat_history table                       │
└─────────────────────────────────────────────────────────────┘
                │                        │
                ▼                        ▼
  ┌─────────────────────┐     ┌────────────────────────────┐
  │  Retrieval index    │     │  Tool executor              │
  │  (sqlite-vss)       │     │  (ai_mcp_bridge.py)         │
  │                     │     │                             │
  │  - whitepaper/*.md  │     │  get_open_signals(user_id)  │
  │  - landing copy     │     │  get_market_context(pair)   │
  │  - feature FAQ      │     │  get_trade_history(user_id) │
  │  - release notes    │     │  get_balance(user_id)       │
  │  - tier matrix      │     │  — all scoped to caller     │
  └─────────────────────┘     └────────────────────────────┘
```

---

## 4. Files to create / modify

### New files

| Path | Purpose |
|---|---|
| `dashboard/chat_assistant.py` | Core orchestrator: intent routing, RAG, tool loop, SSE streaming |
| `dashboard/chat_knowledge/` | Markdown corpus (one `.md` per feature) |
| `dashboard/chat_knowledge/_build_index.py` | Chunk + embed to `chat_knowledge.db` |
| `dashboard/static/js/chat-assistant.js` | Floating bubble + slide-in panel + SSE reader |
| `dashboard/static/css/chat-assistant.css` | Panel styling matching brand palette |
| `proposals/2026-04-23_in-app-chat-assistant.md` | This doc |

### Files to modify

| Path | Change |
|---|---|
| `dashboard/app.py` | Register `POST /api/chat/ask` (SSE), `GET /api/chat/history`, `DELETE /api/chat/history` |
| `dashboard/index.html` / shell template | Include `chat-assistant.js` + `.css` on authed pages only |
| `ai_mcp_bridge.py` | Add `ALLOWED_FOR_DASHBOARD` subset — safe tools only (no admin, no send_message) |
| `openrouter_intelligence.py` | New helper `chat_completion(messages, tools, model_tier)` that wraps existing OpenRouter rotation |

---

## 5. Knowledge base design

Single source of truth: **one markdown file per feature** under
`dashboard/chat_knowledge/`. Each file has YAML frontmatter:

```yaml
---
id: copy-trading-setup
title: How to enable copy-trading
tags: [copy-trading, onboarding, binance, api-keys]
tier_required: pro
last_updated: 2026-04-23
---
```

**Initial corpus (~20 docs):**

- `getting-started.md` — account, verification, tiers
- `reading-signals.md` — anatomy of a signal card
- `copy-trading-setup.md` — Binance keys, leverage mode, IP whitelist
- `copy-trading-tp-modes.md` — pyramid vs. fixed, what each % means
- `copy-trading-sl-modes.md` — signal SL vs. fixed-% SL, trailing behaviour
- `close-positions.md` — per-pair close button, close-all, emergency de-risk
- `trailing-sl.md` — ratcheting algorithm, TP-triggered tightening
- `liquidation-heatmap.md` — reading the chart, 24 h aggregation window
- `predator-regime.md` — three layers, LONG/SHORT block semantics
- `usdt-dominance-gate.md` — macro regime and position sizing
- `roi-interpretation.md` — realized vs unrealized, leverage-aware %
- `tiers-and-billing.md` — Free / Starter / Pro / Ultra matrix
- `referrals.md` — code generation, payout rules
- `api-keys-security.md` — what we do and don't require (no withdrawal)
- `troubleshooting.md` — common failure modes (insufficient margin, min-notional, IP block)
- `stream-mode.md` — `/stream` page, embargo, public vs private
- `mobile-pwa.md` — install to home screen, notifications
- `device-security.md` — device limits per tier, re-auth on new device
- `whitepaper-summary.md` — TL;DR of the whitepaper with deep-link anchors
- `roadmap-live.md` — pulled from the landing page roadmap section (auto-regenerated on deploy)

**Indexing:**

- Chunk size: 400–600 tokens, 80-token overlap.
- Embeddings: local — `sentence-transformers/all-MiniLM-L6-v2` (running
  on the same RTX 3090 used for XGBoost/Transformer). ~80 MB model,
  ~15 ms per query.
- Store: `sqlite-vss` (already have sqlite everywhere). Table schema:
  ```
  chunks(id TEXT PK, doc_id TEXT, chunk_idx INT, text TEXT,
         tier_required TEXT, last_updated REAL)
  chunks_vss(rowid INT, embedding BLOB)
  ```
- Retrieval: top-5 chunks by cosine, filtered by
  `tier_required <= caller.tier`.
- Rebuild trigger: git hook or explicit
  `python -m dashboard.chat_knowledge._build_index` — takes ~5 s for 20 docs.

---

## 6. Intent routing

Before calling the LLM, a cheap classifier decides the path. Two
strategies, use both:

1. **Keyword/regex pre-filter** — ~20 patterns catch ~70 % of intents
   without an LLM round-trip:
   ```
   r"\bopen\s+(signals|positions|trades)\b"    → LIVE (get_open_signals)
   r"\bbalance\b"                              → LIVE (get_balance)
   r"\bhow\s+(do|to)\b"                        → FAQ
   r"\bwhy\s+did\b.*\b(close|stop|trigger)\b"  → LIVE (get_trade_history + RAG)
   ```
2. **Fallback LLM classifier** — single JSON-only call, ~20 tokens out,
   using the cheapest free model. Schema:
   ```json
   {"intent": "FAQ|LIVE|MIXED", "topics": ["..."], "needs_account": bool}
   ```

---

## 7. Tool access — tier-scoped whitelist

Expose only the subset of `ai_mcp_bridge.py` tools that are:

- **Read-only** (no `send_message`, no `cancel_trade_signal`, no `edit_file`,
  no admin tools).
- **User-scoped** (every tool takes `user_id` from the authenticated session
  — the LLM cannot pass arbitrary `user_id`).

Safe subset for dashboard chat:

```python
DASHBOARD_SAFE_TOOLS = [
    "get_open_signals",           # scoped to session user
    "get_market_context",         # public OHLCV
    "get_trade_history",          # scoped to session user
    "get_balance",                # scoped to session user
    "get_signal_details",         # single signal by id, only if user received it
    "search_knowledge_base",      # retrieval over chat_knowledge/
]
```

Unsafe tools (admin / mutating / cross-user / external) are **not
registered** with the chat LLM — no prompt-injection can invoke them.

---

## 8. Guardrails

Baked into the system prompt + enforced server-side:

1. **Scope guard:** *"You are a product guide for Anunnaki World. If asked
   for trading picks, tell the user the platform does not give personalised
   advice and point them to the live signal feed."*
2. **PII guard:** Never echo API keys, email addresses, wallet addresses,
   or Telegram handles — even if they appear in tool output. Middleware
   redacts before sending to the model.
3. **Jailbreak guard:** System prompt pinned at message index 0, cannot be
   overridden by user input. Standard "ignore previous instructions"
   patterns are detected and the request is answered with a canned
   refusal.
4. **Rate limits** (per user, rolling 24 h window):
   - Free: 20 messages/day
   - Starter: 50/day
   - Pro: 200/day
   - Ultra: 500/day
   Enforced via sliding-window counter in SQLite.
5. **Cost cap** (per user, calendar month):
   - Hard cap on total OpenRouter token spend → if exceeded, assistant
     falls back to retrieval-only (no LLM) with a notice.
6. **Abuse log:** Every message + intent + tools-called + latency + cost
   logged to `chat_audit.db`. Operator dashboard shows top-cost users +
   flagged conversations.

---

## 9. UI / UX

- **Floating bubble:** Bottom-right, 56 × 56 px, gold gradient, subtle
  pulse when a new release ships (reads `roadmap-live.md` for a
  `last_updated` signal).
- **Panel:** 420 px wide, 80 vh tall, slides in from right. Dark theme
  only (matches dashboard).
- **First-time onboarding:** On first `/app` visit, bubble animates +
  shows a 3-line tooltip: *"Hi — ask me anything about the platform."*
  Dismissible, stored in `localStorage`.
- **Context buttons:** Every major feature card on the dashboard gets a
  small "?" icon that opens the panel with a pre-filled question, e.g.
  *"Explain the pyramid TP mode"* next to the TP-mode selector.
- **Quick-start chips:** On empty panel, show 4 chips:
  > *How do I enable copy-trading?* · *What's the difference between tiers?*
  > *Explain the trailing SL* · *Show me my open signals*
- **Streaming:** Tokens stream via SSE for <200 ms time-to-first-token
  perception.
- **Markdown rendering:** Whitelist — paragraphs, lists, inline code,
  code blocks, links to our own domain only (links to external domains
  rendered as plain text to prevent injection).
- **Feedback:** 👍 / 👎 on every reply → logged to `chat_feedback` for
  later prompt tuning.

---

## 10. Rollout plan (5 phases)

| Phase | Scope | Gate |
|---|---|---|
| **0. Docs** | Write the 20-doc corpus + build index locally | Operator reviews corpus for accuracy |
| **1. Backend** | `chat_assistant.py`, `/api/chat/ask` SSE, retrieval-only mode (no tools) | Works for Free tier; all answers grounded in corpus |
| **2. Frontend** | Floating bubble + panel + SSE reader. No context buttons yet. | Internal test with 2–3 beta users |
| **3. Tool-call loop** | Enable `DASHBOARD_SAFE_TOOLS` for Pro+. LIVE/MIXED intents work. | Audit log clean for 48 h |
| **4. Context buttons** | Per-feature "?" icons across dashboard | UX polish pass |
| **5. Public launch** | Announce in Telegram + email. Monitor cost dashboard. | Cost-per-user stays < target |

Each phase is independently revertable — later phases degrade gracefully
to earlier ones if disabled.

---

## 11. Cost estimate (monthly)

Rough, for 500 DAU on the free tier + 50 Pro:

- **Retrieval-only Q&A (80 % of messages):**
  500 × 5 msg/day × 30 d = 75k msg → free OpenRouter models → **$0**.
- **Tool-call / LIVE (20 % of Pro messages):**
  50 × 10 msg/day × 30 d × 20 % = 3k msg × ~1500 tokens avg × $0.5 /M = **~$2/mo**.
- **Embedding index:** one-time local build, negligible.
- **sqlite-vss storage:** ~50 MB, fits on existing disk.

Total: **<$10/mo** until user base scales 10×. Scales linearly, easy to
cap via `cost_cap` setting.

---

## 12. Metrics / success criteria

- **Engagement:** % of authed sessions that open the panel (target ≥ 25 % in week 1).
- **Deflection:** reduction in repeated "how do I …" Telegram messages (target ≥ 40 %).
- **Onboarding:** Free → Starter conversion rate for users who ask "what
  does Pro unlock" in the chat (measure A/B — they should convert higher).
- **Quality:** 👍 rate ≥ 75 %; rolling 7-day.
- **Latency:** p95 time-to-first-token ≤ 1.5 s; p95 full-response ≤ 6 s.
- **Cost per message:** ≤ $0.002 blended.

---

## 13. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hallucinates wrong instructions (e.g. tells user to enable withdrawal permission) | Medium | High — security incident | Corpus is authoritative source; system prompt forces *"If unsure, say you're unsure and link to the relevant doc."* |
| Prompt injection via pair name / user input | Medium | Medium | Sanitize tool outputs; pin system prompt at index 0; detect override patterns |
| Cost runaway if free users hammer it | Low | Medium | Hard per-user rate limit + monthly cost cap |
| Model deprecation on OpenRouter free tier | High (weekly churn) | Low | Existing `openrouter_intelligence.py` already rotates; inherit that behaviour |
| Users trust the chat over the signal — miss real trade advice | Low | Low | Scope guard + every financial answer ends with *"This is not financial advice"* footer |
| Knowledge drift (docs lag product) | Medium | Medium | `last_updated` shown in every citation; operator reviews low-score feedback weekly |

---

## 14. Open questions for operator

1. **Default model tier:** use `openrouter/auto` with free-tier preference,
   or pin a specific free model? (I lean toward `auto` with rotation.)
2. **Privacy:** store chat history in clear-text for audit, or hash? (Lean
   clear-text with 30-day TTL, since users may want to scroll back.)
3. **Admin read access:** should ops be able to read any user's chat for
   support? (Default: no, unless user opens a ticket that references the
   conversation.)
4. **Telegram integration:** should the dashboard chat history mirror the
   Telegram chat AI history, or stay siloed? (Recommend: siloed v1, same
   corpus / same tools / different transports.)
5. **Brand voice:** terse operator tone (matches Telegram AI), or more
   welcoming (matches landing-page copy)? (Recommend: welcoming in
   dashboard since it's a first-run experience.)

---

## 15. Decision requested

Approve / reject / amend the plan. If approved, phase 0 (docs + index
build) can start immediately; no production-facing changes until
operator signs off on the corpus.

*Nothing in this proposal has been implemented. This is a plan only.*
