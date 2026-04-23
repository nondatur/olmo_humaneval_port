#!/bin/bash
set -e

MOUNT_POINT="/mnt/gcs"

echo "Waiting for GCS Fuse mount at $MOUNT_POINT..."

# wait until it becomes a mount point or until we can list it without error
for i in {1..30}; do
    if mountpoint -q "$MOUNT_POINT"; then
        echo "GCS Fuse mount is ready."
        break
    fi

    # alternatively test directory access:
    if ls "$MOUNT_POINT" >/dev/null 2>&1; then
        echo "GCS Fuse mount is accessible."
        break
    fi

    echo "Still waiting... ($i)"
    sleep 1
done

# Run the original CMD
exec "$@"
