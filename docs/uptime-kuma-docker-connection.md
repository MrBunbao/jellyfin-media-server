# Uptime Kuma Docker Host Connection

## Overview

This document describes how Uptime Kuma running on the VPS can monitor Docker containers on the NAS/Docker host via Tailscale.

## Network Configuration

| Host | Public IP | Tailscale IP | Role |
|------|-----------|--------------|------|
| VPS | 173.230.150.225 | 100.67.114.27 | Uptime Kuma |
| NAS (nas) | N/A | 100.107.222.83 | Docker Host |

## Tailscale Connectivity

Tailscale is configured on both hosts. Connectivity verified:

```bash
$ tailscale ping 100.67.114.27
pong from vps (100.67.114.27) via 10.1.1.2:41641 in 2ms
```

## Docker Configuration

Docker on the NAS is configured to listen on the Tailscale interface only, not on all interfaces.

### Files Modified

1. `/etc/docker/daemon.json`:
```json
{
  "data-root": "/volume1/@docker",
  "hosts": ["unix:///var/run/docker.sock", "tcp://100.107.222.83:2375"],
  "registry-mirrors": [...]
}
```

2. `/etc/systemd/system/docker.service.d/override.conf`:
```ini
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock
```

### Security Note

Docker is bound ONLY to the Tailscale interface (`100.107.222.83:2375`). This means:
- Only devices on the Tailscale network can access the Docker API
- The Docker API is NOT exposed on the LAN (10.10.10.10) or any public interface
- Tailscale provides encryption and authentication for all traffic

### Restart Docker After Changes

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### Verify Configuration

```bash
# Check Docker is listening on correct interface
sudo ss -tlnp | grep 2375
# Expected: LISTEN 0 4096 100.107.222.83:2375 0.0.0.0:*

# Verify port is NOT accessible on LAN
nc -zv 10.10.10.10 2375
# Expected: Connection refused

# Verify port IS accessible on Tailscale
nc -zv 100.107.222.83 2375
# Expected: succeeded
```

## Testing from VPS

From the VPS (100.67.114.27), run:

```bash
docker -H tcp://100.107.222.83:2375 ps
```

This should list all running containers on the Docker host.

## Uptime Kuma Configuration

In Uptime Kuma on the VPS, add Docker container monitors with:

- **Connection Type**: TCP / HTTP
- **Docker Host**: `tcp://100.107.222.83:2375`
- **Container Name**: (as shown in `docker ps`)
- **Check Interval**: 60 seconds

## Troubleshooting

### Cannot connect from VPS

1. Check Tailscale connectivity:
   ```bash
   tailscale ping 100.107.222.83
   ```

2. Check Docker is running on the host:
   ```bash
   sudo systemctl status docker
   ```

3. Check Docker is listening on correct port:
   ```bash
   sudo ss -tlnp | grep 2375
   ```

### Docker commands fail after restart

If Docker commands fail after modifying configuration, check for conflicting host definitions:

- The `-H` flags in systemd override conflict with `hosts` in daemon.json
- Remove `-H` flags from override.conf and use only daemon.json for host config

## Backups

Original configurations backed up to:
- `/etc/docker/daemon.json.backup.*`
- `/etc/systemd/system/docker.service.d/override.conf.backup.*`
