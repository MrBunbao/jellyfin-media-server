"""Tests for the Janitorr Leaving Soon consistency checker.

All tests use mock data — no live services required.
"""

import textwrap
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from leaving_soon_checker import (
    BrokenMetadata,
    FalsePositive,
    LeavingSoonReport,
    MissingItem,
    find_broken_metadata,
    find_false_positives,
    find_missing_from_collection,
    format_console_summary,
    format_markdown_report,
    parse_janitorr_config,
)


# ------------------------------------------------------------------
# Helpers — mock data builders
# ------------------------------------------------------------------

_UNSET = object()


def _jf_item(
    name: str = "Test Item",
    item_id: str = "jf1",
    overview: str = "A description.",
    provider_ids: dict | object = _UNSET,
    image_tags: dict | None = None,
) -> dict:
    """Build a mock Jellyfin item from a Leaving Soon collection."""
    return {
        "Name": name,
        "Id": item_id,
        "Overview": overview,
        "ProviderIds": {"Tmdb": "12345"} if provider_ids is _UNSET else provider_ids,
        "ImageTags": image_tags if image_tags is not None else {"Primary": "abc"},
    }


def _arr_item(
    title: str = "Test Item",
    arr_id: int = 1,
    tags: list[int] | None = None,
) -> dict:
    """Build a mock Sonarr/Radarr item."""
    return {
        "title": title,
        "id": arr_id,
        "tags": tags or [],
    }


# ------------------------------------------------------------------
# parse_janitorr_config
# ------------------------------------------------------------------

class TestParseJanitorrConfig:
    def test_parses_collection_names(self, tmp_path):
        cfg = tmp_path / "application.yml"
        cfg.write_text(textwrap.dedent("""\
            application:
              leaving-soon: 14d
              exclusion-tags:
                - keep
                - favorite
            clients:
              jellyfin:
                leaving-soon-tv: "Shows (Leaving Soon)"
                leaving-soon-movies: "Movies (Leaving Soon)"
        """))
        result = parse_janitorr_config(str(cfg))
        assert result["leaving_soon_tv"] == "Shows (Leaving Soon)"
        assert result["leaving_soon_movies"] == "Movies (Leaving Soon)"

    def test_parses_leaving_soon_days(self, tmp_path):
        cfg = tmp_path / "application.yml"
        cfg.write_text(textwrap.dedent("""\
            application:
              leaving-soon: 21d
            clients:
              jellyfin: {}
        """))
        result = parse_janitorr_config(str(cfg))
        assert result["leaving_soon_days"] == 21

    def test_parses_exclusion_tags(self, tmp_path):
        cfg = tmp_path / "application.yml"
        cfg.write_text(textwrap.dedent("""\
            application:
              leaving-soon: 7d
              exclusion-tags:
                - keep
                - favorite
                - janitorr_keep
            clients:
              jellyfin: {}
        """))
        result = parse_janitorr_config(str(cfg))
        assert result["exclusion_tags"] == ["keep", "favorite", "janitorr_keep"]

    def test_defaults_when_missing(self, tmp_path):
        cfg = tmp_path / "application.yml"
        cfg.write_text(textwrap.dedent("""\
            application: {}
            clients:
              jellyfin: {}
        """))
        result = parse_janitorr_config(str(cfg))
        assert result["leaving_soon_tv"] == "Shows (Leaving Soon)"
        assert result["leaving_soon_movies"] == "Movies (Leaving Soon)"
        assert result["leaving_soon_days"] == 14
        assert result["exclusion_tags"] == []

    def test_custom_collection_names(self, tmp_path):
        cfg = tmp_path / "application.yml"
        cfg.write_text(textwrap.dedent("""\
            application:
              leaving-soon: 30d
            clients:
              jellyfin:
                leaving-soon-tv: "TV Expiring"
                leaving-soon-movies: "Films Expiring"
        """))
        result = parse_janitorr_config(str(cfg))
        assert result["leaving_soon_tv"] == "TV Expiring"
        assert result["leaving_soon_movies"] == "Films Expiring"
        assert result["leaving_soon_days"] == 30


# ------------------------------------------------------------------
# find_false_positives
# ------------------------------------------------------------------

