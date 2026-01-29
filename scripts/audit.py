#!/usr/bin/env python3
"""Full YAMS health audit — runs all scanners and produces a combined report.

Orchestrates:
  - US-002: Naming compliance scanner
  - US-003: Metadata accuracy checker
  - US-004: Library health checker
  - US-005: Leaving Soon consistency checker

Usage:
  python3 /volume4/docker-v4/yams/scripts/audit.py
  python3 scripts/audit.py [--report-dir /path/to/reports]
"""

import argparse
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the yams root so the tests/scripts packages are accessible
_YAMS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_YAMS_ROOT))

from scripts.naming_scanner import scan_directory, ScanReport
from scripts.metadata_checker import (
    run_check as run_metadata_check,
    MetadataReport,
)
from scripts.library_health_checker import (
    run_health_check,
    HealthReport,
)
from scripts.leaving_soon_checker import (
    run_check as run_leaving_soon_check,
    parse_janitorr_config,
    LeavingSoonReport,
)
from tests.jellyfin_client import JellyfinClient
from tests.sonarr_client import SonarrClient
from tests.radarr_client import RadarrClient

# Default media root for the naming scanner
DEFAULT_MEDIA_ROOT = "/volume4/mediaserver/media"

# Default Janitorr config
DEFAULT_JANITORR_CONFIG = str(_YAMS_ROOT / "config" / "janitorr" / "application.yml")


# ------------------------------------------------------------------
# Aggregate data structure
# ------------------------------------------------------------------

@dataclass
class AuditResult:
    """Combined results from all four scanners."""

    naming: ScanReport | None = None
    metadata: MetadataReport | None = None
    health: HealthReport | None = None
    leaving_soon: LeavingSoonReport | None = None

    errors: dict[str, str] = field(default_factory=dict)

    audited_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    # -- Aggregate counts ------------------------------------------------

    @property
    def files_scanned(self) -> int:
        return self.naming.total if self.naming else 0

    @property
    def naming_issues(self) -> int:
        return len(self.naming.non_compliant) if self.naming else 0

    @property
    def mismatches_found(self) -> int:
        return len(self.metadata.mismatches) if self.metadata else 0

    @property
    def metadata_orphans(self) -> int:
        return len(self.metadata.orphaned) if self.metadata else 0

    @property
    def metadata_missing(self) -> int:
        return len(self.metadata.missing) if self.metadata else 0

    @property
    def health_orphans(self) -> int:
        return len(self.health.orphaned_items) if self.health else 0

    @property
    def duplicates(self) -> int:
        return len(self.health.duplicates) if self.health else 0

    @property
    def duplicate_items(self) -> int:
        return self.health.duplicate_item_count if self.health else 0

    @property
    def unknown_metadata(self) -> int:
        return len(self.health.unknown_items) if self.health else 0

    @property
    def placeholder_posters(self) -> int:
        return len(self.health.placeholder_posters) if self.health else 0

    @property
    def false_positives(self) -> int:
        return len(self.leaving_soon.false_positives) if self.leaving_soon else 0

    @property
    def leaving_soon_missing(self) -> int:
        return len(self.leaving_soon.missing_items) if self.leaving_soon else 0

    @property
    def leaving_soon_broken(self) -> int:
        return len(self.leaving_soon.broken_metadata) if self.leaving_soon else 0

    @property
    def total_issues(self) -> int:
        total = 0
        if self.naming:
            total += self.naming_issues
        if self.metadata:
            total += self.metadata.total_issues
        if self.health:
            total += self.health.total_issues
        if self.leaving_soon:
            total += self.leaving_soon.total_issues
        return total

    @property
    def has_issues(self) -> bool:
        return self.total_issues > 0 or bool(self.errors)


# ------------------------------------------------------------------
# Scanner execution
# ------------------------------------------------------------------

