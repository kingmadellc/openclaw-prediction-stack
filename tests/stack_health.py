#!/usr/bin/env python3
"""
OpenClaw Prediction Stack — Health Check

Run at session start before touching anything. Validates:
  1. SDK packages installed (kalshi_python_sync + kalshi_python)
  2. Config.yaml credentials present and well-formed
  3. No stale env var credential overrides
  4. Kalshi API auth works (live call)
  5. Positions response parses correctly (.positions vs .market_positions)
  6. Portfolio balance accessible
  7. Each skill's imports resolve

Usage:
  python3 ~/skills/tests/stack_health.py
  python3 ~/skills/tests/stack_health.py --verbose
  python3 ~/skills/tests/stack_health.py --skip-auth   # offline check only
"""

import importlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv
SKIP_AUTH = "--skip-auth" in sys.argv

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

results = []


def check(name, passed, msg="", warn=False):
    icon = PASS if passed else (WARN if warn else FAIL)
    results.append({"name": name, "passed": passed, "warn": warn, "msg": msg})
    print(f"  {icon} {name}" + (f" — {msg}" if msg else ""))
    return passed


def section(title):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. SDK Packages
# ══════════════════════════════════════════════════════════════════════════════
section("1. SDK Packages")

sync_sdk = None
try:
    import kalshi_python_sync
    sync_sdk = kalshi_python_sync
    ver = getattr(kalshi_python_sync, "__version__", "unknown")
    check("kalshi_python_sync installed", True, f"v{ver}")
except ImportError:
    check("kalshi_python_sync installed", False, "MISSING — this is the active v3 SDK")

legacy_sdk = None
try:
    import kalshi_python
    legacy_sdk = kalshi_python
    ver = getattr(kalshi_python, "__version__", "unknown")
    check("kalshi_python installed", True, f"v{ver} (legacy fallback)")
except ImportError:
    check("kalshi_python installed", False, "missing", warn=True)

if sync_sdk is None and legacy_sdk is None:
    check("At least one SDK available", False, "NO KALSHI SDK INSTALLED")
    print("\n❌ FATAL: No Kalshi SDK. Run: pip3 install kalshi-python-sync")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# 2. Config.yaml Credentials
# ══════════════════════════════════════════════════════════════════════════════
section("2. Config.yaml Credentials")

config_path = Path.home() / ".openclaw" / "config.yaml"
config = {}
kalshi_cfg = {}

try:
    import yaml
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        kalshi_cfg = config.get("kalshi", {})
        check("config.yaml exists", True, str(config_path))
    else:
        check("config.yaml exists", False, f"not found at {config_path}")
except ImportError:
    check("config.yaml exists", False, "pyyaml not installed — can't read config")

api_key_id = kalshi_cfg.get("api_key_id", "")
private_key_file = kalshi_cfg.get("private_key_file", "")
enabled = kalshi_cfg.get("enabled", False)

check("kalshi.enabled = true", enabled, "" if enabled else "kalshi section disabled")
check("api_key_id present", bool(api_key_id) and api_key_id != "REPLACE_WITH_YOUR_KEY_ID",
      f"{api_key_id[:8]}..." if api_key_id else "empty")
check("private_key_file present", bool(private_key_file), private_key_file or "empty")

if private_key_file:
    key_path = Path(private_key_file).expanduser()
    check("private key file exists", key_path.exists(),
          str(key_path) if key_path.exists() else f"NOT FOUND: {key_path}")
else:
    check("private key file exists", False, "no path configured")

# ══════════════════════════════════════════════════════════════════════════════
# 3. Env Var Credential Override Check
# ══════════════════════════════════════════════════════════════════════════════
section("3. Env Var Credential Override Check")

env_key_id = os.environ.get("KALSHI_KEY_ID", "")
env_key_path = os.environ.get("KALSHI_KEY_PATH", "")

if not env_key_id and not env_key_path:
    check("No stale env var overrides", True, "KALSHI_KEY_ID and KALSHI_KEY_PATH are empty (safe)")
else:
    if env_key_id:
        matches = env_key_id == api_key_id
        check("KALSHI_KEY_ID env var", matches,
              f"matches config.yaml" if matches else f"MISMATCH: env={env_key_id[:8]}... vs config={api_key_id[:8]}...",
              warn=not matches)
    if env_key_path:
        check("KALSHI_KEY_PATH env var set", True, f"{env_key_path}", warn=True)

# ══════════════════════════════════════════════════════════════════════════════
# 4. Kalshi API Auth
# ══════════════════════════════════════════════════════════════════════════════
section("4. Kalshi API Auth")

client = None
if SKIP_AUTH:
    check("Auth test", True, "SKIPPED (--skip-auth)", warn=True)
elif not api_key_id or not private_key_file:
    check("Auth test", False, "cannot test — credentials missing")
