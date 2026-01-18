# TRaSH Guides Custom Format Implementation Guide
## Step-by-Step Instructions for Radarr and Sonarr

This guide will walk you through implementing TRaSH Guides custom formats in your YAMS stack to ensure you only download one high-quality copy of each movie/show.

---

## Overview

**Current State:**
- Radarr: 46 movies using "Any" quality profile (no custom formats)
- Sonarr: 22 shows using "Any" quality profile (no custom formats)
- UpgradeAllowed = 0 (disabled) - THIS MUST BE CHANGED

**Target State:**
- High-quality 1080p WEB-DL focused configuration
- Auto-reject low-quality releases (CAM, TS, YIFY, etc.)
- Prefer top-tier release groups
- Single copy per movie/show with automatic upgrades to better releases

---

## PHASE 1: Backup Current Configuration

Before making any changes, backup your databases:

```bash
# Stop services
cd /volume1/docker/yams
docker compose stop radarr sonarr

# Create backup directory
mkdir -p /volume1/docker/yams/backups/$(date +%Y%m%d)

# Backup databases
cp /volume1/docker/yams/config/radarr/radarr.db /volume1/docker/yams/backups/$(date +%Y%m%d)/radarr.db.backup
cp /volume1/docker/yams/config/sonarr/sonarr.db /volume1/docker/yams/backups/$(date +%Y%m%d)/sonarr.db.backup

# Restart services
docker compose start radarr sonarr
```

**IMPORTANT**: Wait 30 seconds after restart before proceeding to ensure services are fully running.

---

## PHASE 2: Radarr Configuration

### Step 1: Access Radarr Web UI
- Navigate to: http://10.10.10.10:7878
- Log in with your credentials

### Step 2: Import Custom Formats

For each JSON file in `/volume1/docker/yams/trash-guides-setup/radarr/`, import it into Radarr:

1. Go to **Settings** → **Custom Formats**
2. Click the **+** button to add a new custom format
3. Click **Import** in the modal
4. Copy the contents of the JSON file and paste it into the import box
5. Click **Import** button
6. Repeat for all 31 custom format files

**Import Order (recommended):**

**ESSENTIAL - Auto-Reject Formats (Import these FIRST):**
1. `01-br-disk.json` - Blocks full Blu-ray discs
2. `02-lq.json` - Blocks low-quality groups
3. `03-lq-release-title.json` - Blocks CAM, TS, YIFY, etc.
4. `04-x265-hd.json` - Blocks x265 at 1080p
5. `27-no-rlsgroup.json` - Blocks releases without release group
6. `28-obfuscated.json` - Blocks obfuscated releases

**WEB-DL Tier Formats:**
7. `23-web-tier-01.json` - Top-tier WEB groups
8. `24-web-tier-02.json` - Mid-tier WEB groups
9. `25-web-tier-03.json` - Standard WEB groups
10. `26-bluray-tier-01.json` - Top-tier Bluray groups
11. `22-remux-tier-01.json` - Top-tier Remux groups

**Audio Formats (OPTIONAL):**
12. `10-truehd-atmos.json`
13. `11-dts-x.json`
14. `12-atmos-undefined.json`
15. `13-dd-plus-atmos.json`
16. `14-dts-hd-ma.json`
17. `15-flac.json`
18. `16-truehd.json`
19. `17-dts-hd-hra.json`
20. `18-dd-plus.json`
21. `19-dts-es.json`
22. `20-dd.json`
23. `21-aac.json`

**Video Formats (OPTIONAL):**
24. `05-hdr.json`
25. `07-dv-hdr10.json`
26. `08-dv.json`
27. `09-hdr10-plus.json`

**Misc Formats (OPTIONAL):**
28. `06-remaster.json`
29. `29-retags.json`
30. `30-scene.json`
31. `31-hybrid.json`

### Step 3: Modify HD-1080p Quality Profile

1. Go to **Settings** → **Profiles**
2. Click on the **HD-1080p** profile (Profile ID: 4)
3. Make the following changes:

