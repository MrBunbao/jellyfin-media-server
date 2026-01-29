"""Tests for the Jellyfin library health checker.

All tests use mock data — no live services required.
"""

from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from library_health_checker import (
    DuplicateGroup,
    HealthReport,
    OrphanedItem,
    PlaceholderPosterItem,
    UnknownItem,
    detect_duplicates,
    detect_orphaned_items,
    detect_placeholder_posters,
    detect_unknown_items,
    format_console_summary,
    format_markdown_report,
)


# ------------------------------------------------------------------
# Helpers — mock Jellyfin items
# ------------------------------------------------------------------

def _jf_item(
    name: str = "Test Item",
    item_id: str = "jf1",
    media_type: str = "movie",
    overview: str = "A description.",
    provider_ids: dict | None = None,
    image_tags: dict | None = None,
    path: str = "",
    year: int | None = None,
    has_primary_image: bool | None = None,
) -> dict:
    """Build a mock Jellyfin item with configurable fields."""
    item: dict = {
        "Name": name,
        "Id": item_id,
        "ProviderIds": provider_ids or {},
        "ImageTags": image_tags if image_tags is not None else {"Primary": "abc123"},
        "Overview": overview,
    }
    if path:
        item["Path"] = path
    if year is not None:
        item["ProductionYear"] = year
    if has_primary_image is not None:
        item["HasPrimaryImage"] = has_primary_image
    return item


# ------------------------------------------------------------------
# detect_unknown_items
# ------------------------------------------------------------------

class TestDetectUnknownItems:
    def test_healthy_item_not_flagged(self):
        items = [_jf_item(name="Good Movie", overview="Great film.")]
        result = detect_unknown_items(items, "movie")
        assert result == []

    def test_unknown_title(self):
        items = [_jf_item(name="Unknown")]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "title" in result[0].missing_fields

    def test_unknown_title_case_insensitive(self):
        items = [_jf_item(name="UNKNOWN")]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "title" in result[0].missing_fields

    def test_unknown_series_title(self):
        items = [_jf_item(name="Unknown Series")]
        result = detect_unknown_items(items, "tv")
        assert len(result) == 1
        assert "title" in result[0].missing_fields

    def test_empty_title(self):
        items = [_jf_item(name="")]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "title" in result[0].missing_fields
        assert result[0].jellyfin_title == "(empty)"

    def test_missing_description(self):
        items = [_jf_item(name="Good Title", overview="")]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "description" in result[0].missing_fields

    def test_none_overview(self):
        items = [_jf_item(name="Good Title")]
        items[0]["Overview"] = None
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "description" in result[0].missing_fields

    def test_missing_poster(self):
        items = [_jf_item(name="Good Title", image_tags={})]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "poster" in result[0].missing_fields

    def test_multiple_missing_fields(self):
        items = [_jf_item(name="Unknown", overview="", image_tags={})]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert set(result[0].missing_fields) == {"title", "description", "poster"}

    def test_media_type_preserved(self):
        items = [_jf_item(name="Unknown")]
        result_tv = detect_unknown_items(items, "tv")
        result_movie = detect_unknown_items(items, "movie")
        assert result_tv[0].media_type == "tv"
        assert result_movie[0].media_type == "movie"

    def test_whitespace_only_title(self):
        items = [_jf_item(name="   ")]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert "title" in result[0].missing_fields

    def test_mixed_items(self):
        items = [
            _jf_item(name="Good Movie", overview="Fine.", item_id="a"),
            _jf_item(name="Unknown", overview="Has desc.", item_id="b"),
            _jf_item(name="Another Good", overview="OK.", item_id="c"),
        ]
        result = detect_unknown_items(items, "movie")
        assert len(result) == 1
        assert result[0].jellyfin_id == "b"


# ------------------------------------------------------------------
# detect_duplicates
# ------------------------------------------------------------------

