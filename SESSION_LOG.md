# Session Log

Historical record of significant configuration changes and incident responses.

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
