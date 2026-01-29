#!/usr/bin/env python3
"""Fix Janitorr Leaving Soon false positives and refresh broken metadata.

Reads the US-005 Leaving Soon consistency report (produced by
leaving_soon_checker.py), then:
- Removes false positive items from the Leaving Soon Jellyfin collections
- Refreshes metadata on items with broken/missing metadata
- Investigates Janitorr configuration for root cause of false positives
- Re-runs the consistency check to verify improvements

Usage:
  python scripts/fix_leaving_soon.py [--dry-run] [--report-dir /path/to/reports]
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

from scripts.leaving_soon_checker import (
    BrokenMetadata,
    FalsePositive,
    LeavingSoonReport,
    MissingItem,
    get_collection_items,
    parse_janitorr_config,
    run_check as run_leaving_soon_check,
)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class FixAction:
    """Result of a single fix action."""
    title: str
    jellyfin_id: str
    media_type: str
    action: str          # "remove_from_collection" or "refresh_metadata"
    detail: str          # extra context (e.g. reason or missing fields)
    success: bool = False
    error: str = ""
    dry_run: bool = False


@dataclass
class ConfigFinding:
    """A Janitorr configuration finding that may cause false positives."""
    category: str        # e.g. "exclusion_tags", "leaving_soon_window"
    description: str
    recommendation: str


@dataclass
class LeavingSoonFixReport:
    """Aggregated results from all Leaving Soon fix actions."""
    actions: list[FixAction] = field(default_factory=list)
    config_findings: list[ConfigFinding] = field(default_factory=list)
    dry_run: bool = False
    pre_check: LeavingSoonReport | None = None
    post_check: LeavingSoonReport | None = None
    fixed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    @property
    def total_attempted(self) -> int:
        return len(self.actions)

    @property
    def total_succeeded(self) -> int:
        return sum(1 for a in self.actions if a.success)

    @property
    def total_failed(self) -> int:
        return sum(1 for a in self.actions if not a.success)

    @property
    def removal_actions(self) -> list[FixAction]:
        return [a for a in self.actions if a.action == "remove_from_collection"]

    @property
    def refresh_actions(self) -> list[FixAction]:
        return [a for a in self.actions if a.action == "refresh_metadata"]


# ------------------------------------------------------------------
# Collection ID lookup
# ------------------------------------------------------------------

def _find_collection_id(
    jellyfin: JellyfinClient,
    collection_name: str,
) -> str | None:
    """Find the Jellyfin ID of a named collection (boxset).

    Returns the collection ID or None if not found.
    """
    result = jellyfin.get_items(
        IncludeItemTypes="BoxSet",
        Recursive="true",
        SearchTerm=collection_name,
    )
    for item in result.get("Items", []):
        if item.get("Name", "").strip().lower() == collection_name.strip().lower():
            return item["Id"]
    return None


# ------------------------------------------------------------------
# Fix logic
# ------------------------------------------------------------------

def remove_false_positive(
    jellyfin: JellyfinClient,
    collection_id: str,
    fp: FalsePositive,
    dry_run: bool = False,
) -> FixAction:
    """Remove a single false positive item from a Leaving Soon collection."""
    action = FixAction(
        title=fp.title,
        jellyfin_id=fp.jellyfin_id,
        media_type=fp.media_type,
        action="remove_from_collection",
        detail=fp.reason,
        dry_run=dry_run,
    )

    if dry_run:
        action.success = True
        return action

    try:
        jellyfin.remove_from_collection(collection_id, [fp.jellyfin_id])
        action.success = True
    except Exception as exc:
        action.error = str(exc)

    return action


def refresh_broken_item(
    jellyfin: JellyfinClient,
    bm: BrokenMetadata,
    dry_run: bool = False,
) -> FixAction:
    """Refresh metadata for a Leaving Soon item with broken metadata."""
    action = FixAction(
        title=bm.title,
        jellyfin_id=bm.jellyfin_id,
        media_type=bm.media_type,
        action="refresh_metadata",
        detail=", ".join(bm.missing_fields),
        dry_run=dry_run,
    )

    if dry_run:
        action.success = True
        return action

    try:
        jellyfin.refresh_item(bm.jellyfin_id)
        action.success = True
    except Exception as exc:
        action.error = str(exc)

    return action


# ------------------------------------------------------------------
# Janitorr config investigation
# ------------------------------------------------------------------

def investigate_config(
    janitorr_config: dict,
    pre_check: LeavingSoonReport,
) -> list[ConfigFinding]:
    """Investigate Janitorr configuration for root causes of false positives.

    Examines the config and the pre-check results to identify potential
    configuration issues that could lead to false positives.
    """
    findings: list[ConfigFinding] = []

    # Check if exclusion tags are configured
    exclusion_tags = janitorr_config.get("exclusion_tags", [])
    if not exclusion_tags:
        findings.append(ConfigFinding(
            category="exclusion_tags",
            description="No exclusion tags configured in Janitorr",
            recommendation=(
                "Add exclusion tags (e.g. 'keep', 'favorite') in "
                "application.yml under application.exclusion-tags to prevent "
                "accidental tagging of protected items."
            ),
        ))

    # Check leaving-soon window
    days = janitorr_config.get("leaving_soon_days", 14)
    if days < 7:
        findings.append(ConfigFinding(
            category="leaving_soon_window",
            description=f"Leaving-soon window is only {days} day(s)",
            recommendation=(
                "Consider increasing the leaving-soon window to at least 7 "
                "days to give users adequate notice before deletion."
            ),
        ))

    # Check for false positives that suggest a sync/timing issue
    fp_count = pre_check.false_positive_count
    scheduled_total = pre_check.scheduled_tv_count + pre_check.scheduled_movie_count
    if fp_count > 0 and scheduled_total == 0:
        findings.append(ConfigFinding(
            category="sync_issue",
            description=(
                f"Found {fp_count} false positive(s) but no scheduled items "
                "in Sonarr/Radarr — Janitorr may not be syncing tags correctly"
            ),
            recommendation=(
                "Verify that Janitorr is running and that Sonarr/Radarr tag "
                "'janitorr-leaving-soon' is being applied to items approaching "
                "their expiration date."
            ),
        ))

    # Check for high false-positive ratio
    collection_total = (
        pre_check.leaving_soon_tv_count + pre_check.leaving_soon_movie_count
    )
    if collection_total > 0 and fp_count > 0:
        ratio = fp_count / collection_total
        if ratio > 0.5:
            findings.append(ConfigFinding(
                category="high_false_positive_ratio",
                description=(
                    f"{fp_count} of {collection_total} collection items "
                    f"({ratio:.0%}) are false positives"
                ),
                recommendation=(
                    "A high false-positive ratio suggests Janitorr may be "
                    "removing tags from Sonarr/Radarr without updating the "
                    "Jellyfin collection. Check Janitorr logs for errors."
                ),
            ))

    return findings


# ------------------------------------------------------------------
# Main fix orchestration
# ------------------------------------------------------------------

def run_fixes(
    jellyfin: JellyfinClient,
    sonarr: SonarrClient,
    radarr: RadarrClient,
    janitorr_config: dict,
    dry_run: bool = False,
) -> LeavingSoonFixReport:
    """Run the full Leaving Soon fix pipeline:

    1. Run Leaving Soon consistency check to find current issues.
    2. Investigate Janitorr config for root causes.
    3. Remove false positives from Leaving Soon collections.
    4. Refresh metadata on broken items.
    5. Re-run consistency check to verify improvements.
    """
    report = LeavingSoonFixReport(dry_run=dry_run)

    # Step 1: Pre-check
    log.info("Running pre-fix Leaving Soon consistency check...")
    report.pre_check = run_leaving_soon_check(
        jellyfin, sonarr, radarr, janitorr_config,
    )

    fp_list = report.pre_check.false_positives
    broken_list = report.pre_check.broken_metadata

    if not fp_list and not broken_list:
        log.info("No false positives or broken metadata found — nothing to fix.")
        report.config_findings = investigate_config(
            janitorr_config, report.pre_check,
        )
        return report

    log.info(
        "Found %d false positive(s) and %d broken metadata item(s) to fix.",
        len(fp_list), len(broken_list),
    )

    # Step 2: Investigate config
    report.config_findings = investigate_config(janitorr_config, report.pre_check)
    if report.config_findings:
        for f in report.config_findings:
            log.info("Config finding [%s]: %s", f.category, f.description)

    # Step 3: Resolve collection IDs
    tv_collection_name = janitorr_config["leaving_soon_tv"]
    movie_collection_name = janitorr_config["leaving_soon_movies"]

    tv_collection_id = _find_collection_id(jellyfin, tv_collection_name)
    movie_collection_id = _find_collection_id(jellyfin, movie_collection_name)

    if tv_collection_id:
        log.info("TV collection '%s' -> %s", tv_collection_name, tv_collection_id)
    else:
        log.warning("TV collection '%s' not found", tv_collection_name)

    if movie_collection_id:
        log.info("Movie collection '%s' -> %s", movie_collection_name, movie_collection_id)
    else:
        log.warning("Movie collection '%s' not found", movie_collection_name)

    # Step 4: Remove false positives
    for i, fp in enumerate(fp_list, 1):
        collection_id = (
            tv_collection_id if fp.media_type == "tv" else movie_collection_id
        )

        if collection_id is None:
            action = FixAction(
                title=fp.title,
                jellyfin_id=fp.jellyfin_id,
                media_type=fp.media_type,
                action="remove_from_collection",
                detail=fp.reason,
                dry_run=dry_run,
                error=f"Collection not found for {fp.media_type}",
            )
            report.actions.append(action)
            log.warning(
                "[FP %d/%d] SKIPPED %s '%s' — collection not found",
                i, len(fp_list), fp.media_type.upper(), fp.title,
            )
            continue

        log.info(
            "[FP %d/%d] %s %s '%s' from collection%s",
            i, len(fp_list),
            "Would remove" if dry_run else "Removing",
            fp.media_type.upper(), fp.title,
            " [DRY RUN]" if dry_run else "",
        )
        action = remove_false_positive(
            jellyfin, collection_id, fp, dry_run=dry_run,
        )
        report.actions.append(action)

        if action.success:
            log.info("  -> %s", "Would remove [DRY RUN]" if dry_run else "REMOVED")
        else:
            log.warning("  -> FAILED: %s", action.error)

    # Step 5: Refresh broken metadata
    for i, bm in enumerate(broken_list, 1):
        log.info(
            "[Meta %d/%d] %s %s '%s' (missing: %s)%s",
            i, len(broken_list),
            "Would refresh" if dry_run else "Refreshing",
            bm.media_type.upper(), bm.title,
            ", ".join(bm.missing_fields),
            " [DRY RUN]" if dry_run else "",
        )
        action = refresh_broken_item(jellyfin, bm, dry_run=dry_run)
        report.actions.append(action)

        if action.success:
            log.info("  -> %s", "Would refresh [DRY RUN]" if dry_run else "REFRESHED")
        else:
            log.warning("  -> FAILED: %s", action.error)

    # Step 6: Post-fix verification (skip in dry-run mode)
    if not dry_run:
        log.info("Running post-fix Leaving Soon consistency check...")
        report.post_check = run_leaving_soon_check(
            jellyfin, sonarr, radarr, janitorr_config,
        )

    return report


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def format_console_summary(report: LeavingSoonFixReport) -> str:
    """Format a concise console summary of fix results."""
    lines: list[str] = []
    lines.append("Leaving Soon Fix Results")
    lines.append(f"Fixed at: {report.fixed_at}")
    if report.dry_run:
        lines.append("Mode: DRY RUN (no changes made)")
    lines.append("")

    pre = report.pre_check
    if pre:
        lines.append(f"Pre-fix false positives: {pre.false_positive_count}")
        lines.append(f"Pre-fix broken metadata: {pre.broken_count}")
        lines.append(f"Pre-fix missing items: {pre.missing_count}")
    lines.append("")

    removals = report.removal_actions
    refreshes = report.refresh_actions

    lines.append(f"Collection removals attempted: {len(removals)}")
    lines.append(f"  Succeeded: {sum(1 for a in removals if a.success)}")
    lines.append(f"  Failed: {sum(1 for a in removals if not a.success)}")
    lines.append("")

    lines.append(f"Metadata refreshes attempted: {len(refreshes)}")
    lines.append(f"  Succeeded: {sum(1 for a in refreshes if a.success)}")
    lines.append(f"  Failed: {sum(1 for a in refreshes if not a.success)}")
    lines.append("")

    if report.actions:
        lines.append("Details:")
        for a in report.actions:
            if a.dry_run:
                status = "WOULD FIX [DRY RUN]"
            elif a.success:
                status = "OK"
            else:
                status = f"FAILED ({a.error})"
            lines.append(
                f"  [{a.media_type.upper()}] {a.title} "
                f"({a.action}: {a.detail}) -> {status}"
            )
        lines.append("")

    if report.config_findings:
        lines.append("Janitorr config findings:")
        for f in report.config_findings:
            lines.append(f"  [{f.category}] {f.description}")
            lines.append(f"    Recommendation: {f.recommendation}")
        lines.append("")

    post = report.post_check
    if post and not report.dry_run:
        lines.append(f"Post-fix false positives: {post.false_positive_count}")
        lines.append(f"Post-fix broken metadata: {post.broken_count}")
        lines.append(f"Post-fix missing items: {post.missing_count}")
        if pre:
            fp_fixed = pre.false_positive_count - post.false_positive_count
            meta_fixed = pre.broken_count - post.broken_count
            lines.append(
                f"Improvement: {fp_fixed} false positive(s) removed, "
                f"{meta_fixed} metadata issue(s) resolved"
            )
        lines.append("")

    lines.append(
        f"Summary: {report.total_succeeded} of {report.total_attempted} "
        f"actions successful"
    )

    return "\n".join(lines)


def format_markdown_report(report: LeavingSoonFixReport) -> str:
    """Generate a full markdown Leaving Soon fix report."""
    lines: list[str] = []
    lines.append("# Leaving Soon Fix Report")
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
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| False positives | {pre.false_positive_count} |")
        lines.append(f"| Missing from collection | {pre.missing_count} |")
        lines.append(f"| Broken metadata | {pre.broken_count} |")
        lines.append(f"| **Total issues** | **{pre.total_issues}** |")
        lines.append("")

        if pre.false_positives:
            lines.append("### False Positives Found")
            lines.append("")
            lines.append("| Type | Title | Reason |")
            lines.append("|------|-------|--------|")
            for fp in pre.false_positives:
                lines.append(
                    f"| {fp.media_type.upper()} | {fp.title} | {fp.reason} |"
                )
            lines.append("")

        if pre.broken_metadata:
            lines.append("### Broken Metadata Found")
            lines.append("")
            lines.append("| Type | Title | Missing Fields |")
            lines.append("|------|-------|----------------|")
            for bm in pre.broken_metadata:
                fields = ", ".join(bm.missing_fields)
                lines.append(
                    f"| {bm.media_type.upper()} | {bm.title} | {fields} |"
                )
            lines.append("")
    else:
        lines.append("No pre-fix check was performed.")
        lines.append("")

    # Janitorr config findings
    lines.append("## Janitorr Configuration Analysis")
    lines.append("")
    if report.config_findings:
        lines.append("| Category | Finding | Recommendation |")
        lines.append("|----------|---------|----------------|")
        for f in report.config_findings:
            lines.append(
                f"| {f.category} | {f.description} | {f.recommendation} |"
            )
        lines.append("")
    else:
        lines.append("No configuration issues identified.")
        lines.append("")

    # Fix actions
    lines.append("## Fix Actions")
    lines.append("")
    if not report.actions:
        lines.append("No fix actions were needed.")
        lines.append("")
    else:
        lines.append("| # | Type | Title | Action | Detail | Result |")
        lines.append("|---|------|-------|--------|--------|--------|")
        for i, a in enumerate(report.actions, 1):
            if a.dry_run:
                result = "WOULD FIX"
            elif a.success:
                result = "OK"
            else:
                result = f"FAILED: {a.error}"
            lines.append(
                f"| {i} | {a.media_type.upper()} | {a.title} "
                f"| {a.action} | {a.detail} | {result} |"
            )
        lines.append("")

    # Summary table
    removals = report.removal_actions
    refreshes = report.refresh_actions

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Collection removals attempted | {len(removals)} |")
    lines.append(f"| Collection removals succeeded | {sum(1 for a in removals if a.success)} |")
    lines.append(f"| Metadata refreshes attempted | {len(refreshes)} |")
    lines.append(f"| Metadata refreshes succeeded | {sum(1 for a in refreshes if a.success)} |")
    lines.append(f"| **Total attempted** | **{report.total_attempted}** |")
    lines.append(f"| **Total succeeded** | **{report.total_succeeded}** |")
    lines.append(f"| **Total failed** | **{report.total_failed}** |")
    lines.append("")

    # Post-fix verification
    if report.post_check and not report.dry_run:
        lines.append("## Post-Fix Verification")
        lines.append("")
        post = report.post_check
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| False positives remaining | {post.false_positive_count} |")
        lines.append(f"| Missing from collection | {post.missing_count} |")
        lines.append(f"| Broken metadata remaining | {post.broken_count} |")
        lines.append("")

        if pre:
            fp_before = pre.false_positive_count
            fp_after = post.false_positive_count
            meta_before = pre.broken_count
            meta_after = post.broken_count
            lines.append(f"- False positives: {fp_before} -> {fp_after} "
                          f"(**{fp_before - fp_after}** removed)")
            lines.append(f"- Broken metadata: {meta_before} -> {meta_after} "
                          f"(**{meta_before - meta_after}** resolved)")
            lines.append("")
    elif report.dry_run:
        lines.append("## Post-Fix Verification")
        lines.append("")
        lines.append("*Skipped — dry run mode, no changes were made.*")
        lines.append("")

    lines.append(
        f"**Result: {report.total_succeeded} of {report.total_attempted} "
        f"actions successful**"
    )
    lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix Janitorr Leaving Soon false positives and broken metadata"
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
    parser.add_argument(
        "--janitorr-config",
        default=None,
        help="Path to Janitorr application.yml",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    # Locate Janitorr config
    config_path = args.janitorr_config
    if config_path is None:
        config_path = str(
            Path(__file__).resolve().parent.parent
            / "config"
            / "janitorr"
            / "application.yml"
        )

    janitorr_config = parse_janitorr_config(config_path)

    jellyfin = JellyfinClient()
    sonarr = SonarrClient()
    radarr = RadarrClient()

    report = run_fixes(
        jellyfin, sonarr, radarr, janitorr_config, dry_run=args.dry_run,
    )

    # Console summary
    print()
    print(format_console_summary(report))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(
            Path(__file__).resolve().parent.parent / "tests" / "reports"
        )

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "fix-leaving-soon.md"
    report_path.write_text(format_markdown_report(report))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
