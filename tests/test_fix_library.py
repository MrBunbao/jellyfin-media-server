"""Tests for the Jellyfin library cleanup script (fix_library.py).

All tests use mock data — no live services required.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fix_library import (
    CleanupReport,
    RemovalAction,
    format_console_summary,
    format_markdown_report,
    pick_best_item,
    remove_duplicate,
    remove_orphaned,
    run_cleanup,
)
from library_health_checker import (
    DuplicateGroup,
    HealthReport,
    OrphanedItem,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mock_jellyfin() -> MagicMock:
    """Create a mock JellyfinClient."""
    client = MagicMock()
    client.ping.return_value = True
    client.delete_item.return_value = None
    return client


def _orphan(
    title: str = "Gone Movie",
    item_id: str = "orphan1",
    media_type: str = "movie",
    file_path: str = "/media/movies/gone.mkv",
) -> OrphanedItem:
    return OrphanedItem(
        jellyfin_title=title,
        jellyfin_id=item_id,
        media_type=media_type,
        file_path=file_path,
    )


def _dup_group(
    provider: str = "Tmdb",
    provider_id: str = "100",
    media_type: str = "movie",
    items: list[dict] | None = None,
) -> DuplicateGroup:
    if items is None:
        items = [
            {"Name": "Movie A", "Id": "dup1", "ProductionYear": 2020},
            {"Name": "Movie A (copy)", "Id": "dup2", "ProductionYear": 2020},
        ]
    return DuplicateGroup(
        provider=provider,
        provider_id=provider_id,
        media_type=media_type,
        items=items,
    )


# ------------------------------------------------------------------
# RemovalAction / CleanupReport data structures
# ------------------------------------------------------------------

class TestCleanupReport:
    def test_empty_report_counts(self):
        report = CleanupReport()
        assert report.total_attempted == 0
        assert report.total_succeeded == 0
        assert report.total_failed == 0

    def test_counts_with_actions(self):
        report = CleanupReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="A", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True,
            ),
            RemovalAction(
                jellyfin_title="B", jellyfin_id="2", media_type="movie",
                reason="duplicate", detail="Tmdb:100", success=False, error="fail",
            ),
            RemovalAction(
                jellyfin_title="C", jellyfin_id="3", media_type="tv",
                reason="orphaned", detail="/path2", success=True,
            ),
        ]
        assert report.total_attempted == 3
        assert report.total_succeeded == 2
        assert report.total_failed == 1

    def test_orphan_and_duplicate_filters(self):
        report = CleanupReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="A", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True,
            ),
            RemovalAction(
                jellyfin_title="B", jellyfin_id="2", media_type="movie",
                reason="duplicate", detail="Tmdb:100", success=True,
            ),
        ]
        assert len(report.orphan_actions) == 1
        assert len(report.duplicate_actions) == 1
        assert report.orphan_actions[0].jellyfin_title == "A"
        assert report.duplicate_actions[0].jellyfin_title == "B"

    def test_dry_run_flag(self):
        report = CleanupReport(dry_run=True)
        assert report.dry_run is True


# ------------------------------------------------------------------
# remove_orphaned
# ------------------------------------------------------------------

class TestRemoveOrphaned:
    def test_removes_orphan_when_file_missing(self):
        client = _mock_jellyfin()
        orphan = _orphan()
        action = remove_orphaned(
            client, orphan, dry_run=False,
            path_exists_fn=lambda p: False,
        )
        assert action.success is True
        assert action.reason == "orphaned"
        client.delete_item.assert_called_once_with("orphan1")

    def test_skips_when_file_restored(self):
        client = _mock_jellyfin()
        orphan = _orphan()
        action = remove_orphaned(
            client, orphan, dry_run=False,
            path_exists_fn=lambda p: True,
        )
        assert action.success is False
        assert "now exists" in action.error
        client.delete_item.assert_not_called()

    def test_dry_run_no_delete(self):
        client = _mock_jellyfin()
        orphan = _orphan()
        action = remove_orphaned(
            client, orphan, dry_run=True,
            path_exists_fn=lambda p: False,
        )
        assert action.success is True
        assert action.dry_run is True
        client.delete_item.assert_not_called()

    def test_api_error_captured(self):
        client = _mock_jellyfin()
        client.delete_item.side_effect = Exception("API timeout")
        orphan = _orphan()
        action = remove_orphaned(
            client, orphan, dry_run=False,
            path_exists_fn=lambda p: False,
        )
        assert action.success is False
        assert "API timeout" in action.error

    def test_preserves_media_type(self):
        client = _mock_jellyfin()
        orphan = _orphan(media_type="tv")
        action = remove_orphaned(
            client, orphan, dry_run=True,
            path_exists_fn=lambda p: False,
        )
        assert action.media_type == "tv"

    def test_detail_is_file_path(self):
        client = _mock_jellyfin()
        orphan = _orphan(file_path="/media/tv/show/s01e01.mkv")
        action = remove_orphaned(
            client, orphan, dry_run=True,
            path_exists_fn=lambda p: False,
        )
        assert action.detail == "/media/tv/show/s01e01.mkv"


# ------------------------------------------------------------------
# remove_duplicate
# ------------------------------------------------------------------

class TestRemoveDuplicate:
    def test_removes_duplicate_item(self):
        client = _mock_jellyfin()
        action = remove_duplicate(
            client, item_id="dup2", item_name="Movie A (copy)",
            media_type="movie", provider_info="Tmdb:100",
        )
        assert action.success is True
        assert action.reason == "duplicate"
        client.delete_item.assert_called_once_with("dup2")

    def test_dry_run_no_delete(self):
        client = _mock_jellyfin()
        action = remove_duplicate(
            client, item_id="dup2", item_name="Movie A (copy)",
            media_type="movie", provider_info="Tmdb:100", dry_run=True,
        )
        assert action.success is True
        assert action.dry_run is True
        client.delete_item.assert_not_called()

    def test_api_error_captured(self):
        client = _mock_jellyfin()
        client.delete_item.side_effect = Exception("403 Forbidden")
        action = remove_duplicate(
            client, item_id="dup2", item_name="Movie A (copy)",
            media_type="movie", provider_info="Tmdb:100",
        )
        assert action.success is False
        assert "403 Forbidden" in action.error

    def test_detail_is_provider_info(self):
        client = _mock_jellyfin()
        action = remove_duplicate(
            client, item_id="dup2", item_name="Copy",
            media_type="tv", provider_info="Tvdb:500", dry_run=True,
        )
        assert action.detail == "Tvdb:500"
        assert action.media_type == "tv"


# ------------------------------------------------------------------
# pick_best_item
# ------------------------------------------------------------------

class TestPickBestItem:
    def test_picks_item_with_better_metadata(self):
        client = _mock_jellyfin()
        # dup1 has full metadata; dup2 has none
        client.get_item_metadata.side_effect = lambda item_id: {
            "dup1": {
                "Overview": "Great movie.",
                "ImageTags": {"Primary": "hash1"},
                "ProductionYear": 2020,
                "ProviderIds": {"Tmdb": "100", "Imdb": "tt999"},
            },
            "dup2": {
                "Overview": "",
                "ImageTags": {},
                "ProductionYear": None,
                "ProviderIds": {},
            },
        }[item_id]

        group = _dup_group()
        best = pick_best_item(group, client)
        assert best == "dup1"

    def test_picks_second_item_when_better(self):
        client = _mock_jellyfin()
        client.get_item_metadata.side_effect = lambda item_id: {
            "dup1": {
                "Overview": "",
                "ImageTags": {},
                "ProviderIds": {},
            },
            "dup2": {
                "Overview": "Has description",
                "ImageTags": {"Primary": "hash"},
                "ProductionYear": 2020,
                "ProviderIds": {"Tmdb": "100"},
            },
        }[item_id]

        group = _dup_group()
        best = pick_best_item(group, client)
        assert best == "dup2"

    def test_falls_back_to_first_on_tie(self):
        client = _mock_jellyfin()
        # Both items have identical metadata
        meta = {
            "Overview": "Same",
            "ImageTags": {"Primary": "hash"},
            "ProductionYear": 2020,
            "ProviderIds": {"Tmdb": "100"},
        }
        client.get_item_metadata.return_value = meta

        group = _dup_group()
        best = pick_best_item(group, client)
        assert best == "dup1"  # first item wins on tie

    def test_handles_api_error_gracefully(self):
        client = _mock_jellyfin()
        # First item raises; second has metadata
        def side_effect(item_id):
            if item_id == "dup1":
                raise Exception("API error")
            return {
                "Overview": "desc",
                "ImageTags": {"Primary": "hash"},
                "ProductionYear": 2020,
                "ProviderIds": {"Tmdb": "100"},
            }
        client.get_item_metadata.side_effect = side_effect

        group = _dup_group()
        best = pick_best_item(group, client)
        assert best == "dup2"

    def test_triple_duplicate_picks_best(self):
        client = _mock_jellyfin()
        client.get_item_metadata.side_effect = lambda item_id: {
            "a": {"Overview": "", "ImageTags": {}, "ProviderIds": {}},
            "b": {
                "Overview": "Best",
                "ImageTags": {"Primary": "h"},
                "ProductionYear": 2020,
                "ProviderIds": {"Tmdb": "1", "Imdb": "tt1"},
            },
            "c": {"Overview": "OK", "ImageTags": {}, "ProviderIds": {"Tmdb": "1"}},
        }[item_id]

        group = _dup_group(items=[
            {"Name": "A", "Id": "a", "ProductionYear": None},
            {"Name": "B", "Id": "b", "ProductionYear": 2020},
            {"Name": "C", "Id": "c", "ProductionYear": 2020},
        ])
        best = pick_best_item(group, client)
        assert best == "b"


# ------------------------------------------------------------------
# run_cleanup (integration-level with mocks)
# ------------------------------------------------------------------

class TestRunCleanup:
    def _mock_health_check(self, monkeypatch, orphans=None, duplicates=None):
        """Patch run_health_check to return a fixed HealthReport."""
        report = HealthReport()
        report.orphaned_items = orphans or []
        report.duplicates = duplicates or []
        monkeypatch.setattr(
            "fix_library.run_health_check", lambda *a, **kw: report,
        )
        return report

    def test_no_issues_returns_empty(self, monkeypatch):
        self._mock_health_check(monkeypatch)
        client = _mock_jellyfin()
        report = run_cleanup(client, dry_run=False)
        assert report.total_attempted == 0
        assert report.pre_check is not None

    def test_orphans_removed(self, monkeypatch):
        orphans = [
            _orphan(title="Gone 1", item_id="o1"),
            _orphan(title="Gone 2", item_id="o2"),
        ]
        self._mock_health_check(monkeypatch, orphans=orphans)
        client = _mock_jellyfin()

        report = run_cleanup(
            client, dry_run=False, path_exists_fn=lambda p: False,
        )
        assert report.total_attempted == 2
        assert report.total_succeeded == 2
        assert all(a.reason == "orphaned" for a in report.actions)

    def test_orphans_dry_run(self, monkeypatch):
        orphans = [_orphan()]
        self._mock_health_check(monkeypatch, orphans=orphans)
        client = _mock_jellyfin()

        report = run_cleanup(
            client, dry_run=True, path_exists_fn=lambda p: False,
        )
        assert report.total_succeeded == 1
        assert report.dry_run is True
        client.delete_item.assert_not_called()
        # No post-check in dry-run
        assert report.post_check is None

    def test_duplicates_removed(self, monkeypatch):
        dups = [_dup_group()]
        self._mock_health_check(monkeypatch, duplicates=dups)
        client = _mock_jellyfin()
        client.get_item_metadata.return_value = {
            "Overview": "desc",
            "ImageTags": {"Primary": "h"},
            "ProductionYear": 2020,
            "ProviderIds": {"Tmdb": "100"},
        }

        report = run_cleanup(client, dry_run=False)
        # 2 items in group, keep 1, remove 1
        assert report.total_attempted == 1
        assert report.total_succeeded == 1
        assert report.actions[0].reason == "duplicate"

    def test_duplicates_dry_run(self, monkeypatch):
        dups = [_dup_group()]
        self._mock_health_check(monkeypatch, duplicates=dups)
        client = _mock_jellyfin()

        report = run_cleanup(client, dry_run=True)
        assert report.total_succeeded == 1
        client.delete_item.assert_not_called()

    def test_mixed_orphans_and_duplicates(self, monkeypatch):
        orphans = [_orphan()]
        dups = [_dup_group()]
        self._mock_health_check(monkeypatch, orphans=orphans, duplicates=dups)
        client = _mock_jellyfin()
        client.get_item_metadata.return_value = {
            "Overview": "desc",
            "ImageTags": {"Primary": "h"},
            "ProductionYear": 2020,
            "ProviderIds": {"Tmdb": "100"},
        }

        report = run_cleanup(
            client, dry_run=False, path_exists_fn=lambda p: False,
        )
        # 1 orphan + 1 duplicate removal
        assert report.total_attempted == 2
        assert len(report.orphan_actions) == 1
        assert len(report.duplicate_actions) == 1


# ------------------------------------------------------------------
# Console output formatting
# ------------------------------------------------------------------

class TestConsoleOutput:
    def test_summary_includes_counts(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.pre_check.orphaned_items = [_orphan()]
        report.pre_check.duplicates = [_dup_group()]
        report.actions = [
            RemovalAction(
                jellyfin_title="Gone", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path/gone.mkv", success=True,
            ),
            RemovalAction(
                jellyfin_title="Copy", jellyfin_id="2", media_type="movie",
                reason="duplicate", detail="Tmdb:100", success=True,
            ),
        ]
        text = format_console_summary(report)
        assert "Library Cleanup Results" in text
        assert "Pre-cleanup orphaned items: 1" in text
        assert "Pre-cleanup duplicate groups: 1" in text
        assert "Orphan removals attempted: 1" in text
        assert "Duplicate removals attempted: 1" in text
        assert "2 of 2" in text

    def test_dry_run_label(self):
        report = CleanupReport(dry_run=True)
        report.pre_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="X", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True, dry_run=True,
            ),
        ]
        text = format_console_summary(report)
        assert "DRY RUN" in text
        assert "WOULD REMOVE" in text

    def test_failed_action_shows_error(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="Bad", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=False,
                error="API error",
            ),
        ]
        text = format_console_summary(report)
        assert "FAILED (API error)" in text

    def test_post_check_improvement(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.pre_check.orphaned_items = [_orphan(), _orphan(item_id="o2")]
        report.pre_check.duplicates = [_dup_group()]
        report.post_check = HealthReport()
        # After cleanup: 0 orphans, 0 duplicates
        report.actions = [
            RemovalAction(
                jellyfin_title="X", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True,
            ),
        ]
        text = format_console_summary(report)
        assert "Post-cleanup orphaned items: 0" in text
        assert "Post-cleanup duplicate groups: 0" in text
        assert "2 orphans removed" in text

    def test_empty_report_summary(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        text = format_console_summary(report)
        assert "0 of 0" in text


# ------------------------------------------------------------------
# Markdown report formatting
# ------------------------------------------------------------------

class TestMarkdownReport:
    def test_contains_expected_sections(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.pre_check.orphaned_items = [_orphan()]
        report.pre_check.duplicates = [_dup_group()]
        report.actions = [
            RemovalAction(
                jellyfin_title="Gone", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path/gone.mkv", success=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "# Library Cleanup Report" in md
        assert "## Pre-Cleanup Status" in md
        assert "### Orphaned Items Found" in md
        assert "### Duplicate Groups Found" in md
        assert "## Cleanup Actions" in md
        assert "## Summary" in md

    def test_dry_run_mode_label(self):
        report = CleanupReport(dry_run=True)
        report.pre_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="X", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True, dry_run=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "DRY RUN" in md
        assert "WOULD REMOVE" in md
        assert "Skipped" in md

    def test_action_table_rows(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="Film", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/media/film.mkv", success=True,
            ),
            RemovalAction(
                jellyfin_title="Copy", jellyfin_id="2", media_type="tv",
                reason="duplicate", detail="Tvdb:42", success=False,
                error="Not found",
            ),
        ]
        md = format_markdown_report(report)
        assert "MOVIE" in md
        assert "Film" in md
        assert "REMOVED" in md
        assert "TV" in md
        assert "FAILED: Not found" in md

    def test_post_cleanup_verification(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.pre_check.orphaned_items = [_orphan()]
        report.pre_check.duplicates = [_dup_group()]
        report.post_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="X", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "## Post-Cleanup Verification" in md
        assert "Orphaned items remaining" in md
        assert "Duplicate groups remaining" in md
        assert "**1** removed" in md
        assert "**1** resolved" in md

    def test_summary_table_counts(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="A", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/path", success=True,
            ),
            RemovalAction(
                jellyfin_title="B", jellyfin_id="2", media_type="movie",
                reason="duplicate", detail="Tmdb:1", success=True,
            ),
            RemovalAction(
                jellyfin_title="C", jellyfin_id="3", media_type="movie",
                reason="duplicate", detail="Tmdb:2", success=False,
                error="err",
            ),
        ]
        md = format_markdown_report(report)
        assert "Orphan removals attempted | 1" in md
        assert "Orphan removals succeeded | 1" in md
        assert "Duplicate removals attempted | 2" in md
        assert "Duplicate removals succeeded | 1" in md
        assert "**3**" in md  # total attempted

    def test_no_actions_message(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        md = format_markdown_report(report)
        assert "No cleanup actions were needed." in md

    def test_orphaned_path_in_table(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.pre_check.orphaned_items = [
            _orphan(file_path="/data/movies/gone.mkv")
        ]
        report.actions = []
        md = format_markdown_report(report)
        assert "`/data/movies/gone.mkv`" in md

    def test_result_line(self):
        report = CleanupReport()
        report.pre_check = HealthReport()
        report.actions = [
            RemovalAction(
                jellyfin_title="X", jellyfin_id="1", media_type="movie",
                reason="orphaned", detail="/p", success=True,
            ),
        ]
        md = format_markdown_report(report)
        assert "**Result: 1 of 1 removals successful**" in md
