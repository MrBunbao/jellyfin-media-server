#!/usr/bin/env python3
"""Jellyfin library health checker for YAMS.

Scans the Jellyfin library for:
- Items with no metadata (Unknown titles, missing poster/description)
- Duplicate entries (same TMDB/TVDB ID appearing multiple times)
- Orphaned entries (Jellyfin item points to a file path that no longer exists)
- Items with placeholder or default poster images

Usage:
  python scripts/library_health_checker.py [--report-dir /path/to/reports]
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the yams root so the tests package is accessible
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.jellyfin_client import JellyfinClient


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class UnknownItem:
    """An item with missing or placeholder metadata."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str          # "tv" or "movie"
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class DuplicateGroup:
    """A set of items sharing the same external ID."""
    provider: str            # "Tmdb" or "Tvdb"
    provider_id: str
    media_type: str
    items: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass
class OrphanedItem:
    """A Jellyfin item whose underlying file path no longer exists."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str
    file_path: str


@dataclass
class PlaceholderPosterItem:
    """An item using a placeholder or default poster image."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str
    has_primary_image: bool


@dataclass
class HealthReport:
    """Aggregated library health results."""
    unknown_items: list[UnknownItem] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    orphaned_items: list[OrphanedItem] = field(default_factory=list)
    placeholder_posters: list[PlaceholderPosterItem] = field(default_factory=list)
    total_tv_count: int = 0
    total_movie_count: int = 0
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    @property
    def total_items(self) -> int:
        return self.total_tv_count + self.total_movie_count

    @property
    def total_issues(self) -> int:
        return (
            len(self.unknown_items)
            + len(self.duplicates)
            + len(self.orphaned_items)
            + len(self.placeholder_posters)
        )

    @property
    def duplicate_item_count(self) -> int:
        """Total number of duplicate items (sum of items across all groups)."""
        return sum(g.count for g in self.duplicates)


# ------------------------------------------------------------------
# Detection logic
# ------------------------------------------------------------------

_UNKNOWN_TITLES = frozenset({"unknown", "unknown series", "unknown movie", ""})


def detect_unknown_items(items: list[dict], media_type: str) -> list[UnknownItem]:
    """Detect items with missing or placeholder metadata.

    An item is flagged when any of the following are true:
    - Title is "Unknown", blank, or a known placeholder
    - Overview (description) is missing or empty
    - No primary image tag (poster) is present
    """
    results: list[UnknownItem] = []
    for item in items:
        missing: list[str] = []
        title = item.get("Name", "")
        if title.strip().lower() in _UNKNOWN_TITLES:
            missing.append("title")
        if not (item.get("Overview") or "").strip():
            missing.append("description")
        if not item.get("ImageTags", {}).get("Primary"):
            missing.append("poster")
        if missing:
            results.append(UnknownItem(
                jellyfin_title=title or "(empty)",
                jellyfin_id=item.get("Id", ""),
                media_type=media_type,
                missing_fields=missing,
            ))
    return results


def detect_duplicates(items: list[dict], media_type: str) -> list[DuplicateGroup]:
    """Detect items sharing the same TMDB or TVDB provider ID.

    Only IDs that appear more than once are included.
    """
    provider = "Tvdb" if media_type == "tv" else "Tmdb"
    id_map: dict[str, list[dict]] = {}

    for item in items:
        pid = str((item.get("ProviderIds") or {}).get(provider, ""))
        if not pid:
            continue
        id_map.setdefault(pid, []).append(item)

    groups: list[DuplicateGroup] = []
    for pid, group_items in id_map.items():
        if len(group_items) > 1:
            groups.append(DuplicateGroup(
                provider=provider,
                provider_id=pid,
                media_type=media_type,
                items=[
                    {
                        "Name": it.get("Name", ""),
                        "Id": it.get("Id", ""),
                        "ProductionYear": it.get("ProductionYear"),
                    }
                    for it in group_items
                ],
            ))
    return groups


def detect_orphaned_items(
    items: list[dict],
    media_type: str,
    path_exists_fn=os.path.exists,
) -> list[OrphanedItem]:
    """Detect items whose underlying file no longer exists on disk.

    Uses the ``Path`` field from Jellyfin items. Items without a path are
    skipped (they may be virtual items like collections).
    """
    results: list[OrphanedItem] = []
    for item in items:
        file_path = item.get("Path", "")
        if not file_path:
            continue
        if not path_exists_fn(file_path):
            results.append(OrphanedItem(
                jellyfin_title=item.get("Name", ""),
                jellyfin_id=item.get("Id", ""),
                media_type=media_type,
                file_path=file_path,
            ))
    return results


