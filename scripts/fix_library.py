#!/usr/bin/env python3
"""Clean up orphaned and duplicate Jellyfin library entries.

Reads the US-004 library health report (produced by library_health_checker.py),
then removes orphaned entries (file missing) and deduplicates items sharing the
same provider ID via the Jellyfin API.

Usage:
  python scripts/fix_library.py [--dry-run] [--report-dir /path/to/reports]
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

from scripts.library_health_checker import (
    DuplicateGroup,
    HealthReport,
    OrphanedItem,
    run_health_check,
    format_console_summary as format_health_console,
)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class RemovalAction:
    """Result of a single item removal."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str
    reason: str          # "orphaned" or "duplicate"
    detail: str          # e.g. file path or provider info
    success: bool = False
    error: str = ""
    dry_run: bool = False


@dataclass
class CleanupReport:
    """Aggregated results from all cleanup actions."""
    actions: list[RemovalAction] = field(default_factory=list)
    dry_run: bool = False
    pre_check: HealthReport | None = None
    post_check: HealthReport | None = None
    cleaned_at: str = field(
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
    def orphan_actions(self) -> list[RemovalAction]:
        return [a for a in self.actions if a.reason == "orphaned"]

    @property
    def duplicate_actions(self) -> list[RemovalAction]:
        return [a for a in self.actions if a.reason == "duplicate"]


# ------------------------------------------------------------------
# Duplicate resolution — pick the best item to keep
# ------------------------------------------------------------------

def pick_best_item(group: DuplicateGroup, jellyfin: JellyfinClient) -> str:
    """Return the Jellyfin ID of the item to *keep* from a duplicate group.

    Scoring criteria (higher is better):
    - Has an Overview (description): +2
    - Has a Primary image tag (poster): +2
    - Has a ProductionYear: +1
    - More ProviderIds: +1 per extra provider

    On ties, the first item (as returned by the API) wins.
    """
    best_id = group.items[0]["Id"]
    best_score = -1

    for item_dict in group.items:
        try:
            meta = jellyfin.get_item_metadata(item_dict["Id"])
        except Exception:
            # If we can't fetch metadata, score stays at 0
            meta = {}

        score = 0
        if (meta.get("Overview") or "").strip():
            score += 2
        if (meta.get("ImageTags") or {}).get("Primary"):
            score += 2
        if meta.get("ProductionYear"):
            score += 1
        score += len(meta.get("ProviderIds") or {})

        if score > best_score:
            best_score = score
            best_id = item_dict["Id"]

    return best_id


# ------------------------------------------------------------------
# Cleanup logic
# ------------------------------------------------------------------

def remove_orphaned(
    jellyfin: JellyfinClient,
    orphan: OrphanedItem,
    dry_run: bool = False,
    path_exists_fn=os.path.exists,
) -> RemovalAction:
    """Remove a single orphaned Jellyfin entry after re-verifying the file is gone."""
    action = RemovalAction(
        jellyfin_title=orphan.jellyfin_title,
        jellyfin_id=orphan.jellyfin_id,
        media_type=orphan.media_type,
        reason="orphaned",
        detail=orphan.file_path,
        dry_run=dry_run,
    )

    # Re-check: the file might have been restored since the health report
    if path_exists_fn(orphan.file_path):
        action.error = "File now exists — skipping removal"
        return action

    if dry_run:
        action.success = True
        return action

    try:
        jellyfin.delete_item(orphan.jellyfin_id)
        action.success = True
    except Exception as exc:
        action.error = str(exc)

    return action


def remove_duplicate(
    jellyfin: JellyfinClient,
    item_id: str,
    item_name: str,
    media_type: str,
    provider_info: str,
    dry_run: bool = False,
) -> RemovalAction:
    """Remove a single duplicate Jellyfin entry."""
    action = RemovalAction(
        jellyfin_title=item_name,
        jellyfin_id=item_id,
        media_type=media_type,
        reason="duplicate",
        detail=provider_info,
        dry_run=dry_run,
    )

    if dry_run:
        action.success = True
        return action

    try:
        jellyfin.delete_item(item_id)
        action.success = True
    except Exception as exc:
        action.error = str(exc)

    return action


def run_cleanup(
    jellyfin: JellyfinClient,
    dry_run: bool = False,
    path_exists_fn=os.path.exists,
) -> CleanupReport:
    """Run the full cleanup pipeline:

    1. Run library health check to find orphaned/duplicate items.
    2. Remove orphaned entries (file missing on disk).
    3. Remove duplicate entries (keep the one with best metadata).
    4. Re-run health check to verify improvements.
    """
    report = CleanupReport(dry_run=dry_run)

    # Step 1: Pre-check
    log.info("Running pre-cleanup library health check...")
    report.pre_check = run_health_check(jellyfin, path_exists_fn=path_exists_fn)

    orphans = report.pre_check.orphaned_items
    duplicates = report.pre_check.duplicates

    if not orphans and not duplicates:
        log.info("No orphaned or duplicate items found — nothing to clean up.")
        return report

    log.info(
        "Found %d orphaned items and %d duplicate groups to process.",
        len(orphans), len(duplicates),
    )

    # Step 2: Remove orphaned entries
    for i, orphan in enumerate(orphans, 1):
        log.info(
            "[Orphan %d/%d] %s %s '%s' -> %s%s",
            i, len(orphans),
            "Would remove" if dry_run else "Removing",
            orphan.media_type.upper(),
            orphan.jellyfin_title,
            orphan.file_path,
            " [DRY RUN]" if dry_run else "",
        )
        action = remove_orphaned(
            jellyfin, orphan, dry_run=dry_run, path_exists_fn=path_exists_fn,
        )
        report.actions.append(action)

        if action.success:
            log.info("  -> %s", "Would remove [DRY RUN]" if dry_run else "REMOVED")
        else:
            log.warning("  -> SKIPPED/FAILED: %s", action.error)

    # Step 3: Remove duplicate entries
    for i, group in enumerate(duplicates, 1):
        provider_info = f"{group.provider}:{group.provider_id}"
        log.info(
            "[Duplicate group %d/%d] %s %s (%d items)",
            i, len(duplicates),
            group.media_type.upper(),
            provider_info,
            group.count,
        )

        # Pick the best item to keep
        if dry_run:
            # In dry-run mode, still pick best to report accurately but skip API
            # For dry-run, use first item as keeper to avoid unnecessary API calls
            keep_id = group.items[0]["Id"]
        else:
            keep_id = pick_best_item(group, jellyfin)

        keep_name = next(
            (it["Name"] for it in group.items if it["Id"] == keep_id),
            "?",
        )
        log.info("  Keeping: '%s' (ID: %s)", keep_name, keep_id)

        for item in group.items:
            if item["Id"] == keep_id:
                continue
            log.info(
                "  %s '%s' (ID: %s)%s",
                "Would remove" if dry_run else "Removing",
                item["Name"],
                item["Id"],
                " [DRY RUN]" if dry_run else "",
            )
            action = remove_duplicate(
                jellyfin,
                item_id=item["Id"],
                item_name=item["Name"],
                media_type=group.media_type,
                provider_info=provider_info,
                dry_run=dry_run,
            )
            report.actions.append(action)

            if action.success:
                log.info("  -> %s", "Would remove [DRY RUN]" if dry_run else "REMOVED")
            else:
                log.warning("  -> FAILED: %s", action.error)

    # Step 4: Post-cleanup verification (skip in dry-run mode)
    if not dry_run:
        log.info("Running post-cleanup library health check...")
        report.post_check = run_health_check(jellyfin, path_exists_fn=path_exists_fn)

    return report


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def format_console_summary(report: CleanupReport) -> str:
    """Format a concise console summary of cleanup results."""
    lines: list[str] = []
    lines.append("Library Cleanup Results")
    lines.append(f"Cleaned at: {report.cleaned_at}")
    if report.dry_run:
        lines.append("Mode: DRY RUN (no changes made)")
    lines.append("")

    pre = report.pre_check
    if pre:
        lines.append(f"Pre-cleanup orphaned items: {len(pre.orphaned_items)}")
        lines.append(f"Pre-cleanup duplicate groups: {len(pre.duplicates)}")
    lines.append("")

    orphan_actions = report.orphan_actions
    dup_actions = report.duplicate_actions

    lines.append(f"Orphan removals attempted: {len(orphan_actions)}")
    lines.append(f"  Succeeded: {sum(1 for a in orphan_actions if a.success)}")
    lines.append(f"  Failed/Skipped: {sum(1 for a in orphan_actions if not a.success)}")
    lines.append("")

    lines.append(f"Duplicate removals attempted: {len(dup_actions)}")
    lines.append(f"  Succeeded: {sum(1 for a in dup_actions if a.success)}")
    lines.append(f"  Failed: {sum(1 for a in dup_actions if not a.success)}")
    lines.append("")

    if report.actions:
        lines.append("Details:")
        for a in report.actions:
            if a.dry_run:
                status = "WOULD REMOVE [DRY RUN]"
            elif a.success:
                status = "REMOVED"
            else:
                status = f"FAILED ({a.error})"
            lines.append(
                f"  [{a.media_type.upper()}] {a.jellyfin_title} "
                f"({a.reason}: {a.detail}) -> {status}"
            )
        lines.append("")

    post = report.post_check
    if post and not report.dry_run:
        lines.append(f"Post-cleanup orphaned items: {len(post.orphaned_items)}")
        lines.append(f"Post-cleanup duplicate groups: {len(post.duplicates)}")
        if pre:
            orphan_fixed = len(pre.orphaned_items) - len(post.orphaned_items)
            dup_fixed = len(pre.duplicates) - len(post.duplicates)
            lines.append(f"Improvement: {orphan_fixed} orphans removed, {dup_fixed} duplicate groups resolved")
        lines.append("")

    lines.append(
        f"Summary: {report.total_succeeded} of {report.total_attempted} "
        f"removals successful"
    )

    return "\n".join(lines)


def format_markdown_report(report: CleanupReport) -> str:
    """Generate a full markdown cleanup report."""
    lines: list[str] = []
    lines.append("# Library Cleanup Report")
    lines.append("")
    lines.append(f"**Cleaned at:** {report.cleaned_at}")
    if report.dry_run:
        lines.append("**Mode:** DRY RUN (no changes made)")
    lines.append("")

    # Pre-cleanup summary
    lines.append("## Pre-Cleanup Status")
    lines.append("")
    pre = report.pre_check
    if pre:
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| Orphaned items | {len(pre.orphaned_items)} |")
        lines.append(f"| Duplicate groups | {len(pre.duplicates)} ({pre.duplicate_item_count} items) |")
        lines.append("")

        if pre.orphaned_items:
            lines.append("### Orphaned Items Found")
            lines.append("")
            lines.append("| Type | Title | File Path |")
            lines.append("|------|-------|-----------|")
            for o in pre.orphaned_items:
                lines.append(f"| {o.media_type.upper()} | {o.jellyfin_title} | `{o.file_path}` |")
            lines.append("")

        if pre.duplicates:
            lines.append("### Duplicate Groups Found")
            lines.append("")
            lines.append("| Type | Provider ID | Count | Titles |")
            lines.append("|------|-------------|-------|--------|")
            for g in pre.duplicates:
                names = ", ".join(it["Name"] for it in g.items)
                lines.append(
                    f"| {g.media_type.upper()} | {g.provider}:{g.provider_id} "
                    f"| {g.count} | {names} |"
                )
            lines.append("")
    else:
        lines.append("No pre-cleanup check was performed.")
        lines.append("")

    # Cleanup actions
    lines.append("## Cleanup Actions")
    lines.append("")

    if not report.actions:
        lines.append("No cleanup actions were needed.")
        lines.append("")
    else:
        lines.append("| # | Type | Title | Reason | Detail | Result |")
        lines.append("|---|------|-------|--------|--------|--------|")
        for i, a in enumerate(report.actions, 1):
            if a.dry_run:
                result = "WOULD REMOVE"
            elif a.success:
                result = "REMOVED"
            else:
                result = f"FAILED: {a.error}"
            lines.append(
                f"| {i} | {a.media_type.upper()} | {a.jellyfin_title} "
                f"| {a.reason} | {a.detail} | {result} |"
            )
        lines.append("")

    # Summary table
    orphan_actions = report.orphan_actions
    dup_actions = report.duplicate_actions

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Orphan removals attempted | {len(orphan_actions)} |")
    lines.append(f"| Orphan removals succeeded | {sum(1 for a in orphan_actions if a.success)} |")
    lines.append(f"| Duplicate removals attempted | {len(dup_actions)} |")
    lines.append(f"| Duplicate removals succeeded | {sum(1 for a in dup_actions if a.success)} |")
    lines.append(f"| **Total attempted** | **{report.total_attempted}** |")
    lines.append(f"| **Total succeeded** | **{report.total_succeeded}** |")
    lines.append(f"| **Total failed** | **{report.total_failed}** |")
    lines.append("")

    # Post-cleanup verification
    if report.post_check and not report.dry_run:
        lines.append("## Post-Cleanup Verification")
        lines.append("")
        post = report.post_check
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| Orphaned items remaining | {len(post.orphaned_items)} |")
        lines.append(f"| Duplicate groups remaining | {len(post.duplicates)} |")
        lines.append("")

        if pre:
            orphan_before = len(pre.orphaned_items)
            orphan_after = len(post.orphaned_items)
            dup_before = len(pre.duplicates)
            dup_after = len(post.duplicates)
            lines.append(f"- Orphans: {orphan_before} -> {orphan_after} "
                          f"(**{orphan_before - orphan_after}** removed)")
            lines.append(f"- Duplicate groups: {dup_before} -> {dup_after} "
                          f"(**{dup_before - dup_after}** resolved)")
            lines.append("")
    elif report.dry_run:
        lines.append("## Post-Cleanup Verification")
        lines.append("")
        lines.append("*Skipped — dry run mode, no changes were made.*")
        lines.append("")

    lines.append(
        f"**Result: {report.total_succeeded} of {report.total_attempted} "
        f"removals successful**"
    )
    lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up orphaned and duplicate Jellyfin library entries"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be removed without making changes",
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

    report = run_cleanup(jellyfin, dry_run=args.dry_run)

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
    report_path = Path(report_dir) / "fix-library.md"
    report_path.write_text(format_markdown_report(report))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