class TestDetectDuplicates:
    def test_no_duplicates(self):
        items = [
            _jf_item(name="Movie A", item_id="a", provider_ids={"Tmdb": "100"}),
            _jf_item(name="Movie B", item_id="b", provider_ids={"Tmdb": "200"}),
        ]
        result = detect_duplicates(items, "movie")
        assert result == []

    def test_tmdb_duplicate(self):
        items = [
            _jf_item(name="Movie A", item_id="a", provider_ids={"Tmdb": "100"}),
            _jf_item(name="Movie A (copy)", item_id="b", provider_ids={"Tmdb": "100"}),
        ]
        result = detect_duplicates(items, "movie")
        assert len(result) == 1
        assert result[0].provider == "Tmdb"
        assert result[0].provider_id == "100"
        assert result[0].count == 2

    def test_tvdb_duplicate_for_tv(self):
        items = [
            _jf_item(name="Show A", item_id="a", provider_ids={"Tvdb": "500"}),
            _jf_item(name="Show A v2", item_id="b", provider_ids={"Tvdb": "500"}),
        ]
        result = detect_duplicates(items, "tv")
        assert len(result) == 1
        assert result[0].provider == "Tvdb"
        assert result[0].provider_id == "500"

    def test_triple_duplicate(self):
        items = [
            _jf_item(name="Film 1", item_id="a", provider_ids={"Tmdb": "42"}),
            _jf_item(name="Film 2", item_id="b", provider_ids={"Tmdb": "42"}),
            _jf_item(name="Film 3", item_id="c", provider_ids={"Tmdb": "42"}),
        ]
        result = detect_duplicates(items, "movie")
        assert len(result) == 1
        assert result[0].count == 3

    def test_items_without_provider_id_skipped(self):
        items = [
            _jf_item(name="No ID", item_id="a", provider_ids={}),
            _jf_item(name="Also No ID", item_id="b", provider_ids={}),
        ]
        result = detect_duplicates(items, "movie")
        assert result == []

    def test_multiple_duplicate_groups(self):
        items = [
            _jf_item(name="A1", item_id="a1", provider_ids={"Tmdb": "10"}),
            _jf_item(name="A2", item_id="a2", provider_ids={"Tmdb": "10"}),
            _jf_item(name="B1", item_id="b1", provider_ids={"Tmdb": "20"}),
            _jf_item(name="B2", item_id="b2", provider_ids={"Tmdb": "20"}),
            _jf_item(name="C1", item_id="c1", provider_ids={"Tmdb": "30"}),
        ]
        result = detect_duplicates(items, "movie")
        assert len(result) == 2

    def test_duplicate_group_items_have_names(self):
        items = [
            _jf_item(name="Movie X", item_id="a", provider_ids={"Tmdb": "77"}),
            _jf_item(name="Movie X (2)", item_id="b", provider_ids={"Tmdb": "77"}),
        ]
        result = detect_duplicates(items, "movie")
        names = [it["Name"] for it in result[0].items]
        assert "Movie X" in names
        assert "Movie X (2)" in names


# ------------------------------------------------------------------
# detect_orphaned_items
# ------------------------------------------------------------------

class TestDetectOrphanedItems:
    def test_existing_path_not_flagged(self):
        items = [_jf_item(path="/media/movies/film.mkv")]
        result = detect_orphaned_items(items, "movie", path_exists_fn=lambda p: True)
        assert result == []

    def test_missing_path_flagged(self):
        items = [_jf_item(name="Gone Movie", path="/media/movies/gone.mkv")]
        result = detect_orphaned_items(items, "movie", path_exists_fn=lambda p: False)
        assert len(result) == 1
        assert result[0].jellyfin_title == "Gone Movie"
        assert result[0].file_path == "/media/movies/gone.mkv"

    def test_item_without_path_skipped(self):
        items = [_jf_item()]  # no path
        result = detect_orphaned_items(items, "movie", path_exists_fn=lambda p: False)
        assert result == []

    def test_empty_path_skipped(self):
        items = [_jf_item(path="")]
        result = detect_orphaned_items(items, "movie", path_exists_fn=lambda p: False)
        assert result == []

    def test_mixed_existing_and_missing(self):
        existing = {"/media/movies/exists.mkv"}
        items = [
            _jf_item(name="Exists", item_id="a", path="/media/movies/exists.mkv"),
            _jf_item(name="Missing", item_id="b", path="/media/movies/missing.mkv"),
        ]
        result = detect_orphaned_items(
            items, "movie", path_exists_fn=lambda p: p in existing
        )
        assert len(result) == 1
        assert result[0].jellyfin_title == "Missing"

    def test_media_type_preserved(self):
        items = [_jf_item(path="/path/to/show")]
        result = detect_orphaned_items(items, "tv", path_exists_fn=lambda p: False)
        assert result[0].media_type == "tv"


# ------------------------------------------------------------------
# detect_placeholder_posters
# ------------------------------------------------------------------

