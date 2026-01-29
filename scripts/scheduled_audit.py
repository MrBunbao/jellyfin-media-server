#!/usr/bin/env python3
"""Scheduled YAMS health audit — runs the full audit on a cron schedule.

Wraps the US-006 audit orchestrator with:
  - Configurable schedule via AUDIT_SCHEDULE (cron expression, default: weekly)
  - Timestamped reports saved to the reports directory
  - Optional webhook notification with summary
  - Health status file for Docker health checks
  - Docker-friendly stdout logging

Environment variables:
  AUDIT_SCHEDULE       Cron expression (default: "0 3 * * 0" = Sunday 03:00)
  AUDIT_REPORT_DIR     Report output directory (default: /reports)
  AUDIT_WEBHOOK_URL    Optional webhook URL for notifications
  AUDIT_RUN_ON_START   Run audit immediately on startup (default: "true")
  AUDIT_MEDIA_ROOT     Media root path (default: /volume4/mediaserver/media)
  AUDIT_JANITORR_CFG   Janitorr config path

All Jellyfin/Sonarr/Radarr environment variables are inherited from
the existing tests/config.py loader.

Usage:
  # Run as a scheduled service (default):
  python3 scripts/scheduled_audit.py

  # Run once and exit:
  python3 scripts/scheduled_audit.py --once
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the yams root so the scripts/tests packages are accessible
_YAMS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_YAMS_ROOT))

from scripts.audit import (
    AuditResult,
    run_all_scanners,
    format_console_output,
    format_markdown_report,
)

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

DEFAULT_SCHEDULE = "0 3 * * 0"  # Sunday 03:00
DEFAULT_REPORT_DIR = str(_YAMS_ROOT / "tests" / "reports")
DEFAULT_MEDIA_ROOT = "/volume4/mediaserver/media"
DEFAULT_JANITORR_CONFIG = str(_YAMS_ROOT / "config" / "janitorr" / "application.yml")

# Health status file — written after each audit run
HEALTH_STATUS_FILE = "/tmp/yams-audit-health.json"


def _get_config() -> dict:
    """Load configuration from environment variables."""
    return {
        "schedule": os.environ.get("AUDIT_SCHEDULE", DEFAULT_SCHEDULE),
        "report_dir": os.environ.get("AUDIT_REPORT_DIR", DEFAULT_REPORT_DIR),
        "webhook_url": os.environ.get("AUDIT_WEBHOOK_URL", ""),
        "run_on_start": os.environ.get("AUDIT_RUN_ON_START", "true").lower()
        in ("true", "1", "yes"),
        "media_root": os.environ.get("AUDIT_MEDIA_ROOT", DEFAULT_MEDIA_ROOT),
        "janitorr_config": os.environ.get(
            "AUDIT_JANITORR_CFG", DEFAULT_JANITORR_CONFIG
        ),
    }


# ------------------------------------------------------------------
# Cron expression parser (minimal — supports standard 5-field cron)
# ------------------------------------------------------------------


def parse_cron(expr: str) -> dict:
    """Parse a 5-field cron expression into a dict of allowed values.

    Fields: minute, hour, day-of-month, month, day-of-week
    Supports: *, specific numbers, comma lists, ranges (e.g. 1-5), steps (e.g. */2)
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(
            f"Invalid cron expression: expected 5 fields, got {len(fields)}: {expr!r}"
        )

    names = ["minute", "hour", "dom", "month", "dow"]
    ranges = [
        (0, 59),
        (0, 23),
        (1, 31),
        (1, 12),
        (0, 6),
    ]

    parsed: dict[str, set[int]] = {}
    for name, field, (lo, hi) in zip(names, fields, ranges):
        parsed[name] = _parse_cron_field(field, lo, hi)

    return parsed


def _parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    """Parse a single cron field into a set of allowed integer values."""
    values: set[int] = set()
    for part in field.split(","):
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                start, end = lo, hi
            elif "-" in base:
                a, b = base.split("-", 1)
                start, end = int(a), int(b)
            else:
                start, end = int(base), hi
            values.update(range(start, end + 1, step))
        elif part == "*":
            values.update(range(lo, hi + 1))
        elif "-" in part:
            a, b = part.split("-", 1)
            values.update(range(int(a), int(b) + 1))
        else:
            values.add(int(part))
    return values


def cron_matches(cron: dict, dt: datetime) -> bool:
    """Check if a datetime matches a parsed cron expression."""
    return (
        dt.minute in cron["minute"]
        and dt.hour in cron["hour"]
        and dt.day in cron["dom"]
        and dt.month in cron["month"]
        and dt.weekday() in _convert_dow(cron["dow"])
    )


def _convert_dow(dow_set: set[int]) -> set[int]:
    """Convert cron day-of-week (0=Sun) to Python weekday (0=Mon).

    Cron: 0=Sun, 1=Mon, ..., 6=Sat
    Python: 0=Mon, 1=Tue, ..., 6=Sun
    """
    converted: set[int] = set()
    for d in dow_set:
        if d == 0:
            converted.add(6)  # Sun → 6
        else:
            converted.add(d - 1)  # Mon=1→0, Tue=2→1, etc.
    return converted


