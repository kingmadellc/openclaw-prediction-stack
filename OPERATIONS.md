<!-- CODEX: operator guide added so the stack's "operational" claims map to a repeatable verification runbook. -->
# Prediction Stack Operations

This checklist is the fastest way to verify that the public stack is wired correctly after setup changes, doc changes, or environment migration.

## 1. Validate prerequisites

Run the setup validator:

```bash
python3 prediction-stack-setup/scripts/validate_setup.py --verbose
```

Expected outcome:
- `Kalshi API` passes
- `Anthropic (Claude)` passes
- Optional services either pass or fail with an understood reason

Run the broader health audit:

```bash
python3 tests/stack_health.py --skip-auth
```

Use the full auth path when you want a live Kalshi check:

```bash
python3 tests/stack_health.py --verbose
```

## 2. Dry-run the runtime skills

Kalshalyst:

```bash
python3 kalshalyst/scripts/auto_trader.py --dry-run
```

Prediction Market Arbiter:

```bash
python3 prediction-market-arbiter/scripts/arbiter.py --dry-run
```

Xpulse:

```bash
python3 xpulse/scripts/xpulse.py --dry-run
```

Morning Brief:

```bash
python3 market-morning-brief/scripts/morning_brief.py --dry-run
```

Evening Brief:

```bash
python3 market-morning-brief/scripts/evening_brief.py --mode market --dry-run
```

## 3. Check the cache contract

The runtime skills should populate or consume these files:

- `~/.openclaw/state/kalshalyst_cache.json`
- `~/.openclaw/state/arbiter_cache.json`
- `~/.openclaw/state/x_signal_cache.json`

Morning Brief should degrade cleanly when any cache is missing or stale, and should render the matching section when the cache is fresh.

## 4. Verify scheduling

If you use the setup wizard's cron flow:

```bash
openclaw cron list
```

Confirm the six default jobs exist:

- `morning-brief`
- `evening-brief`
- `edge-scan`
- `xpulse-scan`
- `drift-monitor`
- `arbiter-scan`

Spot-check one job manually:

```bash
openclaw cron run edge-scan
```

## 5. Regression gate before publishing

Run the test suite:

```bash
python3 -m pytest tests -q
```

At minimum, run the targeted contract tests added for this repo-hardening pass:

```bash
python3 -m pytest tests/test_validate_setup.py tests/test_cache_contracts.py tests/test_docs_consistency.py -q
```
