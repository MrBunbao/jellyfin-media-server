#!/usr/bin/env python3
"""Jellyfin metadata accuracy checker for YAMS.

Compares Jellyfin library metadata against Sonarr (TV) and Radarr (movies)
to identify mismatches in titles, years, and external IDs, as well as
orphaned or missing items.

Usage:
  python scripts/metadata_checker.py [--report-dir /path/to/reports]
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
from tests.sonarr_client import SonarrClient
from tests.radarr_client import RadarrClient


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class Mismatch:
    """A single metadata discrepancy between Jellyfin and Sonarr/Radarr."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str          # "tv" or "movie"
    field: str               # "title", "year", or "external_id"
    jellyfin_value: str
    arr_value: str
    arr_title: str = ""


@dataclass
class OrphanedItem:
    """An item present in Jellyfin but not in Sonarr/Radarr."""
    jellyfin_title: str
    jellyfin_id: str
    media_type: str
    jellyfin_year: int | None = None


@dataclass
class MissingItem:
    """An item present in Sonarr/Radarr but not in Jellyfin."""
    arr_title: str
    arr_id: int
    media_type: str
    arr_year: int | None = None
    external_id: str = ""


@dataclass
class MetadataReport:
    """Aggregated metadata comparison results."""
    mismatches: list[Mismatch] = field(default_factory=list)
    orphaned: list[OrphanedItem] = field(default_factory=list)
    missing: list[MissingItem] = field(default_factory=list)
    jellyfin_tv_count: int = 0
    jellyfin_movie_count: int = 0
    sonarr_count: int = 0
    radarr_count: int = 0
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    @property
    def total_issues(self) -> int:
        return len(self.mismatches) + len(self.orphaned) + len(self.missing)


# ------------------------------------------------------------------
# Jellyfin item helpers
# ------------------------------------------------------------------

def _get_jellyfin_provider_id(item: dict, provider: str) -> str:
    """Extract a provider ID from a Jellyfin item's ProviderIds dict."""
    ids = item.get("ProviderIds") or {}
    return str(ids.get(provider, ""))


def _get_jellyfin_year(item: dict) -> int | None:
    """Extract production year from a Jellyfin item."""
    return item.get("ProductionYear")


# ------------------------------------------------------------------
# Comparison logic
# ------------------------------------------------------------------

def compare_tv_shows(
    jellyfin_shows: list[dict],
    sonarr_series: list[dict],
) -> tuple[list[Mismatch], list[OrphanedItem], list[MissingItem]]:
    """Compare Jellyfin TV shows against Sonarr series.

    Matching is done by TVDB ID when available, then falls back to
    normalised title matching.
    """
    mismatches: list[Mismatch] = []
    orphaned: list[OrphanedItem] = []
    missing: list[MissingItem] = []

    # Index Sonarr series by TVDB ID and normalised title
    sonarr_by_tvdb: dict[str, dict] = {}
    sonarr_by_title: dict[str, dict] = {}
    for s in sonarr_series:
        tvdb = str(s.get("tvdbId", ""))
        if tvdb:
            sonarr_by_tvdb[tvdb] = s
        sonarr_by_title[_normalise(s.get("title", ""))] = s

    matched_sonarr_ids: set[int] = set()

    for jf in jellyfin_shows:
        jf_title = jf.get("Name", "")
        jf_id = jf.get("Id", "")
        jf_tvdb = _get_jellyfin_provider_id(jf, "Tvdb")
        jf_year = _get_jellyfin_year(jf)

        # Try to find a matching Sonarr entry
        sonarr_entry = None
        if jf_tvdb and jf_tvdb in sonarr_by_tvdb:
            sonarr_entry = sonarr_by_tvdb[jf_tvdb]
        else:
            sonarr_entry = sonarr_by_title.get(_normalise(jf_title))

        if sonarr_entry is None:
            orphaned.append(OrphanedItem(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="tv",
                jellyfin_year=jf_year,
            ))
            continue

        matched_sonarr_ids.add(sonarr_entry.get("id", 0))

        # Compare title
        s_title = sonarr_entry.get("title", "")
        if _normalise(jf_title) != _normalise(s_title):
            mismatches.append(Mismatch(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="tv",
                field="title",
                jellyfin_value=jf_title,
                arr_value=s_title,
                arr_title=s_title,
            ))

        # Compare year
        s_year = sonarr_entry.get("year")
        if jf_year and s_year and jf_year != s_year:
            mismatches.append(Mismatch(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="tv",
                field="year",
                jellyfin_value=str(jf_year),
                arr_value=str(s_year),
                arr_title=s_title,
            ))

        # Check missing external ID
        s_tvdb = str(sonarr_entry.get("tvdbId", ""))
        if not jf_tvdb and s_tvdb:
            mismatches.append(Mismatch(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="tv",
                field="external_id",
                jellyfin_value="(none)",
                arr_value=f"tvdb:{s_tvdb}",
                arr_title=s_title,
            ))

    # Sonarr items not matched in Jellyfin
    for s in sonarr_series:
        if s.get("id", 0) not in matched_sonarr_ids:
            missing.append(MissingItem(
                arr_title=s.get("title", ""),
                arr_id=s.get("id", 0),
                media_type="tv",
                arr_year=s.get("year"),
                external_id=f"tvdb:{s.get('tvdbId', '')}",
            ))

    return mismatches, orphaned, missing


