---
name: Social Poster
description: "Automated social media agency for the OpenClaw Prediction Stack. Reads scan results, formats them in your writing voice, and posts to X via Postiz CLI. Supports timestamped prediction calls, builder threads, market resolution follow-ups, and morning brief summaries. Designed to run on cron — scan fires, this skill picks up the output and posts it without human intervention."
license: MIT
---

# Social Poster — Prediction Stack Social Media Agent

## Overview

Social Poster is the distribution layer for the OpenClaw Prediction Stack. It takes raw scan output (from Kalshalyst, Market Morning Brief, or Portfolio Drift Monitor) and converts it into voice-consistent social media posts via the Postiz CLI.

The pipeline: **Scan → Voice Format → Review/Auto-Post → Track Resolution**

This skill does NOT estimate probabilities or make trading decisions. It is a formatting and distribution agent. It reads what the stack produces and turns it into posts.

## When to Use This Skill

- After a Kalshalyst scan produces edges worth sharing publicly
- When Market Morning Brief generates a daily digest
- When a previously-called market resolves (follow-up quote-tweet)
- When you want to post a builder thread about the system
- When you want to schedule a week of prediction calls from a single scan

## Requirements

### Tools

1. **Postiz CLI** (required)
   - Install: `npm install -g postiz`
   - Set API key: `export POSTIZ_API_KEY=your_key`
   - Connect X account in Postiz dashboard at postiz.com
   - Get integration ID: `postiz integrations:list`

2. **Kalshalyst** (upstream dependency)
   - Produces scan results with edges, tickers, and market context
   - Social Poster reads these outputs — it does not run scans itself

3. **Voice Profile** (required)
   - Location: `~/memory/voice.md`
   - All posts are formatted against this voice profile
   - If voice file is missing, skill refuses to post (no generic AI slop)

### Configuration

Create `~/.openclaw/social-poster.yaml`:

```yaml
# Postiz integration ID for X (@KingMadeLLC)
x_integration_id: "your-x-integration-id"

# Posting mode: "draft" (review before posting) or "schedule" (auto-post)
mode: "draft"

# Maximum posts per day (prevents flooding)
max_daily_posts: 3

# Minimum edge threshold to auto-generate a post (decimal)
min_edge_for_post: 0.10

# Hours between posts (prevents burst posting)
min_hours_between: 4

# Voice profile path
voice_file: "~/memory/voice.md"

# Scan results directory (where kalshalyst drops output)
scan_dir: "~/scans/"

# Resolution tracking file
resolution_tracker: "~/social-poster/resolutions.json"
```

---

## How It Works

### Phase 1: Intake

Read the latest scan output. Scan results come from Kalshalyst and contain:
- Market ticker (e.g., KXRECESSION-26)
- Market title and category
- Current market price (in cents)
- Model estimated probability
- Edge (model_prob - market_price)
- Confidence level
- Key factors driving the estimate

The skill looks for scan results in `scan_dir` (default: `~/scans/`). It reads the most recent `.json` or `.md` scan file.

### Phase 2: Filter

Not every edge is worth posting. Filter criteria:
- **Edge ≥ min_edge_for_post** (default: 10 cents) — small edges aren't interesting to the timeline
- **Category is postable** — skip "other" category, skip markets with ambiguous resolution criteria
- **Not already posted** — check resolution tracker to avoid duplicate calls on the same market
- **Daily limit not hit** — respect max_daily_posts

### Phase 3: Voice Format

This is the core transformation. Take the raw scan data and format it as a post in the operator's voice.

**Voice rules (loaded from ~/memory/voice.md):**
- Lowercase default
- Short punchy sentences (≤15 words)
- No exclamation marks
- Dashes over commas
- States, doesn't pitch
- Specific numbers — always include the ticker, the price, the model estimate
- No hashtags (one community tag max)
- No emojis in body text
- Employment filter active (no Microsoft references, no "hardware PM" positioning)

**Post template for prediction calls:**

```
my model says [event] probability is [model_pct]%. kalshi has it at [market_price]¢.

[1-2 sentence contrarian thesis — why market is wrong]

[TICKER]. checking back [resolution timeframe].
```

**Post template for resolution follow-ups:**

```
called this [timeframe ago]. [TICKER] at [original_price]¢, model said [model_pct]%.

resolved [YES/NO] at [resolution_price]¢. [outcome: "+X¢ edge captured" or "missed this one — model overweighted Y"]
```

**Thread template for builder updates:**

```
Post 1: [hook — single interesting number or claim]

Post 2-N: [supporting detail, one concept per post]

Final post: [what's next or CTA to follow]
```

### Phase 4: Post via Postiz

Execute the post using Postiz CLI:

```bash
# Single prediction call
postiz posts:create \
  -c "my model says recession probability is 52%. kalshi has it at 35¢.\n\ntariff escalation + consumer confidence collapse — market is pricing the pre-tariff world.\n\nKXRECSSNBER-26. checking back in december." \
  -s "2026-03-13T18:00:00Z" \
  -i "$X_INTEGRATION_ID" \
  -t schedule

# Thread (multiple -c flags, 5min delay between)
postiz posts:create \
  -c "built a system that mass-estimates kalshi markets and finds where they're wrong." \
  -c "five phases. fetch every open market. classify by category. estimate true probability using claude opus in contrarian mode. calculate edge. alert." \
  -c "the key insight — blind estimation is worthless." \
  -d 5 \
  -s "2026-03-13T19:00:00Z" \
  -i "$X_INTEGRATION_ID" \
  -t schedule
```

