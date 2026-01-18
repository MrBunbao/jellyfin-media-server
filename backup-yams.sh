#!/bin/bash
# YAMS Automated Backup Script with Rotation
# Keeps the last 5 backups

BACKUP_DIR="/volume4/docker-v4/yams/backups"
MAX_BACKUPS=5
LOG_FILE="${BACKUP_DIR}/backup.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting YAMS backup..." >> "$LOG_FILE"

# Run the backup
/usr/local/bin/yams backup "$BACKUP_DIR" >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup completed successfully" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup failed!" >> "$LOG_FILE"
    exit 1
fi

# Rotate old backups - keep only the last MAX_BACKUPS
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rotating old backups (keeping last $MAX_BACKUPS)..." >> "$LOG_FILE"
ls -t "$BACKUP_DIR"/yams-backup-*.tar.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm -f

# Log current backups
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current backups:" >> "$LOG_FILE"
ls -lh "$BACKUP_DIR"/yams-backup-*.tar.gz 2>/dev/null >> "$LOG_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup process completed" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
