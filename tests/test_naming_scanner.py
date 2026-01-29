"""Tests for the TRaSH Guide naming compliance scanner."""

from pathlib import Path

import pytest

# Allow imports from the scripts directory
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from naming_scanner import (
    FileResult,
    ScanReport,
    detect_media_type,
    format_console_summary,
    format_markdown_report,
    is_extra_file,
    is_video_file,
    scan_directory,
    validate_movie_filename,
    validate_tv_filename,
)


# ---------------------------------------------------------------------------
# is_video_file
# ---------------------------------------------------------------------------

class TestIsVideoFile:
    @pytest.mark.parametrize("ext", [".mkv", ".mp4", ".avi", ".mov", ".ts"])
    def test_video_extensions_accepted(self, ext):
        assert is_video_file(Path(f"test{ext}")) is True

    @pytest.mark.parametrize("ext", [".srt", ".nfo", ".jpg", ".txt", ".nzb"])
    def test_non_video_extensions_rejected(self, ext):
        assert is_video_file(Path(f"test{ext}")) is False


# ---------------------------------------------------------------------------
# is_extra_file
# ---------------------------------------------------------------------------

class TestIsExtraFile:
    @pytest.mark.parametrize("filename", [
        "Movie (2020)-trailer.mkv",
        "Movie (2020)-sample.mkv",
        "Movie (2020)-behindthescenes.mkv",
        "Movie (2020)-featurette.mkv",
    ])
    def test_extras_detected(self, filename):
        assert is_extra_file(filename) is True

    @pytest.mark.parametrize("filename", [
        "Movie (2020) [Bluray-1080p].mkv",
        "Movie (2020).mkv",
        "Show (2020) - S01E01 - Ep [WEB-1080p].mkv",
    ])
    def test_regular_files_not_flagged(self, filename):
        assert is_extra_file(filename) is False


# ---------------------------------------------------------------------------
# detect_media_type
# ---------------------------------------------------------------------------

class TestDetectMediaType:
    def test_tvshows_detected(self, tmp_path):
        f = tmp_path / "tvshows" / "Show" / "file.mkv"
        assert detect_media_type(f, tmp_path) == "tv"

    def test_tv_detected(self, tmp_path):
        f = tmp_path / "tv" / "Show" / "file.mkv"
        assert detect_media_type(f, tmp_path) == "tv"

    def test_movies_detected(self, tmp_path):
        f = tmp_path / "movies" / "Movie" / "file.mkv"
        assert detect_media_type(f, tmp_path) == "movie"

    def test_unknown_directory_returns_none(self, tmp_path):
        f = tmp_path / "music" / "song.mp3"
        assert detect_media_type(f, tmp_path) is None

    def test_file_outside_root_returns_none(self, tmp_path):
        f = Path("/some/other/path/file.mkv")
        assert detect_media_type(f, tmp_path) is None


# ---------------------------------------------------------------------------
# validate_tv_filename
# ---------------------------------------------------------------------------

class TestValidateTvFilename:
    @pytest.mark.parametrize("filename", [
        # Single bracket group (simple)
        "Breaking Bad (2008) - S01E01 - Pilot [Bluray-1080p].mkv",
        "The Last of Us (2023) - S01E03 - Long Long Time [WEBDL-2160p].mkv",
        "Shogun (2024) - S01E10 - A Dream of a Dream [HDTV-720p].mp4",
        # Three-digit episode number
        "One Piece (1999) - S01E100 - The Start [WEB-1080p].mkv",
        # Proper tag in bracket
        "Dark (2017) - S02E01 - Beginnings and Endings [Remux-1080p Proper].mkv",
        # Multiple bracket groups (real Sonarr TRaSH output)
        "Breaking Bad (2008) - S01E01 - Pilot [Bluray-1080p][DTS 5.1][x264]-CJ.mkv",
        "Fallout (2024) - S01E01 - The End [WEBDL-2160p][EAC3 Atmos 5.1][DV HDR10][h265]-FLUX.mkv",
    ])
    def test_compliant_tv_names(self, filename):
        result = validate_tv_filename(filename)
        assert result.compliant is True
        assert result.media_type == "tv"

    @pytest.mark.parametrize("filename", [
        "breaking.bad.s01e01.720p.mkv",
        "Breaking Bad S01E01.mkv",
        "Breaking Bad - S01E01 - Pilot.mkv",
        "S01E01 - Pilot [720p].mkv",
        "Breaking Bad (2008) S01E01 Pilot [720p].mkv",
    ])
    def test_non_compliant_tv_names(self, filename):
        result = validate_tv_filename(filename)
        assert result.compliant is False
        assert result.media_type == "tv"
        assert result.message != ""

    def test_multi_episode_format(self):
        filename = "Show (2020) - S01E01-E02 - Double Pilot [WEB-1080p].mkv"
        result = validate_tv_filename(filename)
        assert result.compliant is True


