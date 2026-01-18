#!/bin/bash
# Recyclarr TRaSH Guides Sync Script
# Automatically syncs custom formats and quality profiles

cd /volume4/docker-v4/yams || exit 1
/usr/bin/docker compose run --rm recyclarr sync
