#!/usr/bin/env bash
# Steam/GameVault invokes this as:  optima-settings-launcher.sh <product_id>
#
# Runs the game's settings/config application (resolution, graphics, etc.) via
# `optima-cli settings <product_id>`, which auto-detects the settings exe, deploys
# the EAX shim, seeds the game's install-path registry key, and runs it under the
# SAME umu/Proton prefix optima-cli uses for the game itself — so whatever the
# player changes here is what the game reads on launch. Runs NATIVELY
# (Compatibility=false); optima-cli does all the Proton work, so we do NOT want
# Steam to wrap us in a second Proton.
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="Extensions"
ID=$1

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/Optima/settings.sh"

mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/settings-${ID}.log"

# Steam Game Mode launches with LC_ALL=C (POSIX). Force UTF-8 so multibyte paths
# encode correctly under Proton.
eff_locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$eff_locale" in
  *[Uu][Tt][Ff]*) : ;;
  *) export LANG=C.UTF-8 LC_ALL=C.UTF-8 ;;
esac

# Resolve the install dir so the settings app runs against the copy the store
# installed (SD-card aware). Falls back to optima-cli's own default if absent.
GAME_DIR=$("$OPTIMACONF" --get-game-dir "$ID" --dbfile "$DBFILE" 2>/dev/null | tail -1)

echo "[$(date)] launching settings for product '${ID}' (dir: ${GAME_DIR})" >> "$LOG"

if [[ -n "${GAME_DIR}" && -d "${GAME_DIR}" ]]; then
    exec "$OPTIMA_CMD" settings "$ID" --path "${GAME_DIR}" >> "$LOG" 2>&1
else
    exec "$OPTIMA_CMD" settings "$ID" >> "$LOG" 2>&1
fi
