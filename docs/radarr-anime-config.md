# Radarr-Anime Configuration (US-005)

## Overview
TRaSH Guides-compliant configuration for Radarr-Anime instance.

## Configuration Details

### Root Folder
- Path: `/data/media/anime-movies`
- Accessible: Yes

### Quality Profile: Remux-1080p - Anime
- **Upgrade Allowed**: Yes
- **Upgrade Until**: Bluray-1080p
- **Minimum Quality**: HDTV-720p (720p and above enabled)
- **Minimum Format Score**: 100
- **Score Set**: anime-radarr

#### Enabled Qualities (by priority):
1. Bluray-1080p
2. Remux-1080p
3. WEB 1080p (HDTV-1080p, WEBRip-1080p, WEBDL-1080p)
4. Bluray-720p
5. WEB 720p (HDTV-720p, WEBRip-720p, WEBDL-720p)

#### Disabled Qualities:
- All 480p and below (SDTV, DVD, WEB 480p, Bluray-480p, Bluray-576p)
- 2160p (not applicable for 1080p anime profile)

### Custom Formats (30 total)
Imported from TRaSH Guides anime-radarr template:

#### Anime Tier Scoring:
- Anime BD Tier 01-08 (1400 to 700 points)
- Anime Web Tier 01-06 (600 to 100 points)
- Remux Tier 01-03 (975, 950, 925 points)

#### Excluded Content:
- Anime Raws: -10000 (unsubbed content)
- Dubs Only: -10000 (no original audio)
- Anime LQ Groups: -10000
- VOSTFR: -10000 (French subs only)

#### Quality Bonuses:
- Uncensored: +100
- 10bit: +50
- Anime Dual Audio: +50

### Naming Scheme (Jellyfin Compatible)
- **Folder Format**: `{Movie CleanTitle} ({Release Year}) [tmdbid-{TmdbId}]`
- **Movie Format**: `{Movie CleanTitle} {(Release Year)} [tmdbid-{TmdbId}] - {{Edition Tags}} {[MediaInfo 3D]}{[Custom Formats]}{[Quality Full]}{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{MediaInfo AudioLanguages}{[MediaInfo VideoDynamicRangeType]}[{Mediainfo VideoCodec }{MediaInfo VideoBitDepth}bit]{-Release Group}`

## Recyclarr Template Used
- `radarr-quality-profile-anime`
- `radarr-custom-formats-anime`
- `radarr-quality-definition-anime`

## Configuration Date
2026-02-03

## Acceptance Criteria Status
- [x] Root folder set to /data/media/anime-movies
- [x] Quality profile Remux-1080p - Anime created
- [x] Anime-specific custom formats imported from TRaSH Guides
- [x] Naming scheme follows TRaSH recommendations for anime movies
- [x] Minimum quality set to HDTV-720p, upgrade until Bluray-1080p
- [x] Browser verification confirms UI changes