class TestFindFalsePositives:
    def test_no_false_positives_when_all_scheduled(self):
        items = [
            _jf_item(name="Breaking Bad", item_id="a"),
            _jf_item(name="The Office", item_id="b"),
        ]
        scheduled = {"breaking bad", "the office"}
        result = find_false_positives(items, scheduled, "tv")
        assert result == []

    def test_detects_false_positive(self):
        items = [
            _jf_item(name="Breaking Bad", item_id="a"),
            _jf_item(name="Not Scheduled", item_id="b"),
        ]
        scheduled = {"breaking bad"}
        result = find_false_positives(items, scheduled, "tv")
        assert len(result) == 1
        assert result[0].title == "Not Scheduled"
        assert result[0].media_type == "tv"

    def test_all_false_positives(self):
        items = [
            _jf_item(name="Show A", item_id="a"),
            _jf_item(name="Show B", item_id="b"),
        ]
        scheduled: set[str] = set()
        result = find_false_positives(items, scheduled, "tv")
        assert len(result) == 2

    def test_case_insensitive_matching(self):
        items = [_jf_item(name="BREAKING BAD", item_id="a")]
        scheduled = {"breaking bad"}
        result = find_false_positives(items, scheduled, "tv")
        assert result == []

    def test_whitespace_tolerance(self):
        items = [_jf_item(name="  Breaking Bad  ", item_id="a")]
        scheduled = {"breaking bad"}
        result = find_false_positives(items, scheduled, "tv")
        assert result == []

    def test_empty_collection(self):
        result = find_false_positives([], {"something"}, "movie")
        assert result == []

    def test_preserves_media_type(self):
        items = [_jf_item(name="Unscheduled")]
        result = find_false_positives(items, set(), "movie")
        assert result[0].media_type == "movie"

    def test_reason_populated(self):
        items = [_jf_item(name="Unscheduled")]
        result = find_false_positives(items, set(), "tv")
        assert "not tagged" in result[0].reason.lower()


# ------------------------------------------------------------------
# find_missing_from_collection
# ------------------------------------------------------------------

class TestFindMissingFromCollection:
    def test_no_missing_when_all_present(self):
        collection_titles = {"breaking bad", "the office"}
        scheduled = [
            _arr_item(title="Breaking Bad", arr_id=1),
            _arr_item(title="The Office", arr_id=2),
        ]
        result = find_missing_from_collection(
            collection_titles, scheduled, "tv", "janitorr-leaving-soon"
        )
        assert result == []

    def test_detects_missing_item(self):
        collection_titles = {"breaking bad"}
        scheduled = [
            _arr_item(title="Breaking Bad", arr_id=1),
            _arr_item(title="The Office", arr_id=2),
        ]
        result = find_missing_from_collection(
            collection_titles, scheduled, "tv", "janitorr-leaving-soon"
        )
        assert len(result) == 1
        assert result[0].title == "The Office"
        assert result[0].arr_id == 2

    def test_all_missing(self):
        collection_titles: set[str] = set()
        scheduled = [
            _arr_item(title="Show A", arr_id=1),
            _arr_item(title="Show B", arr_id=2),
        ]
        result = find_missing_from_collection(
            collection_titles, scheduled, "tv", "janitorr-leaving-soon"
        )
        assert len(result) == 2

    def test_case_insensitive_matching(self):
        collection_titles = {"breaking bad"}
        scheduled = [_arr_item(title="BREAKING BAD", arr_id=1)]
        result = find_missing_from_collection(
            collection_titles, scheduled, "tv", "janitorr-leaving-soon"
        )
        assert result == []

    def test_empty_scheduled(self):
        result = find_missing_from_collection(
            {"something"}, [], "movie", "janitorr-leaving-soon"
        )
        assert result == []

    def test_preserves_media_type(self):
        result = find_missing_from_collection(
            set(), [_arr_item(title="Film")], "movie", "janitorr-leaving-soon"
        )
        assert result[0].media_type == "movie"

    def test_tag_preserved(self):
        result = find_missing_from_collection(
            set(), [_arr_item(title="Film")], "movie", "custom-tag"
        )
        assert result[0].tag == "custom-tag"


# ------------------------------------------------------------------
# find_broken_metadata
# ------------------------------------------------------------------