**Quality Settings:**
- **Upgrade Allowed**: ENABLE (check the box)
- **Upgrade Until**: Set to **Bluray-1080p**
- **Upgrade Until Custom Format Score**: 10000

**Allowed Qualities (check these):**
- Bluray-1080p
- WEB-DL-1080p (WEBDL-1080p)
- WEBRip-1080p
- Bluray-720p
- WEB-DL-720p (WEBDL-720p)

**Blocked Qualities (uncheck these):**
- BR-DISK
- Remux-1080p (unless you want Remux - large files)
- HDTV-1080p
- HDTV-720p
- DVD
- SDTV

### Step 4: Configure Custom Format Scores

Scroll down to the **Custom Formats** section in the quality profile and set these scores:

**ESSENTIAL - Auto-Reject (Negative Scores):**
- BR-DISK: **-10000**
- LQ: **-10000**
- LQ (Release Title): **-10000**
- x265 (HD): **-10000**
- No-RlsGroup: **-10000**
- Obfuscated: **-10000**

**WEB-DL Tier Scores:**
- WEB Tier 01: **1800**
- WEB Tier 02: **1200**
- WEB Tier 03: **600**
- BluRay Tier 01: **1500**
- Remux Tier 01: **2000** (if you imported it)

**Audio Scores (if imported):**
- TrueHD Atmos: **500**
- DTS X: **480**
- ATMOS (undefined): **460**
- DD+ ATMOS: **450**
- TrueHD: **400**
- DTS-HD MA: **390**
- FLAC: **380**
- DD+: **120**
- DD: **100**
- AAC: **80**

**Video Scores (if imported):**
- HDR (undefined): **100**
- DV HDR10: **90**
- DV: **80**
- HDR10+: **70**

**Misc Scores (if imported):**
- Remaster: **25**
- Hybrid: **10**
- Retags: **-5**
- Scene: **-10**

4. Click **Save** at the bottom

### Step 5: Change Existing Movies to New Profile

1. Go to **Movies** → **Mass Editor**
2. Select all 46 movies
3. In the bottom toolbar, click **Edit**
4. Change **Quality Profile** to **HD-1080p**
5. Click **Apply**

---

## PHASE 3: Sonarr Configuration

### Step 1: Access Sonarr Web UI
- Navigate to: http://10.10.10.10:8989
- Log in with your credentials

### Step 2: Import Custom Formats

For each JSON file in `/volume1/docker/yams/trash-guides-setup/sonarr/`, import it into Sonarr:

1. Go to **Settings** → **Custom Formats**
2. Click the **+** button to add a new custom format
3. Click **Import** in the modal
4. Copy the contents of the JSON file and paste it into the import box
5. Click **Import** button
6. Repeat for all 25 custom format files

**Import Order (recommended):**

**ESSENTIAL - Auto-Reject Formats (Import these FIRST):**
1. `01-lq.json` - Blocks low-quality groups
2. `02-lq-release-title.json` - Blocks HDTV, RARBG, YIFY
3. `03-x265-hd.json` - Blocks x265 at 1080p
4. `22-no-rlsgroup.json` - Blocks releases without release group
5. `23-obfuscated.json` - Blocks obfuscated releases

**WEB-DL Tier Formats:**
6. `18-web-tier-01.json` - Top-tier WEB groups
7. `19-web-tier-02.json` - Mid-tier WEB groups
8. `20-web-tier-03.json` - Standard WEB groups
9. `21-web-scene.json` - Scene WEB releases

**Audio Formats (OPTIONAL):**
10. `08-truehd-atmos.json`
11. `09-dts-x.json`
12. `10-atmos-undefined.json`
13. `11-dd-plus-atmos.json`
14. `12-dts-hd-ma.json`
15. `13-flac.json`
16. `14-truehd.json`
17. `15-dd-plus.json`
18. `16-dd.json`
19. `17-aac.json`

**Video Formats (OPTIONAL):**
20. `04-hdr.json`
21. `05-dv-hdr10.json`
22. `06-dv.json`
23. `07-hdr10-plus.json`

