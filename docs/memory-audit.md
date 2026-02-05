# Memory Audit Report

**Generated:** 2026-02-04
**Compose File:** `/volume4/docker-v4/yams/docker-compose.yaml`

## Summary

**Finding:** No containers in the YAMS stack have explicit memory limits configured. All containers have access to the full host memory (62.57 GiB), making them vulnerable to OOM conditions during resource contention.

---

## Memory Configuration Audit

### Media Containers

| Container | Memory Limit | Risk Level |
|-----------|--------------|------------|
| jellyfin | **None** (62.57 GiB host max) | HIGH |
| jellyseerr | **None** (62.57 GiB host max) | MEDIUM |
| jellystat | **None** (62.57 GiB host max) | LOW |
| jellystat-db | **None** (62.57 GiB host max) | MEDIUM |
| komga | **Not defined in compose** | N/A |

### Arr Stack

| Container | Memory Limit | Risk Level |
|-----------|--------------|------------|
| sonarr | **None** (62.57 GiB host max) | HIGH |
| sonarr-anime | **None** (62.57 GiB host max) | HIGH |
| radarr | **None** (62.57 GiB host max) | HIGH |
| radarr-anime | **None** (62.57 GiB host max) | HIGH |
| prowlarr | **None** (62.57 GiB host max) | MEDIUM |
| bazarr | **None** (62.57 GiB host max) | LOW |
| lidarr | **None** (62.57 GiB host max) | MEDIUM |
| readarr | **None** (62.57 GiB host max) | MEDIUM |
| whisparr | **None** (62.57 GiB host max) | MEDIUM |

### Download Stack

| Container | Memory Limit | Risk Level |
|-----------|--------------|------------|
| qbittorrent | **None** (62.57 GiB host max) | HIGH |
| gluetun | **None** (62.57 GiB host max) | MEDIUM |
| sabnzbd | **None** (62.57 GiB host max) | MEDIUM |

### Other Services

| Container | Memory Limit | Risk Level |
|-----------|--------------|------------|
| tdarr | **None** (62.57 GiB host max) | HIGH |
| subgen | **None** (62.57 GiB host max) | HIGH |
| meilisearch | **None** (62.57 GiB host max) | MEDIUM |
| flaresolverr | **None** (62.57 GiB host max) | MEDIUM |
| homarr | **None** (62.57 GiB host max) | LOW |
| recyclarr | **None** (62.57 GiB host max) | LOW |
| unpackerr | **None** (62.57 GiB host max) | LOW |
| janitorr | **None** (62.57 GiB host max) | LOW |
| wizarr | **None** (62.57 GiB host max) | LOW |
| tvheadend | **None** (62.57 GiB host max) | MEDIUM |
| threadfin | **None** (62.57 GiB host max) | LOW |
| sd-xmltv | **None** (62.57 GiB host max) | LOW |
| xmltv-sd | **None** (62.57 GiB host max) | LOW |
| trailarr | **None** (62.57 GiB host max) | LOW |
| sportarr | **None** (62.57 GiB host max) | LOW |
| anchorr | **None** (62.57 GiB host max) | LOW |
| autobrr | **None** (62.57 GiB host max) | LOW |
| huntarr | **None** (62.57 GiB host max) | LOW |
| cleanuparr | **None** (62.57 GiB host max) | LOW |
| qbitmanage | **None** (62.57 GiB host max) | LOW |
| swaparr-radarr | **None** (62.57 GiB host max) | LOW |
| swaparr-sonarr | **None** (62.57 GiB host max) | LOW |
| yams-healthcheck | **None** (62.57 GiB host max) | LOW |
| yams-monitor | **None** (62.57 GiB host max) | LOW |

---

## Current Memory Usage Baseline

Captured at: 2026-02-04

### Running Containers (YAMS Stack)

| Container | Memory Usage | Memory % | Status |
|-----------|--------------|----------|--------|
| jellyfin | 792.8 MiB | 1.24% | Running |
| jellyseerr | 250.7 MiB | 0.39% | Running |
| jellystat | 91.57 MiB | 0.14% | Running |
| jellystat-db | 70.46 MiB | 0.11% | Running |

### Stopped Containers (YAMS Stack)

| Container | Exit Code | Time Since Exit |
|-----------|-----------|-----------------|
| bazarr | 0 | ~17 hours |
| gluetun | 1 | ~17 hours |
| prowlarr | 0 | ~17 hours |
| qbittorrent | 0 | ~17 hours |
| radarr | 0 | ~17 hours |
| radarr-anime | 0 | ~17 hours |
| sonarr | 0 | ~17 hours |
| sonarr-anime | 0 | ~17 hours |
| swaparr-radarr | 137 (OOM/killed) | ~17 hours |
| swaparr-sonarr | 137 (OOM/killed) | ~17 hours |

**Note:** Exit code 137 indicates the container was killed (SIGKILL), often due to OOM conditions or manual stop.

### Not Defined in Compose

The following containers from the acceptance criteria are not defined in `docker-compose.yaml`:
- **komga** - Not present
- **transmission** - Not present (qbittorrent is used instead)

---

## Risk Assessment

### HIGH Risk Containers (Priority for Memory Limits)

1. **jellyfin** - Media transcoding can consume significant memory, especially with multiple concurrent streams
2. **tdarr** - Transcoding operations are memory-intensive
3. **subgen** - Whisper AI model requires substantial memory
4. **sonarr/sonarr-anime** - Large media libraries cause high memory usage
5. **radarr/radarr-anime** - Large media libraries cause high memory usage
6. **qbittorrent** - Many active torrents can increase memory usage

### MEDIUM Risk Containers

- **gluetun** - VPN operations
- **meilisearch** - Search indexing
- **jellyseerr** - Request management
- **jellystat-db** - PostgreSQL database
- **flaresolverr** - Browser automation
- **prowlarr** - Indexer management
- **sabnzbd** - Usenet downloads
- **tvheadend** - Live TV streaming
- **lidarr/readarr/whisparr** - Media management

### LOW Risk Containers

- Utility services (recyclarr, unpackerr, janitorr, etc.)
- Notification/webhook services (anchorr, notifiarr)
- Lightweight monitoring (yams-monitor, yams-healthcheck)

---

## Recommendations

1. **Immediate:** Add memory limits to HIGH risk containers
2. **Short-term:** Add memory limits to MEDIUM risk containers
3. **Configure memory reservation** for critical services to ensure baseline availability
4. **Monitor** container memory usage over time to establish accurate limits

### Example Configuration

```yaml
services:
  jellyfin:
    # ... existing config ...
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 1G
```

---

## Notes

- Host total memory: 62.57 GiB
- Some containers (e.g., scrypted, xibo-cms-*) have memory limits set but are not part of the YAMS stack
- The swaparr containers exited with code 137, which may indicate previous OOM conditions
