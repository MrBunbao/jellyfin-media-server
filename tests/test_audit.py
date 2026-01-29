"""Tests for the full YAMS audit orchestrator.

All tests use mock data — no live services required.
"""

from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit import (
    AuditResult,
    format_console_output,
    format_markdown_report,
    _build_prioritized_actions,
)
from naming_scanner import FileResult, ScanReport
from metadata_checker import MetadataReport, Mismatch, OrphanedItem as MetaOrphan, MissingItem as MetaMissing
from library_health_checker import (
    HealthReport,
    UnknownItem,
    DuplicateGroup,
    OrphanedItem as HealthOrphan,
    PlaceholderPosterItem,
)
from leaving_soon_checker import (
    LeavingSoonReport,
    FalsePositive,
    MissingItem as LSMissing,
    BrokenMetadata,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _clean_audit() -> AuditResult:
    """Build an AuditResult with no issues."""
    result = AuditResult()
    result.naming = ScanReport(media_root="/media")
    result.naming.results = [
        FileResult(path="/media/movies/Good (2020).mkv", filename="Good (2020).mkv",
                   media_type="movie", compliant=True, expected_pattern=""),
    ]
    result.metadata = MetadataReport(
        jellyfin_tv_count=5, jellyfin_movie_count=10,
        sonarr_count=5, radarr_count=10,
    )
    result.health = HealthReport(total_tv_count=5, total_movie_count=10)
    result.leaving_soon = LeavingSoonReport(
        leaving_soon_tv_count=2, leaving_soon_movie_count=3,
        scheduled_tv_count=2, scheduled_movie_count=3,
    )
    return result


def _audit_with_issues() -> AuditResult:
    """Build an AuditResult with issues in every scanner."""
    result = AuditResult()

    # Naming: 1 compliant, 1 non-compliant
    result.naming = ScanReport(media_root="/media")
    result.naming.results = [
        FileResult(path="/media/movies/Good (2020).mkv", filename="Good (2020).mkv",
                   media_type="movie", compliant=True, expected_pattern=""),
        FileResult(path="/media/movies/bad-name.mkv", filename="bad-name.mkv",
                   media_type="movie", compliant=False,
                   expected_pattern="Movie Name (Year) ...",
                   message="Does not match movie pattern"),
    ]

    # Metadata: 1 mismatch, 1 orphan, 1 missing
    result.metadata = MetadataReport(
        jellyfin_tv_count=5, jellyfin_movie_count=10,
        sonarr_count=5, radarr_count=10,
    )
    result.metadata.mismatches = [
        Mismatch(jellyfin_title="Film A", jellyfin_id="jf1",
                 media_type="movie", field="title",
                 jellyfin_value="Film A", arr_value="Film Alpha"),
    ]
    result.metadata.orphaned = [
        MetaOrphan(jellyfin_title="Old Show", jellyfin_id="jf2",
                   media_type="tv", jellyfin_year=2019),
    ]
    result.metadata.missing = [
        MetaMissing(arr_title="New Movie", arr_id=99,
                    media_type="movie", arr_year=2024,
                    external_id="tmdb:12345"),
    ]

    # Health: 1 unknown, 1 duplicate, 1 orphan, 1 poster
    result.health = HealthReport(total_tv_count=5, total_movie_count=10)
    result.health.unknown_items = [
        UnknownItem(jellyfin_title="Unknown", jellyfin_id="h1",
                    media_type="movie", missing_fields=["title"]),
    ]
    result.health.duplicates = [
        DuplicateGroup(provider="Tmdb", provider_id="100",
                       media_type="movie",
                       items=[{"Name": "Dup A", "Id": "a"},
                              {"Name": "Dup B", "Id": "b"}]),
    ]
    result.health.orphaned_items = [
        HealthOrphan(jellyfin_title="Gone", jellyfin_id="h2",
                     media_type="movie", file_path="/media/gone.mkv"),
    ]
    result.health.placeholder_posters = [
        PlaceholderPosterItem(jellyfin_title="NoPic", jellyfin_id="h3",
                              media_type="tv", has_primary_image=False),
    ]

    # Leaving Soon: 1 false positive, 1 missing, 1 broken
    result.leaving_soon = LeavingSoonReport(
        leaving_soon_tv_count=3, leaving_soon_movie_count=2,
        scheduled_tv_count=2, scheduled_movie_count=2,
    )
    result.leaving_soon.false_positives = [
        FalsePositive(title="Not Leaving", jellyfin_id="ls1",
                      media_type="tv",
                      reason="Not tagged for deletion in Sonarr/Radarr"),
    ]
    result.leaving_soon.missing_items = [
        LSMissing(title="Should Be Listed", arr_id=50,
                  media_type="movie", tag="janitorr-leaving-soon"),
    ]
    result.leaving_soon.broken_metadata = [
        BrokenMetadata(title="Broken Item", jellyfin_id="ls2",
                       media_type="tv", missing_fields=["description"]),
    ]

    return result


# ------------------------------------------------------------------
# AuditResult properties
# ------------------------------------------------------------------

class TestAuditResult:
    def test_clean_has_no_issues(self):
        result = _clean_audit()
        assert result.total_issues == 0
        assert result.has_issues is False

    def test_issues_detected(self):
        result = _audit_with_issues()
        assert result.total_issues > 0
        assert result.has_issues is True

    def test_total_counts(self):
        result = _audit_with_issues()
        assert result.files_scanned == 2
        assert result.naming_issues == 1
        assert result.mismatches_found == 1
        assert result.metadata_orphans == 1
        assert result.metadata_missing == 1
        assert result.health_orphans == 1
        assert result.duplicates == 1
        assert result.duplicate_items == 2
        assert result.unknown_metadata == 1
        assert result.placeholder_posters == 1
        assert result.false_positives == 1
        assert result.leaving_soon_missing == 1
        assert result.leaving_soon_broken == 1

    def test_total_issues_sum(self):
        result = _audit_with_issues()
        # naming: 1, metadata: 3, health: 4, leaving_soon: 3 = 11
        assert result.total_issues == 11

    def test_errors_flag_has_issues(self):
        result = _clean_audit()
        result.errors["naming"] = "some error"
        assert result.has_issues is True

    def test_none_scanners_safe(self):
        result = AuditResult()
        assert result.files_scanned == 0
        assert result.naming_issues == 0
        assert result.mismatches_found == 0
        assert result.total_issues == 0
        assert result.has_issues is False


# ------------------------------------------------------------------
# Console output
# ------------------------------------------------------------------

class TestConsoleOutput:
    def test_section_headers_present(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "1. Naming Compliance (US-002)" in text
        assert "2. Metadata Accuracy (US-003)" in text
        assert "3. Library Health (US-004)" in text
        assert "4. Leaving Soon Consistency (US-005)" in text
        assert "Summary" in text

    def test_clean_shows_all_clear(self):
        result = _clean_audit()
        text = format_console_output(result)
        assert "ALL CLEAR" in text

    def test_issues_shows_issues_found(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "ISSUES FOUND" in text

    def test_naming_counts(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "Files scanned:    2" in text
        assert "Non-compliant:    1" in text

    def test_metadata_counts(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "Mismatches:       1" in text
        assert "Orphaned:         1" in text
        assert "Missing:          1" in text

    def test_health_counts(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "Unknown metadata: 1" in text
        assert "Duplicates:       1 groups" in text
        assert "Orphaned paths:   1" in text
        assert "Missing posters:  1" in text

    def test_leaving_soon_counts(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "False positives:  1" in text
        assert "Missing from collection: 1" in text
        assert "Broken metadata:  1" in text

    def test_scanner_error_shown(self):
        result = _clean_audit()
        result.naming = None
        result.errors["naming"] = "Traceback...\nFileNotFoundError: missing"
        text = format_console_output(result)
        assert "ERROR:" in text
        assert "FileNotFoundError" in text

    def test_client_error_skips_api_scanners(self):
        result = AuditResult()
        result.errors["clients"] = "ConnectionError: refused"
        text = format_console_output(result)
        assert "SKIPPED" in text

    def test_summary_total_issues(self):
        result = _audit_with_issues()
        text = format_console_output(result)
        assert "Total issues:        11" in text


# ------------------------------------------------------------------
# Markdown report
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_report_title(self):
        result = _clean_audit()
        md = format_markdown_report(result)
        assert "# YAMS Full Audit Report" in md

    def test_total_counts_table(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "## Total Counts" in md
        assert "Files scanned (naming) | 2" in md
        assert "Naming non-compliant | 1" in md
        assert "Metadata mismatches | 1" in md
        assert "**Total issues** | **11**" in md

    def test_prioritized_action_list_present(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "## Prioritized Action List" in md
        assert "Priority" in md

    def test_section_headers(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "## 1. Naming Compliance" in md
        assert "## 2. Metadata Accuracy" in md
        assert "## 3. Library Health" in md
        assert "## 4. Leaving Soon Consistency" in md

    def test_naming_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "bad-name.mkv" in md

    def test_metadata_mismatch_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "Film A" in md
        assert "Film Alpha" in md

    def test_metadata_orphan_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "Old Show" in md

    def test_metadata_missing_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "New Movie" in md
        assert "tmdb:12345" in md

    def test_health_duplicate_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "Tmdb:100" in md
        assert "Dup A" in md

    def test_health_orphan_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "`/media/gone.mkv`" in md

    def test_leaving_soon_false_positive_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "Not Leaving" in md

    def test_leaving_soon_missing_details(self):
        result = _audit_with_issues()
        md = format_markdown_report(result)
        assert "Should Be Listed" in md

    def test_clean_report_no_action_items(self):
        result = _clean_audit()
        md = format_markdown_report(result)
        assert "No issues found" in md

    def test_scanner_error_in_report(self):
        result = AuditResult()
        result.errors["naming"] = "Traceback...\nOSError: bad"
        md = format_markdown_report(result)
        assert "## Scanner Errors" in md
        assert "OSError: bad" in md


# ------------------------------------------------------------------
# Prioritized action list
# ------------------------------------------------------------------

class TestPrioritizedActions:
    def test_empty_when_clean(self):
        result = _clean_audit()
        actions = _build_prioritized_actions(result)
        assert actions == []

    def test_all_categories_present(self):
        result = _audit_with_issues()
        actions = _build_prioritized_actions(result)
        categories = [a[0] for a in actions]
        assert "Orphaned file paths" in categories
        assert "Duplicate entries" in categories
        assert "Metadata mismatches" in categories
        assert "Leaving Soon false positives" in categories
        assert "Missing from Leaving Soon" in categories
        assert "Orphaned in Jellyfin" in categories
        assert "Missing from Jellyfin" in categories
        assert "Unknown / missing metadata" in categories
        assert "Placeholder posters" in categories
        assert "Leaving Soon broken metadata" in categories
        assert "Naming non-compliant" in categories

    def test_orphaned_files_highest_priority(self):
        result = _audit_with_issues()
        actions = _build_prioritized_actions(result)
        assert actions[0][0] == "Orphaned file paths"

    def test_naming_lowest_priority(self):
        result = _audit_with_issues()
        actions = _build_prioritized_actions(result)
        assert actions[-1][0] == "Naming non-compliant"

    def test_counts_accurate(self):
        result = _audit_with_issues()
        actions = _build_prioritized_actions(result)
        action_map = {a[0]: a[1] for a in actions}
        assert action_map["Orphaned file paths"] == 1
        assert action_map["Duplicate entries"] == 2  # item count, not group count
        assert action_map["Metadata mismatches"] == 1
        assert action_map["Naming non-compliant"] == 1
