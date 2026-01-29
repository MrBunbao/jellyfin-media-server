"""Tests for the scheduled YAMS audit runner.

All tests use mock data — no live services required.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scheduled_audit import (
    parse_cron,
    _parse_cron_field,
    cron_matches,
    _convert_dow,
    _get_config,
    _write_health_status,
    run_audit,
    HEALTH_STATUS_FILE,
)
from scripts.audit import AuditResult


# ------------------------------------------------------------------
# Cron expression parser
# ------------------------------------------------------------------

class TestParseCronField:
    def test_star(self):
        assert _parse_cron_field("*", 0, 59) == set(range(0, 60))

    def test_single_value(self):
        assert _parse_cron_field("5", 0, 59) == {5}

    def test_comma_list(self):
        assert _parse_cron_field("1,3,5", 0, 59) == {1, 3, 5}

    def test_range(self):
        assert _parse_cron_field("1-5", 0, 59) == {1, 2, 3, 4, 5}

    def test_step_from_star(self):
        result = _parse_cron_field("*/15", 0, 59)
        assert 0 in result
        assert 15 in result
        assert 30 in result
        assert 45 in result

    def test_step_from_range(self):
        result = _parse_cron_field("1-10/3", 0, 59)
        assert result == {1, 4, 7, 10}

    def test_combo(self):
        result = _parse_cron_field("1,5-7,*/30", 0, 59)
        assert 1 in result
        assert 5 in result
        assert 6 in result
        assert 7 in result
        assert 0 in result
        assert 30 in result


class TestParseCron:
    def test_weekly_sunday(self):
        cron = parse_cron("0 3 * * 0")
        assert cron["minute"] == {0}
        assert cron["hour"] == {3}
        assert cron["dom"] == set(range(1, 32))
        assert cron["month"] == set(range(1, 13))
        assert cron["dow"] == {0}

    def test_daily_midnight(self):
        cron = parse_cron("0 0 * * *")
        assert cron["minute"] == {0}
        assert cron["hour"] == {0}
        assert cron["dow"] == set(range(0, 7))

    def test_every_6_hours(self):
        cron = parse_cron("0 */6 * * *")
        assert cron["hour"] == {0, 6, 12, 18}

    def test_invalid_field_count(self):
        with pytest.raises(ValueError, match="expected 5 fields"):
            parse_cron("* * *")

    def test_weekday_only(self):
        cron = parse_cron("30 9 * * 1-5")
        assert cron["minute"] == {30}
        assert cron["hour"] == {9}
        assert cron["dow"] == {1, 2, 3, 4, 5}


class TestConvertDow:
    def test_sunday(self):
        # Cron 0 (Sun) → Python 6
        assert _convert_dow({0}) == {6}

    def test_monday(self):
        # Cron 1 (Mon) → Python 0
        assert _convert_dow({1}) == {0}

    def test_full_week(self):
        # Cron 0-6 → Python 0-6
        result = _convert_dow({0, 1, 2, 3, 4, 5, 6})
        assert result == {0, 1, 2, 3, 4, 5, 6}


class TestCronMatches:
    def test_sunday_3am_match(self):
        cron = parse_cron("0 3 * * 0")
        # Sunday 2026-02-01 03:00
        dt = datetime(2026, 2, 1, 3, 0)  # Feb 1 2026 is a Sunday
        assert cron_matches(cron, dt) is True

    def test_sunday_3am_no_match_wrong_hour(self):
        cron = parse_cron("0 3 * * 0")
        dt = datetime(2026, 2, 1, 4, 0)
        assert cron_matches(cron, dt) is False

    def test_sunday_3am_no_match_wrong_day(self):
        cron = parse_cron("0 3 * * 0")
        # Monday
        dt = datetime(2026, 2, 2, 3, 0)
        assert cron_matches(cron, dt) is False

    def test_daily_matches_any_day(self):
        cron = parse_cron("0 0 * * *")
        dt = datetime(2026, 1, 15, 0, 0)  # Thursday
        assert cron_matches(cron, dt) is True

    def test_every_15_minutes(self):
        cron = parse_cron("*/15 * * * *")
        assert cron_matches(cron, datetime(2026, 1, 1, 12, 0)) is True
        assert cron_matches(cron, datetime(2026, 1, 1, 12, 15)) is True
        assert cron_matches(cron, datetime(2026, 1, 1, 12, 7)) is False


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

class TestGetConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure the audit-specific env vars aren't set
            for key in ["AUDIT_SCHEDULE", "AUDIT_REPORT_DIR", "AUDIT_WEBHOOK_URL",
                        "AUDIT_RUN_ON_START", "AUDIT_MEDIA_ROOT", "AUDIT_JANITORR_CFG"]:
                os.environ.pop(key, None)
            config = _get_config()
        assert config["schedule"] == "0 3 * * 0"
        assert config["run_on_start"] is True
        assert config["webhook_url"] == ""

    def test_custom_schedule(self):
        with patch.dict(os.environ, {"AUDIT_SCHEDULE": "0 0 * * *"}):
            config = _get_config()
        assert config["schedule"] == "0 0 * * *"

    def test_webhook_url(self):
        with patch.dict(os.environ, {"AUDIT_WEBHOOK_URL": "https://hooks.example.com/abc"}):
            config = _get_config()
        assert config["webhook_url"] == "https://hooks.example.com/abc"

    def test_run_on_start_false(self):
        with patch.dict(os.environ, {"AUDIT_RUN_ON_START": "false"}):
            config = _get_config()
        assert config["run_on_start"] is False

    def test_run_on_start_zero(self):
        with patch.dict(os.environ, {"AUDIT_RUN_ON_START": "0"}):
            config = _get_config()
        assert config["run_on_start"] is False


# ------------------------------------------------------------------
# Health status file
# ------------------------------------------------------------------

class TestHealthStatus:
    def test_writes_healthy_status(self, tmp_path):
        status_file = tmp_path / "health.json"
        result = AuditResult()
        with patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(status_file)):
            _write_health_status(result, "/reports/test.md")

        data = json.loads(status_file.read_text())
        assert data["status"] == "healthy"
        assert data["total_issues"] == 0
        assert data["scanner_errors"] == 0
        assert data["has_issues"] is False

    def test_writes_unhealthy_on_errors(self, tmp_path):
        status_file = tmp_path / "health.json"
        result = AuditResult()
        result.errors["naming"] = "some error"
        with patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(status_file)):
            _write_health_status(result, "/reports/test.md")

        data = json.loads(status_file.read_text())
        assert data["status"] == "unhealthy"
        assert data["scanner_errors"] == 1

    def test_includes_report_path(self, tmp_path):
        status_file = tmp_path / "health.json"
        result = AuditResult()
        with patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(status_file)):
            _write_health_status(result, "/reports/2026-01-28_030000_full-audit.md")

        data = json.loads(status_file.read_text())
        assert data["report_path"] == "/reports/2026-01-28_030000_full-audit.md"


# ------------------------------------------------------------------
# Audit execution
# ------------------------------------------------------------------

class TestRunAudit:
    def test_saves_timestamped_report(self, tmp_path):
        mock_result = AuditResult()
        config = {
            "media_root": "/media",
            "janitorr_config": "/config/janitorr/application.yml",
            "report_dir": str(tmp_path),
            "webhook_url": "",
        }

        with patch("scripts.scheduled_audit.run_all_scanners", return_value=mock_result), \
             patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(tmp_path / "health.json")):
            result = run_audit(config)

        # Should have created a timestamped report and the latest copy
        reports = list(tmp_path.glob("*_full-audit.md"))
        assert len(reports) == 1
        assert reports[0].name.endswith("_full-audit.md")
        # Date prefix format: YYYY-MM-DD_HHMMSS
        prefix = reports[0].name.split("_full-audit.md")[0]
        assert len(prefix) == len("2026-01-28_030000")

        # Latest symlink/copy should also exist
        assert (tmp_path / "full-audit.md").exists()

    def test_writes_health_file(self, tmp_path):
        mock_result = AuditResult()
        health_file = tmp_path / "health.json"
        config = {
            "media_root": "/media",
            "janitorr_config": "/config/janitorr/application.yml",
            "report_dir": str(tmp_path),
            "webhook_url": "",
        }

        with patch("scripts.scheduled_audit.run_all_scanners", return_value=mock_result), \
             patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(health_file)):
            run_audit(config)

        assert health_file.exists()
        data = json.loads(health_file.read_text())
        assert "last_run" in data
        assert "status" in data

    def test_sends_webhook_when_configured(self, tmp_path):
        mock_result = AuditResult()
        config = {
            "media_root": "/media",
            "janitorr_config": "/config/janitorr/application.yml",
            "report_dir": str(tmp_path),
            "webhook_url": "https://hooks.example.com/test",
        }

        mock_post = MagicMock()
        mock_post.return_value.raise_for_status = MagicMock()

        with patch("scripts.scheduled_audit.run_all_scanners", return_value=mock_result), \
             patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(tmp_path / "health.json")), \
             patch("requests.post", mock_post):
            run_audit(config)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://hooks.example.com/test"
        assert "content" in call_args[1]["json"]

    def test_no_webhook_when_not_configured(self, tmp_path):
        mock_result = AuditResult()
        config = {
            "media_root": "/media",
            "janitorr_config": "/config/janitorr/application.yml",
            "report_dir": str(tmp_path),
            "webhook_url": "",
        }

        with patch("scripts.scheduled_audit.run_all_scanners", return_value=mock_result), \
             patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(tmp_path / "health.json")), \
             patch("requests.post") as mock_post:
            run_audit(config)

        mock_post.assert_not_called()

    def test_returns_result(self, tmp_path):
        mock_result = AuditResult()
        config = {
            "media_root": "/media",
            "janitorr_config": "/config/janitorr/application.yml",
            "report_dir": str(tmp_path),
            "webhook_url": "",
        }

        with patch("scripts.scheduled_audit.run_all_scanners", return_value=mock_result), \
             patch("scripts.scheduled_audit.HEALTH_STATUS_FILE", str(tmp_path / "health.json")):
            result = run_audit(config)

        assert isinstance(result, AuditResult)