def run_all_scanners(
    media_root: str = DEFAULT_MEDIA_ROOT,
    janitorr_config_path: str = DEFAULT_JANITORR_CONFIG,
) -> AuditResult:
    """Run all four scanners and collect results."""
    result = AuditResult()

    # US-002: Naming compliance
    try:
        result.naming = scan_directory(media_root)
    except Exception:
        result.errors["naming"] = traceback.format_exc()

    # Shared API clients for US-003, US-004, US-005
    try:
        jellyfin = JellyfinClient()
        sonarr = SonarrClient()
        radarr = RadarrClient()
    except Exception:
        result.errors["clients"] = traceback.format_exc()
        return result

    # US-003: Metadata accuracy
    try:
        result.metadata = run_metadata_check(jellyfin, sonarr, radarr)
    except Exception:
        result.errors["metadata"] = traceback.format_exc()

    # US-004: Library health
    try:
        result.health = run_health_check(jellyfin)
    except Exception:
        result.errors["health"] = traceback.format_exc()

    # US-005: Leaving Soon consistency
    try:
        janitorr_cfg = parse_janitorr_config(janitorr_config_path)
        result.leaving_soon = run_leaving_soon_check(
            jellyfin, sonarr, radarr, janitorr_cfg
        )
    except Exception:
        result.errors["leaving_soon"] = traceback.format_exc()

    return result


# ------------------------------------------------------------------
# Console output
# ------------------------------------------------------------------

_DIVIDER = "=" * 72

def format_console_output(result: AuditResult) -> str:
    """Format the combined console output with section headers."""
    lines: list[str] = []

    lines.append(_DIVIDER)
    lines.append("  YAMS Full Audit")
    lines.append(f"  {result.audited_at}")
    lines.append(_DIVIDER)
    lines.append("")

    # -- Section 1: Naming Compliance ------------------------------------
    lines.append("-" * 40)
    lines.append("1. Naming Compliance (US-002)")
    lines.append("-" * 40)
    if result.naming:
        r = result.naming
        lines.append(f"  Files scanned:    {r.total}")
        lines.append(f"  Compliant:        {r.compliant_count} ({r.compliance_pct:.1f}%)")
        lines.append(f"  Non-compliant:    {len(r.non_compliant)}")
    elif "naming" in result.errors:
        lines.append(f"  ERROR: {_first_line(result.errors['naming'])}")
    lines.append("")

    # -- Section 2: Metadata Accuracy ------------------------------------
    lines.append("-" * 40)
    lines.append("2. Metadata Accuracy (US-003)")
    lines.append("-" * 40)
    if result.metadata:
        r = result.metadata
        lines.append(f"  Mismatches:       {len(r.mismatches)}")
        lines.append(f"  Orphaned:         {len(r.orphaned)}")
        lines.append(f"  Missing:          {len(r.missing)}")
        lines.append(f"  Total issues:     {r.total_issues}")
    elif "metadata" in result.errors:
        lines.append(f"  ERROR: {_first_line(result.errors['metadata'])}")
    elif "clients" in result.errors:
        lines.append("  SKIPPED: API client initialisation failed")
    lines.append("")

    # -- Section 3: Library Health ---------------------------------------
    lines.append("-" * 40)
    lines.append("3. Library Health (US-004)")
    lines.append("-" * 40)
    if result.health:
        r = result.health
        lines.append(f"  Items checked:    {r.total_items}")
        lines.append(f"  Unknown metadata: {len(r.unknown_items)}")
        lines.append(f"  Duplicates:       {len(r.duplicates)} groups ({r.duplicate_item_count} items)")
        lines.append(f"  Orphaned paths:   {len(r.orphaned_items)}")
        lines.append(f"  Missing posters:  {len(r.placeholder_posters)}")
        lines.append(f"  Total issues:     {r.total_issues}")
    elif "health" in result.errors:
        lines.append(f"  ERROR: {_first_line(result.errors['health'])}")
    elif "clients" in result.errors:
        lines.append("  SKIPPED: API client initialisation failed")
    lines.append("")

    # -- Section 4: Leaving Soon -----------------------------------------
    lines.append("-" * 40)
    lines.append("4. Leaving Soon Consistency (US-005)")
    lines.append("-" * 40)
    if result.leaving_soon:
        r = result.leaving_soon
        lines.append(f"  False positives:  {r.false_positive_count}")
        lines.append(f"  Missing from collection: {r.missing_count}")
        lines.append(f"  Broken metadata:  {r.broken_count}")
        lines.append(f"  Total issues:     {r.total_issues}")
    elif "leaving_soon" in result.errors:
        lines.append(f"  ERROR: {_first_line(result.errors['leaving_soon'])}")
    elif "clients" in result.errors:
        lines.append("  SKIPPED: API client initialisation failed")
    lines.append("")

    # -- Summary ---------------------------------------------------------
    lines.append(_DIVIDER)
    lines.append("  Summary")
    lines.append(_DIVIDER)
    lines.append(f"  Files scanned:       {result.files_scanned}")
    lines.append(f"  Total issues:        {result.total_issues}")
    lines.append(f"  Scanner errors:      {len(result.errors)}")
    lines.append("")
    if result.has_issues:
        lines.append("  Status: ISSUES FOUND")
    else:
        lines.append("  Status: ALL CLEAR")
    lines.append(_DIVIDER)

    return "\n".join(lines)


