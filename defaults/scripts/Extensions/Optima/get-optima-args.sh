#!/usr/bin/env bash
PLATFORM=Optima
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"

export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH
export WORKING_DIR=$DECKY_PLUGIN_DIR

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/Optima/settings.sh"

# Per-game launch args stored in the DB (Game.Arguments) take priority so the
# user can override anything in the GameVault UI. $1 is the product id (ShortName).
# Ubisoft SP titles run fine with no extra args; optima-cli auto-selects the exe
# and never passes -offline by default (some titles reject it), so the default
# is empty. optima-launcher.sh forwards whatever this prints via OPTIMA_ARGS.
ARGS=$($OPTIMACONF --get-args "${1}" --dbfile $DBFILE)
echo $ARGS
