#!/usr/bin/env bash
PLATFORM=RPGMaker
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
export DECKY_PLUGIN_DIR="${DECKY_PLUGIN_DIR:-${HOME}/homebrew/plugins/GameVault}"
export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-${HOME}/homebrew/logs/GameVault}"

export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="${Extensions:-Extensions}"

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/RPGMaker/settings.sh"

# Returns the engine tag (mv|mz|vxace|xp|vx) stored in the Arguments column.
ARGS=$($RPGMAKERCONF --get-args "${1}" --dbfile $DBFILE)
echo $ARGS
