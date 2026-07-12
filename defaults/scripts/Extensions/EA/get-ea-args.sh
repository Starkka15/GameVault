#!/usr/bin/env bash
PLATFORM=EA
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"

export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH

export WORKING_DIR=$DECKY_PLUGIN_DIR

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/settings.sh"

# Per-game launch args stored in the DB (Game.Arguments) take priority so the
# user can override anything in the GameVault UI.
ARGS=$($EACONF --get-args "${1}" --dbfile $DBFILE)

# Fallback defaults for games that need specific launch tokens. $1 is the slug
# (ea.py uses slug as ShortName). These are appended to the game's command line
# by ea-launcher.sh. Verified 2026-07-12:
#   - Battlelog-era Battlefields boot to a black screen without the right
#     -webmode/-requestState; Hardline has a clean offline campaign token,
#     BF4/BF3 use the online "sparta" frontend (live EA servers still up).
#   - Newer/self-contained titles (Mirror's Edge Catalyst, Burnout) need none.
if [[ -z "${ARGS// }" ]]; then
    case "$1" in
        battlefield-hardline)
            ARGS="-webmode spoffline" ;;                       # offline campaign, no Battlelog
        battlefield-4|battlefield-3)
            ARGS="-webmode sparta -requestState State_Sparta" ;; # online Battlelog frontend
    esac
fi

echo $ARGS
