#!/bin/bash

set -u
cd "$(dirname "$0")"

EXTRA_ARGS=()
EXTRA_ARGS+=( --dry-run )
#EXTRA_ARGS+=( --workflow-use-backlog --workflow-use-approved )

./src/housekeep.py \
    --gitlab-url "https://git.brickburg.de" \
    --project "christian/machen" \
    --close-obsolete --lock-closed --assign-closed --set-confidential --notify-due \
    --counters \
    --workflow-labels \
    --label-group "~prio:low,~prio:medium*,~prio:high,include-closed" \
    --label-group "~Kind:Bürokratie,~Kind:Docs,~Kind:Maintenance,~Kind:Projekt,~Kind:Vereinsarbeit,~Kind:Wohnung,~Kind:Other*,include-closed" \
    --label-category "~Lichtspielfreunde,~nerdbridge,~Kind:Vereinsarbeit" \
    --delay 0 --max-updated-age $((60*60*24*30*1)) \
    "${EXTRA_ARGS[@]}"
