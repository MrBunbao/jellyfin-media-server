# Radarr Quality Profile Scoring Guide
## TRaSH Guides WEB-DL 1080p Configuration

This configuration is based on TRaSH Guides recommendations for high-quality 1080p WEB-DL releases.
Reference: https://trash-guides.info/Radarr/radarr-setup-quality-profiles/

### Quality Profile: HD-1080p (Recommended)

**Profile Configuration:**
- Name: HD-1080p
- Upgrade Allowed: YES (Enable this!)
- Upgrade Until: Bluray-1080p or WEB-DL-1080p
- Minimum Custom Format Score: 0
- Upgrade Until Custom Format Score: 10000

**Allowed Qualities (in order of preference):**
1. Bluray-1080p
2. WEB-DL-1080p (WEBDL-1080p)
3. WEBRip-1080p
4. Bluray-720p
5. WEB-DL-720p (WEBDL-720p)

**Blocked Qualities:**
- BR-DISK (will be blocked via custom format)
- Remux-1080p (too large for most use cases)
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
| BR-DISK | -10000 | Block full Blu-ray discs (huge files) |
| LQ | -10000 | Block low-quality release groups |
| LQ (Release Title) | -10000 | Block CAM, TS, HDTV-720p, YIFY, etc. |
| x265 (HD) | -10000 | Block x265 at 1080p (compatibility issues) |
| No-RlsGroup | -10000 | Block releases without proper release group |
| Obfuscated | -10000 | Block obfuscated/fake releases |

### QUALITY PREFERENCE - WEB-DL Tiers

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| WEB Tier 01 | 1800 | Top-tier WEB release groups (ABBIE, APEX, NTb, etc.) |
| WEB Tier 02 | 1200 | Mid-tier WEB release groups |
| WEB Tier 03 | 600 | Standard WEB release groups |
| BluRay Tier 01 | 1500 | Top-tier Bluray release groups |
| Remux Tier 01 | 2000 | Top-tier Remux groups (if you allow Remux) |

### AUDIO QUALITY (Optional)

| Custom Format | Score | Purpose |
|--------------|-------|---------|
| TrueHD Atmos | 500 | Highest audio quality |
| DTS X | 480 | High-end audio |
| ATMOS (undefined) | 460 | Atmos audio (codec unknown) |
| DD+ ATMOS | 450 | DD+ with Atmos |
| TrueHD | 400 | Lossless audio |
| DTS-HD MA | 390 | DTS Master Audio |
| FLAC | 380 | Lossless audio |
| DD+ | 120 | Good WEB-DL audio |
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
| Remaster | 25 | Prefer remastered versions |
| Hybrid | 10 | Hybrid releases (Bluray + WEB) |
| Retags | -5 | Slight penalty for retags |
| Scene | -10 | Slight penalty for scene releases |

---

## How This Works

### Example 1: WEB-DL-1080p Release from Top Group
- Base Quality: WEB-DL-1080p
- Custom Format: WEB Tier 01 (+1800)
- Custom Format: DD+ ATMOS (+450)
- **Total Score: 2250** - Will be downloaded and kept

### Example 2: WEB-DL-1080p from Unknown Group
- Base Quality: WEB-DL-1080p
- No matching release group custom format
- **Total Score: 0** - Will download but can be upgraded

### Example 3: x265 HD Release (BLOCKED)
- Base Quality: WEB-DL-1080p
- Custom Format: x265 (HD) (-10000)
- **Total Score: -10000** - REJECTED, will not download

### Example 4: YIFY Release (BLOCKED)
- Base Quality: Bluray-1080p
- Custom Format: LQ (Release Title) (-10000)
- **Total Score: -10000** - REJECTED, will not download

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
- You will NEVER get: CAM, TS, YIFY, x265 HD, BR-DISK, obfuscated releases
- You will PREFER: Top-tier WEB-DL groups with good audio
- You will UPGRADE: From lower-tier groups to top-tier when available
- You will STOP: At the best available 1080p WEB-DL or Bluray release

---

## Storage Efficiency

This configuration optimizes for:
- Single high-quality copy per movie
- Reasonable file sizes (5-15GB per movie typically)
- Excellent quality-to-size ratio
- Compatibility with most devices (no x265 HD)
