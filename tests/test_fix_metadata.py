"""Tests for the Jellyfin metadata fix script (US-007).

All tests use mock API data — no live services required.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fix_metadata import (
    FixAttempt,
    FixReport,
    fix_mismatch,
    run_fixes,
    format_console_summary_fix,
    format_markdown_report,
    _extract_external_id,
    _get_provider_for_type,
)
from metadata_checker import Mismatch, MetadataReport


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mismatch(
    title: str = "Test Show",
    jf_id: str = "jf1",
    media_type: str = "tv",
    field: str = "title",
    jf_value: str = "Test Show",
    arr_value: str = "Test Show Correct",
    arr_title: str = "Test Show Correct",
) -> Mismatch:
    """Build a mock Mismatch."""
    return Mismatch(
        jellyfin_title=title,
        jellyfin_id=jf_id,
        media_type=media_type,
        field=field,
        jellyfin_value=jf_value,
        arr_value=arr_value,
        arr_title=arr_title,
    )


def _mock_jellyfin() -> MagicMock:
    """Build a mock JellyfinClient."""
    client = MagicMock()
    client.refresh_item.return_value = None
    client.search_remote.return_value = [{"Name": "Result"}]
    client.apply_search_result.return_value = None
    return client


# ------------------------------------------------------------------
# _extract_external_id
# ------------------------------------------------------------------

class TestExtractExternalId:
    def test_tvdb_format(self):
        assert _extract_external_id("tvdb:81189") == "81189"

    def test_tmdb_format(self):
        assert _extract_external_id("tmdb:603") == "603"

    def test_plain_number(self):
        assert _extract_external_id("12345") == "12345"

    def test_empty_string(self):
        assert _extract_external_id("") == ""


# ------------------------------------------------------------------
# _get_provider_for_type
# ------------------------------------------------------------------

class TestGetProviderForType:
    def test_tv(self):
        name, field = _get_provider_for_type("tv")
        assert name == "Tvdb"
        assert field == "tvdbId"

    def test_movie(self):
        name, field = _get_provider_for_type("movie")
        assert name == "Tmdb"
        assert field == "tmdbId"


# ------------------------------------------------------------------
# fix_mismatch
# ------------------------------------------------------------------

class TestFixMismatch:
    def test_dry_run_always_succeeds(self):
        m = _mismatch(field="title")
        jf = _mock_jellyfin()
        result = fix_mismatch(jf, m, dry_run=True)
        assert result.success is True
        assert result.dry_run is True
        assert result.action == "refresh"
        jf.refresh_item.assert_not_called()
        jf.search_remote.assert_not_called()

    def test_title_mismatch_triggers_refresh(self):
        m = _mismatch(field="title")
        jf = _mock_jellyfin()
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is True
        assert result.action == "refresh"
        jf.refresh_item.assert_called_once_with("jf1")

    def test_year_mismatch_triggers_refresh(self):
        m = _mismatch(field="year", jf_value="2020", arr_value="2019")
        jf = _mock_jellyfin()
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is True
        assert result.action == "refresh"
        jf.refresh_item.assert_called_once_with("jf1")

    def test_external_id_mismatch_triggers_identify(self):
        m = _mismatch(
            field="external_id",
            jf_value="(none)",
            arr_value="tvdb:81189",
            media_type="tv",
        )
        jf = _mock_jellyfin()
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is True
        assert result.action == "identify"
        jf.search_remote.assert_called_once_with(
            item_id="jf1",
            media_type="tv",
            provider_id="81189",
            provider_name="Tvdb",
        )
        jf.apply_search_result.assert_called_once_with("jf1")

    def test_external_id_movie_uses_tmdb(self):
        m = _mismatch(
            field="external_id",
            jf_value="(none)",
            arr_value="tmdb:603",
            media_type="movie",
        )
        jf = _mock_jellyfin()
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is True
        jf.search_remote.assert_called_once_with(
            item_id="jf1",
            media_type="movie",
            provider_id="603",
            provider_name="Tmdb",
        )

    def test_identify_no_results_fails(self):
        m = _mismatch(
            field="external_id",
            jf_value="(none)",
            arr_value="tvdb:99999",
            media_type="tv",
        )
        jf = _mock_jellyfin()
        jf.search_remote.return_value = []
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is False
        assert "No remote search results" in result.error
        jf.apply_search_result.assert_not_called()

    def test_refresh_exception_captured(self):
        m = _mismatch(field="title")
        jf = _mock_jellyfin()
        jf.refresh_item.side_effect = Exception("Connection refused")
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is False
        assert "Connection refused" in result.error

    def test_search_remote_exception_captured(self):
        m = _mismatch(
            field="external_id",
            jf_value="(none)",
            arr_value="tvdb:12345",
            media_type="tv",
        )
        jf = _mock_jellyfin()
        jf.search_remote.side_effect = Exception("Timeout")
        result = fix_mismatch(jf, m, dry_run=False)
        assert result.success is False
        assert "Timeout" in result.error


# ------------------------------------------------------------------
# run_fixes
# ------------------------------------------------------------------

class TestRunFixes:
    def _mock_clients(self, mismatches: list[Mismatch] | None = None):
        """Return (jellyfin, sonarr, radarr) mocks with a pre-configured report."""
        jf = _mock_jellyfin()
        sonarr = MagicMock()
        radarr = MagicMock()

        pre_report = MetadataReport()
        pre_report.mismatches = mismatches or []

        post_report = MetadataReport()
        # Post-check returns no mismatches (all fixed)

        return jf, sonarr, radarr, pre_report, post_report

    @patch("fix_metadata.run_metadata_check")
    def test_no_mismatches_returns_empty(self, mock_check):
        mock_check.return_value = MetadataReport()
        jf, sonarr, radarr = _mock_jellyfin(), MagicMock(), MagicMock()

        report = run_fixes(jf, sonarr, radarr)
        assert report.total_attempted == 0
        assert report.total_succeeded == 0

    @patch("fix_metadata.run_metadata_check")
    def test_fixes_title_mismatch(self, mock_check):
        pre = MetadataReport()
        pre.mismatches = [_mismatch(field="title")]
        post = MetadataReport()

        mock_check.side_effect = [pre, post]

        jf = _mock_jellyfin()
        sonarr, radarr = MagicMock(), MagicMock()

        report = run_fixes(jf, sonarr, radarr, dry_run=False)
        assert report.total_attempted == 1
        assert report.total_succeeded == 1
        jf.refresh_item.assert_called_once()
        # Pre and post checks both executed
        assert mock_check.call_count == 2

    @patch("fix_metadata.run_metadata_check")
    def test_dry_run_skips_post_check(self, mock_check):
        pre = MetadataReport()
        pre.mismatches = [_mismatch(field="title")]

        mock_check.return_value = pre

        jf = _mock_jellyfin()
        sonarr, radarr = MagicMock(), MagicMock()

        report = run_fixes(jf, sonarr, radarr, dry_run=True)
        assert report.total_attempted == 1
        assert report.total_succeeded == 1
        assert report.dry_run is True
        assert report.post_check is None
        # Only pre-check, no post-check
        assert mock_check.call_count == 1
        jf.refresh_item.assert_not_called()

    @patch("fix_metadata.run_metadata_check")
    def test_multiple_mismatches(self, mock_check):
        pre = MetadataReport()
        pre.mismatches = [
            _mismatch(field="title", jf_id="a", title="Show A"),
            _mismatch(field="year", jf_id="b", title="Show B"),
            _mismatch(
                field="external_id", jf_id="c", title="Show C",
                jf_value="(none)", arr_value="tvdb:111",
            ),
        ]
        post = MetadataReport()

        mock_check.side_effect = [pre, post]

        jf = _mock_jellyfin()
        sonarr, radarr = MagicMock(), MagicMock()

        report = run_fixes(jf, sonarr, radarr)
        assert report.total_attempted == 3
        assert report.total_succeeded == 3
        # 2 refresh calls (title + year) and 1 identify flow
        assert jf.refresh_item.call_count == 2
        assert jf.search_remote.call_count == 1
        assert jf.apply_search_result.call_count == 1

    @patch("fix_metadata.run_metadata_check")
    def test_partial_failure(self, mock_check):
        pre = MetadataReport()
        pre.mismatches = [
            _mismatch(field="title", jf_id="ok"),
            _mismatch(field="title", jf_id="fail"),
        ]
        post = MetadataReport()

        mock_check.side_effect = [pre, post]

        jf = _mock_jellyfin()
        # Second refresh call fails
        jf.refresh_item.side_effect = [None, Exception("Server error")]
        sonarr, radarr = MagicMock(), MagicMock()

        report = run_fixes(jf, sonarr, radarr)
        assert report.total_attempted == 2
        assert report.total_succeeded == 1
        assert report.total_failed == 1


# ------------------------------------------------------------------
# FixReport properties
# ------------------------------------------------------------------

class TestFixReport:
    def test_empty_report(self):
        report = FixReport()
        assert report.total_attempted == 0
        assert report.total_succeeded == 0
        assert report.total_failed == 0

    def test_counts(self):
        report = FixReport()
        report.attempts = [
            FixAttempt("A", "1", "tv", "title", "refresh", success=True),
            FixAttempt("B", "2", "movie", "year", "refresh", success=False, error="err"),
            FixAttempt("C", "3", "tv", "external_id", "identify", success=True),
        ]
        assert report.total_attempted == 3
        assert report.total_succeeded == 2
        assert report.total_failed == 1


# ------------------------------------------------------------------
# Console summary formatting
# ------------------------------------------------------------------

class TestConsoleSummary:
    def test_basic_output(self):
        report = FixReport()
        report.pre_check = MetadataReport()
        report.pre_check.mismatches = [_mismatch()]
        report.attempts = [
            FixAttempt("Show", "1", "tv", "title", "refresh", success=True),
        ]
        text = format_console_summary_fix(report)
        assert "Metadata Fix Results" in text
        assert "Pre-fix mismatches: 1" in text
        assert "Succeeded: 1" in text
        assert "1 of 1 items successfully fixed" in text

    def test_dry_run_label(self):
        report = FixReport(dry_run=True)
        report.attempts = [
            FixAttempt("Show", "1", "tv", "title", "refresh",
                       success=True, dry_run=True),
        ]
        text = format_console_summary_fix(report)
        assert "DRY RUN" in text
        assert "WOULD FIX" in text

    def test_post_check_improvement(self):
        pre = MetadataReport()
        pre.mismatches = [_mismatch(), _mismatch(jf_id="2")]
        post = MetadataReport()
        post.mismatches = [_mismatch(jf_id="2")]

        report = FixReport(dry_run=False)
        report.pre_check = pre
        report.post_check = post
        report.attempts = [
            FixAttempt("A", "1", "tv", "title", "refresh", success=True),
            FixAttempt("B", "2", "tv", "title", "refresh", success=False, error="err"),
        ]
        text = format_console_summary_fix(report)
        assert "Post-fix mismatches: 1" in text
        assert "Improvement: 1 items corrected" in text

    def test_no_attempts(self):
        report = FixReport()
        report.pre_check = MetadataReport()
        text = format_console_summary_fix(report)
        assert "Fix attempts: 0" in text
        assert "0 of 0 items successfully fixed" in text


# ------------------------------------------------------------------
# Markdown report formatting
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_contains_expected_sections(self):
        pre = MetadataReport()
        pre.mismatches = [_mismatch()]
        post = MetadataReport()

        report = FixReport()
        report.pre_check = pre
        report.post_check = post
        report.attempts = [
            FixAttempt("Show", "1", "tv", "title", "refresh", success=True),
        ]
        md = format_markdown_report(report)
        assert "# Metadata Fix Report" in md
        assert "## Pre-Fix Status" in md
        assert "## Fix Attempts" in md
        assert "## Summary" in md
        assert "## Post-Fix Verification" in md

    def test_dry_run_mode_shown(self):
        report = FixReport(dry_run=True)
        report.attempts = [
            FixAttempt("Show", "1", "tv", "title", "refresh",
                       success=True, dry_run=True),
        ]
        md = format_markdown_report(report)
        assert "DRY RUN" in md
        assert "WOULD FIX" in md
        assert "no changes were made" in md

    def test_post_check_shows_remaining(self):
        pre = MetadataReport()
        pre.mismatches = [
            _mismatch(jf_id="1"),
            _mismatch(jf_id="2", title="Other Show"),
        ]
        post = MetadataReport()
        post.mismatches = [
            _mismatch(jf_id="2", title="Other Show"),
        ]

        report = FixReport()
        report.pre_check = pre
        report.post_check = post
        report.attempts = [
            FixAttempt("Show", "1", "tv", "title", "refresh", success=True),
            FixAttempt("Other", "2", "tv", "title", "refresh",
                       success=False, error="err"),
        ]
        md = format_markdown_report(report)
        assert "Remaining mismatched metadata items: **1**" in md
        assert "Before: 2 mismatches" in md
        assert "After: 1 mismatches" in md
        assert "**1** items corrected" in md

    def test_failed_attempt_shows_error(self):
        report = FixReport()
        report.pre_check = MetadataReport()
        report.attempts = [
            FixAttempt("Show", "1", "tv", "title", "refresh",
                       success=False, error="Connection refused"),
        ]
        md = format_markdown_report(report)
        assert "FAILED: Connection refused" in md

    def test_summary_table(self):
        report = FixReport()
        report.attempts = [
            FixAttempt("A", "1", "tv", "title", "refresh", success=True),
            FixAttempt("B", "2", "movie", "year", "refresh", success=True),
            FixAttempt("C", "3", "tv", "external_id", "identify",
                       success=False, error="no results"),
        ]
        md = format_markdown_report(report)
        assert "| Total attempted | 3 |" in md
        assert "| Succeeded | 2 |" in md
        assert "| Failed | 1 |" in md

    def test_result_line(self):
        report = FixReport()
        report.attempts = [
            FixAttempt("A", "1", "tv", "title", "refresh", success=True),
        ]
        md = format_markdown_report(report)
        assert "1 of 1 items successfully fixed" in md
