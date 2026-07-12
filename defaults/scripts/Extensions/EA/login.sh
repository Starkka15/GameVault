#!/usr/bin/env bash
# These need to be exported because it does not get executed in the context of the plugin.
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="Extensions"
ID=$1
echo $1
shift

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/settings.sh"

# Use the browser wrapper installed by install_deps.sh
if [[ -f "${HOME}/.local/bin/open-browser" ]]; then
    export BROWSER="${HOME}/.local/bin/open-browser"
fi

echo "Starting EA Play login..." >> "${DECKY_PLUGIN_LOG_DIR}/ealogin.log"

$MAXIMA_CMD account-info &>> "${DECKY_PLUGIN_LOG_DIR}/ealogin.log"

if [ $? -eq 0 ]; then
    echo "Login successful" >> "${DECKY_PLUGIN_LOG_DIR}/ealogin.log"
else
    echo "Login failed" >> "${DECKY_PLUGIN_LOG_DIR}/ealogin.log"
fi

"${DECKY_PLUGIN_DIR}/scripts/gamevault.sh" EA loginstatus --flush-cache
