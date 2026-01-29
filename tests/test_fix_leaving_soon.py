"""Tests for the Janitorr Leaving Soon fix script (fix_leaving_soon.py).

All tests use mock data — no live services required.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fix_leaving_soon import (
    ConfigFinding,
    FixAction,
    LeavingSoonFixReport,
    format_console_summary,
    format_markdown_report,
    investigate_config,
    refresh_broken_item,
    remove_false_positive,
    run_fixes,
)
from leaving_soon_checker import (
    BrokenMetadata,
    FalsePositive,
    LeavingSoonReport,
    MissingItem,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mock_jellyfin() -> MagicMock:
    """Create a mock JellyfinClient."""
    client = MagicMock()
    client.ping.return_value = True
    client.remove_from_collection.return_value = None
    client.refresh_item.return_value = None
    return client


def _fp(
    title: str = "Stale Show",
    jellyfin_id: str = "fp1",
    media_type: str = "tv",
    reason: str = "Not tagged for deletion in Sonarr/Radarr",
) -> FalsePositive:
    return FalsePositive(
        title=title,
        jellyfin_id=jellyfin_id,
        media_type=media_type,
        reason=reason,
    )


def _broken(
    title: str = "Bad Item",
    jellyfin_id: str = "bm1",
    media_type: str = "movie",
    missing_fields: list[str] | None = None,
) -> BrokenMetadata:
    return BrokenMetadata(
        title=title,
        jellyfin_id=jellyfin_id,
        media_type=media_type,
        missing_fields=missing_fields or ["poster"],
    )


def _pre_check(
    false_positives: list[FalsePositive] | None = None,
    broken_metadata: list[BrokenMetadata] | None = None,
    missing_items: list[MissingItem] | None = None,
    ls_tv: int = 5,
    ls_movie: int = 3,
    sched_tv: int = 4,
    sched_movie: int = 2,
) -> LeavingSoonReport:
    report = LeavingSoonReport(
        leaving_soon_tv_count=ls_tv,
        leaving_soon_movie_count=ls_movie,
        scheduled_tv_count=sched_tv,
        scheduled_movie_count=sched_movie,
    )
    report.false_positives = false_positives or []
    report.broken_metadata = broken_metadata or []
    report.missing_items = missing_items or []
    return report


# ------------------------------------------------------------------
# FixAction / LeavingSoonFixReport data structures
# ------------------------------------------------------------------

class TestLeavingSoonFixReport:
    def test_empty_report_counts(self):
        report = LeavingSoonFixReport()
        assert report.total_attempted == 0
        assert report.total_succeeded == 0
        assert report.total_failed == 0

    def test_counts_with_actions(self):
        report = LeavingSoonFixReport()
        report.actions = [
            FixAction(
                title="A", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=True,
            ),
            FixAction(
                title="B", jellyfin_id="2", media_type="movie",
                action="refresh_metadata", detail="poster",
                success=False, error="fail",
            ),
            FixAction(
                title="C", jellyfin_id="3", media_type="tv",
                action="refresh_metadata", detail="title",
                success=True,
            ),
        ]
        assert report.total_attempted == 3
        assert report.total_succeeded == 2
        assert report.total_failed == 1

    def test_removal_and_refresh_filters(self):
        report = LeavingSoonFixReport()
        report.actions = [
            FixAction(
                title="A", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=True,
            ),
            FixAction(
                title="B", jellyfin_id="2", media_type="movie",
                action="refresh_metadata", detail="poster",
                success=True,
            ),
        ]
        assert len(report.removal_actions) == 1
        assert len(report.refresh_actions) == 1
        assert report.removal_actions[0].title == "A"
        assert report.refresh_actions[0].title == "B"

    def test_dry_run_flag(self):
        report = LeavingSoonFixReport(dry_run=True)
        assert report.dry_run is True


# ------------------------------------------------------------------
# remove_false_positive
# ------------------------------------------------------------------

class TestRemoveFalsePositive:
    def test_removes_from_collection(self):
        client = _mock_jellyfin()
        fp = _fp()
        action = remove_false_positive(client, "col1", fp, dry_run=False)
        assert action.success is True
        assert action.action == "remove_from_collection"
        client.remove_from_collection.assert_called_once_with("col1", ["fp1"])

    def test_dry_run_no_removal(self):
        client = _mock_jellyfin()
        fp = _fp()
        action = remove_false_positive(client, "col1", fp, dry_run=True)
        assert action.success is True
        assert action.dry_run is True
        client.remove_from_collection.assert_not_called()

    def test_api_error_captured(self):
        client = _mock_jellyfin()
        client.remove_from_collection.side_effect = Exception("API timeout")
        fp = _fp()
        action = remove_false_positive(client, "col1", fp, dry_run=False)
        assert action.success is False
        assert "API timeout" in action.error

    def test_preserves_media_type(self):
        client = _mock_jellyfin()
        fp = _fp(media_type="movie")
        action = remove_false_positive(client, "col1", fp, dry_run=True)
        assert action.media_type == "movie"

    def test_detail_is_reason(self):
        client = _mock_jellyfin()
        fp = _fp(reason="Custom reason")
        action = remove_false_positive(client, "col1", fp, dry_run=True)
        assert action.detail == "Custom reason"


# ------------------------------------------------------------------
# refresh_broken_item
# ------------------------------------------------------------------

class TestRefreshBrokenItem:
    def test_refreshes_metadata(self):
        client = _mock_jellyfin()
        bm = _broken()
        action = refresh_broken_item(client, bm, dry_run=False)
        assert action.success is True
        assert action.action == "refresh_metadata"
        client.refresh_item.assert_called_once_with("bm1")

    def test_dry_run_no_refresh(self):
        client = _mock_jellyfin()
        bm = _broken()
        action = refresh_broken_item(client, bm, dry_run=True)
        assert action.success is True
        assert action.dry_run is True
        client.refresh_item.assert_not_called()

    def test_api_error_captured(self):
        client = _mock_jellyfin()
        client.refresh_item.side_effect = Exception("503 Unavailable")
        bm = _broken()
        action = refresh_broken_item(client, bm, dry_run=False)
        assert action.success is False
        assert "503 Unavailable" in action.error

    def test_detail_is_missing_fields(self):
        client = _mock_jellyfin()
        bm = _broken(missing_fields=["title", "poster"])
        action = refresh_broken_item(client, bm, dry_run=True)
        assert action.detail == "title, poster"

    def test_preserves_media_type(self):
        client = _mock_jellyfin()
        bm = _broken(media_type="tv")
        action = refresh_broken_item(client, bm, dry_run=True)
        assert action.media_type == "tv"


# ------------------------------------------------------------------
# investigate_config
# ------------------------------------------------------------------

class TestInvestigateConfig:
    def test_no_findings_for_healthy_config(self):
        config = {
            "exclusion_tags": ["keep", "favorite"],
            "leaving_soon_days": 14,
        }
        pre = _pre_check()
        findings = investigate_config(config, pre)
        assert findings == []

    def test_missing_exclusion_tags(self):
        config = {
            "exclusion_tags": [],
            "leaving_soon_days": 14,
        }
        pre = _pre_check()
        findings = investigate_config(config, pre)
        cats = [f.category for f in findings]
        assert "exclusion_tags" in cats

    def test_short_leaving_soon_window(self):
        config = {
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 3,
        }
        pre = _pre_check()
        findings = investigate_config(config, pre)
        cats = [f.category for f in findings]
        assert "leaving_soon_window" in cats

    def test_sync_issue_detected(self):
        config = {
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        pre = _pre_check(
            false_positives=[_fp()],
            sched_tv=0, sched_movie=0,
        )
        findings = investigate_config(config, pre)
        cats = [f.category for f in findings]
        assert "sync_issue" in cats

    def test_high_false_positive_ratio(self):
        config = {
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        pre = _pre_check(
            false_positives=[_fp(), _fp(jellyfin_id="fp2"), _fp(jellyfin_id="fp3")],
            ls_tv=3, ls_movie=1,
        )
        findings = investigate_config(config, pre)
        cats = [f.category for f in findings]
        assert "high_false_positive_ratio" in cats

    def test_no_false_positives_no_ratio_finding(self):
        config = {
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        pre = _pre_check(false_positives=[], ls_tv=5, ls_movie=3)
        findings = investigate_config(config, pre)
        cats = [f.category for f in findings]
        assert "high_false_positive_ratio" not in cats


# ------------------------------------------------------------------
# run_fixes (integration-level with mocks)
# ------------------------------------------------------------------

class TestRunFixes:
    def _mock_check(self, monkeypatch, pre_check=None):
        """Patch run_leaving_soon_check to return a fixed report."""
        calls = {"count": 0}
        check = pre_check or _pre_check()

        def fake_check(*a, **kw):
            calls["count"] += 1
            return check

        monkeypatch.setattr(
            "fix_leaving_soon.run_leaving_soon_check", fake_check,
        )
        return calls

    def _mock_collection_lookup(self, monkeypatch, tv_id="col_tv", movie_id="col_mv"):
        """Patch _find_collection_id to return fixed IDs."""
        def fake_find(jellyfin, name):
            if "tv" in name.lower() or "show" in name.lower():
                return tv_id
            return movie_id

        monkeypatch.setattr(
            "fix_leaving_soon._find_collection_id", fake_find,
        )

    def test_no_issues_returns_empty(self, monkeypatch):
        self._mock_check(monkeypatch, _pre_check())
        self._mock_collection_lookup(monkeypatch)
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=False,
        )
        assert report.total_attempted == 0
        assert report.pre_check is not None

    def test_false_positives_removed(self, monkeypatch):
        pre = _pre_check(false_positives=[
            _fp(title="Stale 1", jellyfin_id="fp1"),
            _fp(title="Stale 2", jellyfin_id="fp2"),
        ])
        self._mock_check(monkeypatch, pre)
        self._mock_collection_lookup(monkeypatch)
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=False,
        )
        assert report.total_attempted == 2
        assert report.total_succeeded == 2
        assert all(a.action == "remove_from_collection" for a in report.actions)

    def test_broken_metadata_refreshed(self, monkeypatch):
        pre = _pre_check(broken_metadata=[
            _broken(title="Bad 1", jellyfin_id="bm1"),
        ])
        self._mock_check(monkeypatch, pre)
        self._mock_collection_lookup(monkeypatch)
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=False,
        )
        assert report.total_attempted == 1
        assert report.total_succeeded == 1
        assert report.actions[0].action == "refresh_metadata"

    def test_dry_run_no_api_calls(self, monkeypatch):
        pre = _pre_check(
            false_positives=[_fp()],
            broken_metadata=[_broken()],
        )
        self._mock_check(monkeypatch, pre)
        self._mock_collection_lookup(monkeypatch)
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=True,
        )
        assert report.total_succeeded == 2
        assert report.dry_run is True
        client.remove_from_collection.assert_not_called()
        client.refresh_item.assert_not_called()
        # No post-check in dry-run
        assert report.post_check is None

    def test_mixed_fp_and_broken(self, monkeypatch):
        pre = _pre_check(
            false_positives=[_fp()],
            broken_metadata=[_broken()],
        )
        self._mock_check(monkeypatch, pre)
        self._mock_collection_lookup(monkeypatch)
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=False,
        )
        assert report.total_attempted == 2
        assert len(report.removal_actions) == 1
        assert len(report.refresh_actions) == 1

    def test_collection_not_found_skips(self, monkeypatch):
        pre = _pre_check(false_positives=[_fp()])
        self._mock_check(monkeypatch, pre)
        monkeypatch.setattr(
            "fix_leaving_soon._find_collection_id", lambda j, n: None,
        )
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": ["keep"],
            "leaving_soon_days": 14,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=False,
        )
        assert report.total_attempted == 1
        assert report.total_failed == 1
        assert "not found" in report.actions[0].error.lower()

    def test_config_findings_populated(self, monkeypatch):
        pre = _pre_check(false_positives=[_fp()], sched_tv=0, sched_movie=0)
        self._mock_check(monkeypatch, pre)
        self._mock_collection_lookup(monkeypatch)
        client = _mock_jellyfin()
        config = {
            "leaving_soon_tv": "Shows (Leaving Soon)",
            "leaving_soon_movies": "Movies (Leaving Soon)",
            "exclusion_tags": [],
            "leaving_soon_days": 3,
        }
        report = run_fixes(
            client, MagicMock(), MagicMock(), config, dry_run=False,
        )
        assert len(report.config_findings) > 0
        cats = [f.category for f in report.config_findings]
        assert "exclusion_tags" in cats
        assert "leaving_soon_window" in cats
        assert "sync_issue" in cats


# ------------------------------------------------------------------
# Console output formatting
# ------------------------------------------------------------------

class TestConsoleOutput:
    def test_summary_includes_counts(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            false_positives=[_fp()],
            broken_metadata=[_broken()],
        )
        report.actions = [
            FixAction(
                title="Stale", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=True,
            ),
            FixAction(
                title="Bad", jellyfin_id="2", media_type="movie",
                action="refresh_metadata", detail="poster",
                success=True,
            ),
        ]
        text = format_console_summary(report)
        assert "Leaving Soon Fix Results" in text
        assert "Pre-fix false positives: 1" in text
        assert "Pre-fix broken metadata: 1" in text
        assert "Collection removals attempted: 1" in text
        assert "Metadata refreshes attempted: 1" in text
        assert "2 of 2" in text

    def test_dry_run_label(self):
        report = LeavingSoonFixReport(dry_run=True)
        report.pre_check = _pre_check(false_positives=[_fp()])
        report.actions = [
            FixAction(
                title="X", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=True, dry_run=True,
            ),
        ]
        text = format_console_summary(report)
        assert "DRY RUN" in text
        assert "WOULD FIX" in text

    def test_failed_action_shows_error(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(false_positives=[_fp()])
        report.actions = [
            FixAction(
                title="Bad", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=False, error="API error",
            ),
        ]
        text = format_console_summary(report)
        assert "FAILED (API error)" in text

    def test_config_findings_in_output(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        report.config_findings = [
            ConfigFinding(
                category="exclusion_tags",
                description="No exclusion tags",
                recommendation="Add tags",
            ),
        ]
        text = format_console_summary(report)
        assert "exclusion_tags" in text
        assert "No exclusion tags" in text

    def test_post_check_improvement(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            false_positives=[_fp(), _fp(jellyfin_id="fp2")],
            broken_metadata=[_broken()],
        )
        report.post_check = _pre_check()  # clean
        report.actions = [
            FixAction(
                title="X", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="r",
                success=True,
            ),
        ]
        text = format_console_summary(report)
        assert "Post-fix false positives: 0" in text
        assert "Post-fix broken metadata: 0" in text
        assert "2 false positive(s) removed" in text

    def test_empty_report_summary(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        text = format_console_summary(report)
        assert "0 of 0" in text


# ------------------------------------------------------------------
# Markdown report formatting
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_contains_expected_sections(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            false_positives=[_fp()],
            broken_metadata=[_broken()],
        )
        report.config_findings = [
            ConfigFinding(
                category="test", description="desc", recommendation="rec",
            ),
        ]
        report.actions = [
            FixAction(
                title="Stale", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "# Leaving Soon Fix Report" in md
        assert "## Pre-Fix Status" in md
        assert "### False Positives Found" in md
        assert "### Broken Metadata Found" in md
        assert "## Janitorr Configuration Analysis" in md
        assert "## Fix Actions" in md
        assert "## Summary" in md

    def test_dry_run_mode_label(self):
        report = LeavingSoonFixReport(dry_run=True)
        report.pre_check = _pre_check(false_positives=[_fp()])
        report.actions = [
            FixAction(
                title="X", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="reason",
                success=True, dry_run=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "DRY RUN" in md
        assert "WOULD FIX" in md
        assert "Skipped" in md

    def test_action_table_rows(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            false_positives=[_fp()],
            broken_metadata=[_broken()],
        )
        report.actions = [
            FixAction(
                title="Stale Show", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="Not tagged",
                success=True,
            ),
            FixAction(
                title="Bad Movie", jellyfin_id="2", media_type="movie",
                action="refresh_metadata", detail="poster",
                success=False, error="Timeout",
            ),
        ]
        md = format_markdown_report(report)
        assert "TV" in md
        assert "Stale Show" in md
        assert "OK" in md
        assert "MOVIE" in md
        assert "FAILED: Timeout" in md

    def test_post_fix_verification(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            false_positives=[_fp()],
            broken_metadata=[_broken()],
        )
        report.post_check = _pre_check()  # clean
        report.actions = [
            FixAction(
                title="X", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="r",
                success=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "## Post-Fix Verification" in md
        assert "False positives remaining" in md
        assert "Broken metadata remaining" in md
        assert "**1** removed" in md

    def test_summary_table_counts(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        report.actions = [
            FixAction(
                title="A", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="r",
                success=True,
            ),
            FixAction(
                title="B", jellyfin_id="2", media_type="movie",
                action="refresh_metadata", detail="poster",
                success=True,
            ),
            FixAction(
                title="C", jellyfin_id="3", media_type="movie",
                action="refresh_metadata", detail="title",
                success=False, error="err",
            ),
        ]
        md = format_markdown_report(report)
        assert "Collection removals attempted | 1" in md
        assert "Collection removals succeeded | 1" in md
        assert "Metadata refreshes attempted | 2" in md
        assert "Metadata refreshes succeeded | 1" in md
        assert "**3**" in md  # total attempted

    def test_no_actions_message(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        md = format_markdown_report(report)
        assert "No fix actions were needed." in md

    def test_no_config_findings_message(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        md = format_markdown_report(report)
        assert "No configuration issues identified." in md

    def test_config_findings_table(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        report.config_findings = [
            ConfigFinding(
                category="exclusion_tags",
                description="No exclusion tags configured",
                recommendation="Add exclusion tags",
            ),
        ]
        md = format_markdown_report(report)
        assert "exclusion_tags" in md
        assert "No exclusion tags configured" in md
        assert "Add exclusion tags" in md

    def test_result_line(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check()
        report.actions = [
            FixAction(
                title="X", jellyfin_id="1", media_type="tv",
                action="remove_from_collection", detail="r",
                success=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "**Result: 1 of 1 actions successful**" in md

    def test_false_positive_table_in_precheck(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            false_positives=[
                _fp(title="Orphan Show", media_type="tv", reason="Not tagged"),
            ],
        )
        md = format_markdown_report(report)
        assert "| TV | Orphan Show | Not tagged |" in md

    def test_broken_metadata_table_in_precheck(self):
        report = LeavingSoonFixReport()
        report.pre_check = _pre_check(
            broken_metadata=[
                _broken(title="Bad Film", media_type="movie",
                        missing_fields=["poster", "description"]),
            ],
        )
        md = format_markdown_report(report)
        assert "| MOVIE | Bad Film | poster, description |" in md