class TestFindBrokenMetadata:
    def test_healthy_item_not_flagged(self):
        items = [_jf_item(name="Good Show", overview="Great show.")]
        result = find_broken_metadata(items, "tv")
        assert result == []

    def test_unknown_title(self):
        items = [_jf_item(name="Unknown")]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert "title" in result[0].missing_fields

    def test_empty_title(self):
        items = [_jf_item(name="")]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert "title" in result[0].missing_fields
        assert result[0].title == "(empty)"

    def test_missing_description(self):
        items = [_jf_item(name="Good Title", overview="")]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert "description" in result[0].missing_fields

    def test_none_overview(self):
        items = [_jf_item(name="Good Title")]
        items[0]["Overview"] = None
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert "description" in result[0].missing_fields

    def test_missing_poster(self):
        items = [_jf_item(name="Good Title", image_tags={})]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert "poster" in result[0].missing_fields

    def test_missing_provider_ids(self):
        items = [_jf_item(name="Good Title", provider_ids={})]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert "provider_ids" in result[0].missing_fields

    def test_multiple_missing_fields(self):
        items = [_jf_item(
            name="Unknown",
            overview="",
            image_tags={},
            provider_ids={},
        )]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert set(result[0].missing_fields) == {
            "title", "description", "poster", "provider_ids",
        }

    def test_media_type_preserved(self):
        items = [_jf_item(name="Unknown")]
        result_tv = find_broken_metadata(items, "tv")
        result_movie = find_broken_metadata(items, "movie")
        assert result_tv[0].media_type == "tv"
        assert result_movie[0].media_type == "movie"

    def test_mixed_items(self):
        items = [
            _jf_item(name="Good Item", item_id="a"),
            _jf_item(name="Unknown", item_id="b"),
            _jf_item(name="Also Good", item_id="c"),
        ]
        result = find_broken_metadata(items, "movie")
        assert len(result) == 1
        assert result[0].jellyfin_id == "b"


# ------------------------------------------------------------------
# LeavingSoonReport properties
# ------------------------------------------------------------------

class TestLeavingSoonReport:
    def test_total_issues(self):
        report = LeavingSoonReport()
        report.false_positives = [
            FalsePositive(title="X", jellyfin_id="1", media_type="tv", reason="test"),
        ]
        report.missing_items = [
            MissingItem(title="Y", arr_id=1, media_type="movie", tag="t"),
        ]
        report.broken_metadata = [
            BrokenMetadata(
                title="Z", jellyfin_id="2", media_type="tv",
                missing_fields=["title"],
            ),
        ]
        assert report.total_issues == 3

    def test_empty_report(self):
        report = LeavingSoonReport()
        assert report.total_issues == 0
        assert report.false_positive_count == 0
        assert report.missing_count == 0
        assert report.broken_count == 0

    def test_individual_counts(self):
        report = LeavingSoonReport()
        report.false_positives = [
            FalsePositive(title="A", jellyfin_id="1", media_type="tv", reason="r"),
            FalsePositive(title="B", jellyfin_id="2", media_type="movie", reason="r"),
        ]
        report.missing_items = [
            MissingItem(title="C", arr_id=1, media_type="tv", tag="t"),
        ]
        report.broken_metadata = [
            BrokenMetadata(
                title="D", jellyfin_id="3", media_type="movie",
                missing_fields=["poster"],
            ),
            BrokenMetadata(
                title="E", jellyfin_id="4", media_type="tv",
                missing_fields=["title"],
            ),
            BrokenMetadata(
                title="F", jellyfin_id="5", media_type="tv",
                missing_fields=["description"],
            ),
        ]
        assert report.false_positive_count == 2
        assert report.missing_count == 1
        assert report.broken_count == 3
        assert report.total_issues == 6


# ------------------------------------------------------------------
# Console output formatting
# ------------------------------------------------------------------

class TestConsoleOutput:
    def test_summary_includes_counts(self):
        report = LeavingSoonReport(
            leaving_soon_tv_count=5,
            leaving_soon_movie_count=10,
            scheduled_tv_count=4,
            scheduled_movie_count=9,
        )
        report.false_positives = [
            FalsePositive(title="FP", jellyfin_id="1", media_type="tv", reason="test"),
        ]
        report.missing_items = [
            MissingItem(title="MI", arr_id=1, media_type="movie", tag="t"),
        ]
        report.broken_metadata = [
            BrokenMetadata(
                title="BM", jellyfin_id="2", media_type="tv",
                missing_fields=["title"],
            ),
        ]
        text = format_console_summary(report)
        assert "Leaving Soon TV shows:  5" in text
        assert "Leaving Soon movies:    10" in text
        assert "Scheduled TV (tagged):  4" in text
        assert "Scheduled movies (tagged): 9" in text
        assert "False positives" in text
        assert "Missing from collection" in text
        assert "Broken/missing metadata" in text
        assert "Total issues: 3" in text

    def test_no_issues_message(self):
        report = LeavingSoonReport()
        text = format_console_summary(report)
        assert "no issues found" in text

    def test_false_positive_details(self):
        report = LeavingSoonReport()
        report.false_positives = [
            FalsePositive(
                title="Orphan Show", jellyfin_id="1",
                media_type="tv", reason="Not tagged for deletion in Sonarr/Radarr",
            ),
        ]
        text = format_console_summary(report)
        assert "[TV] Orphan Show" in text
        assert "Not tagged" in text

    def test_missing_details(self):
        report = LeavingSoonReport()
        report.missing_items = [
            MissingItem(
                title="Hidden Film", arr_id=1,
                media_type="movie", tag="janitorr-leaving-soon",
            ),
        ]
        text = format_console_summary(report)
        assert "[MOVIE] Hidden Film" in text
        assert "janitorr-leaving-soon" in text

    def test_broken_metadata_details(self):
        report = LeavingSoonReport()
        report.broken_metadata = [
            BrokenMetadata(
                title="Bad Item", jellyfin_id="1",
                media_type="movie", missing_fields=["title", "poster"],
            ),
        ]
        text = format_console_summary(report)
        assert "[MOVIE] Bad Item" in text
        assert "title, poster" in text