else:
    try:
        try:
            from kalshi_python_sync import Configuration, KalshiClient
            sdk_label = "kalshi_python_sync"
        except ImportError:
            from kalshi_python import Configuration, KalshiClient
            sdk_label = "kalshi_python"

        key_path = Path(private_key_file).expanduser()
        cfg = Configuration(host="https://api.elections.kalshi.com/trade-api/v2")
        with open(key_path) as f:
            cfg.private_key_pem = f.read().strip()
        cfg.api_key_id = api_key_id

        client = KalshiClient(cfg)

        # Auth check — try public method first
        start = time.time()
        try:
            resp = client.get_positions(limit=1)
            elapsed = int((time.time() - start) * 1000)
            check("Kalshi auth (get_positions)", True, f"OK in {elapsed}ms via {sdk_label}")
        except (TypeError, AttributeError) as e:
            # Fallback to internal API
            client._portfolio_api.get_balance()
            elapsed = int((time.time() - start) * 1000)
            check("Kalshi auth (fallback _portfolio_api)", True, f"OK in {elapsed}ms via {sdk_label}", warn=True)
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err:
            check("Kalshi auth", False, f"AUTH FAILED — check credentials: {err[:100]}")
        else:
            check("Kalshi auth", False, f"{err[:100]}")

# ══════════════════════════════════════════════════════════════════════════════
# 5. Positions Response Parsing
# ══════════════════════════════════════════════════════════════════════════════
section("5. Positions Response Parsing")

if SKIP_AUTH or client is None:
    check("Positions parsing", True, "SKIPPED", warn=True)
else:
    try:
        resp = client.get_positions(limit=5)

        if hasattr(resp, "positions") and resp.positions is not None:
            check("Positions field (.positions)", True, f"{len(resp.positions)} positions via v3 SDK")
        elif hasattr(resp, "market_positions") and resp.market_positions is not None:
            check("Positions field (.market_positions)", True, f"{len(resp.market_positions)} positions via v2 SDK", warn=True)
        elif isinstance(resp, dict):
            positions = resp.get("market_positions", resp.get("positions", []))
            check("Positions field (dict fallback)", True, f"{len(positions)} positions", warn=True)
        else:
            check("Positions field", False, f"Unexpected type: {type(resp)}")
    except Exception as e:
        check("Positions parsing", False, str(e)[:100])

# ══════════════════════════════════════════════════════════════════════════════
# 6. Portfolio Balance
# ══════════════════════════════════════════════════════════════════════════════
section("6. Portfolio Balance")

if SKIP_AUTH or client is None:
    check("Balance check", True, "SKIPPED", warn=True)
else:
    try:
        bal_resp = client._portfolio_api.get_balance()
        balance = getattr(bal_resp, "balance", None)
        if balance is not None:
            check("Balance accessible", True, f"${balance / 100:.2f}")
        else:
            check("Balance accessible", False, f"Unexpected response: {bal_resp}")
    except Exception as e:
        check("Balance accessible", False, f"_portfolio_api.get_balance() failed: {str(e)[:80]}", warn=True)

# ══════════════════════════════════════════════════════════════════════════════
# 7. Skill Import Audit
# ══════════════════════════════════════════════════════════════════════════════
section("7. Skill Import Audit")

skills_dir = Path.home() / "skills"
if not skills_dir.exists():
    skills_dir = Path(__file__).parent.parent

bad_imports = []
for py_file in sorted(skills_dir.rglob("*.py")):
    if py_file.name.startswith("__") or "test" in py_file.parts:
        continue
    try:
        content = py_file.read_text()
        # Check for v2-only imports (not wrapped in try/except with v3)
        if "from kalshi_python import" in content:
            # Check if it's properly guarded with kalshi_python_sync
            if "kalshi_python_sync" not in content:
                rel = py_file.relative_to(skills_dir)
                bad_imports.append(str(rel))
    except Exception:
        pass

if bad_imports:
    check("All skills use v3 SDK import pattern", False,
          f"{len(bad_imports)} file(s) use kalshi_python without v3 fallback")
    for f in bad_imports:
        print(f"       → {f}")
else:
    check("All skills use v3 SDK import pattern", True)

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 50}")
passed = sum(1 for r in results if r["passed"])
warned = sum(1 for r in results if r["warn"])
failed = sum(1 for r in results if not r["passed"])
total = len(results)

if failed == 0 and warned == 0:
    print(f"  ✅ ALL GREEN — {passed}/{total} checks passed")
elif failed == 0:
    print(f"  ⚠️  {passed}/{total} passed, {warned} warnings")
else:
    print(f"  ❌ {failed} FAILED, {warned} warnings, {passed} passed out of {total}")
print(f"{'═' * 50}\n")

sys.exit(1 if failed > 0 else 0)