# ---------------------------------------------------------------------------
# validate_movie_filename
# ---------------------------------------------------------------------------

class TestValidateMovieFilename:
    @pytest.mark.parametrize("filename", [
        # Simple bracket format
        "The Matrix (1999) [Bluray-1080p].mkv",
        "Dune Part Two (2024) [Remux-2160p].mkv",
        "Oppenheimer (2023) [WEB-1080p Proper].mp4",
        "KPop Demon Hunters (2025) [WEBRip-1080p].mp4",
        # Bare name with year only
        "KPop Demon Hunters (2025).mp4",
        # Full TRaSH Radarr format with imdbid and multiple bracket groups
        "Jobs (2013) [imdbid-tt2357129] - [Remux-1080p][DTS-HD MA 5.1][VC1]-Rus.mkv",
        "Pulp Fiction (1994) [imdbid-tt0110912] - [Bluray-2160p][DTS-HD MA 5.1][DV HDR10][x265]-W4NK3R.mkv",
        "Sonic the Hedgehog 3 (2024) [imdbid-tt18259086] - [Hybrid][Bluray-1080p][EAC3 7.1][x264]-ZoroSenpai.mkv",
        # Edition tag in braces
        "The Lord of the Rings The Return of the King (2003) [imdbid-tt0167260] - {Extended} [Hybrid][Bluray-2160p][TrueHD Atmos 7.1][DV HDR10][x265]-TAoE.mkv",
    ])
    def test_compliant_movie_names(self, filename):
        result = validate_movie_filename(filename)
        assert result.compliant is True
        assert result.media_type == "movie"

    @pytest.mark.parametrize("filename", [
        "The.Matrix.1999.1080p.mkv",
        "The Matrix 1999 [1080p].mkv",
        "matrix.mkv",
        "The Matrix (1999).mkv.part",
    ])
    def test_non_compliant_movie_names(self, filename):
        result = validate_movie_filename(filename)
        assert result.compliant is False
        assert result.media_type == "movie"
        assert result.message != ""


# ---------------------------------------------------------------------------
# scan_directory — with mock filesystem
# ---------------------------------------------------------------------------