# ------------------------------------------------------------------
# Markdown report formatting
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_report_contains_expected_sections(self):
        report = LeavingSoonReport(
            leaving_soon_tv_count=3,
            leaving_soon_movie_count=5,
            scheduled_tv_count=2,
            scheduled_movie_count=4,
        )
        report.false_positives = [
            FalsePositive(title="FP", jellyfin_id="1", media_type="tv", reason="test"),
        ]
        report.missing_items = [
            MissingItem(title="MI", arr_id=1, media_type="movie", tag="t"),
        ]
        report.broken_metadata = [
            BrokenMetadata(
                title="BM", jellyfin_id="2", media_type="tv",
                missing_fields=["title"],
            ),
        ]
        md = format_markdown_report(report)
        assert "# Leaving Soon Consistency Report" in md
        assert "## Collection Counts" in md
        assert "## Issue Summary" in md
        assert "## False Positives" in md
        assert "## Missing from Collection" in md
        assert "## Broken/Missing Metadata" in md

    def test_all_consistent_report(self):
        report = LeavingSoonReport()
        md = format_markdown_report(report)
        assert "no issues found" in md

    def test_collection_counts_in_table(self):
        report = LeavingSoonReport(
            leaving_soon_tv_count=3,
            leaving_soon_movie_count=7,
            scheduled_tv_count=2,
            scheduled_movie_count=6,
        )
        md = format_markdown_report(report)
        assert "| Leaving Soon TV shows | 3 |" in md
        assert "| Leaving Soon movies | 7 |" in md
        assert "| Scheduled TV (tagged in Sonarr) | 2 |" in md
        assert "| Scheduled movies (tagged in Radarr) | 6 |" in md

    def test_summary_table_counts(self):
        report = LeavingSoonReport()
        report.false_positives = [
            FalsePositive(title="X", jellyfin_id="1", media_type="tv", reason="r"),
            FalsePositive(title="Y", jellyfin_id="2", media_type="movie", reason="r"),
        ]
        md = format_markdown_report(report)
        assert "| False positives | 2 |" in md

    def test_false_positive_table(self):
        report = LeavingSoonReport()
        report.false_positives = [
            FalsePositive(
                title="Stale Show", jellyfin_id="1",
                media_type="tv", reason="Not tagged",
            ),
        ]
        md = format_markdown_report(report)
        assert "| TV | Stale Show | Not tagged |" in md

    def test_missing_item_table(self):
        report = LeavingSoonReport()
        report.missing_items = [
            MissingItem(
                title="Hidden Film", arr_id=1,
                media_type="movie", tag="janitorr-leaving-soon",
            ),
        ]
        md = format_markdown_report(report)
        assert "| MOVIE | Hidden Film | janitorr-leaving-soon |" in md

    def test_broken_metadata_table(self):
        report = LeavingSoonReport()
        report.broken_metadata = [
            BrokenMetadata(
                title="Bad Movie", jellyfin_id="1",
                media_type="movie", missing_fields=["poster", "description"],
            ),
        ]
        md = format_markdown_report(report)
        assert "| MOVIE | Bad Movie | poster, description |" in md

    def test_issue_summary_total(self):
        report = LeavingSoonReport()
        report.false_positives = [
            FalsePositive(title="A", jellyfin_id="1", media_type="tv", reason="r"),
        ]
        report.missing_items = [
            MissingItem(title="B", arr_id=1, media_type="movie", tag="t"),
        ]
        report.broken_metadata = [
            BrokenMetadata(
                title="C", jellyfin_id="2", media_type="tv",
                missing_fields=["title"],
            ),
        ]
        md = format_markdown_report(report)
        assert "**3**" in md
