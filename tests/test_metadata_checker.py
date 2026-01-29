"""Tests for the Jellyfin metadata accuracy checker.

All tests use mock API data — no live services required.
"""

from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from metadata_checker import (
    MetadataReport,
    Mismatch,
    MissingItem,
    OrphanedItem,
    _normalise,
    compare_movies,
    compare_tv_shows,
    format_console_summary,
    format_markdown_report,
)


# ------------------------------------------------------------------
# Helpers — mock Jellyfin / Sonarr / Radarr items
# ------------------------------------------------------------------

def _jf_show(name: str, year: int, tvdb: str = "", item_id: str = "jf1") -> dict:
    """Build a mock Jellyfin TV show item."""
    ids: dict[str, str] = {}
    if tvdb:
        ids["Tvdb"] = tvdb
    return {
        "Name": name,
        "Id": item_id,
        "ProductionYear": year,
        "ProviderIds": ids,
    }


def _sonarr_series(title: str, year: int, tvdb: int = 0, sid: int = 1) -> dict:
    """Build a mock Sonarr series entry."""
    return {"title": title, "year": year, "tvdbId": tvdb, "id": sid}


def _jf_movie(name: str, year: int, tmdb: str = "", item_id: str = "jf1") -> dict:
    """Build a mock Jellyfin movie item."""
    ids: dict[str, str] = {}
    if tmdb:
        ids["Tmdb"] = tmdb
    return {
        "Name": name,
        "Id": item_id,
        "ProductionYear": year,
        "ProviderIds": ids,
    }


def _radarr_movie(title: str, year: int, tmdb: int = 0, rid: int = 1) -> dict:
    """Build a mock Radarr movie entry."""
    return {"title": title, "year": year, "tmdbId": tmdb, "id": rid}


# ------------------------------------------------------------------
# _normalise
# ------------------------------------------------------------------

class TestNormalise:
    def test_lowercase(self):
        assert _normalise("Hello World") == "hello world"

    def test_strip_whitespace(self):
        assert _normalise("  padded  ") == "padded"

    def test_empty_string(self):
        assert _normalise("") == ""


# ------------------------------------------------------------------
# compare_tv_shows
# ------------------------------------------------------------------