class TestDetectPlaceholderPosters:
    def test_item_with_poster_not_flagged(self):
        items = [_jf_item(image_tags={"Primary": "hash123"})]
        result = detect_placeholder_posters(items, "movie")
        assert result == []

    def test_item_missing_primary_image_tag(self):
        items = [_jf_item(name="No Poster", image_tags={})]
        result = detect_placeholder_posters(items, "movie")
        assert len(result) == 1
        assert result[0].jellyfin_title == "No Poster"
        assert result[0].has_primary_image is False

    def test_none_image_tags(self):
        items = [_jf_item(name="None Tags")]
        items[0]["ImageTags"] = None
        result = detect_placeholder_posters(items, "movie")
        assert len(result) == 1

    def test_has_primary_image_false(self):
        items = [_jf_item(
            name="Explicit False",
            image_tags={"Primary": "tag"},
            has_primary_image=False,
        )]
        result = detect_placeholder_posters(items, "movie")
        assert len(result) == 1

    def test_mixed_items(self):
        items = [
            _jf_item(name="Has Poster", item_id="a", image_tags={"Primary": "x"}),
            _jf_item(name="No Poster", item_id="b", image_tags={}),
            _jf_item(name="Also Has", item_id="c", image_tags={"Primary": "y"}),
        ]
        result = detect_placeholder_posters(items, "movie")
        assert len(result) == 1
        assert result[0].jellyfin_id == "b"

    def test_media_type_preserved(self):
        items = [_jf_item(image_tags={})]
        result = detect_placeholder_posters(items, "tv")
        assert result[0].media_type == "tv"


# ------------------------------------------------------------------
# HealthReport properties
# ------------------------------------------------------------------

class TestHealthReport:
    def test_total_items(self):
        report = HealthReport(total_tv_count=5, total_movie_count=10)
        assert report.total_items == 15

    def test_total_issues(self):
        report = HealthReport()
        report.unknown_items = [
            UnknownItem(
                jellyfin_title="X", jellyfin_id="1",
                media_type="movie", missing_fields=["title"],
            ),
        ]
        report.duplicates = [
            DuplicateGroup(
                provider="Tmdb", provider_id="100",
                media_type="movie", items=[{"Name": "A", "Id": "a"}, {"Name": "B", "Id": "b"}],
            ),
        ]
        report.orphaned_items = [
            OrphanedItem(
                jellyfin_title="Y", jellyfin_id="2",
                media_type="tv", file_path="/gone",
            ),
        ]
        report.placeholder_posters = [
            PlaceholderPosterItem(
                jellyfin_title="Z", jellyfin_id="3",
                media_type="movie", has_primary_image=False,
            ),
        ]
        assert report.total_issues == 4

    def test_empty_report(self):
        report = HealthReport()
        assert report.total_issues == 0
        assert report.total_items == 0

    def test_duplicate_item_count(self):
        report = HealthReport()
        report.duplicates = [
            DuplicateGroup(
                provider="Tmdb", provider_id="1", media_type="movie",
                items=[{"Name": "A", "Id": "a"}, {"Name": "B", "Id": "b"}],
            ),
            DuplicateGroup(
                provider="Tmdb", provider_id="2", media_type="movie",
                items=[
                    {"Name": "C", "Id": "c"},
                    {"Name": "D", "Id": "d"},
                    {"Name": "E", "Id": "e"},
                ],
            ),
        ]
        assert report.duplicate_item_count == 5

    def test_duplicate_group_count_property(self):
        group = DuplicateGroup(
            provider="Tvdb", provider_id="42", media_type="tv",
            items=[{"Name": "A", "Id": "1"}, {"Name": "B", "Id": "2"}],
        )
        assert group.count == 2


# ------------------------------------------------------------------
# Console output formatting
# ------------------------------------------------------------------

class TestConsoleOutput:
    def test_summary_includes_counts(self):
        report = HealthReport(total_tv_count=10, total_movie_count=50)
        report.unknown_items = [
            UnknownItem(
                jellyfin_title="Bad", jellyfin_id="1",
                media_type="movie", missing_fields=["title", "description"],
            ),
        ]
        report.duplicates = [
            DuplicateGroup(
                provider="Tmdb", provider_id="100", media_type="movie",
                items=[
                    {"Name": "Dup A", "Id": "a", "ProductionYear": 2020},
                    {"Name": "Dup B", "Id": "b", "ProductionYear": 2020},
                ],
            ),
        ]
        report.orphaned_items = [
            OrphanedItem(
                jellyfin_title="Gone", jellyfin_id="2",
                media_type="tv", file_path="/missing/path",
            ),
        ]
        report.placeholder_posters = [
            PlaceholderPosterItem(
                jellyfin_title="NoPoster", jellyfin_id="3",
                media_type="movie", has_primary_image=False,
            ),
        ]
        text = format_console_summary(report)
        assert "TV shows:  10" in text
        assert "Movies:    50" in text
        assert "Unknown / missing metadata: 1" in text
        assert "Duplicate entries:" in text
        assert "1 groups" in text
        assert "2 items" in text
        assert "Orphaned file paths:        1" in text
        assert "Placeholder posters:        1" in text

    def test_no_issues_message(self):
        report = HealthReport()
        text = format_console_summary(report)
        assert "Library is healthy" in text

    def test_unknown_details(self):
        report = HealthReport()
        report.unknown_items = [
            UnknownItem(
                jellyfin_title="Unknown", jellyfin_id="1",
                media_type="movie", missing_fields=["title", "poster"],
            ),
        ]
        text = format_console_summary(report)
        assert "[MOVIE] Unknown" in text
        assert "title, poster" in text

    def test_orphaned_details(self):
        report = HealthReport()
        report.orphaned_items = [
            OrphanedItem(
                jellyfin_title="Film", jellyfin_id="1",
                media_type="movie", file_path="/data/movies/gone.mkv",
            ),
        ]
        text = format_console_summary(report)
        assert "[MOVIE] Film" in text
        assert "/data/movies/gone.mkv" in text

    def test_duplicate_details(self):
        report = HealthReport()
        report.duplicates = [
            DuplicateGroup(
                provider="Tmdb", provider_id="42", media_type="movie",
                items=[
                    {"Name": "Film A", "Id": "a", "ProductionYear": 2020},
                    {"Name": "Film B", "Id": "b", "ProductionYear": 2020},
                ],
            ),
        ]
        text = format_console_summary(report)
        assert "Tmdb:42" in text
        assert "Film A" in text
        assert "Film B" in text

    def test_placeholder_details(self):
        report = HealthReport()
        report.placeholder_posters = [
            PlaceholderPosterItem(
                jellyfin_title="NoPic", jellyfin_id="1",
                media_type="tv", has_primary_image=False,
            ),
        ]
        text = format_console_summary(report)
        assert "[TV] NoPic" in text