def _first_line(text: str) -> str:
    """Extract the last line of a traceback (the actual exception message)."""
    stripped = text.strip()
    if stripped:
        return stripped.splitlines()[-1]
    return "(unknown error)"


# ------------------------------------------------------------------
# Markdown report
# ------------------------------------------------------------------

def format_markdown_report(result: AuditResult) -> str:
    """Generate the combined markdown audit report."""
    lines: list[str] = []

    lines.append("# YAMS Full Audit Report")
    lines.append("")
    lines.append(f"**Audited at:** {result.audited_at}")
    lines.append("")

    # -- Total Counts ---------------------------------------------------
    lines.append("## Total Counts")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Files scanned (naming) | {result.files_scanned} |")
    lines.append(f"| Naming non-compliant | {result.naming_issues} |")
    lines.append(f"| Metadata mismatches | {result.mismatches_found} |")
    lines.append(f"| Metadata orphans (in Jellyfin, not in Arr) | {result.metadata_orphans} |")
    lines.append(f"| Metadata missing (in Arr, not in Jellyfin) | {result.metadata_missing} |")
    lines.append(f"| Library unknown/missing metadata | {result.unknown_metadata} |")
    lines.append(f"| Library duplicates | {result.duplicates} groups ({result.duplicate_items} items) |")
    lines.append(f"| Library orphaned file paths | {result.health_orphans} |")
    lines.append(f"| Library placeholder posters | {result.placeholder_posters} |")
    lines.append(f"| Leaving Soon false positives | {result.false_positives} |")
    lines.append(f"| Leaving Soon missing from collection | {result.leaving_soon_missing} |")
    lines.append(f"| Leaving Soon broken metadata | {result.leaving_soon_broken} |")
    lines.append(f"| **Total issues** | **{result.total_issues}** |")
    lines.append(f"| Scanner errors | {len(result.errors)} |")
    lines.append("")

    # -- Prioritized Action List ----------------------------------------
    lines.append("## Prioritized Action List")
    lines.append("")
    lines.append("Issues ordered by impact — fix the highest-priority items first.")
    lines.append("")

    actions = _build_prioritized_actions(result)
    if actions:
        lines.append("| Priority | Category | Count | Action |")
        lines.append("|----------|----------|-------|--------|")
        for i, (category, count, action) in enumerate(actions, 1):
            lines.append(f"| {i} | {category} | {count} | {action} |")
        lines.append("")
    else:
        lines.append("No issues found — nothing to fix!")
        lines.append("")

    # -- Scanner errors -------------------------------------------------
    if result.errors:
        lines.append("## Scanner Errors")
        lines.append("")
        lines.append("The following scanners encountered errors:")
        lines.append("")
        for scanner, tb in result.errors.items():
            lines.append(f"### {scanner}")
            lines.append("")
            lines.append("```")
            lines.append(tb.strip())
            lines.append("```")
            lines.append("")

    # -- Section: Naming Compliance -------------------------------------
    lines.append("## 1. Naming Compliance")
    lines.append("")
    if result.naming:
        r = result.naming
        lines.append(f"**Media root:** `{r.media_root}`")
        lines.append(f"**Files scanned:** {r.total}")
        lines.append(f"**Compliant:** {r.compliant_count} ({r.compliance_pct:.1f}%)")
        lines.append(f"**Non-compliant:** {len(r.non_compliant)}")
        lines.append("")
        if r.non_compliant:
            lines.append("| Type | File | Expected Pattern |")
            lines.append("|------|------|------------------|")
            for f in r.non_compliant:
                lines.append(f"| {f.media_type.upper()} | `{f.filename}` | `{f.expected_pattern}` |")
            lines.append("")
    else:
        lines.append(_scanner_error_md("naming", result))

    # -- Section: Metadata Accuracy -------------------------------------
    lines.append("## 2. Metadata Accuracy")
    lines.append("")
    if result.metadata:
        r = result.metadata
        lines.append("| Source | Count |")
        lines.append("|--------|-------|")
        lines.append(f"| Jellyfin TV | {r.jellyfin_tv_count} |")
        lines.append(f"| Jellyfin Movies | {r.jellyfin_movie_count} |")
        lines.append(f"| Sonarr | {r.sonarr_count} |")
        lines.append(f"| Radarr | {r.radarr_count} |")
        lines.append("")
        lines.append(f"**Mismatches:** {len(r.mismatches)}  ")
        lines.append(f"**Orphaned:** {len(r.orphaned)}  ")
        lines.append(f"**Missing:** {len(r.missing)}")
        lines.append("")
        if r.mismatches:
            lines.append("### Mismatches")
            lines.append("")
            lines.append("| Type | Title | Field | Jellyfin | Arr |")
            lines.append("|------|-------|-------|----------|-----|")
            for m in r.mismatches:
                lines.append(
                    f"| {m.media_type.upper()} | {m.jellyfin_title} "
                    f"| {m.field} | {m.jellyfin_value} | {m.arr_value} |"
                )
            lines.append("")
        if r.orphaned:
            lines.append("### Orphaned in Jellyfin")
            lines.append("")
            lines.append("| Type | Title | Year |")
            lines.append("|------|-------|------|")
            for o in r.orphaned:
                year = str(o.jellyfin_year) if o.jellyfin_year else "—"
                lines.append(f"| {o.media_type.upper()} | {o.jellyfin_title} | {year} |")
            lines.append("")
        if r.missing:
            lines.append("### Missing from Jellyfin")
            lines.append("")
            lines.append("| Type | Title | Year | External ID |")
            lines.append("|------|-------|------|-------------|")
            for m in r.missing:
                year = str(m.arr_year) if m.arr_year else "—"
                lines.append(f"| {m.media_type.upper()} | {m.arr_title} | {year} | {m.external_id} |")
            lines.append("")
    else:
        lines.append(_scanner_error_md("metadata", result))

    # -- Section: Library Health -----------------------------------------
    lines.append("## 3. Library Health")
    lines.append("")
    if result.health:
        r = result.health
        lines.append(f"**Items checked:** {r.total_items}")
        lines.append(f"**Total issues:** {r.total_issues}")
        lines.append("")
        if r.unknown_items:
            lines.append("### Unknown / Missing Metadata")
            lines.append("")
            lines.append("| Type | Title | Missing Fields |")
            lines.append("|------|-------|----------------|")
            for u in r.unknown_items:
                fields = ", ".join(u.missing_fields)
                lines.append(f"| {u.media_type.upper()} | {u.jellyfin_title} | {fields} |")
            lines.append("")
        if r.duplicates:
            lines.append("### Duplicates")
            lines.append("")
            lines.append("| Type | Provider ID | Count | Titles |")
            lines.append("|------|-------------|-------|--------|")
            for g in r.duplicates:
                names = ", ".join(it["Name"] for it in g.items)
                lines.append(
                    f"| {g.media_type.upper()} | {g.provider}:{g.provider_id} "
                    f"| {g.count} | {names} |"
                )
            lines.append("")
        if r.orphaned_items:
            lines.append("### Orphaned File Paths")
            lines.append("")
            lines.append("| Type | Title | Path |")
            lines.append("|------|-------|------|")
            for o in r.orphaned_items:
                lines.append(f"| {o.media_type.upper()} | {o.jellyfin_title} | `{o.file_path}` |")
            lines.append("")
        if r.placeholder_posters:
            lines.append("### Placeholder Posters")
            lines.append("")
            lines.append("| Type | Title |")
            lines.append("|------|-------|")
            for p in r.placeholder_posters:
                lines.append(f"| {p.media_type.upper()} | {p.jellyfin_title} |")
            lines.append("")
    else:
        lines.append(_scanner_error_md("health", result))

    # -- Section: Leaving Soon -------------------------------------------
    lines.append("## 4. Leaving Soon Consistency")
    lines.append("")
    if result.leaving_soon:
        r = result.leaving_soon
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| Leaving Soon TV | {r.leaving_soon_tv_count} |")
        lines.append(f"| Leaving Soon Movies | {r.leaving_soon_movie_count} |")
        lines.append(f"| Scheduled TV | {r.scheduled_tv_count} |")
        lines.append(f"| Scheduled Movies | {r.scheduled_movie_count} |")
        lines.append("")
        lines.append(f"**False positives:** {r.false_positive_count}  ")
        lines.append(f"**Missing from collection:** {r.missing_count}  ")
        lines.append(f"**Broken metadata:** {r.broken_count}")
        lines.append("")
        if r.false_positives:
            lines.append("### False Positives")
            lines.append("")
            lines.append("| Type | Title | Reason |")
            lines.append("|------|-------|--------|")
            for fp in r.false_positives:
                lines.append(f"| {fp.media_type.upper()} | {fp.title} | {fp.reason} |")
            lines.append("")
        if r.missing_items:
            lines.append("### Missing from Collection")
            lines.append("")
            lines.append("| Type | Title | Tag |")
            lines.append("|------|-------|-----|")
            for mi in r.missing_items:
                lines.append(f"| {mi.media_type.upper()} | {mi.title} | {mi.tag} |")
            lines.append("")
        if r.broken_metadata:
            lines.append("### Broken Metadata")
            lines.append("")
            lines.append("| Type | Title | Missing Fields |")
            lines.append("|------|-------|----------------|")
            for bm in r.broken_metadata:
                fields = ", ".join(bm.missing_fields)
                lines.append(f"| {bm.media_type.upper()} | {bm.title} | {fields} |")
            lines.append("")
    else:
        lines.append(_scanner_error_md("leaving_soon", result))

    return "\n".join(lines)