class TestScanDirectory:
    def _build_tree(self, tmp_path: Path, files: list[str]) -> None:
        """Create a directory tree from a list of relative paths."""
        for f in files:
            p = tmp_path / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")

    def test_scans_compliant_tv_and_movies(self, tmp_path):
        self._build_tree(tmp_path, [
            "tv/Show (2020)/Season 01/Show (2020) - S01E01 - Pilot [WEB-1080p].mkv",
            "movies/Film (2021)/Film (2021) [Bluray-1080p].mkv",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 2
        assert report.compliant_count == 2
        assert report.compliance_pct == 100.0

    def test_detects_non_compliant_files(self, tmp_path):
        self._build_tree(tmp_path, [
            "tv/bad_show/bad.show.s01e01.mkv",
            "movies/bad_movie/bad.movie.2021.mkv",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 2
        assert report.compliant_count == 0
        assert len(report.non_compliant) == 2

    def test_ignores_non_video_files(self, tmp_path):
        self._build_tree(tmp_path, [
            "tv/Show (2020)/poster.jpg",
            "tv/Show (2020)/Show (2020) - S01E01 - Ep [WEB-1080p].mkv",
            "movies/Film (2021)/Film (2021).nfo",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 1  # only the .mkv

    def test_ignores_non_media_directories(self, tmp_path):
        self._build_tree(tmp_path, [
            "music/Artist/song.mp4",
            "downloads/torrents/file.mkv",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 0

    def test_ignores_trailer_files(self, tmp_path):
        self._build_tree(tmp_path, [
            "movies/Film (2021)/Film (2021) [Bluray-1080p].mkv",
            "movies/Film (2021)/Film (2021)-trailer.mkv",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 1  # trailer skipped

    def test_empty_directory(self, tmp_path):
        report = scan_directory(str(tmp_path))
        assert report.total == 0
        assert report.compliance_pct == 100.0

    def test_nonexistent_directory(self):
        report = scan_directory("/nonexistent/path")
        assert report.total == 0

    def test_full_trash_radarr_naming(self, tmp_path):
        self._build_tree(tmp_path, [
            "movies/Pulp Fiction (1994)/Pulp Fiction (1994) [imdbid-tt0110912] - [Bluray-2160p][DTS-HD MA 5.1][DV HDR10][x265]-W4NK3R.mkv",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 1
        assert report.compliant_count == 1

    def test_full_trash_sonarr_naming(self, tmp_path):
        self._build_tree(tmp_path, [
            "tv/Breaking Bad (2008)/Season 01/Breaking Bad (2008) - S01E01 - Pilot [Bluray-1080p][DTS 5.1][x264]-CJ.mkv",
        ])
        report = scan_directory(str(tmp_path))
        assert report.total == 1
        assert report.compliant_count == 1


# ---------------------------------------------------------------------------
# ScanReport properties
# ---------------------------------------------------------------------------

class TestScanReport:
    def test_properties_with_mixed_results(self):
        report = ScanReport(media_root="/test")
        report.results = [
            FileResult(path="/a", filename="a", media_type="tv",
                       compliant=True, expected_pattern="..."),
            FileResult(path="/b", filename="b", media_type="movie",
                       compliant=False, expected_pattern="...", message="bad"),
            FileResult(path="/c", filename="c", media_type="tv",
                       compliant=True, expected_pattern="..."),
        ]
        assert report.total == 3
        assert report.compliant_count == 2
        assert len(report.non_compliant) == 1
        assert report.compliance_pct == pytest.approx(66.7, abs=0.1)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

class TestConsoleOutput:
    def test_summary_includes_counts(self):
        report = ScanReport(media_root="/media")
        report.results = [
            FileResult(path="/a", filename="a.mkv", media_type="tv",
                       compliant=True, expected_pattern="..."),
            FileResult(path="/b", filename="b.mkv", media_type="movie",
                       compliant=False, expected_pattern="...", message="bad"),
        ]
        text = format_console_summary(report)
        assert "1 of 2 files compliant" in text
        assert "50.0%" in text
        assert "Non-compliant files:" in text
        assert "b.mkv" in text

    def test_all_compliant_message(self):
        report = ScanReport(media_root="/media")
        report.results = [
            FileResult(path="/a", filename="a.mkv", media_type="tv",
                       compliant=True, expected_pattern="..."),
        ]
        text = format_console_summary(report)
        assert "All files are compliant!" in text


class TestMarkdownReport:
    def test_report_contains_expected_sections(self):
        report = ScanReport(media_root="/media")
        report.results = [
            FileResult(path="/a", filename="a.mkv", media_type="tv",
                       compliant=False, expected_pattern="...", message="bad"),
        ]
        md = format_markdown_report(report)
        assert "# Naming Compliance Report" in md
        assert "## Expected Patterns" in md
        assert "## Non-Compliant Files" in md
        assert "## All Scanned Files" in md
        assert "FAIL" in md

    def test_all_compliant_report(self):
        report = ScanReport(media_root="/media")
        report.results = [
            FileResult(path="/a", filename="a.mkv", media_type="movie",
                       compliant=True, expected_pattern="..."),
        ]
        md = format_markdown_report(report)
        assert "All files are compliant!" in md
        assert "PASS" in md
