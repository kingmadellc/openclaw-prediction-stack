# OpenClaw Prediction Market Trading Stack

Ten autonomous skills that scan, analyze, compare, and trade prediction markets — with a setup wizard that wires them into a proactive, scheduled system delivering intelligence to your phone.

**v1.0** — Full stack operational. 5 of 10 skills published on [ClawHub](https://clawhub.ai), remaining 5 queued. First prediction market skill suite on ClawHub.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/kingmadellc/openclaw-prediction-stack.git

# Then tell your OpenClaw agent:
# "Set up my prediction stack"
```

The [setup wizard](prediction-stack-setup/) walks you through API keys, delivery config, and scheduled jobs. Under 5 minutes to a fully operational trading system.

## The Stack

| # | Skill | What It Does |
|---|-------|-------------|
| 1 | [**Kalshalyst**](kalshalyst/) | Contrarian edge scanner — finds Kalshi mispricings via LLM analysis, Brier calibration, Kelly sizing. Five-phase pipeline: fetch, classify, estimate, edge-score, alert. |
| 2 | [**Kalshi Command Center**](kalshi-command-center/) | Full Kalshi trading CLI — portfolio P&L, live market scanning with edge scoring, trade execution, risk management. Built-in safety: $25 max trade, 100 contract cap, $50 daily loss cutoff. |
| 3 | [**Polymarket Command Center**](polymarket-command-center/) | Read-only Polymarket interface — trending markets, detailed odds with probability bars, search, watchlists. Zero API key required. |
| 4 | [**Prediction Market Arbiter**](prediction-market-arbiter/) | Cross-platform divergence scanner — fuzzy-matches Kalshi vs Polymarket prices across 1000+ markets per run. Detects arbitrage and mispricings automatically. |
| 5 | [**Xpulse**](xpulse/) | X/Twitter social signal scanner — DuckDuckGo search + two-stage local LLM filtering (tradeable signal detection, then materiality gating). Position-aware, fail-closed. |
| 6 | [**Portfolio Drift Monitor**](portfolio-drift-monitor/) | Position drift alerts — snapshot comparison fires when any Kalshi position moves beyond threshold since last check. Directional indicators, rate-limited. |
| 7 | [**Market Morning Brief**](market-morning-brief/) | Daily intelligence digest — aggregates portfolio P&L, top edges, divergences, social signals, crypto prices, Polymarket trends into a 30-second scan. Morning + evening editions. |
| 8 | [**Personality Engine**](personality-engine/) | Six-system behavior engine — editorial voice, selective silence, variable timing, micro-initiations, context buffer, response tracking. Domain-agnostic with default trading config. |
| 9 | [**Prediction Stack Orchestrator**](prediction-stack-orchestrator/) | Three-agent pipeline manager (Kalshalyst → Eval → Executor) for automated trading with validation loops, retry logic, and veto power. Routes markets through estimation and validates before execution. |
| 10 | [**Prediction Stack Setup**](prediction-stack-setup/) | Setup wizard — detects installed skills, walks through API keys, creates cron jobs, enables heartbeat, tests iMessage delivery. Turns 10 standalone skills into a connected system. |

## How They Connect

```
┌─────────────────────────────────────────────────────────────┐
│                    SCHEDULED JOBS (Cron)                     │
│  edge-scan → xpulse-scan → drift-monitor → arbiter-scan    │
│  morning-brief (8AM) ←── reads all caches ──→ evening-brief │
└─────────────┬───────────────────────────────────┬───────────┘
              │                                   │
              ▼                                   ▼
┌─────────────────────────┐   ┌───────────────────────────────┐
│    INTELLIGENCE LAYER   │   │      DELIVERY LAYER           │
│                         │   │                               │
│  Kalshalyst ──→ cache   │   │  BlueBubbles → iMessage       │
│  Arbiter ──→ cache      │   │  openclaw send → your phone   │
│  Xpulse ──→ cache       │   │  Heartbeat (30m ambient)      │
│  Portfolio Drift        │   │                               │
│  Morning Brief ←── all  │   └───────────────────────────────┘
│  Personality Engine     │
└─────────────────────────┘   ┌───────────────────────────────┐
              │               │      EXECUTION LAYER          │
              ▼               │  Kalshi CC → trade on edges   │
┌─────────────────────────┐   │  Polymarket CC → market data  │
│   ORCHESTRATION LAYER   │   │  Orchestrator → automated     │
│  Orchestrator validates │   │    pipeline (estimate →       │
│  estimates + routes to  │   │    validate → execute)        │
│  execution or retry     │   └───────────────────────────────┘
└─────────────────────────┘
```

Skills communicate via JSON cache files — no direct dependencies. Install any subset and each works standalone. The Morning Brief reads whatever caches exist and gracefully skips the rest.

## What Fires When

| Time | Job | What Happens |
|------|-----|-------------|
| 8:00 AM | morning-brief + edge-scan | Full digest + first edge scan |
| 9:00 AM | drift-monitor + arbiter-scan | Position check + arbitrage scan |
| Every 30m | xpulse-scan | Social signal check (8 AM – 10 PM) |
| Every 2h | edge-scan | Kalshalyst edge detection (8 AM – 8 PM) |
| Hourly | drift-monitor | Position drift check (9 AM – 8 PM) |
| 3x daily | arbiter-scan | Cross-platform divergence (9 AM, 1 PM, 5 PM) |
| 6:00 PM | evening-brief | Evening summary |

Most scans are **silent by design** — they only alert when something exceeds your configured thresholds. Silence means the filters are working.

## Cost to Run

**$0/month** if you have a Claude Max subscription. The LLM calls run through the Claude CLI at no additional cost — your subscription covers it.

No Claude subscription? The stack still works. Kalshalyst and Xpulse fall back to **Qwen** (local, free via Ollama) at degraded but functional accuracy — still meaningfully above coin-flip on edge detection. Every other skill in the stack (Command Centers, Arbiter, Drift Monitor, Morning Brief, Orchestrator) requires zero LLM calls.

All external APIs are free: Kalshi API, Polymarket Gamma API, DuckDuckGo search.

| Component | Claude Max | Qwen (Free) |
|-----------|-----------|-------------|
| Kalshalyst edge scanning | Full accuracy | Degraded, above baseline |
| Xpulse signal filtering | Full accuracy | Degraded, above baseline |
| Everything else | No LLM needed | No LLM needed |

## Requirements

- [OpenClaw](https://openclaw.ai) agent
- [Ollama](https://ollama.ai) with `qwen2.5:7b` (free, local) — or Claude Max subscription for full performance
- Kalshi API key (free at [kalshi.com](https://kalshi.com))
- Optional: BlueBubbles for iMessage delivery

## Author

[KingMadeLLC](https://github.com/kingmadellc)

## License

MIT