def compare_movies(
    jellyfin_movies: list[dict],
    radarr_movies: list[dict],
) -> tuple[list[Mismatch], list[OrphanedItem], list[MissingItem]]:
    """Compare Jellyfin movies against Radarr movies.

    Matching is done by TMDB ID when available, then falls back to
    normalised title + year matching.
    """
    mismatches: list[Mismatch] = []
    orphaned: list[OrphanedItem] = []
    missing: list[MissingItem] = []

    # Index Radarr movies by TMDB ID and normalised title+year
    radarr_by_tmdb: dict[str, dict] = {}
    radarr_by_title_year: dict[str, dict] = {}
    for r in radarr_movies:
        tmdb = str(r.get("tmdbId", ""))
        if tmdb:
            radarr_by_tmdb[tmdb] = r
        key = f"{_normalise(r.get('title', ''))}_{r.get('year', '')}"
        radarr_by_title_year[key] = r

    matched_radarr_ids: set[int] = set()

    for jf in jellyfin_movies:
        jf_title = jf.get("Name", "")
        jf_id = jf.get("Id", "")
        jf_tmdb = _get_jellyfin_provider_id(jf, "Tmdb")
        jf_year = _get_jellyfin_year(jf)

        # Try to find a matching Radarr entry
        radarr_entry = None
        if jf_tmdb and jf_tmdb in radarr_by_tmdb:
            radarr_entry = radarr_by_tmdb[jf_tmdb]
        else:
            key = f"{_normalise(jf_title)}_{jf_year}"
            radarr_entry = radarr_by_title_year.get(key)

        if radarr_entry is None:
            orphaned.append(OrphanedItem(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="movie",
                jellyfin_year=jf_year,
            ))
            continue

        matched_radarr_ids.add(radarr_entry.get("id", 0))

        # Compare title
        r_title = radarr_entry.get("title", "")
        if _normalise(jf_title) != _normalise(r_title):
            mismatches.append(Mismatch(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="movie",
                field="title",
                jellyfin_value=jf_title,
                arr_value=r_title,
                arr_title=r_title,
            ))

        # Compare year
        r_year = radarr_entry.get("year")
        if jf_year and r_year and jf_year != r_year:
            mismatches.append(Mismatch(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="movie",
                field="year",
                jellyfin_value=str(jf_year),
                arr_value=str(r_year),
                arr_title=r_title,
            ))

        # Check missing external ID
        r_tmdb = str(radarr_entry.get("tmdbId", ""))
        if not jf_tmdb and r_tmdb:
            mismatches.append(Mismatch(
                jellyfin_title=jf_title,
                jellyfin_id=jf_id,
                media_type="movie",
                field="external_id",
                jellyfin_value="(none)",
                arr_value=f"tmdb:{r_tmdb}",
                arr_title=r_title,
            ))

    # Radarr items not matched in Jellyfin
    for r in radarr_movies:
        if r.get("id", 0) not in matched_radarr_ids:
            missing.append(MissingItem(
                arr_title=r.get("title", ""),
                arr_id=r.get("id", 0),
                media_type="movie",
                arr_year=r.get("year"),
                external_id=f"tmdb:{r.get('tmdbId', '')}",
            ))

    return mismatches, orphaned, missing


