#!/usr/bin/env python3
"""TRaSH Guide naming compliance scanner for YAMS media files.

Scans media directories and validates file naming against TRaSH guide
conventions for movies and TV shows.

TRaSH naming patterns:
  TV:    Show Name (Year) - S##E## - Episode Name [Quality][...].ext
  Movie: Movie Name (Year) [imdbid-ttXXX] - [Source][Quality][Audio][...]-Release.ext
         Movie Name (Year) [Quality-Release].ext
         Movie Name (Year).ext

Usage:
  python scripts/naming_scanner.py [--media-root /path/to/media]
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Default media root for the YAMS stack
DEFAULT_MEDIA_ROOT = "/volume4/mediaserver/media"

# Video file extensions to scan
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts",
}

# Files to skip (trailers, samples, extras)
SKIP_SUFFIXES = ("-trailer", "-sample", "-behindthescenes", "-featurette")

# TRaSH naming patterns
#
# TV: Show Name (Year) - S##E## - Episode Name [Quality][Audio][Codec]-Release.ext
# Requires: Name (Year) - S##E## - Title, then one or more bracket groups
TV_PATTERN = re.compile(
    r"^.+\(\d{4}\)\s-\sS\d{2}E\d{2,3}(?:-E\d{2,3})?\s-\s"
    r".+\[.+\](?:\[.+?\])*(?:-\S+)?\.\w+$"
)

# Movie TRaSH patterns (from most specific to least):
#   Full:   Movie (Year) [imdbid-ttXXX] - {Edition} [Source][Quality][Audio][HDR][Codec]-Release.ext
#   Simple: Movie (Year) [Quality-Release].ext
#   Bare:   Movie (Year).ext
MOVIE_PATTERN = re.compile(
    r"^.+\(\d{4}\)"
    r"(?:"
    r"\s\[imdbid-tt\d+\]"          # [imdbid-ttXXX]
    r"\s-\s"                        # separator
    r"(?:\{.+?\}\s)?"               # optional {Edition}
    r"\[.+\](?:\[.+?\])*"          # bracket groups
    r"(?:-\S+)?"                    # optional -Release
    r"|"
    r"\s\[.+?\](?:\[.+?\])*"       # simple bracket groups
    r"(?:-\S+)?"                    # optional -Release
    r")?"
    r"\.\w+$"
)


@dataclass
class FileResult:
    """Result of validating a single file."""
    path: str
    filename: str
    media_type: str  # "tv" or "movie"
    compliant: bool
    expected_pattern: str
    message: str = ""


@dataclass
class ScanReport:
    """Aggregated scan results."""
    media_root: str
    results: list[FileResult] = field(default_factory=list)
    scanned_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def compliant_count(self) -> int:
        return sum(1 for r in self.results if r.compliant)

    @property
    def non_compliant(self) -> list[FileResult]:
        return [r for r in self.results if not r.compliant]

    @property
    def compliance_pct(self) -> float:
        if self.total == 0:
            return 100.0
        return (self.compliant_count / self.total) * 100


def is_video_file(path: Path) -> bool:
    """Check if a path points to a video file."""
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_extra_file(filename: str) -> bool:
    """Check if a file is a trailer, sample, or other extra."""
    stem = Path(filename).stem.lower()
    return any(stem.endswith(suffix) for suffix in SKIP_SUFFIXES)


def detect_media_type(filepath: Path, media_root: Path) -> str | None:
    """Determine if a file is a TV show or movie based on its directory."""
    try:
        rel = filepath.relative_to(media_root)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    top_dir = parts[0].lower()
    if top_dir in ("tvshows", "tv", "tv shows"):
        return "tv"
    if top_dir in ("movies", "movie", "films"):
        return "movie"
    return None


def validate_tv_filename(filename: str) -> FileResult:
    """Validate a TV show filename against TRaSH naming convention."""
    expected = "Show Name (Year) - S##E## - Episode Name [Quality][...].ext"
    if TV_PATTERN.match(filename):
        return FileResult(
            path="",
            filename=filename,
            media_type="tv",
            compliant=True,
            expected_pattern=expected,
        )
    return FileResult(
        path="",
        filename=filename,
        media_type="tv",
        compliant=False,
        expected_pattern=expected,
        message=f"Does not match TV pattern: {expected}",
    )


def validate_movie_filename(filename: str) -> FileResult:
    """Validate a movie filename against TRaSH naming convention."""
    expected = "Movie Name (Year) [imdbid-ttXXX] - [Quality][...]-Release.ext"
    if MOVIE_PATTERN.match(filename):
        return FileResult(
            path="",
            filename=filename,
            media_type="movie",
            compliant=True,
            expected_pattern=expected,
        )
    return FileResult(
        path="",
        filename=filename,
        media_type="movie",
        compliant=False,
        expected_pattern=expected,
        message=f"Does not match movie pattern: {expected}",
    )


def scan_directory(media_root: str) -> ScanReport:
    """Walk the media root and validate every video file found."""
    root = Path(media_root)
    report = ScanReport(media_root=media_root)

    if not root.exists():
        return report

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if not is_video_file(fpath):
                continue
            if is_extra_file(fname):
                continue
            media_type = detect_media_type(fpath, root)
            if media_type is None:
                continue

            if media_type == "tv":
                result = validate_tv_filename(fname)
            else:
                result = validate_movie_filename(fname)

            result.path = str(fpath)
            report.results.append(result)

    return report


def format_console_summary(report: ScanReport) -> str:
    """Format a concise console summary."""
    lines: list[str] = []
    lines.append(f"Naming Compliance Scan — {report.media_root}")
    lines.append(f"Scanned at: {report.scanned_at}")
    lines.append(f"{report.compliant_count} of {report.total} files compliant "
                 f"({report.compliance_pct:.1f}%)")
    lines.append("")

    if report.non_compliant:
        lines.append("Non-compliant files:")
        for r in report.non_compliant:
            lines.append(f"  [{r.media_type.upper()}] {r.path}")
            lines.append(f"    Actual:   {r.filename}")
            lines.append(f"    Expected: {r.expected_pattern}")
        lines.append("")
    else:
        lines.append("All files are compliant!")

    return "\n".join(lines)


def format_markdown_report(report: ScanReport) -> str:
    """Generate a full markdown compliance report."""
    lines: list[str] = []
    lines.append("# Naming Compliance Report")
    lines.append("")
    lines.append(f"**Media root:** `{report.media_root}`")
    lines.append(f"**Scanned at:** {report.scanned_at}")
    lines.append(f"**Total files:** {report.total}")
    lines.append(f"**Compliant:** {report.compliant_count} "
                 f"({report.compliance_pct:.1f}%)")
    lines.append(f"**Non-compliant:** {len(report.non_compliant)}")
    lines.append("")

    lines.append("## Expected Patterns")
    lines.append("")
    lines.append("| Type | TRaSH Pattern |")
    lines.append("|------|---------------|")
    lines.append("| TV   | `Show Name (Year) - S##E## - Episode Name "
                 "[Quality][...].ext` |")
    lines.append("| Movie | `Movie Name (Year) [imdbid-ttXXX] - "
                 "[Quality][...]-Release.ext` |")
    lines.append("")

    if report.non_compliant:
        lines.append("## Non-Compliant Files")
        lines.append("")
        lines.append("| Type | File | Expected Pattern |")
        lines.append("|------|------|------------------|")
        for r in report.non_compliant:
            lines.append(
                f"| {r.media_type.upper()} | `{r.filename}` "
                f"| `{r.expected_pattern}` |"
            )
        lines.append("")
    else:
        lines.append("## Result")
        lines.append("")
        lines.append("All files are compliant!")
        lines.append("")

    if report.results:
        lines.append("## All Scanned Files")
        lines.append("")
        lines.append("| Status | Type | File |")
        lines.append("|--------|------|------|")
        for r in report.results:
            status = "PASS" if r.compliant else "FAIL"
            lines.append(
                f"| {status} | {r.media_type.upper()} | `{r.filename}` |"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TRaSH Guide naming compliance scanner"
    )
    parser.add_argument(
        "--media-root",
        default=DEFAULT_MEDIA_ROOT,
        help=f"Path to the media root directory (default: {DEFAULT_MEDIA_ROOT})",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Directory to save the markdown report",
    )
    args = parser.parse_args()

    report = scan_directory(args.media_root)

    # Console summary
    print(format_console_summary(report))

    # Markdown report
    report_dir = args.report_dir
    if report_dir is None:
        report_dir = str(
            Path(__file__).resolve().parent.parent / "tests" / "reports"
        )

    os.makedirs(report_dir, exist_ok=True)
    report_path = Path(report_dir) / "naming-compliance.md"
    report_path.write_text(format_markdown_report(report))
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
