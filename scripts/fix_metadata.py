#!/usr/bin/env python3
"""Fix Jellyfin metadata mismatches detected by the metadata accuracy checker.

Reads the US-003 metadata accuracy report (produced by metadata_checker.py),
then uses the Jellyfin Identify and Refresh APIs to correct mismatched items.

Usage:
  python scripts/fix_metadata.py [--dry-run] [--report-dir /path/to/reports]
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the yams root so the tests package is accessible
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.jellyfin_client import JellyfinClient
from tests.sonarr_client import SonarrClient
from tests.radarr_client import RadarrClient

from scripts.metadata_checker import (
    Mismatch,
    MetadataReport,
    run_check as run_metadata_check,
    format_console_summary,
)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class FixAttempt:
    """Result of a single metadata fix attempt."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str
    field: str
    action: str          # "identify" or "refresh"
    success: bool = False
    error: str = ""
    dry_run: bool = False


@dataclass
class FixReport:
    """Aggregated results from all fix attempts."""
    attempts: list[FixAttempt] = field(default_factory=list)
    dry_run: bool = False
    pre_check: MetadataReport | None = None
    post_check: MetadataReport | None = None
    fixed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    @property
    def total_attempted(self) -> int:
        return len(self.attempts)

    @property
    def total_succeeded(self) -> int:
        return sum(1 for a in self.attempts if a.success)

    @property
    def total_failed(self) -> int:
        return sum(1 for a in self.attempts if not a.success)


# ------------------------------------------------------------------
# Provider-ID helpers
# ------------------------------------------------------------------

def _get_provider_for_type(media_type: str) -> tuple[str, str]:
    """Return (provider_name, arr_id_field) for a media type.

    For TV shows we use Tvdb; for movies we use Tmdb.
    """
    if media_type == "tv":
        return ("Tvdb", "tvdbId")
    return ("Tmdb", "tmdbId")


def _extract_external_id(arr_value: str) -> str:
    """Extract the numeric ID from an arr_value like 'tvdb:81189' or 'tmdb:603'."""
    if ":" in arr_value:
        return arr_value.split(":", 1)[1]
    return arr_value


# ------------------------------------------------------------------
# Fix logic
# ------------------------------------------------------------------

def fix_mismatch(
    jellyfin: JellyfinClient,
    mismatch: Mismatch,
    dry_run: bool = False,
) -> FixAttempt:
    """Attempt to fix a single metadata mismatch.

    For external_id mismatches: uses the Identify (RemoteSearch) API to
    re-match the item against the correct provider ID.

    For title/year mismatches: triggers a full metadata refresh which pulls
    fresh data from the currently matched provider.
    """
    attempt = FixAttempt(
        jellyfin_title=mismatch.jellyfin_title,
        jellyfin_id=mismatch.jellyfin_id,
        media_type=mismatch.media_type,
        field=mismatch.field,
        action="identify" if mismatch.field == "external_id" else "refresh",
        dry_run=dry_run,
    )

    if dry_run:
        attempt.success = True
        return attempt

    try:
        if mismatch.field == "external_id":
            # Re-identify: search for the correct external ID and apply
            provider_name, _ = _get_provider_for_type(mismatch.media_type)
            ext_id = _extract_external_id(mismatch.arr_value)
            results = jellyfin.search_remote(
                item_id=mismatch.jellyfin_id,
                media_type=mismatch.media_type,
                provider_id=ext_id,
                provider_name=provider_name,
            )
            if results:
                jellyfin.apply_search_result(mismatch.jellyfin_id)
                attempt.success = True
            else:
                attempt.error = f"No remote search results for {provider_name}:{ext_id}"
        else:
            # Title or year mismatch: trigger full metadata refresh
            jellyfin.refresh_item(mismatch.jellyfin_id)
            attempt.success = True
    except Exception as exc:
        attempt.error = str(exc)

    return attempt