**Misc Formats (OPTIONAL):**
24. `24-retags.json`
25. `25-season-pack.json`

### Step 3: Modify HD-1080p Quality Profile

1. Go to **Settings** → **Profiles**
2. Click on the **HD-1080p** profile (Profile ID: 4)
3. Make the following changes:

**Quality Settings:**
- **Upgrade Allowed**: ENABLE (check the box)
- **Upgrade Until**: Set to **WEB-DL-1080p** (WEBDL-1080p)
- **Upgrade Until Custom Format Score**: 10000

**Allowed Qualities (check these):**
- WEB-DL-1080p (WEBDL-1080p)
- WEBRip-1080p
- Bluray-1080p (for older shows)
- WEB-DL-720p (WEBDL-720p)
- WEBRip-720p

**Blocked Qualities (uncheck these):**
- HDTV-1080p
- HDTV-720p
- DVD
- SDTV

### Step 4: Configure Custom Format Scores

Scroll down to the **Custom Formats** section in the quality profile and set these scores:

**ESSENTIAL - Auto-Reject (Negative Scores):**
- LQ: **-10000**
- LQ (Release Title): **-10000**
- x265 (HD): **-10000**
- No-RlsGroup: **-10000**
- Obfuscated: **-10000**

**WEB-DL Tier Scores:**
- WEB Tier 01: **1800**
- WEB Tier 02: **1200**
- WEB Tier 03: **600**
- WEB Scene: **400**

**Audio Scores (if imported):**
- TrueHD Atmos: **500**
- DTS X: **480**
- ATMOS (undefined): **460**
- DD+ ATMOS: **450**
- DTS-HD MA: **390**
- FLAC: **380**
- TrueHD: **400**
- DD+: **120**
- DD: **100**
- AAC: **80**

**Video Scores (if imported):**
- HDR (undefined): **100**
- DV HDR10: **90**
- DV: **80**
- HDR10+: **70**

**Misc Scores (if imported):**
- Season Pack: **15**
- Retags: **-5**

4. Click **Save** at the bottom

### Step 5: Change Existing Shows to New Profile

1. Go to **Series** → **Mass Editor**
2. Select all 22 shows
3. In the bottom toolbar, click **Edit**
4. Change **Quality Profile** to **HD-1080p**
5. Click **Apply**

---

## PHASE 4: Verification and Testing

### Step 1: Verify Custom Formats are Loaded

**Radarr:**
1. Go to **Settings** → **Custom Formats**
2. Verify you see all imported custom formats
3. Click on a few to ensure they have specifications (regex patterns)

**Sonarr:**
1. Go to **Settings** → **Custom Formats**
2. Verify you see all imported custom formats
3. Click on a few to ensure they have specifications (regex patterns)

### Step 2: Test with Manual Search