def _normalise(title: str) -> str:
    """Normalise a title for comparison (lowercase, strip whitespace)."""
    return title.strip().lower()


# ------------------------------------------------------------------
# Data fetching
# ------------------------------------------------------------------

def fetch_jellyfin_items(client: JellyfinClient) -> tuple[list[dict], list[dict]]:
    """Fetch TV shows and movies from Jellyfin.

    Returns (tv_shows, movies) as two separate lists.
    """
    tv_shows: list[dict] = []
    movies: list[dict] = []

    libraries = client.get_libraries()
    for lib in libraries:
        collection_type = (lib.get("CollectionType") or "").lower()
        lib_id = lib.get("ItemId", "")

        if collection_type == "tvshows":
            items = client.get_items(
                parent_id=lib_id,
                IncludeItemTypes="Series",
                Recursive="true",
                Fields="ProviderIds,ProductionYear",
            )
            tv_shows.extend(items.get("Items", []))

        elif collection_type == "movies":
            items = client.get_items(
                parent_id=lib_id,
                IncludeItemTypes="Movie",
                Recursive="true",
                Fields="ProviderIds,ProductionYear",
            )
            movies.extend(items.get("Items", []))

    return tv_shows, movies


def run_check(
    jellyfin: JellyfinClient,
    sonarr: SonarrClient,
    radarr: RadarrClient,
) -> MetadataReport:
    """Execute the full metadata comparison and return a report."""
    report = MetadataReport()

    # Fetch all data
    jf_tv, jf_movies = fetch_jellyfin_items(jellyfin)
    sonarr_series = sonarr.get_series()
    radarr_movies = radarr.get_movies()

    report.jellyfin_tv_count = len(jf_tv)
    report.jellyfin_movie_count = len(jf_movies)
    report.sonarr_count = len(sonarr_series)
    report.radarr_count = len(radarr_movies)

    # Compare TV
    tv_mismatches, tv_orphaned, tv_missing = compare_tv_shows(jf_tv, sonarr_series)
    report.mismatches.extend(tv_mismatches)
    report.orphaned.extend(tv_orphaned)
    report.missing.extend(tv_missing)

    # Compare Movies
    mv_mismatches, mv_orphaned, mv_missing = compare_movies(jf_movies, radarr_movies)
    report.mismatches.extend(mv_mismatches)
    report.orphaned.extend(mv_orphaned)
    report.missing.extend(mv_missing)

    return report


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def format_console_summary(report: MetadataReport) -> str:
    """Format a concise console summary."""
    lines: list[str] = []
    lines.append("Metadata Accuracy Check")
    lines.append(f"Checked at: {report.checked_at}")
    lines.append("")
    lines.append("Library counts:")
    lines.append(f"  Jellyfin TV shows: {report.jellyfin_tv_count}")
    lines.append(f"  Jellyfin movies:   {report.jellyfin_movie_count}")
    lines.append(f"  Sonarr series:     {report.sonarr_count}")
    lines.append(f"  Radarr movies:     {report.radarr_count}")
    lines.append("")
    lines.append("Issues found:")
    lines.append(f"  Mismatched metadata: {len(report.mismatches)}")
    lines.append(f"  Orphaned in Jellyfin (not in Sonarr/Radarr): {len(report.orphaned)}")
    lines.append(f"  Missing from Jellyfin (in Sonarr/Radarr): {len(report.missing)}")
    lines.append(f"  Total issues: {report.total_issues}")
    lines.append("")

    if report.mismatches:
        lines.append("Mismatched items:")
        for m in report.mismatches:
            lines.append(f"  [{m.media_type.upper()}] {m.jellyfin_title}")
            lines.append(f"    Field: {m.field}")
            lines.append(f"    Jellyfin: {m.jellyfin_value}")
            lines.append(f"    Sonarr/Radarr: {m.arr_value}")
        lines.append("")

    if report.orphaned:
        lines.append("Orphaned in Jellyfin:")
        for o in report.orphaned:
            year = f" ({o.jellyfin_year})" if o.jellyfin_year else ""
            lines.append(f"  [{o.media_type.upper()}] {o.jellyfin_title}{year}")
        lines.append("")

    if report.missing:
        lines.append("Missing from Jellyfin:")
        for m in report.missing:
            year = f" ({m.arr_year})" if m.arr_year else ""
            lines.append(f"  [{m.media_type.upper()}] {m.arr_title}{year}")
        lines.append("")

    if report.total_issues == 0:
        lines.append("All metadata is in sync!")

    return "\n".join(lines)


