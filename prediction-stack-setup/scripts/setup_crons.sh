#!/bin/bash
# setup_crons.sh — Wire the OpenClaw Prediction Stack cron jobs
#
# Ships with the stack. Run once after install or anytime you need to rewire.
# Uses native crontab — no OpenClaw CLI dependency.
#
# Usage:
#   bash ~/skills/prediction-stack-setup/scripts/setup_crons.sh
#   bash ~/skills/prediction-stack-setup/scripts/setup_crons.sh --remove   # tear down all stack crons
#   bash ~/skills/prediction-stack-setup/scripts/setup_crons.sh --status   # show current stack crons
#
# All jobs log to ~/.openclaw/logs/ and post to Slack if webhook is configured.

set -u

SKILLS_DIR="${HOME}/skills"
OPENCLAW_DIR="${HOME}/.openclaw"
LOG_DIR="${OPENCLAW_DIR}/logs"
MARKER="# OPENCLAW-STACK"

mkdir -p "$LOG_DIR"

# ── Helpers ──────────────────────────────────────────────────────────────

show_status() {
    echo "=== OpenClaw Prediction Stack Cron Jobs ==="
    crontab -l 2>/dev/null | grep "$MARKER" || echo "(none installed)"
    echo ""
    echo "=== Log files ==="
    ls -lh "$LOG_DIR"/*.log 2>/dev/null || echo "(no logs yet)"
}

remove_crons() {
    echo "Removing OpenClaw stack cron jobs..."
    crontab -l 2>/dev/null | grep -v "$MARKER" | crontab -
    echo "Done. All stack cron jobs removed."
    echo "Other cron jobs are untouched."
}

# ── Parse args ───────────────────────────────────────────────────────────

if [ "${1:-}" = "--status" ]; then
    show_status
    exit 0
fi

if [ "${1:-}" = "--remove" ]; then
    remove_crons
    exit 0
fi

# ── Build cron entries ───────────────────────────────────────────────────

echo "=== OpenClaw Prediction Stack — Cron Setup ==="
echo ""
echo "Skills dir: $SKILLS_DIR"
echo "Logs dir:   $LOG_DIR"
echo ""

# Remove existing stack crons first (idempotent reinstall)
crontab -l 2>/dev/null | grep -v "$MARKER" > /tmp/openclaw_cron_clean 2>/dev/null || true

cat >> /tmp/openclaw_cron_clean << CRONS
# ── Auto-Trader Scan (every 3 hours, 7am-10pm) ── $MARKER
0 7,10,13,16,19,22 * * * cd ${SKILLS_DIR}/kalshalyst/scripts && /usr/bin/python3 auto_trader.py >> ${LOG_DIR}/auto_trader.log 2>&1 $MARKER
# ── Portfolio Drift Monitor (hourly, 8am-11pm) ── $MARKER
0 8-23 * * * cd ${SKILLS_DIR}/portfolio-drift-monitor/scripts && /usr/bin/python3 portfolio_drift.py >> ${LOG_DIR}/portfolio_drift.log 2>&1 $MARKER
# ── Morning Brief (daily 7:30am) ── $MARKER
30 7 * * * cd ${SKILLS_DIR}/market-morning-brief/scripts && /usr/bin/python3 morning_brief.py >> ${LOG_DIR}/morning_brief.log 2>&1 $MARKER
# ── Evening Brief (daily 9pm) ── $MARKER
0 21 * * * cd ${SKILLS_DIR}/market-morning-brief/scripts && /usr/bin/python3 morning_brief.py --evening >> ${LOG_DIR}/morning_brief.log 2>&1 $MARKER
# ── Xpulse Signal Scan (every 2 hours, 8am-10pm) ── $MARKER
0 8,10,12,14,16,18,20,22 * * * cd ${SKILLS_DIR}/xpulse/scripts && /usr/bin/python3 xpulse.py >> ${LOG_DIR}/xpulse.log 2>&1 $MARKER
# ── Arbiter Divergence Scan (3x daily) ── $MARKER
0 9,14,19 * * * cd ${SKILLS_DIR}/prediction-market-arbiter/scripts && /usr/bin/python3 arbiter.py >> ${LOG_DIR}/arbiter.log 2>&1 $MARKER
# ── Stale Order Cleanup (daily 6am, before first scan) ── $MARKER
0 6 * * * cd ${SKILLS_DIR}/kalshalyst/scripts && /usr/bin/python3 -c "from auto_trader import cleanup_stale_orders; from kalshi_commands import _get_client; c=_get_client(); cleanup_stale_orders(c, 120)" >> ${LOG_DIR}/auto_trader.log 2>&1 $MARKER
# ── Log Rotation (weekly Sunday 5am) ── $MARKER
0 5 * * 0 find ${LOG_DIR} -name "*.log" -size +10M -exec truncate -s 0 {} \; $MARKER
CRONS

# Install
crontab /tmp/openclaw_cron_clean
rm /tmp/openclaw_cron_clean

echo "Cron jobs installed:"
echo ""
crontab -l | grep "$MARKER" | grep -v "^#" | while read -r line; do
    schedule=$(echo "$line" | awk '{print $1,$2,$3,$4,$5}')
    cmd=$(echo "$line" | sed "s|.*python3 ||; s| >>.*||; s|.*-c .*|stale order cleanup|")
    echo "  $schedule  →  $cmd"
done

echo ""
echo "=== Schedule Summary ==="
echo "  Auto-Trader:     6x/day (7am, 10am, 1pm, 4pm, 7pm, 10pm)"
echo "  Portfolio Drift:  Hourly (8am-11pm)"
echo "  Morning Brief:    Daily 7:30am"
echo "  Evening Brief:    Daily 9pm"
echo "  Xpulse Signals:   8x/day (every 2hr, 8am-10pm)"
echo "  Arbiter:          3x/day (9am, 2pm, 7pm)"
echo "  Stale Cleanup:    Daily 6am"
echo "  Log Rotation:     Weekly Sunday 5am"
echo ""
echo "Logs: $LOG_DIR"
echo "Remove: bash $0 --remove"
echo "Status: bash $0 --status"
echo ""
echo "IMPORTANT: Run sync_skills.sh first to ensure runtime uses latest code:"
echo "  bash ~/skills/sync_skills.sh"