def run_fixes(
    jellyfin: JellyfinClient,
    sonarr: SonarrClient,
    radarr: RadarrClient,
    dry_run: bool = False,
) -> FixReport:
    """Run the full fix pipeline:

    1. Run metadata accuracy check to get current mismatches.
    2. Attempt to fix each mismatch.
    3. Re-run metadata accuracy check to verify improvements.
    """
    report = FixReport(dry_run=dry_run)

    # Step 1: Run pre-check
    log.info("Running pre-fix metadata accuracy check...")
    report.pre_check = run_metadata_check(jellyfin, sonarr, radarr)
    mismatches = report.pre_check.mismatches

    if not mismatches:
        log.info("No metadata mismatches found - nothing to fix.")
        return report

    log.info("Found %d mismatched items to fix.", len(mismatches))

    # Step 2: Fix each mismatch
    for i, mismatch in enumerate(mismatches, 1):
        log.info(
            "[%d/%d] %s %s '%s' (%s: %s -> %s)%s",
            i, len(mismatches),
            "Would fix" if dry_run else "Fixing",
            mismatch.media_type.upper(),
            mismatch.jellyfin_title,
            mismatch.field,
            mismatch.jellyfin_value,
            mismatch.arr_value,
            " [DRY RUN]" if dry_run else "",
        )
        attempt = fix_mismatch(jellyfin, mismatch, dry_run=dry_run)
        report.attempts.append(attempt)

        if attempt.success:
            log.info("  -> %s", "Would succeed [DRY RUN]" if dry_run else "OK")
        else:
            log.warning("  -> FAILED: %s", attempt.error)

    # Step 3: Re-run metadata check to verify (skip in dry-run mode)
    if not dry_run:
        log.info("Running post-fix metadata accuracy check...")
        report.post_check = run_metadata_check(jellyfin, sonarr, radarr)

    return report


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def format_console_summary_fix(report: FixReport) -> str:
    """Format a concise console summary of fix results."""
    lines: list[str] = []
    lines.append("Metadata Fix Results")
    lines.append(f"Fixed at: {report.fixed_at}")
    if report.dry_run:
        lines.append("Mode: DRY RUN (no changes made)")
    lines.append("")

    pre = report.pre_check
    if pre:
        lines.append(f"Pre-fix mismatches: {len(pre.mismatches)}")

    lines.append(f"Fix attempts: {report.total_attempted}")
    lines.append(f"Succeeded: {report.total_succeeded}")
    lines.append(f"Failed: {report.total_failed}")
    lines.append("")

    if report.attempts:
        lines.append("Details:")
        for a in report.attempts:
            status = "OK" if a.success else f"FAILED ({a.error})"
            if a.dry_run:
                status = "WOULD FIX [DRY RUN]"
            lines.append(
                f"  [{a.media_type.upper()}] {a.jellyfin_title} "
                f"({a.field}) -> {a.action}: {status}"
            )
        lines.append("")

    post = report.post_check
    if post and not report.dry_run:
        lines.append(f"Post-fix mismatches: {len(post.mismatches)}")
        if pre:
            improved = len(pre.mismatches) - len(post.mismatches)
            lines.append(f"Improvement: {improved} items corrected")
        lines.append("")

    lines.append(
        f"Summary: {report.total_succeeded} of {report.total_attempted} "
        f"items successfully fixed"
    )

    return "\n".join(lines)


def format_markdown_report(report: FixReport) -> str:
    """Generate a full markdown fix report."""
    lines: list[str] = []
    lines.append("# Metadata Fix Report")
    lines.append("")
    lines.append(f"**Fixed at:** {report.fixed_at}")
    if report.dry_run:
        lines.append("**Mode:** DRY RUN (no changes made)")
    lines.append("")

    # Pre-fix summary
    lines.append("## Pre-Fix Status")
    lines.append("")
    pre = report.pre_check
    if pre:
        lines.append(f"Mismatched metadata items found: **{len(pre.mismatches)}**")
        lines.append("")
        if pre.mismatches:
            lines.append("| Type | Title | Field | Jellyfin Value | Arr Value |")
            lines.append("|------|-------|-------|----------------|-----------|")
            for m in pre.mismatches:
                lines.append(
                    f"| {m.media_type.upper()} | {m.jellyfin_title} "
                    f"| {m.field} | {m.jellyfin_value} | {m.arr_value} |"
                )
            lines.append("")
    else:
        lines.append("No pre-fix check was performed.")
        lines.append("")

    # Fix attempts
    lines.append("## Fix Attempts")
    lines.append("")
    lines.append("| # | Type | Title | Field | Action | Result |")
    lines.append("|---|------|-------|-------|--------|--------|")
    for i, a in enumerate(report.attempts, 1):
        if a.dry_run:
            result = "WOULD FIX"
        elif a.success:
            result = "OK"
        else:
            result = f"FAILED: {a.error}"
        lines.append(
            f"| {i} | {a.media_type.upper()} | {a.jellyfin_title} "
            f"| {a.field} | {a.action} | {result} |"
        )
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Total attempted | {report.total_attempted} |")
    lines.append(f"| Succeeded | {report.total_succeeded} |")
    lines.append(f"| Failed | {report.total_failed} |")
    lines.append("")

    # Post-fix verification
    if report.post_check and not report.dry_run:
        lines.append("## Post-Fix Verification")
        lines.append("")
        post = report.post_check
        lines.append(f"Remaining mismatched metadata items: **{len(post.mismatches)}**")
        lines.append("")
        if pre:
            before = len(pre.mismatches)
            after = len(post.mismatches)
            improved = before - after
            lines.append(f"- Before: {before} mismatches")
            lines.append(f"- After: {after} mismatches")
            lines.append(f"- Improvement: **{improved}** items corrected")
            lines.append("")
        if post.mismatches:
            lines.append("### Remaining Mismatches")
            lines.append("")
            lines.append("| Type | Title | Field | Jellyfin Value | Arr Value |")
            lines.append("|------|-------|-------|----------------|-----------|")
            for m in post.mismatches:
                lines.append(
                    f"| {m.media_type.upper()} | {m.jellyfin_title} "
                    f"| {m.field} | {m.jellyfin_value} | {m.arr_value} |"
                )
            lines.append("")
    elif report.dry_run:
        lines.append("## Post-Fix Verification")
        lines.append("")
        lines.append("*Skipped — dry run mode, no changes were made.*")
        lines.append("")

    lines.append(
        f"**Result: {report.total_succeeded} of {report.total_attempted} "
        f"items successfully fixed**"
    )
    lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix Jellyfin metadata mismatches detected by the accuracy checker"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be fixed without making changes",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to save the markdown report",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    jellyfin = JellyfinClient()
    sonarr = SonarrClient()
    radarr = RadarrClient()

    report = run_fixes(jellyfin, sonarr, radarr, dry_run=args.dry_run)

    # Console summary
    print()
    print(format_console_summary_fix(report))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(
            Path(__file__).resolve().parent.parent / "tests" / "reports"
        )

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "fix-metadata.md"
    report_path.write_text(format_markdown_report(report))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
