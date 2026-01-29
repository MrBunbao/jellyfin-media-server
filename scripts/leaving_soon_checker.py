#!/usr/bin/env python3
"""Janitorr Leaving Soon consistency checker for YAMS.

Validates that the Jellyfin "Leaving Soon" collections only contain items
actually scheduled for deletion by Janitorr, and that all items scheduled
for deletion appear in the collections.

Cross-references:
- Jellyfin "Leaving Soon" collections (TV and movies)
- Sonarr series tags (janitorr-leaving-soon)
- Radarr movie tags (janitorr-leaving-soon)
- Janitorr configuration (leaving-soon window, exclusion tags)

Usage:
  python scripts/leaving_soon_checker.py [--report-dir /path/to/reports]
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Allow imports from the yams root so the tests package is accessible
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.jellyfin_client import JellyfinClient
from tests.sonarr_client import SonarrClient
from tests.radarr_client import RadarrClient


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class FalsePositive:
    """An item in Leaving Soon that is NOT scheduled for deletion."""
    title: str
    jellyfin_id: str
    media_type: str          # "tv" or "movie"
    reason: str              # why it's a false positive


@dataclass
class MissingItem:
    """An item scheduled for deletion that is NOT in Leaving Soon."""
    title: str
    arr_id: int
    media_type: str
    tag: str                 # the tag that marks it for deletion


@dataclass
class BrokenMetadata:
    """An item in Leaving Soon with broken or missing metadata."""
    title: str
    jellyfin_id: str
    media_type: str
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class LeavingSoonReport:
    """Aggregated Leaving Soon consistency results."""
    false_positives: list[FalsePositive] = field(default_factory=list)
    missing_items: list[MissingItem] = field(default_factory=list)
    broken_metadata: list[BrokenMetadata] = field(default_factory=list)
    leaving_soon_tv_count: int = 0
    leaving_soon_movie_count: int = 0
    scheduled_tv_count: int = 0
    scheduled_movie_count: int = 0
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    @property
    def total_issues(self) -> int:
        return (
            len(self.false_positives)
            + len(self.missing_items)
            + len(self.broken_metadata)
        )

    @property
    def false_positive_count(self) -> int:
        return len(self.false_positives)

    @property
    def missing_count(self) -> int:
        return len(self.missing_items)

    @property
    def broken_count(self) -> int:
        return len(self.broken_metadata)


# ------------------------------------------------------------------
# Janitorr config parsing
# ------------------------------------------------------------------

_LEAVING_SOON_TAG = "janitorr-leaving-soon"

_DURATION_RE = re.compile(r"(\d+)\s*d")


def parse_janitorr_config(config_path: str) -> dict:
    """Parse Janitorr application.yml and extract relevant settings.

    Returns a dict with keys:
      - leaving_soon_tv: Jellyfin collection name for TV leaving soon
      - leaving_soon_movies: Jellyfin collection name for movies leaving soon
      - exclusion_tags: list of tag names that prevent deletion
      - leaving_soon_days: number of days in the leaving-soon window
    """
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    clients = cfg.get("clients", {})
    jf_cfg = clients.get("jellyfin", {})
    app_cfg = cfg.get("application", {})

    leaving_soon_raw = app_cfg.get("leaving-soon", "14d")
    match = _DURATION_RE.search(str(leaving_soon_raw))
    days = int(match.group(1)) if match else 14

    return {
        "leaving_soon_tv": jf_cfg.get("leaving-soon-tv", "Shows (Leaving Soon)"),
        "leaving_soon_movies": jf_cfg.get(
            "leaving-soon-movies", "Movies (Leaving Soon)"
        ),
        "exclusion_tags": app_cfg.get("exclusion-tags", []),
        "leaving_soon_days": days,
    }


# ------------------------------------------------------------------
# Detection logic
# ------------------------------------------------------------------

def _normalise(title: str) -> str:
    """Normalise a title for comparison (lowercase, strip whitespace)."""
    return title.strip().lower()


def find_false_positives(
    leaving_soon_items: list[dict],
    scheduled_titles: set[str],
    media_type: str,
) -> list[FalsePositive]:
    """Find items in Leaving Soon that are NOT scheduled for deletion.

    Args:
        leaving_soon_items: Jellyfin items from the Leaving Soon collection.
        scheduled_titles: Normalised titles of items tagged for deletion
                          in Sonarr/Radarr.
        media_type: "tv" or "movie".
    """
    results: list[FalsePositive] = []
    for item in leaving_soon_items:
        title = item.get("Name", "")
        if _normalise(title) not in scheduled_titles:
            results.append(FalsePositive(
                title=title,
                jellyfin_id=item.get("Id", ""),
                media_type=media_type,
                reason="Not tagged for deletion in Sonarr/Radarr",
            ))
    return results


def find_missing_from_collection(
    leaving_soon_titles: set[str],
    scheduled_items: list[dict],
    media_type: str,
    tag_name: str,
) -> list[MissingItem]:
    """Find items scheduled for deletion that are NOT in Leaving Soon.

    Args:
        leaving_soon_titles: Normalised titles from the Leaving Soon collection.
        scheduled_items: Sonarr/Radarr items tagged for deletion.
        media_type: "tv" or "movie".
        tag_name: The tag marking the item for deletion.
    """
    results: list[MissingItem] = []
    for item in scheduled_items:
        title = item.get("title", "")
        if _normalise(title) not in leaving_soon_titles:
            results.append(MissingItem(
                title=title,
                arr_id=item.get("id", 0),
                media_type=media_type,
                tag=tag_name,
            ))
    return results


def find_broken_metadata(
    leaving_soon_items: list[dict],
    media_type: str,
) -> list[BrokenMetadata]:
    """Find items in Leaving Soon with broken or missing metadata.

    Flags items where:
    - Title is empty or "Unknown"
    - Overview/description is missing
    - No primary image (poster) is present
    - No provider IDs (TVDB/TMDB) are present
    """
    _unknown_titles = frozenset({"unknown", "unknown series", "unknown movie", ""})
    results: list[BrokenMetadata] = []
    for item in leaving_soon_items:
        missing: list[str] = []
        title = item.get("Name", "")
        if title.strip().lower() in _unknown_titles:
            missing.append("title")
        if not (item.get("Overview") or "").strip():
            missing.append("description")
        if not item.get("ImageTags", {}).get("Primary"):
            missing.append("poster")
        provider_ids = item.get("ProviderIds") or {}
        if not provider_ids:
            missing.append("provider_ids")
        if missing:
            results.append(BrokenMetadata(
                title=title or "(empty)",
                jellyfin_id=item.get("Id", ""),
                media_type=media_type,
                missing_fields=missing,
            ))
    return results


# ------------------------------------------------------------------
# Arr tag helpers
# ------------------------------------------------------------------

def get_tagged_series(
    sonarr: SonarrClient,
    tag_name: str = _LEAVING_SOON_TAG,
) -> list[dict]:
    """Return Sonarr series that have the leaving-soon tag."""
    all_series = sonarr.get_series()
    tags = _get_sonarr_tags(sonarr)
    tag_id = tags.get(tag_name.lower())
    if tag_id is None:
        return []
    return [s for s in all_series if tag_id in (s.get("tags") or [])]


def get_tagged_movies(
    radarr: RadarrClient,
    tag_name: str = _LEAVING_SOON_TAG,
) -> list[dict]:
    """Return Radarr movies that have the leaving-soon tag."""
    all_movies = radarr.get_movies()
    tags = _get_radarr_tags(radarr)
    tag_id = tags.get(tag_name.lower())
    if tag_id is None:
        return []
    return [m for m in all_movies if tag_id in (m.get("tags") or [])]


def _get_sonarr_tags(sonarr: SonarrClient) -> dict[str, int]:
    """Fetch Sonarr tags and return {lowercase_label: id} mapping."""
    resp = sonarr.session.get(f"{sonarr.url}/api/v3/tag")
    resp.raise_for_status()
    return {t["label"].lower(): t["id"] for t in resp.json()}


def _get_radarr_tags(radarr: RadarrClient) -> dict[str, int]:
    """Fetch Radarr tags and return {lowercase_label: id} mapping."""
    resp = radarr.session.get(f"{radarr.url}/api/v3/tag")
    resp.raise_for_status()
    return {t["label"].lower(): t["id"] for t in resp.json()}


# ------------------------------------------------------------------
# Jellyfin collection helpers
# ------------------------------------------------------------------

def get_collection_items(
    jellyfin: JellyfinClient,
    collection_name: str,
) -> list[dict]:
    """Get all items from a named Jellyfin collection (boxset).

    Searches for the collection by name, then returns its child items
    with relevant metadata fields.
    """
    # Search for the collection by name
    result = jellyfin.get_items(
        IncludeItemTypes="BoxSet",
        Recursive="true",
        SearchTerm=collection_name,
    )
    items = result.get("Items", [])

    # Find exact match
    collection = None
    for item in items:
        if _normalise(item.get("Name", "")) == _normalise(collection_name):
            collection = item
            break

    if collection is None:
        return []

    # Get items within the collection
    fields = "ProviderIds,ProductionYear,Overview,ImageTags"
    child_result = jellyfin.get_items(
        parent_id=collection["Id"],
        Recursive="true",
        Fields=fields,
    )
    return child_result.get("Items", [])


# ------------------------------------------------------------------
# Main check orchestration
# ------------------------------------------------------------------

def run_check(
    jellyfin: JellyfinClient,
    sonarr: SonarrClient,
    radarr: RadarrClient,
    janitorr_config: dict,
) -> LeavingSoonReport:
    """Execute the full Leaving Soon consistency check and return a report."""
    report = LeavingSoonReport()

    tv_collection_name = janitorr_config["leaving_soon_tv"]
    movie_collection_name = janitorr_config["leaving_soon_movies"]

    # Fetch Leaving Soon collections from Jellyfin
    ls_tv_items = get_collection_items(jellyfin, tv_collection_name)
    ls_movie_items = get_collection_items(jellyfin, movie_collection_name)
    report.leaving_soon_tv_count = len(ls_tv_items)
    report.leaving_soon_movie_count = len(ls_movie_items)

    # Fetch tagged items from Sonarr/Radarr
    tagged_series = get_tagged_series(sonarr)
    tagged_movies = get_tagged_movies(radarr)
    report.scheduled_tv_count = len(tagged_series)
    report.scheduled_movie_count = len(tagged_movies)

    # Build normalised title sets for cross-referencing
    scheduled_tv_titles = {_normalise(s.get("title", "")) for s in tagged_series}
    scheduled_movie_titles = {_normalise(m.get("title", "")) for m in tagged_movies}
    ls_tv_titles = {_normalise(i.get("Name", "")) for i in ls_tv_items}
    ls_movie_titles = {_normalise(i.get("Name", "")) for i in ls_movie_items}

    # False positives: in Leaving Soon but NOT scheduled for deletion
    report.false_positives.extend(
        find_false_positives(ls_tv_items, scheduled_tv_titles, "tv")
    )
    report.false_positives.extend(
        find_false_positives(ls_movie_items, scheduled_movie_titles, "movie")
    )

    # Missing: scheduled for deletion but NOT in Leaving Soon
    report.missing_items.extend(
        find_missing_from_collection(
            ls_tv_titles, tagged_series, "tv", _LEAVING_SOON_TAG
        )
    )
    report.missing_items.extend(
        find_missing_from_collection(
            ls_movie_titles, tagged_movies, "movie", _LEAVING_SOON_TAG
        )
    )

    # Broken metadata in Leaving Soon items
    report.broken_metadata.extend(find_broken_metadata(ls_tv_items, "tv"))
    report.broken_metadata.extend(find_broken_metadata(ls_movie_items, "movie"))

    return report


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def format_console_summary(report: LeavingSoonReport) -> str:
    """Format a concise console summary."""
    lines: list[str] = []
    lines.append("Leaving Soon Consistency Check")
    lines.append(f"Checked at: {report.checked_at}")
    lines.append("")
    lines.append("Collection counts:")
    lines.append(f"  Leaving Soon TV shows:  {report.leaving_soon_tv_count}")
    lines.append(f"  Leaving Soon movies:    {report.leaving_soon_movie_count}")
    lines.append(f"  Scheduled TV (tagged):  {report.scheduled_tv_count}")
    lines.append(f"  Scheduled movies (tagged): {report.scheduled_movie_count}")
    lines.append("")
    lines.append("Issues found:")
    lines.append(f"  False positives (in collection, not scheduled): {report.false_positive_count}")
    lines.append(f"  Missing from collection (scheduled, not shown): {report.missing_count}")
    lines.append(f"  Broken/missing metadata: {report.broken_count}")
    lines.append(f"  Total issues: {report.total_issues}")
    lines.append("")

    if report.false_positives:
        lines.append("False positives:")
        for fp in report.false_positives:
            lines.append(f"  [{fp.media_type.upper()}] {fp.title}")
            lines.append(f"    Reason: {fp.reason}")
        lines.append("")

    if report.missing_items:
        lines.append("Missing from collection:")
        for mi in report.missing_items:
            lines.append(f"  [{mi.media_type.upper()}] {mi.title}")
            lines.append(f"    Tag: {mi.tag}")
        lines.append("")

    if report.broken_metadata:
        lines.append("Broken/missing metadata:")
        for bm in report.broken_metadata:
            fields = ", ".join(bm.missing_fields)
            lines.append(f"  [{bm.media_type.upper()}] {bm.title} — missing: {fields}")
        lines.append("")

    if report.total_issues == 0:
        lines.append("Leaving Soon collections are consistent — no issues found!")

    return "\n".join(lines)


def format_markdown_report(report: LeavingSoonReport) -> str:
    """Generate a full markdown Leaving Soon consistency report."""
    lines: list[str] = []
    lines.append("# Leaving Soon Consistency Report")
    lines.append("")
    lines.append(f"**Checked at:** {report.checked_at}")
    lines.append("")

    # Collection counts
    lines.append("## Collection Counts")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| Leaving Soon TV shows | {report.leaving_soon_tv_count} |")
    lines.append(f"| Leaving Soon movies | {report.leaving_soon_movie_count} |")
    lines.append(f"| Scheduled TV (tagged in Sonarr) | {report.scheduled_tv_count} |")
    lines.append(f"| Scheduled movies (tagged in Radarr) | {report.scheduled_movie_count} |")
    lines.append("")

    # Issue summary
    lines.append("## Issue Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| False positives | {report.false_positive_count} |")
    lines.append(f"| Missing from collection | {report.missing_count} |")
    lines.append(f"| Broken/missing metadata | {report.broken_count} |")
    lines.append(f"| **Total issues** | **{report.total_issues}** |")
    lines.append("")

    # False positives
    if report.false_positives:
        lines.append("## False Positives")
        lines.append("")
        lines.append("Items in the Leaving Soon collection that are NOT scheduled for deletion.")
        lines.append("")
        lines.append("| Type | Title | Reason |")
        lines.append("|------|-------|--------|")
        for fp in report.false_positives:
            lines.append(f"| {fp.media_type.upper()} | {fp.title} | {fp.reason} |")
        lines.append("")

    # Missing items
    if report.missing_items:
        lines.append("## Missing from Collection")
        lines.append("")
        lines.append("Items scheduled for deletion that are NOT in the Leaving Soon collection.")
        lines.append("")
        lines.append("| Type | Title | Tag |")
        lines.append("|------|-------|-----|")
        for mi in report.missing_items:
            lines.append(f"| {mi.media_type.upper()} | {mi.title} | {mi.tag} |")
        lines.append("")

    # Broken metadata
    if report.broken_metadata:
        lines.append("## Broken/Missing Metadata")
        lines.append("")
        lines.append("Items in the Leaving Soon collection with incomplete metadata.")
        lines.append("")
        lines.append("| Type | Title | Missing Fields |")
        lines.append("|------|-------|----------------|")
        for bm in report.broken_metadata:
            fields = ", ".join(bm.missing_fields)
            lines.append(f"| {bm.media_type.upper()} | {bm.title} | {fields} |")
        lines.append("")

    if report.total_issues == 0:
        lines.append("## Result")
        lines.append("")
        lines.append("Leaving Soon collections are consistent — no issues found!")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Janitorr Leaving Soon consistency checker"
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

    report = run_check(jellyfin, sonarr, radarr, janitorr_config)

    # Console summary
    print(format_console_summary(report))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(
            Path(__file__).resolve().parent.parent / "tests" / "reports"
        )

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "leaving-soon.md"
    report_path.write_text(format_markdown_report(report))
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