def detect_placeholder_posters(
    items: list[dict],
    media_type: str,
) -> list[PlaceholderPosterItem]:
    """Detect items with placeholder or missing poster images.

    Flags items where:
    - No ``Primary`` image tag exists in ``ImageTags``
    - ``HasPrimaryImage`` is explicitly False (when available from API)
    """
    results: list[PlaceholderPosterItem] = []
    for item in items:
        image_tags = item.get("ImageTags") or {}
        has_primary = bool(image_tags.get("Primary"))
        # Also check the explicit boolean field when present
        if not has_primary or item.get("HasPrimaryImage") is False:
            results.append(PlaceholderPosterItem(
                jellyfin_title=item.get("Name", ""),
                jellyfin_id=item.get("Id", ""),
                media_type=media_type,
                has_primary_image=has_primary,
            ))
    return results


# ------------------------------------------------------------------
# Data fetching
# ------------------------------------------------------------------

def fetch_library_items(client: JellyfinClient) -> tuple[list[dict], list[dict]]:
    """Fetch TV shows and movies from Jellyfin with health-relevant fields.

    Returns (tv_shows, movies) as two separate lists.
    """
    tv_shows: list[dict] = []
    movies: list[dict] = []

    libraries = client.get_libraries()
    for lib in libraries:
        collection_type = (lib.get("CollectionType") or "").lower()
        lib_id = lib.get("ItemId", "")

        fields = "ProviderIds,ProductionYear,Overview,Path,ImageTags"

        if collection_type == "tvshows":
            items = client.get_items(
                parent_id=lib_id,
                IncludeItemTypes="Series",
                Recursive="true",
                Fields=fields,
            )
            tv_shows.extend(items.get("Items", []))

        elif collection_type == "movies":
            items = client.get_items(
                parent_id=lib_id,
                IncludeItemTypes="Movie",
                Recursive="true",
                Fields=fields,
            )
            movies.extend(items.get("Items", []))

    return tv_shows, movies


def run_health_check(
    jellyfin: JellyfinClient,
    path_exists_fn=os.path.exists,
) -> HealthReport:
    """Execute the full library health check and return a report."""
    report = HealthReport()

    tv_shows, movies = fetch_library_items(jellyfin)
    report.total_tv_count = len(tv_shows)
    report.total_movie_count = len(movies)

    # Unknown / missing metadata
    report.unknown_items.extend(detect_unknown_items(tv_shows, "tv"))
    report.unknown_items.extend(detect_unknown_items(movies, "movie"))

    # Duplicates
    report.duplicates.extend(detect_duplicates(tv_shows, "tv"))
    report.duplicates.extend(detect_duplicates(movies, "movie"))

    # Orphaned files
    report.orphaned_items.extend(
        detect_orphaned_items(tv_shows, "tv", path_exists_fn)
    )
    report.orphaned_items.extend(
        detect_orphaned_items(movies, "movie", path_exists_fn)
    )

    # Placeholder posters
    report.placeholder_posters.extend(detect_placeholder_posters(tv_shows, "tv"))
    report.placeholder_posters.extend(detect_placeholder_posters(movies, "movie"))

    return report


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def format_console_summary(report: HealthReport) -> str:
    """Format a concise console summary."""
    lines: list[str] = []
    lines.append("Library Health Check")
    lines.append(f"Checked at: {report.checked_at}")
    lines.append("")
    lines.append("Library counts:")
    lines.append(f"  TV shows:  {report.total_tv_count}")
    lines.append(f"  Movies:    {report.total_movie_count}")
    lines.append(f"  Total:     {report.total_items}")
    lines.append("")
    lines.append("Issues found:")
    lines.append(f"  Unknown / missing metadata: {len(report.unknown_items)}")
    lines.append(f"  Duplicate entries:          {len(report.duplicates)} groups ({report.duplicate_item_count} items)")
    lines.append(f"  Orphaned file paths:        {len(report.orphaned_items)}")
    lines.append(f"  Placeholder posters:        {len(report.placeholder_posters)}")
    lines.append(f"  Total issue categories:     {report.total_issues}")
    lines.append("")

    if report.unknown_items:
        lines.append("Unknown / missing metadata:")
        for u in report.unknown_items:
            fields = ", ".join(u.missing_fields)
            lines.append(f"  [{u.media_type.upper()}] {u.jellyfin_title} — missing: {fields}")
        lines.append("")

    if report.duplicates:
        lines.append("Duplicate entries:")
        for g in report.duplicates:
            names = ", ".join(it["Name"] for it in g.items)
            lines.append(
                f"  [{g.media_type.upper()}] {g.provider}:{g.provider_id} "
                f"({g.count} items: {names})"
            )
        lines.append("")

    if report.orphaned_items:
        lines.append("Orphaned file paths:")
        for o in report.orphaned_items:
            lines.append(f"  [{o.media_type.upper()}] {o.jellyfin_title} -> {o.file_path}")
        lines.append("")

    if report.placeholder_posters:
        lines.append("Placeholder posters:")
        for p in report.placeholder_posters:
            lines.append(f"  [{p.media_type.upper()}] {p.jellyfin_title}")
        lines.append("")

    if report.total_issues == 0:
        lines.append("Library is healthy — no issues found!")

    return "\n".join(lines)


