#!/usr/bin/env bash
# Runs as a Steam launch entry (from Optima_login) so it executes in a graphical
# session where a browser can open. optima-cli hosts Ubisoft's WebAuth SDK page
# on https://localhost.ubisoft.com:31034 and opens it in $BROWSER; the user signs
# in once (email + password + Ubisoft authorize) and optima-cli captures the
# session ticket AND stores the email/username/password profile the emu needs.
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="Extensions"
ID=$1
echo $1
shift

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/Optima/settings.sh"

# Use the browser wrapper installed by install_deps.sh.
if [[ -f "${HOME}/.local/bin/open-browser" ]]; then
    export BROWSER="${HOME}/.local/bin/open-browser"
fi

mkdir -p "$DECKY_PLUGIN_LOG_DIR"
echo "Starting Ubisoft Connect login..." >> "${DECKY_PLUGIN_LOG_DIR}/optimalogin.log"

# --local hosts the WebAuth SDK page and blocks until the ticket is captured.
$OPTIMA_CMD login --local &>> "${DECKY_PLUGIN_LOG_DIR}/optimalogin.log"

if [ $? -eq 0 ]; then
    echo "Login successful" >> "${DECKY_PLUGIN_LOG_DIR}/optimalogin.log"
else
    echo "Login failed" >> "${DECKY_PLUGIN_LOG_DIR}/optimalogin.log"
fi

"${DECKY_PLUGIN_DIR}/scripts/gamevault.sh" Optima loginstatus --flush-cache
