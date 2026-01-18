# Sonarr Quality Profile Scoring Guide
## TRaSH Guides WEB-DL 1080p Configuration

This configuration is based on TRaSH Guides recommendations for high-quality 1080p WEB-DL TV shows.
Reference: https://trash-guides.info/Sonarr/sonarr-setup-quality-profiles/

### Quality Profile: WEB-DL-1080p (Recommended)

**Profile Configuration:**
- Name: WEB-DL-1080p
- Upgrade Allowed: YES (Enable this!)
- Upgrade Until: WEB-DL-1080p or Bluray-1080p
- Minimum Custom Format Score: 0
- Upgrade Until Custom Format Score: 10000

**Allowed Qualities (in order of preference):**
1. WEB-DL-1080p (WEBDL-1080p)
2. WEBRip-1080p
3. Bluray-1080p (for older shows)
4. WEB-DL-720p (WEBDL-720p)
5. WEBRip-720p

**Blocked Qualities:**
- HDTV-1080p (inferior to WEB-DL)
- HDTV-720p (inferior to WEB-DL)
- DVD
- SDTV
- All 2160p/4K formats (unless you want 4K)

---

## Custom Format Scoring

### ESSENTIAL - Auto-Reject (Negative Scores)

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| LQ | -10000 | Block low-quality release groups |
| LQ (Release Title) | -10000 | Block HDTV, RARBG, YIFY, MeGusta |
| x265 (HD) | -10000 | Block x265 at 1080p (compatibility issues) |
| No-RlsGroup | -10000 | Block releases without proper release group |
| Obfuscated | -10000 | Block obfuscated/fake releases |

### QUALITY PREFERENCE - WEB-DL Tiers

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| WEB Tier 01 | 1800 | Top-tier WEB groups (ABBIE, NTb, NTG, FLUX, etc.) |
| WEB Tier 02 | 1200 | Mid-tier WEB release groups |
| WEB Tier 03 | 600 | Standard WEB release groups |
| WEB Scene | 400 | Scene WEB releases (acceptable quality) |

### AUDIO QUALITY (Optional)

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| TrueHD Atmos | 500 | Highest audio quality |
| DTS X | 480 | High-end audio |
| ATMOS (undefined) | 460 | Atmos audio (codec unknown) |
| DD+ ATMOS | 450 | DD+ with Atmos |
| DTS-HD MA | 390 | DTS Master Audio |
| FLAC | 380 | Lossless audio |
| TrueHD | 400 | Lossless audio |
| DD+ | 120 | Good WEB-DL audio (most common) |
| DD | 100 | Acceptable audio |
| AAC | 80 | Basic but acceptable |

### VIDEO QUALITY (Optional)

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| HDR (undefined) | 100 | Basic HDR |
| DV HDR10 | 90 | Dolby Vision with HDR10 |
| DV | 80 | Dolby Vision only |
| HDR10+ | 70 | HDR10+ |

### MISC (Optional)

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| Season Pack | 15 | Slight preference for season packs |
| Retags | -5 | Slight penalty for retags |

---

## How This Works for TV Shows

### Example 1: Latest Episode from Top-Tier Group
- Base Quality: WEB-DL-1080p
- Custom Format: WEB Tier 01 (+1800)
- Custom Format: DD+ ATMOS (+450)
- **Total Score: 2250** - Will be downloaded and kept

### Example 2: Episode from Unknown Group
- Base Quality: WEB-DL-1080p
- No matching release group custom format
- **Total Score: 0** - Will download but can be upgraded

### Example 3: x265 HD Release (BLOCKED)
- Base Quality: WEB-DL-1080p
- Custom Format: x265 (HD) (-10000)
- **Total Score: -10000** - REJECTED, will not download

### Example 4: HDTV Release (BLOCKED)
- Base Quality: HDTV-1080p
- Custom Format: LQ (Release Title) (-10000)
- **Total Score: -10000** - REJECTED, will not download

### Example 5: Season Pack Upgrade
- Base Quality: WEB-DL-1080p
- Custom Format: WEB Tier 01 (+1800)
- Custom Format: Season Pack (+15)
- Custom Format: DD+ (+120)
- **Total Score: 1935** - Will replace individual episodes

---

## TV-Specific Considerations

### Why WEB-DL for TV Shows?
- TV shows are released to streaming services first (WEB-DL)
- WEB-DL is available hours after airing (vs. months for Bluray)
- Quality difference between WEB-DL and Bluray is minimal for TV
- File sizes are reasonable (1-3GB per episode)

### Season Packs vs. Individual Episodes
- Season packs are scored slightly higher (+15)
- Sonarr will upgrade individual episodes to season pack if score is higher
- Season packs must match or exceed the quality of individual episodes

---

## Implementation Strategy

1. **Start Conservative**: Import only the ESSENTIAL auto-reject formats first
2. **Test Downloads**: Verify low-quality releases are being blocked
3. **Add Tiers**: Import WEB Tier formats to prefer better release groups
4. **Fine-tune**: Add audio/video quality formats based on your preferences
5. **Monitor**: Watch your queue for a week and adjust scores as needed

---

## Expected Behavior

With this configuration:
- You will NEVER get: HDTV, RARBG, YIFY, MeGusta, x265 HD, obfuscated releases
- You will PREFER: Top-tier WEB-DL groups with good audio
- You will UPGRADE: From lower-tier groups to top-tier when available
- You will STOP: At the best available 1080p WEB-DL release

---

## Storage Efficiency

This configuration optimizes for:
- Single high-quality copy per episode
- Reasonable file sizes (1-3GB per episode typically)
- Excellent quality-to-size ratio for TV shows
- Fast availability (WEB-DL releases quickly)
- Compatibility with most devices (no x265 HD)

---

## Typical File Sizes

- 30-minute show: 1-1.5GB per episode
- 60-minute show: 2-3GB per episode
- Full season (22 episodes): 25-45GB
- Full season (10 episodes): 15-25GB
