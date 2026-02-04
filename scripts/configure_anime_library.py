#!/usr/bin/env python3
"""Configure Jellyfin Anime library with optimal settings for anime metadata.

US-010: Create Jellyfin Anime Series library

This script ensures the Anime library is configured with:
- AniDB as primary metadata provider
- TheTVDB as secondary metadata provider
- NFO local metadata enabled
- Provider IDs (anidbid, tvdbid, tmdbid) supported via enabled fetchers

Usage:
    python scripts/configure_anime_library.py [--verify-only]
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.jellyfin_client import JellyfinClient


# Expected configuration for anime library
ANIME_LIBRARY_NAME = "Anime"

# Metadata provider order: AniDB first, TheTVDB second
SERIES_METADATA_FETCHERS = [
    "AniDB",
    "TheTVDB",
    "AniList",
    "AniSearch",
    "Missing Episode Fetcher",
    "TVmaze",
    "TheMovieDb",
    "The Open Movie Database",
]

SERIES_IMAGE_FETCHERS = [
    "AniDB",
    "TheTVDB",
    "Fanart",
    "AniList",
    "AniSearch",
    "TVmaze",
    "TheMovieDb",
]

SEASON_METADATA_FETCHERS = [
    "AniDB",
    "TheTVDB",
    "TVmaze",
    "TheMovieDb",
]

SEASON_IMAGE_FETCHERS = [
    "AniDB",
    "TheTVDB",
    "Fanart",
    "AniList",
    "AniSearch",
    "TVmaze",
    "TheMovieDb",
]

EPISODE_METADATA_FETCHERS = [
    "AniDB",
    "TheTVDB",
    "TVmaze",
    "TheMovieDb",
    "The Open Movie Database",
]

EPISODE_IMAGE_FETCHERS = [
    "AniDB",
    "TheTVDB",
    "TVmaze",
    "TheMovieDb",
    "The Open Movie Database",
    "Embedded Image Extractor",
    "Screen Grabber",
]


def get_anime_library(client: JellyfinClient) -> dict | None:
    """Find the Anime library in Jellyfin."""
    libraries = client.get_libraries()
    for lib in libraries:
        if lib["Name"] == ANIME_LIBRARY_NAME:
            return lib
    return None


def verify_configuration(library: dict) -> tuple[bool, list[str]]:
    """Verify the Anime library configuration matches expected settings.

    Returns:
        Tuple of (all_passed, list of error messages)
    """
    errors = []
    opts = library.get("LibraryOptions", {})

    # Check content type
    if library.get("CollectionType") != "tvshows":
        errors.append(f"Content type should be 'tvshows', got '{library.get('CollectionType')}'")

    # Check path
    if library.get("Locations", [None])[0] != "/data/media/anime":
        errors.append(f"Path should be '/data/media/anime', got '{library.get('Locations')}'")

    # Check NFO metadata
    if opts.get("LocalMetadataReaderOrder") != ["Nfo"]:
        errors.append(f"NFO not enabled, got '{opts.get('LocalMetadataReaderOrder')}'")

    if not opts.get("SaveLocalMetadata"):
        errors.append("SaveLocalMetadata should be True")

    # Check metadata provider order
    type_options = opts.get("TypeOptions", [])
    for to in type_options:
        item_type = to["Type"]
        fetchers = to.get("MetadataFetchers", [])

        if item_type == "Series":
            if len(fetchers) < 2:
                errors.append(f"Series has insufficient metadata fetchers: {fetchers}")
            elif fetchers[0] != "AniDB":
                errors.append(f"Series first fetcher should be 'AniDB', got '{fetchers[0]}'")
            elif fetchers[1] != "TheTVDB":
                errors.append(f"Series second fetcher should be 'TheTVDB', got '{fetchers[1]}'")

        elif item_type == "Season":
            if len(fetchers) < 2:
                errors.append(f"Season has insufficient metadata fetchers: {fetchers}")
            elif fetchers[0] != "AniDB":
                errors.append(f"Season first fetcher should be 'AniDB', got '{fetchers[0]}'")
            elif fetchers[1] != "TheTVDB":
                errors.append(f"Season second fetcher should be 'TheTVDB', got '{fetchers[1]}'")

        elif item_type == "Episode":
            if len(fetchers) < 2:
                errors.append(f"Episode has insufficient metadata fetchers: {fetchers}")
            elif fetchers[0] != "AniDB":
                errors.append(f"Episode first fetcher should be 'AniDB', got '{fetchers[0]}'")
            elif fetchers[1] != "TheTVDB":
                errors.append(f"Episode second fetcher should be 'TheTVDB', got '{fetchers[1]}'")

    return len(errors) == 0, errors


def configure_library(client: JellyfinClient, library: dict) -> None:
    """Configure the Anime library with optimal settings."""
    current_options = library["LibraryOptions"]

    # Update TypeOptions with correct metadata provider order
    updated_type_options = []
    for type_opt in current_options.get("TypeOptions", []):
        item_type = type_opt["Type"]

        if item_type == "Series":
            type_opt["MetadataFetchers"] = SERIES_METADATA_FETCHERS
            type_opt["MetadataFetcherOrder"] = SERIES_METADATA_FETCHERS.copy()
            type_opt["ImageFetchers"] = SERIES_IMAGE_FETCHERS
            type_opt["ImageFetcherOrder"] = SERIES_IMAGE_FETCHERS.copy()

        elif item_type == "Season":
            type_opt["MetadataFetchers"] = SEASON_METADATA_FETCHERS
            type_opt["MetadataFetcherOrder"] = SEASON_METADATA_FETCHERS.copy()
            type_opt["ImageFetchers"] = SEASON_IMAGE_FETCHERS
            type_opt["ImageFetcherOrder"] = SEASON_IMAGE_FETCHERS.copy()

        elif item_type == "Episode":
            type_opt["MetadataFetchers"] = EPISODE_METADATA_FETCHERS
            type_opt["MetadataFetcherOrder"] = EPISODE_METADATA_FETCHERS.copy()
            type_opt["ImageFetchers"] = EPISODE_IMAGE_FETCHERS
            type_opt["ImageFetcherOrder"] = EPISODE_IMAGE_FETCHERS.copy()

        updated_type_options.append(type_opt)

    # Build updated options
    updated_options = current_options.copy()
    updated_options["TypeOptions"] = updated_type_options
    updated_options["LocalMetadataReaderOrder"] = ["Nfo"]
    updated_options["SaveLocalMetadata"] = True

    # Apply configuration
    client.update_library_options(library["ItemId"], updated_options)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Jellyfin Anime library")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify configuration, don't make changes",
    )
    args = parser.parse_args()

    client = JellyfinClient()

    # Check connectivity
    if not client.ping():
        print("ERROR: Cannot connect to Jellyfin server")
        return 1

    # Find Anime library
    library = get_anime_library(client)
    if not library:
        print(f"ERROR: Library '{ANIME_LIBRARY_NAME}' not found")
        return 1

    print(f"Found Anime library: {library['ItemId']}")

    # Verify current configuration
    passed, errors = verify_configuration(library)

    if passed:
        print("Configuration verified successfully")
        print("  - Content type: tvshows (Shows)")
        print("  - Path: /data/media/anime")
        print("  - Metadata order: AniDB -> TheTVDB -> ...")
        print("  - NFO local metadata: enabled")
        return 0

    if args.verify_only:
        print("Configuration verification FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1

    # Apply configuration
    print("Applying configuration...")
    configure_library(client, library)

    # Refresh library list and verify
    library = get_anime_library(client)
    passed, errors = verify_configuration(library)

    if passed:
        print("Configuration applied and verified successfully")
        return 0
    else:
        print("Configuration applied but verification failed:")
        for error in errors:
            print(f"  - {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