def _scanner_error_md(scanner_key: str, result: AuditResult) -> str:
    """Return markdown for a scanner that failed or was skipped."""
    if scanner_key in result.errors:
        return f"**ERROR:** Scanner failed.\n\n```\n{result.errors[scanner_key].strip()}\n```\n"
    if "clients" in result.errors:
        return "*Skipped — API client initialisation failed.*\n"
    return "*No data collected.*\n"


def _build_prioritized_actions(
    result: AuditResult,
) -> list[tuple[str, int, str]]:
    """Build a prioritized list of (category, count, action) tuples.

    Priority order (most impactful first):
    1. Orphaned file paths — items point to missing files, causes playback errors
    2. Duplicate entries — confuses users, wastes storage
    3. Metadata mismatches — wrong titles/years visible to users
    4. Leaving Soon false positives — misleads users about expiring content
    5. Missing from Leaving Soon — users don't know content is expiring
    6. Orphaned in Jellyfin (metadata) — stale entries in library
    7. Missing from Jellyfin — content in Arr not surfaced to users
    8. Unknown / missing metadata — incomplete library presentation
    9. Placeholder posters — cosmetic, missing artwork
    10. Leaving Soon broken metadata — cosmetic for expiring items
    11. Naming non-compliant — file naming hygiene
    """
    actions: list[tuple[str, int, str]] = []

    if result.health_orphans > 0:
        actions.append((
            "Orphaned file paths",
            result.health_orphans,
            "Remove stale Jellyfin entries or restore missing media files",
        ))
    if result.duplicates > 0:
        actions.append((
            "Duplicate entries",
            result.duplicate_items,
            "Merge or remove duplicate library items sharing the same provider ID",
        ))
    if result.mismatches_found > 0:
        actions.append((
            "Metadata mismatches",
            result.mismatches_found,
            "Refresh metadata in Jellyfin or correct titles/years in Sonarr/Radarr",
        ))
    if result.false_positives > 0:
        actions.append((
            "Leaving Soon false positives",
            result.false_positives,
            "Remove items from Leaving Soon collection or tag them in Sonarr/Radarr",
        ))
    if result.leaving_soon_missing > 0:
        actions.append((
            "Missing from Leaving Soon",
            result.leaving_soon_missing,
            "Add scheduled items to the Leaving Soon collection in Jellyfin",
        ))
    if result.metadata_orphans > 0:
        actions.append((
            "Orphaned in Jellyfin",
            result.metadata_orphans,
            "Remove stale entries from Jellyfin or re-add to Sonarr/Radarr",
        ))
    if result.metadata_missing > 0:
        actions.append((
            "Missing from Jellyfin",
            result.metadata_missing,
            "Trigger a library scan in Jellyfin to pick up Sonarr/Radarr content",
        ))
    if result.unknown_metadata > 0:
        actions.append((
            "Unknown / missing metadata",
            result.unknown_metadata,
            "Identify and refresh metadata for items with missing titles/descriptions/posters",
        ))
    if result.placeholder_posters > 0:
        actions.append((
            "Placeholder posters",
            result.placeholder_posters,
            "Download missing poster artwork via metadata refresh",
        ))
    if result.leaving_soon_broken > 0:
        actions.append((
            "Leaving Soon broken metadata",
            result.leaving_soon_broken,
            "Fix metadata for items in Leaving Soon collections",
        ))
    if result.naming_issues > 0:
        actions.append((
            "Naming non-compliant",
            result.naming_issues,
            "Rename files to match TRaSH Guide conventions via Sonarr/Radarr rename",
        ))

    return actions


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="YAMS full health audit — runs all scanners and produces a combined report"
    )
    parser.add_argument(
        "--media-root",
        default=DEFAULT_MEDIA_ROOT,
        help=f"Path to the media root directory (default: {DEFAULT_MEDIA_ROOT})",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to save the markdown report",
    )
    parser.add_argument(
        "--janitorr-config",
        default=DEFAULT_JANITORR_CONFIG,
        help=f"Path to Janitorr application.yml (default: {DEFAULT_JANITORR_CONFIG})",
    )
    args = parser.parse_args()

    # Run all scanners
    result = run_all_scanners(
        media_root=args.media_root,
        janitorr_config_path=args.janitorr_config,
    )

    # Console output
    print(format_console_output(result))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(_YAMS_ROOT / "tests" / "reports")

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "full-audit.md"
    report_path.write_text(format_markdown_report(result))
    print(f"\nReport saved to {report_path}")

    # Exit code
    sys.exit(1 if result.has_issues else 0)


if __name__ == "__main__":
    main()