# ------------------------------------------------------------------
# Audit execution
# ------------------------------------------------------------------


def run_audit(config: dict) -> AuditResult:
    """Execute the full audit and save results."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    log(f"Starting audit run at {timestamp}")

    # Run all scanners
    result = run_all_scanners(
        media_root=config["media_root"],
        janitorr_config_path=config["janitorr_config"],
    )

    # Console output (captured by Docker logging)
    print(format_console_output(result))

    # Save timestamped markdown report
    report_dir = Path(config["report_dir"])
    report_dir.mkdir(parents=True, exist_ok=True)

    report_filename = f"{timestamp}_full-audit.md"
    report_path = report_dir / report_filename
    report_path.write_text(format_markdown_report(result))
    log(f"Report saved: {report_path}")

    # Also update the latest symlink / copy for easy access
    latest_path = report_dir / "full-audit.md"
    latest_path.write_text(format_markdown_report(result))

    # Update health status file
    _write_health_status(result, str(report_path))

    # Send notification if configured
    if config["webhook_url"]:
        _send_webhook(config["webhook_url"], result)

    log(f"Audit complete: {result.total_issues} issues, {len(result.errors)} errors")
    return result


def _write_health_status(result: AuditResult, report_path: str) -> None:
    """Write a JSON health status file for the Docker health check."""
    status = {
        "last_run": result.audited_at,
        "total_issues": result.total_issues,
        "scanner_errors": len(result.errors),
        "has_issues": result.has_issues,
        "report_path": report_path,
        "status": "unhealthy" if result.errors else "healthy",
    }
    Path(HEALTH_STATUS_FILE).write_text(json.dumps(status, indent=2))


def _send_webhook(url: str, result: AuditResult) -> None:
    """Send a summary notification via webhook (Discord/Slack-compatible)."""
    try:
        import requests
    except ImportError:
        log("WARNING: requests not installed, skipping webhook notification")
        return

    status_emoji = "RED" if result.has_issues else "GREEN"
    status_text = "ISSUES FOUND" if result.has_issues else "ALL CLEAR"

    summary = (
        f"YAMS Health Audit — {status_text} [{status_emoji}]\n"
        f"Run: {result.audited_at}\n"
        f"Total issues: {result.total_issues}\n"
        f"Scanner errors: {len(result.errors)}\n"
    )

    if result.has_issues:
        details = []
        if result.naming_issues > 0:
            details.append(f"  Naming: {result.naming_issues}")
        if result.mismatches_found > 0:
            details.append(f"  Metadata mismatches: {result.mismatches_found}")
        if result.health_orphans > 0:
            details.append(f"  Orphaned files: {result.health_orphans}")
        if result.duplicates > 0:
            details.append(f"  Duplicates: {result.duplicate_items}")
        if result.false_positives > 0:
            details.append(f"  Leaving Soon false positives: {result.false_positives}")
        if details:
            summary += "\n".join(details)

    payload = {"content": summary}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log("Webhook notification sent successfully")
    except Exception as exc:
        log(f"WARNING: Webhook notification failed: {exc}")


# ------------------------------------------------------------------
# Scheduler loop
# ------------------------------------------------------------------


_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown
    log(f"Received signal {signum}, shutting down...")
    _shutdown = True


def run_scheduler(config: dict) -> None:
    """Run the audit on a cron schedule, looping until shutdown."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    schedule = config["schedule"]
    cron = parse_cron(schedule)
    log(f"Scheduled audit: {schedule}")
    log(f"Report directory: {config['report_dir']}")
    if config["webhook_url"]:
        log("Webhook notifications: enabled")

    # Optionally run immediately on startup
    if config["run_on_start"]:
        log("Running initial audit on startup...")
        try:
            run_audit(config)
        except Exception as exc:
            log(f"ERROR: Initial audit failed: {exc}")

    log("Entering schedule loop (checking every 60s)...")
    last_run_minute: str = ""

    while not _shutdown:
        now = datetime.now()
        current_minute = now.strftime("%Y-%m-%d %H:%M")

        if current_minute != last_run_minute and cron_matches(cron, now):
            last_run_minute = current_minute
            try:
                run_audit(config)
            except Exception as exc:
                log(f"ERROR: Scheduled audit failed: {exc}")

        # Sleep 30s between checks (ensures we don't miss a minute window)
        for _ in range(30):
            if _shutdown:
                break
            time.sleep(1)

    log("Scheduler stopped.")


# ------------------------------------------------------------------
# Logging helper
# ------------------------------------------------------------------


def log(message: str) -> None:
    """Print a timestamped log message to stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {message}", flush=True)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YAMS scheduled health audit — runs the full audit on a cron schedule"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single audit and exit (no scheduling)",
    )
    args = parser.parse_args()

    config = _get_config()

    if args.once:
        result = run_audit(config)
        sys.exit(1 if result.has_issues else 0)
    else:
        run_scheduler(config)


if __name__ == "__main__":
    main()
