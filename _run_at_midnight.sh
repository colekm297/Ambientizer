#!/bin/bash
cd ~/Projects/Ambientizer
TARGET=$(date -v+1d -v0H -v0M -v0S +%s 2>/dev/null || date -d "tomorrow 00:00:00" +%s)
NOW=$(date +%s)
SLEEP_SECS=$((TARGET - NOW))
echo "$(date): sleeping ${SLEEP_SECS}s until midnight ($(date -r $TARGET))" >> _upload_private.log
sleep "$SLEEP_SECS"
echo "$(date): waking up, starting private upload batch (15 tracks)" >> _upload_private.log
cd ~/Projects/Ambientizer && .venv/bin/python _upload_private.py >> _upload_private.log 2>&1