def format_markdown_report(report: HealthReport) -> str:
    """Generate a full markdown library health report."""
    lines: list[str] = []
    lines.append("# Library Health Report")
    lines.append("")
    lines.append(f"**Checked at:** {report.checked_at}")
    lines.append("")

    # Library counts
    lines.append("## Library Counts")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| TV Shows | {report.total_tv_count} |")
    lines.append(f"| Movies | {report.total_movie_count} |")
    lines.append(f"| **Total** | **{report.total_items}** |")
    lines.append("")

    # Summary
    lines.append("## Issue Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| Unknown / missing metadata | {len(report.unknown_items)} |")
    lines.append(f"| Duplicate entries | {len(report.duplicates)} groups ({report.duplicate_item_count} items) |")
    lines.append(f"| Orphaned file paths | {len(report.orphaned_items)} |")
    lines.append(f"| Placeholder posters | {len(report.placeholder_posters)} |")
    lines.append(f"| **Total issue categories** | **{report.total_issues}** |")
    lines.append("")

    # Unknown items
    if report.unknown_items:
        lines.append("## Unknown / Missing Metadata")
        lines.append("")
        lines.append("Items with missing title, description, or poster.")
        lines.append("")
        lines.append("| Type | Title | Missing Fields |")
        lines.append("|------|-------|----------------|")
        for u in report.unknown_items:
            fields = ", ".join(u.missing_fields)
            lines.append(f"| {u.media_type.upper()} | {u.jellyfin_title} | {fields} |")
        lines.append("")

    # Duplicates
    if report.duplicates:
        lines.append("## Duplicate Entries")
        lines.append("")
        lines.append("Items sharing the same TMDB/TVDB ID.")
        lines.append("")
        lines.append("| Type | Provider ID | Count | Titles |")
        lines.append("|------|-------------|-------|--------|")
        for g in report.duplicates:
            names = ", ".join(it["Name"] for it in g.items)
            lines.append(
                f"| {g.media_type.upper()} | {g.provider}:{g.provider_id} "
                f"| {g.count} | {names} |"
            )
        lines.append("")

    # Orphaned items
    if report.orphaned_items:
        lines.append("## Orphaned File Paths")
        lines.append("")
        lines.append("Jellyfin items pointing to files that no longer exist on disk.")
        lines.append("")
        lines.append("| Type | Title | File Path |")
        lines.append("|------|-------|-----------|")
        for o in report.orphaned_items:
            lines.append(f"| {o.media_type.upper()} | {o.jellyfin_title} | `{o.file_path}` |")
        lines.append("")

    # Placeholder posters
    if report.placeholder_posters:
        lines.append("## Placeholder Posters")
        lines.append("")
        lines.append("Items with missing or default poster images.")
        lines.append("")
        lines.append("| Type | Title | Has Primary Image |")
        lines.append("|------|-------|-------------------|")
        for p in report.placeholder_posters:
            lines.append(f"| {p.media_type.upper()} | {p.jellyfin_title} | {p.has_primary_image} |")
        lines.append("")

    if report.total_issues == 0:
        lines.append("## Result")
        lines.append("")
        lines.append("Library is healthy — no issues found!")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Jellyfin library health checker"
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to save the markdown report",
    )
    args = parser.parse_args()

    jellyfin = JellyfinClient()
    report = run_health_check(jellyfin)

    # Console summary
    print(format_console_summary(report))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(
            Path(__file__).resolve().parent.parent / "tests" / "reports"
        )

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "library-health.md"
    report_path.write_text(format_markdown_report(report))
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