def format_markdown_report(report: MetadataReport) -> str:
    """Generate a full markdown metadata accuracy report."""
    lines: list[str] = []
    lines.append("# Metadata Accuracy Report")
    lines.append("")
    lines.append(f"**Checked at:** {report.checked_at}")
    lines.append("")
    lines.append("## Library Counts")
    lines.append("")
    lines.append("| Source | Type | Count |")
    lines.append("|--------|------|-------|")
    lines.append(f"| Jellyfin | TV Shows | {report.jellyfin_tv_count} |")
    lines.append(f"| Jellyfin | Movies | {report.jellyfin_movie_count} |")
    lines.append(f"| Sonarr | Series | {report.sonarr_count} |")
    lines.append(f"| Radarr | Movies | {report.radarr_count} |")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| Mismatched metadata | {len(report.mismatches)} |")
    lines.append(f"| Orphaned in Jellyfin | {len(report.orphaned)} |")
    lines.append(f"| Missing from Jellyfin | {len(report.missing)} |")
    lines.append(f"| **Total issues** | **{report.total_issues}** |")
    lines.append("")

    if report.mismatches:
        lines.append("## Mismatched Metadata")
        lines.append("")
        lines.append("| Type | Jellyfin Title | Field | Jellyfin Value | Sonarr/Radarr Value |")
        lines.append("|------|----------------|-------|----------------|---------------------|")
        for m in report.mismatches:
            lines.append(
                f"| {m.media_type.upper()} | {m.jellyfin_title} "
                f"| {m.field} | {m.jellyfin_value} | {m.arr_value} |"
            )
        lines.append("")

    if report.orphaned:
        lines.append("## Orphaned in Jellyfin")
        lines.append("")
        lines.append("Items present in Jellyfin but not found in Sonarr/Radarr.")
        lines.append("")
        lines.append("| Type | Title | Year |")
        lines.append("|------|-------|------|")
        for o in report.orphaned:
            year = str(o.jellyfin_year) if o.jellyfin_year else "—"
            lines.append(f"| {o.media_type.upper()} | {o.jellyfin_title} | {year} |")
        lines.append("")

    if report.missing:
        lines.append("## Missing from Jellyfin")
        lines.append("")
        lines.append("Items present in Sonarr/Radarr but not found in Jellyfin.")
        lines.append("")
        lines.append("| Type | Title | Year | External ID |")
        lines.append("|------|-------|------|-------------|")
        for m in report.missing:
            year = str(m.arr_year) if m.arr_year else "—"
            lines.append(
                f"| {m.media_type.upper()} | {m.arr_title} | {year} | {m.external_id} |"
            )
        lines.append("")

    if report.total_issues == 0:
        lines.append("## Result")
        lines.append("")
        lines.append("All metadata is in sync!")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Jellyfin metadata accuracy checker"
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to save the markdown report",
    )
    args = parser.parse_args()

    jellyfin = JellyfinClient()
    sonarr = SonarrClient()
    radarr = RadarrClient()

    report = run_check(jellyfin, sonarr, radarr)

    # Console summary
    print(format_console_summary(report))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(
            Path(__file__).resolve().parent.parent / "tests" / "reports"
        )

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "metadata-accuracy.md"
    report_path.write_text(format_markdown_report(report))
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