**Radarr:**
1. Go to a movie in your library
2. Click **Manual Search**
3. Look at the results - you should see:
   - Custom format icons/tags on each release
   - Negative scores on low-quality releases (red X)
   - Positive scores on high-quality releases (green checkmark)
   - Some releases completely blocked (won't appear)

**Sonarr:**
1. Go to a show in your library
2. Click on an episode
3. Click **Manual Search**
4. Look at the results - you should see:
   - Custom format icons/tags on each release
   - Negative scores on low-quality releases (red X)
   - Positive scores on high-quality releases (green checkmark)
   - Some releases completely blocked (won't appear)

### Step 3: Monitor Queue

1. Check **Activity** → **Queue** in both Radarr and Sonarr
2. Verify that downloads match your quality expectations
3. Check that low-quality releases are NOT being downloaded

### Step 4: Check Automatic Search (Optional)

If you want to trigger searches for upgrades:

**Radarr:**
```bash
# Trigger RSS sync
curl -X POST http://10.10.10.10:7878/api/v3/command \
  -H "X-Api-Key: YOUR_RADARR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "RssSync"}'
```

**Sonarr:**
```bash
# Trigger RSS sync
curl -X POST http://10.10.10.10:8989/api/v3/command \
  -H "X-Api-Key: YOUR_SONARR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "RssSync"}'
```

---

## PHASE 5: Monitoring and Adjustment (First Week)

### What to Watch For

1. **Download Quality**: Check that downloads are from good release groups
2. **False Rejections**: Verify that legitimate releases aren't being blocked
3. **Upgrade Behavior**: Confirm that upgrades are happening when better releases appear
4. **Storage Usage**: Monitor disk space (should be reasonable with WEB-DL)

### Common Adjustments

**Too Many Rejections:**
- Consider removing some negative score custom formats
- Reduce negative scores from -10000 to -1000

**Not Enough Upgrades:**
- Increase scores for top-tier release groups
- Lower the "Upgrade Until Custom Format Score"

**Too Many Upgrades:**
- Decrease scores for audio/video quality formats
- Increase the "Minimum Custom Format Score"

**File Sizes Too Large:**
- Block Remux quality tier
- Add negative score to Bluray Tier 01

---

## PHASE 6: Optional Enhancements

### Enable Automatic Search for Upgrades

**Radarr:**
1. Go to **Settings** → **Media Management**
2. Enable **Automatically Search for Upgrades**
3. Set **Rescan Movie Folder after Refresh**: Enabled

**Sonarr:**
1. Go to **Settings** → **Media Management**
2. Enable **Automatically Search for Upgrades**
3. Set **Rescan TV Folder after Refresh**: Enabled

### Configure Release Profiles (Deprecated in v4)

If you're on Radarr/Sonarr v3, you may also want release profiles. In v4+, custom formats replace release profiles.

---

## Troubleshooting

### Problem: "No results found" for searches

**Solution:**
- Check that your indexers (Prowlarr/Jackett) are working
- Verify VPN (Gluetun) is connected
- Temporarily disable all negative score custom formats to test

### Problem: Still downloading low-quality releases

**Solution:**
- Verify custom formats are assigned scores in the quality profile
- Check that UpgradeAllowed is enabled
- Ensure negative scores are actually -10000 (not -1000)

### Problem: Too many upgrades happening

**Solution:**
- Lower the scores for audio/video quality formats
- Set a higher "Minimum Custom Format Score"
- Set a lower "Upgrade Until Custom Format Score"

### Problem: Custom format import fails

**Solution:**
- Ensure you're copying the ENTIRE JSON content
- Check that Radarr/Sonarr is v4+ (custom formats don't work in v3)
- Try importing via the UI instead of API

---

## Expected Results

After full implementation:

**Radarr (46 movies):**
- All movies on HD-1080p profile
- Upgrades enabled
- Auto-reject: CAM, TS, YIFY, x265 HD, BR-DISK
- Prefer: Top-tier WEB-DL/Bluray groups
- Average file size: 5-15GB per movie

**Sonarr (22 shows):**
- All shows on HD-1080p profile
- Upgrades enabled
- Auto-reject: HDTV, RARBG, YIFY, x265 HD
- Prefer: Top-tier WEB-DL groups
- Average file size: 1-3GB per episode

**Storage Efficiency:**
- Single high-quality copy per movie/episode
- No duplicate downloads
- Automatic upgrades to better releases when available
- Reasonable file sizes (WEB-DL, not Remux)

---

## Reference Links

- TRaSH Guides Main: https://trash-guides.info/
- Radarr Quality Profiles: https://trash-guides.info/Radarr/radarr-setup-quality-profiles/
- Radarr Custom Formats: https://trash-guides.info/Radarr/Radarr-collection-of-custom-formats/
- Sonarr Quality Profiles: https://trash-guides.info/Sonarr/sonarr-setup-quality-profiles/
- Sonarr Custom Formats: https://trash-guides.info/Sonarr/sonarr-collection-of-custom-formats/

---

## Support

If you encounter issues:
1. Check the TRaSH Guides documentation
2. Review Radarr/Sonarr logs: **System** → **Logs**
3. Test with manual search to isolate the issue
4. Verify custom formats are correctly imported and scored