class TestCompareTvShows:
    def test_matching_by_tvdb_id(self):
        jf = [_jf_show("Breaking Bad", 2008, tvdb="81189")]
        sonarr = [_sonarr_series("Breaking Bad", 2008, tvdb=81189)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        assert mismatches == []
        assert orphaned == []
        assert missing == []

    def test_matching_by_title_fallback(self):
        jf = [_jf_show("Breaking Bad", 2008)]
        sonarr = [_sonarr_series("Breaking Bad", 2008, tvdb=81189)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        # Should match by title; only issue is missing external ID
        assert len(mismatches) == 1
        assert mismatches[0].field == "external_id"
        assert orphaned == []
        assert missing == []

    def test_title_mismatch(self):
        jf = [_jf_show("Breaking Baad", 2008, tvdb="81189")]
        sonarr = [_sonarr_series("Breaking Bad", 2008, tvdb=81189)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        title_mismatches = [m for m in mismatches if m.field == "title"]
        assert len(title_mismatches) == 1
        assert title_mismatches[0].jellyfin_value == "Breaking Baad"
        assert title_mismatches[0].arr_value == "Breaking Bad"

    def test_year_mismatch(self):
        jf = [_jf_show("Show", 2020, tvdb="100")]
        sonarr = [_sonarr_series("Show", 2019, tvdb=100)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        year_mismatches = [m for m in mismatches if m.field == "year"]
        assert len(year_mismatches) == 1
        assert year_mismatches[0].jellyfin_value == "2020"
        assert year_mismatches[0].arr_value == "2019"

    def test_missing_external_id(self):
        jf = [_jf_show("Show", 2020, tvdb="")]
        sonarr = [_sonarr_series("Show", 2020, tvdb=12345)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        id_mismatches = [m for m in mismatches if m.field == "external_id"]
        assert len(id_mismatches) == 1
        assert id_mismatches[0].jellyfin_value == "(none)"
        assert "tvdb:12345" in id_mismatches[0].arr_value

    def test_orphaned_in_jellyfin(self):
        jf = [_jf_show("Unknown Show", 2023)]
        sonarr: list[dict] = []
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        assert len(orphaned) == 1
        assert orphaned[0].jellyfin_title == "Unknown Show"
        assert orphaned[0].media_type == "tv"

    def test_missing_from_jellyfin(self):
        jf: list[dict] = []
        sonarr = [_sonarr_series("New Show", 2025, tvdb=99999, sid=7)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        assert len(missing) == 1
        assert missing[0].arr_title == "New Show"
        assert missing[0].media_type == "tv"

    def test_case_insensitive_title_match(self):
        jf = [_jf_show("breaking bad", 2008, tvdb="81189")]
        sonarr = [_sonarr_series("Breaking Bad", 2008, tvdb=81189)]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        # Matched by TVDB ID; title differs in case only — should flag
        title_mismatches = [m for m in mismatches if m.field == "title"]
        assert len(title_mismatches) == 0  # normalised match

    def test_multiple_shows(self):
        jf = [
            _jf_show("Show A", 2020, tvdb="100", item_id="a"),
            _jf_show("Show B", 2021, tvdb="200", item_id="b"),
        ]
        sonarr = [
            _sonarr_series("Show A", 2020, tvdb=100, sid=1),
            _sonarr_series("Show B", 2021, tvdb=200, sid=2),
            _sonarr_series("Show C", 2022, tvdb=300, sid=3),
        ]
        mismatches, orphaned, missing = compare_tv_shows(jf, sonarr)
        assert mismatches == []
        assert orphaned == []
        assert len(missing) == 1
        assert missing[0].arr_title == "Show C"


# ------------------------------------------------------------------
# compare_movies
# ------------------------------------------------------------------

class TestCompareMovies:
    def test_matching_by_tmdb_id(self):
        jf = [_jf_movie("The Matrix", 1999, tmdb="603")]
        radarr = [_radarr_movie("The Matrix", 1999, tmdb=603)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        assert mismatches == []
        assert orphaned == []
        assert missing == []

    def test_matching_by_title_year_fallback(self):
        jf = [_jf_movie("The Matrix", 1999)]
        radarr = [_radarr_movie("The Matrix", 1999, tmdb=603)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        # Matched by title+year; missing TMDB ID
        id_mismatches = [m for m in mismatches if m.field == "external_id"]
        assert len(id_mismatches) == 1
        assert orphaned == []
        assert missing == []

    def test_title_mismatch(self):
        jf = [_jf_movie("Matrix", 1999, tmdb="603")]
        radarr = [_radarr_movie("The Matrix", 1999, tmdb=603)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        title_mismatches = [m for m in mismatches if m.field == "title"]
        assert len(title_mismatches) == 1
        assert title_mismatches[0].jellyfin_value == "Matrix"
        assert title_mismatches[0].arr_value == "The Matrix"

    def test_year_mismatch(self):
        jf = [_jf_movie("Movie", 2020, tmdb="555")]
        radarr = [_radarr_movie("Movie", 2019, tmdb=555)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        year_mismatches = [m for m in mismatches if m.field == "year"]
        assert len(year_mismatches) == 1
        assert year_mismatches[0].jellyfin_value == "2020"
        assert year_mismatches[0].arr_value == "2019"

    def test_missing_external_id(self):
        jf = [_jf_movie("Movie", 2020, tmdb="")]
        radarr = [_radarr_movie("Movie", 2020, tmdb=555)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        id_mismatches = [m for m in mismatches if m.field == "external_id"]
        assert len(id_mismatches) == 1
        assert "tmdb:555" in id_mismatches[0].arr_value

    def test_orphaned_in_jellyfin(self):
        jf = [_jf_movie("Old Movie", 1985)]
        radarr: list[dict] = []
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        assert len(orphaned) == 1
        assert orphaned[0].jellyfin_title == "Old Movie"
        assert orphaned[0].media_type == "movie"

    def test_missing_from_jellyfin(self):
        jf: list[dict] = []
        radarr = [_radarr_movie("New Movie", 2025, tmdb=99999, rid=42)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        assert len(missing) == 1
        assert missing[0].arr_title == "New Movie"
        assert missing[0].media_type == "movie"

    def test_case_insensitive_title_match(self):
        jf = [_jf_movie("the matrix", 1999, tmdb="603")]
        radarr = [_radarr_movie("The Matrix", 1999, tmdb=603)]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        title_mismatches = [m for m in mismatches if m.field == "title"]
        assert len(title_mismatches) == 0

    def test_multiple_movies(self):
        jf = [
            _jf_movie("Film A", 2020, tmdb="10", item_id="a"),
            _jf_movie("Film B", 2021, tmdb="20", item_id="b"),
        ]
        radarr = [
            _radarr_movie("Film A", 2020, tmdb=10, rid=1),
            _radarr_movie("Film B", 2021, tmdb=20, rid=2),
            _radarr_movie("Film C", 2022, tmdb=30, rid=3),
        ]
        mismatches, orphaned, missing = compare_movies(jf, radarr)
        assert mismatches == []
        assert orphaned == []
        assert len(missing) == 1
        assert missing[0].arr_title == "Film C"


# ------------------------------------------------------------------
# MetadataReport properties
# ------------------------------------------------------------------

class TestMetadataReport:
    def test_total_issues(self):
        report = MetadataReport()
        report.mismatches = [
            Mismatch(
                jellyfin_title="X", jellyfin_id="1", media_type="tv",
                field="title", jellyfin_value="X", arr_value="Y",
            ),
        ]
        report.orphaned = [
            OrphanedItem(jellyfin_title="A", jellyfin_id="2", media_type="tv"),
        ]
        report.missing = [
            MissingItem(arr_title="B", arr_id=3, media_type="movie"),
        ]
        assert report.total_issues == 3

    def test_empty_report(self):
        report = MetadataReport()
        assert report.total_issues == 0


# ------------------------------------------------------------------
# Console output formatting
# ------------------------------------------------------------------

class TestConsoleOutput:
    def test_summary_includes_counts(self):
        report = MetadataReport(
            jellyfin_tv_count=10,
            jellyfin_movie_count=50,
            sonarr_count=12,
            radarr_count=48,
        )
        report.mismatches = [
            Mismatch(
                jellyfin_title="Show", jellyfin_id="1", media_type="tv",
                field="title", jellyfin_value="Show", arr_value="The Show",
            ),
        ]
        report.orphaned = [
            OrphanedItem(
                jellyfin_title="Old", jellyfin_id="2", media_type="movie",
                jellyfin_year=1990,
            ),
        ]
        report.missing = [
            MissingItem(
                arr_title="New", arr_id=5, media_type="tv", arr_year=2025,
            ),
        ]
        text = format_console_summary(report)
        assert "Mismatched metadata: 1" in text
        assert "Orphaned in Jellyfin" in text
        assert "Missing from Jellyfin" in text
        assert "Total issues: 3" in text
        assert "Jellyfin TV shows: 10" in text
        assert "Radarr movies:" in text and "48" in text

    def test_no_issues_message(self):
        report = MetadataReport()
        text = format_console_summary(report)
        assert "All metadata is in sync!" in text

    def test_orphaned_shows_year(self):
        report = MetadataReport()
        report.orphaned = [
            OrphanedItem(
                jellyfin_title="Film", jellyfin_id="1", media_type="movie",
                jellyfin_year=2020,
            ),
        ]
        text = format_console_summary(report)
        assert "Film (2020)" in text

    def test_missing_shows_year(self):
        report = MetadataReport()
        report.missing = [
            MissingItem(
                arr_title="Series", arr_id=1, media_type="tv", arr_year=2023,
            ),
        ]
        text = format_console_summary(report)
        assert "Series (2023)" in text


# ------------------------------------------------------------------
# Markdown report formatting
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_report_contains_expected_sections(self):
        report = MetadataReport(
            jellyfin_tv_count=5,
            jellyfin_movie_count=10,
            sonarr_count=5,
            radarr_count=10,
        )
        report.mismatches = [
            Mismatch(
                jellyfin_title="X", jellyfin_id="1", media_type="tv",
                field="title", jellyfin_value="X", arr_value="Y",
            ),
        ]
        report.orphaned = [
            OrphanedItem(
                jellyfin_title="Orphan", jellyfin_id="2", media_type="movie",
                jellyfin_year=2019,
            ),
        ]
        report.missing = [
            MissingItem(
                arr_title="Gone", arr_id=3, media_type="tv",
                arr_year=2024, external_id="tvdb:111",
            ),
        ]
        md = format_markdown_report(report)
        assert "# Metadata Accuracy Report" in md
        assert "## Library Counts" in md
        assert "## Summary" in md
        assert "## Mismatched Metadata" in md
        assert "## Orphaned in Jellyfin" in md
        assert "## Missing from Jellyfin" in md
        assert "tvdb:111" in md

    def test_all_synced_report(self):
        report = MetadataReport()
        md = format_markdown_report(report)
        assert "All metadata is in sync!" in md

    def test_library_counts_in_table(self):
        report = MetadataReport(
            jellyfin_tv_count=3,
            jellyfin_movie_count=7,
            sonarr_count=4,
            radarr_count=8,
        )
        md = format_markdown_report(report)
        assert "| Jellyfin | TV Shows | 3 |" in md
        assert "| Radarr | Movies | 8 |" in md

    def test_summary_table_total(self):
        report = MetadataReport()
        report.mismatches = [
            Mismatch(
                jellyfin_title="X", jellyfin_id="1", media_type="tv",
                field="year", jellyfin_value="2020", arr_value="2019",
            ),
        ]
        md = format_markdown_report(report)
        assert "**1**" in md  # total issues bold
