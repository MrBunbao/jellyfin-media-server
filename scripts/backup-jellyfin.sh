#!/bin/bash
#
# Jellyfin Backup Script
# Backs up user data, databases, metadata, and cache (excluded from git)
# Complements git repository at: https://github.com/MrBunbao/jellyfin-config
#

set -euo pipefail

# Configuration
JELLYFIN_CONFIG="/volume1/docker/yams/config/jellyfin"
BACKUP_DIR="/volume1/docker/yams/backups/jellyfin"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="jellyfin-data-${DATE}.tar.gz"
LOG_FILE="${BACKUP_DIR}/backup.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "${LOG_FILE}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "${LOG_FILE}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "${LOG_FILE}"
}

# Function to create backup
backup() {
    log "Starting Jellyfin data backup..."
    
    cd "${JELLYFIN_CONFIG}"
    
    # Create list of items to backup (excluded from git)
    BACKUP_ITEMS=(
        "users"
        "data/data"
        "data/metadata"
        "cache"
        "log"
    )
    
    # Check which items exist
    EXISTING_ITEMS=()
    for item in "${BACKUP_ITEMS[@]}"; do
        if [ -e "${item}" ]; then
            EXISTING_ITEMS+=("${item}")
            log "  Including: ${item}"
        else
            warn "  Skipping (not found): ${item}"
        fi
    done
    
    if [ ${#EXISTING_ITEMS[@]} -eq 0 ]; then
        error "No backup items found!"
        exit 1
    fi
    
    # Create backup
    log "Creating compressed archive..."
    tar czf "${BACKUP_DIR}/${BACKUP_NAME}" "${EXISTING_ITEMS[@]}" 2>&1 | tee -a "${LOG_FILE}"
    
    # Check if backup was created successfully
    if [ -f "${BACKUP_DIR}/${BACKUP_NAME}" ]; then
        BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}" | cut -f1)
        log "Backup created successfully: ${BACKUP_NAME} (${BACKUP_SIZE})"
    else
        error "Backup creation failed!"
        exit 1
    fi
    
    # Cleanup old backups
    log "Cleaning up backups older than ${RETENTION_DAYS} days..."
    find "${BACKUP_DIR}" -name "jellyfin-data-*.tar.gz" -mtime +${RETENTION_DAYS} -delete 2>&1 | tee -a "${LOG_FILE}"
    
    # List current backups
    log "Current backups:"
    ls -lh "${BACKUP_DIR}"/jellyfin-data-*.tar.gz 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}' | tee -a "${LOG_FILE}"
    
    log "Backup completed successfully!"
}

# Function to restore from backup
restore() {
    local backup_file="$1"
    
    if [ -z "${backup_file}" ]; then
        error "Please specify a backup file to restore"
        echo "Available backups:"
        ls -lh "${BACKUP_DIR}"/jellyfin-data-*.tar.gz 2>/dev/null || echo "  No backups found"
        exit 1
    fi
    
    if [ ! -f "${backup_file}" ]; then
        error "Backup file not found: ${backup_file}"
        exit 1
    fi
    
    log "Restoring from backup: ${backup_file}"
    warn "This will OVERWRITE existing data!"
    read -p "Are you sure? (yes/no): " -r
    if [[ ! $REPLY =~ ^yes$ ]]; then
        log "Restore cancelled"
        exit 0
    fi
    
    log "Stopping Jellyfin container..."
    docker stop jellyfin || warn "Could not stop Jellyfin (may not be running)"
    
    cd "${JELLYFIN_CONFIG}"
    
    log "Extracting backup..."
    tar xzf "${backup_file}" 2>&1 | tee -a "${LOG_FILE}"
    
    log "Starting Jellyfin container..."
    docker start jellyfin || error "Failed to start Jellyfin"
    
    log "Restore completed successfully!"
}

# Function to list backups
list_backups() {
    log "Available backups in ${BACKUP_DIR}:"
    if ls "${BACKUP_DIR}"/jellyfin-data-*.tar.gz 1> /dev/null 2>&1; then
        ls -lh "${BACKUP_DIR}"/jellyfin-data-*.tar.gz | awk '{printf "  %s  %s  (%s)\n", $6, $7, $5}'
    else
        echo "  No backups found"
    fi
}

# Main
case "${1:-backup}" in
    backup)
        backup
        ;;
    restore)
        restore "${2:-}"
        ;;
    list)
        list_backups
        ;;
    *)
        echo "Usage: $0 {backup|restore|list}"
        echo ""
        echo "Commands:"
        echo "  backup          Create a new backup (default)"
        echo "  restore <file>  Restore from specified backup file"
        echo "  list            List available backups"
        echo ""
        echo "Examples:"
        echo "  $0 backup"
        echo "  $0 restore ${BACKUP_DIR}/jellyfin-data-20250124_020000.tar.gz"
        echo "  $0 list"
        exit 1
        ;;
esac
