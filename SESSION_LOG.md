# Session Log

Historical record of significant configuration changes and incident responses.

---

## 2026-02-04: Anime Movies Migration to Radarr-Anime (US-013)

**Purpose:** Migrate existing anime movies from the regular Movies library to the dedicated anime movies library managed by Radarr-Anime.

**Movies Migrated:**
1. **Demon Slayer: Kimetsu no Yaiba Infinity Castle (2025)** - tmdbId: 1311031 - ✅ HAS FILE (6.5GB)
2. **Demon Slayer -Kimetsu no Yaiba- The Movie: Mugen Train (2020)** - tmdbId: 635302 - Monitored (no file)
3. **JUJUTSU KAISEN: Hidden Inventory / Premature Death - The Movie (2025)** - tmdbId: 1338799 - Monitored (no file)
4. **My Hero Academia: World Heroes' Mission (2021)** - tmdbId: 768744 - Monitored (no file)
5. **Solo Leveling -ReAwakening- (2024)** - tmdbId: 1357633 - Monitored (no file)

**Process:**
1. Added all 5 anime movies to Radarr-Anime via API
2. Created hardlink of Demon Slayer Infinity Castle file from `/data/media/movies` to `/data/media/anime-movies`
3. Radarr-Anime detected and indexed the file automatically
4. Removed all 5 anime movies from main Radarr (kept files for Demon Slayer since hardlinked)
5. Deleted original movie folder from `/data/media/movies`
6. Triggered Jellyfin library refresh

**Hardlink Verification:**
- Both files shared inode 220338619 (confirmed hardlink)
- Link count = 2 before deletion, 1 after removing original
- No duplicate storage used

**Final State:**
- **Radarr-Anime:** 5 movies (1 with file, 4 monitored/wanted)
- **Main Radarr:** 0 anime movies (correctly removed)
- **Jellyfin Anime Movies:** Library refreshed, will show Demon Slayer

**Root Folders:**
- Radarr-Anime: `/data/media/anime-movies`
- Main Radarr: `/data/media/movies`

---

## 2026-02-03: Sonarr-Anime Download Client & Indexer Configuration (US-007)

**Purpose:** Connect Sonarr-Anime to indexers and download client for anime downloading.

**Changes Made:**

1. **Added qBittorrent as download client**
   - Host: gluetun (via VPN)
   - Port: 8889
   - Category: `anime` (saves to /data/torrents/anime)
   - Username: admad

2. **Nyaa.si indexer synced via Prowlarr**
   - Nyaa.si was already in Prowlarr (id: 27)
   - Forced application sync to add to Sonarr-Anime
   - Now appears as "Nyaa.si (Prowlarr)" in Sonarr-Anime

**Indexers Available (12 total):**
- Torrent: AnimeTosho, EZTV, LimeTorrents, Nyaa.si, The Pirate Bay, TorrentDownload, Uindex
- Usenet: altHUB, AnimeTosho (Usenet), NZBFinder, NZBgeek, NzbPlanet

**Verification:**
- Download client test: PASSED
- Indexer connectivity test: PASSED
- Search test ("one piece"): 979 results including Nyaa.si
- Health check: No issues

---

## 2026-02-04: Prowlarr Integration for Anime Instances

**Purpose:** Integrate Sonarr-Anime and Radarr-Anime with Prowlarr for automatic indexer sync.

**Changes Made:**
1. **Added Sonarr-Anime as Prowlarr application (id: 7)**
   - Base URL: http://172.60.0.52:8989
   - Sync Level: fullSync
   - Categories: TV (5000-5090 including TV/Anime 5070)

2. **Added Radarr-Anime as Prowlarr application (id: 8)**
   - Base URL: http://172.60.0.53:7878
   - Sync Level: fullSync
   - Categories: Movies (2000-2090)

3. **Created "anime" tag (id: 2) in Prowlarr**
   - For selective indexer sync to anime instances

4. **Tagged AnimeTosho indexers with anime tag:**
   - AnimeTosho (id: 20) - torrent
   - AnimeTosho (Usenet) (id: 22) - usenet

**Indexers Synced:**
- Sonarr-Anime: 11 indexers (including AnimeTosho)
- Radarr-Anime: 10 indexers (including AnimeTosho)

**Verification:**
- Both applications visible in Prowlarr Settings > Apps
- Indexers visible in both anime instances under Settings > Indexers

---

## 2026-02-03: Anime Movies Library Created

**Purpose:** Dedicated Jellyfin library for anime movies, separate from regular movies with anime-specific metadata providers.

**Configuration:**
- **Library Name:** Anime Movies
- **Collection Type:** movies
- **Container Path:** `/data/media/anime-movies`
- **Host Path:** `/volume4/mediaserver/media/anime-movies`