# ------------------------------------------------------------------
# Markdown report formatting
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_report_contains_expected_sections(self):
        report = HealthReport(total_tv_count=5, total_movie_count=10)
        report.unknown_items = [
            UnknownItem(
                jellyfin_title="Bad Title", jellyfin_id="1",
                media_type="tv", missing_fields=["title"],
            ),
        ]
        report.duplicates = [
            DuplicateGroup(
                provider="Tvdb", provider_id="999", media_type="tv",
                items=[
                    {"Name": "Show 1", "Id": "a", "ProductionYear": 2021},
                    {"Name": "Show 1 copy", "Id": "b", "ProductionYear": 2021},
                ],
            ),
        ]
        report.orphaned_items = [
            OrphanedItem(
                jellyfin_title="Orphan", jellyfin_id="2",
                media_type="movie", file_path="/gone/file.mkv",
            ),
        ]
        report.placeholder_posters = [
            PlaceholderPosterItem(
                jellyfin_title="NoPoster", jellyfin_id="3",
                media_type="movie", has_primary_image=False,
            ),
        ]
        md = format_markdown_report(report)
        assert "# Library Health Report" in md
        assert "## Library Counts" in md
        assert "## Issue Summary" in md
        assert "## Unknown / Missing Metadata" in md
        assert "## Duplicate Entries" in md
        assert "## Orphaned File Paths" in md
        assert "## Placeholder Posters" in md

    def test_all_healthy_report(self):
        report = HealthReport()
        md = format_markdown_report(report)
        assert "Library is healthy" in md

    def test_library_counts_in_table(self):
        report = HealthReport(total_tv_count=3, total_movie_count=7)
        md = format_markdown_report(report)
        assert "| TV Shows | 3 |" in md
        assert "| Movies | 7 |" in md
        assert "**10**" in md

    def test_summary_table_counts(self):
        report = HealthReport()
        report.unknown_items = [
            UnknownItem(
                jellyfin_title="X", jellyfin_id="1",
                media_type="movie", missing_fields=["title"],
            ),
        ]
        md = format_markdown_report(report)
        assert "Unknown / missing metadata | 1" in md

    def test_orphaned_path_in_code_block(self):
        report = HealthReport()
        report.orphaned_items = [
            OrphanedItem(
                jellyfin_title="Film", jellyfin_id="1",
                media_type="movie", file_path="/data/movies/file.mkv",
            ),
        ]
        md = format_markdown_report(report)
        assert "`/data/movies/file.mkv`" in md

    def test_duplicate_provider_id_shown(self):
        report = HealthReport()
        report.duplicates = [
            DuplicateGroup(
                provider="Tmdb", provider_id="555", media_type="movie",
                items=[
                    {"Name": "A", "Id": "1", "ProductionYear": 2020},
                    {"Name": "B", "Id": "2", "ProductionYear": 2020},
                ],
            ),
        ]
        md = format_markdown_report(report)
        assert "Tmdb:555" in md

    def test_placeholder_poster_boolean(self):
        report = HealthReport()
        report.placeholder_posters = [
            PlaceholderPosterItem(
                jellyfin_title="X", jellyfin_id="1",
                media_type="movie", has_primary_image=False,
            ),
        ]
        md = format_markdown_report(report)
        assert "False" in md