**Mode behavior:**
- `draft` mode: Creates post as draft in Postiz (`-t draft`). You review in the Postiz dashboard before it goes live. **Recommended for first 2 weeks.**
- `schedule` mode: Schedules post for auto-publish (`-t schedule`). Fully autonomous.

### Phase 5: Track & Follow Up

After posting a prediction call, log it to the resolution tracker:

```json
{
  "market_id": "KXRECESSION-26",
  "posted_at": "2026-03-13T18:00:00Z",
  "model_estimate": 0.52,
  "market_price_at_post": 0.35,
  "edge_at_post": 0.17,
  "post_id": "postiz-post-id",
  "status": "open",
  "resolved_at": null,
  "resolution": null
}
```

When the market resolves:
1. Check resolution tracker for open entries
2. Look up final resolution on Kalshi
3. Generate follow-up post using resolution template
4. Post via Postiz
5. Update tracker entry with resolution data

This is the credibility flywheel: call → timestamp → resolve → show receipt → repeat.

---

## Automation: Cron Integration

Wire this into your existing prediction stack cron schedule:

```bash
# After kalshalyst scan completes (e.g., daily at 9:15am after the 9am scan)
15 9 * * * cd ~/skills && python3 -c "
import json, subprocess, datetime

# Read latest scan
with open('$HOME/scans/latest_scan.json') as f:
    scan = json.load(f)

# Filter for postable edges
postable = [m for m in scan.get('markets', []) if abs(m.get('edge', 0)) >= 0.10]

if not postable:
    print('No edges worth posting today')
    exit(0)

# Take top edge
best = max(postable, key=lambda m: abs(m.get('edge', 0)))

# Format post (simplified — full voice formatting done by the agent)
ticker = best.get('ticker', 'UNKNOWN')
model_pct = int(best['model_estimate'] * 100)
market_price = int(best['market_price'] * 100)
edge = int(abs(best['edge']) * 100)

content = f'my model says {best[\"title\"].lower()} probability is {model_pct}%. kalshi has it at {market_price}¢.\n\nedge: {edge}¢.\n\n{ticker}.'

# Schedule for 30 min from now
post_time = (datetime.datetime.utcnow() + datetime.timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')

subprocess.run([
    'postiz', 'posts:create',
    '-c', content,
    '-s', post_time,
    '-i', '$X_INTEGRATION_ID',
    '-t', 'draft'
])
"
```

Or better — use OpenClaw's scheduled task system:

```
Task: social-poster-daily
Schedule: "15 9 * * *"  (daily at 9:15am, after scan)
Prompt: "Read the latest kalshalyst scan results. Find the top edge (≥10¢). Format a prediction call post using my voice profile at ~/memory/voice.md. Post it as a draft via Postiz CLI. Log the call to the resolution tracker."
```

---

## Commands Reference

### Manual posting

```bash
# List your connected platforms
postiz integrations:list

# Create a scheduled post
postiz posts:create -c "content" -s "2026-03-13T18:00:00Z" -i "integration-id"

# Create a draft (review before posting)
postiz posts:create -c "content" -s "2026-03-13T18:00:00Z" -i "integration-id" -t draft

# Post a thread (multiple -c flags)
postiz posts:create -c "tweet 1" -c "tweet 2" -c "tweet 3" -d 5 -s "2026-03-13T18:00:00Z" -i "integration-id"

# List recent posts
postiz posts:list

# Check analytics
postiz analytics:platform "integration-id"
postiz analytics:post "post-id"
```

### Voice formatting shortcuts

When the agent formats posts, it should:
1. Read `~/memory/voice.md` first
2. Write the post
3. Check against voice rules (lowercase? short sentences? no exclamation marks? specific numbers?)
4. If any rule violated, rewrite
5. Never post without voice check passing

---

## What This Skill Does NOT Do

- Does not estimate probabilities (that's Kalshalyst)
- Does not execute trades (that's Kalshi Command Center)
- Does not monitor social signals (that's Xpulse)
- Does not generate images or media (text-only posts)
- Does not interact with other platforms besides what Postiz supports
- Does not bypass the voice profile — if voice.md is missing, refuse to post

---

## Integration with Prediction Stack

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│  Kalshalyst  │────▶│ Social Poster │────▶│  Postiz CLI   │────▶ X / Reddit
│  (scan)      │     │ (format)      │     │  (distribute) │
└─────────────┘     └──────────────┘     └───────────────┘
       │                    │
       ▼                    ▼
┌─────────────┐     ┌──────────────┐
│  Orchestrator│     │  Resolution  │
│  (trade)     │     │  Tracker     │
└─────────────┘     └──────────────┘
```

The stack flow:
1. Kalshalyst scans → produces edges
2. Orchestrator decides whether to trade
3. **Social Poster picks up the same scan → formats → posts**
4. When market resolves → Social Poster generates follow-up
5. Resolution follow-ups build public track record

Social Poster runs in parallel with the trading pipeline. It reads the same scan data but its output goes to X, not to Kalshi.