**Metadata Providers (ordered):**
1. AniDB (primary)
2. TheMovieDb (secondary)
3. The Open Movie Database

**Settings:**
- NFO local metadata: Enabled
- Language: Japanese (ja)
- Country: Japan (JP)
- Save local metadata: Enabled
- Realtime monitoring: Enabled

**Related Services:**
- radarr-anime (port 7879) manages anime movie downloads to this folder

---

## 2026-01-13: Live TV Migration

**Issue:** The xmltv-sd container was using tv_grab_sd_json, a 10-year-old grabber that Schedules Direct explicitly warned would get the account blocked.

**Solution:**
1. Stopped and removed xmltv-sd container (banned grabber)
2. Added Threadfin container (Schedules Direct approved M3U/XMLTV proxy)
3. Configured Jellyfin to use native Schedules Direct integration for EPG

**New Architecture:**
- **Tuner**: HDHomeRun FLEX 4K (10.10.10.20) - direct connection to Jellyfin
- **EPG**: Jellyfin native Schedules Direct (USA-OTA-84084 lineup)
- **Proxy**: Threadfin available at port 34400 if needed

**Containers Changed:**
- xmltv-sd: Commented out in docker-compose.yaml with warning
- threadfin: Added (172.60.0.41, port 34400)

**Jellyfin Configuration:**
- Dashboard > Live TV > TV Guide Data Providers
- Type: Schedules Direct
- Country: United States, Zip: 84084

---

## 2026-01-12: Jellyfin Backdrops Enabled by Default

**Issue:** Backdrops are disabled by default for all users in Jellyfin. Users must manually enable them in Display settings.

**Solution:** Modified `main.jellyfin.bundle.js` to change the default value from false to true.

**File location (inside container):** `/usr/share/jellyfin/web/main.jellyfin.bundle.js`

**Change made:**
```javascript
// Before: default is false (!1)
value:function(e){return void 0!==e?this.set("enableBackdrops",e.toString(),!1):(0,i.G4)(this.get("enableBackdrops",!1),!1)}

// After: default is true (!0)
value:function(e){return void 0!==e?this.set("enableBackdrops",e.toString(),!1):(0,i.G4)(this.get("enableBackdrops",!1),!0)}
```

**Persistence:** Created startup script to apply the change on every container start:
- **Script:** `/volume4/docker-v4/yams/config/jellyfin/custom-cont-init.d/enable-backdrops.sh`
- Uses LinuxServer.io custom-cont-init.d mechanism
- Runs automatically when Jellyfin container starts, survives container updates/recreations

**Effect:** Changes the default from opt-in to opt-out. Users who haven't set a preference will now see backdrops.

---

## 2025-12-13: DNS Blocking & Post-Incident Cleanup

**Symptoms:**
- Sonarr: "Failed to authenticate with qBittorrent"
- Prowlarr: 9 indexers unavailable for 6+ hours (EZTV, YTS, AnimeTosho, LimeTorrents, etc.)
- SSL certificate errors: "unable to get local issuer certificate"

**Root Causes:**
1. **qBittorrent auth failure**: Password was changed during Dec 12 incident but Sonarr/Radarr still had old credentials.
2. **Network-level DNS blocking**: Network intercepts DNS queries to Google DNS (8.8.8.8) and returns fake IPs (203.0.113.250 - RFC 5737 test range) for torrent-related domains.

**Fix Applied:**
Updated all containers in `docker-compose.yaml` to use Tailscale DNS as primary:
```yaml
dns:
  - 100.100.100.100  # Tailscale MagicDNS (bypasses network blocking)
  - 8.8.8.8          # Fallback
```

---

## 2025-12-12: qBittorrent Compromise

**What happened:**
- qBittorrent was exposed to the internet without Authentik protection
- Attacker gained access (likely brute-forced weak password)
- Malicious AutoRun scripts were injected into qBittorrent config
- Malware executed on every torrent add since Dec 9, 2025

**Malware details:**
- Called `https://yify.foo` (77.110.110.55) and `http://ax29g9q123.anondns.net`
- Base64-encoded payload that fetched and executed remote scripts
- Located in `[AutoRun]` section of `qBittorrent.conf`

**Remediation performed:**
1. Removed malicious AutoRun entries from qBittorrent.conf
2. Changed qBittorrent password
3. Updated `scripts/update-port.sh` with new credentials
4. Set up Authentik forward auth protection via NPM

**Containment factors:**
- qBittorrent container was NOT privileged
- Container only had access to `/data` and `/config` volumes
- All traffic went through Gluetun VPN (home IP not exposed)
- Malware could not escape to host system
