#!/usr/bin/env bash
# Runs as a Steam shortcut so it has a window and an on-screen keyboard in Game
# Mode. ZOOM has no OAuth flow and no device-code login, so the only way in is
# the ordinary email/password form the website uses.
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="Extensions"

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/Zoom/settings.sh"

LOG="${DECKY_PLUGIN_LOG_DIR}/zoomlogin.log"
mkdir -p "${DECKY_PLUGIN_LOG_DIR}"

function ask() {
    local title="$1" text="$2" hide="$3" out=""
    if command -v kdialog &>/dev/null; then
        if [[ "${hide}" == "password" ]]; then
            out=$(kdialog --title "${title}" --password "${text}" 2>/dev/null)
        else
            out=$(kdialog --title "${title}" --inputbox "${text}" 2>/dev/null)
        fi
    elif command -v zenity &>/dev/null; then
        if [[ "${hide}" == "password" ]]; then
            out=$(zenity --password --title "${title}" 2>/dev/null)
        else
            out=$(zenity --entry --title "${title}" --text "${text}" --width 500 2>/dev/null)
        fi
    else
        echo "No dialog tool available (kdialog/zenity)" >> "${LOG}"
    fi
    printf '%s' "${out}"
}

function fail() {
    echo "$1" >> "${LOG}"
    if command -v kdialog &>/dev/null; then
        kdialog --error "$1" 2>/dev/null
    elif command -v zenity &>/dev/null; then
        zenity --error --text "$1" 2>/dev/null
    fi
}

EMAIL=$(ask "ZOOM Platform Login" "Email address for your ZOOM Platform account:")
if [[ -z "${EMAIL}" ]]; then
    echo "No email entered" >> "${LOG}"
    exit 0
fi

PASSWORD=$(ask "ZOOM Platform Login" "Password:" password)
if [[ -z "${PASSWORD}" ]]; then
    echo "No password entered" >> "${LOG}"
    exit 0
fi

# The credentials go straight to zoom-config.py as argv and are never written to
# disk; only the resulting session cookie is persisted.
RESULT=$("$ZOOMCONF" --login "${EMAIL}" "${PASSWORD}" --dbfile "${DBFILE}" 2>> "${LOG}")
echo "login result: ${RESULT}" >> "${LOG}"
unset PASSWORD

if echo "${RESULT}" | grep -q '"TwoFactorRequired": true'; then
    CODE=$(ask "ZOOM Platform" "Two-factor code from your authenticator app (or a recovery code):")
    if [[ -n "${CODE}" ]]; then
        RESULT=$("$ZOOMCONF" --two-factor "${CODE}" --dbfile "${DBFILE}" 2>> "${LOG}")
        echo "2fa result: ${RESULT}" >> "${LOG}"
    fi
fi

if echo "${RESULT}" | grep -q '"LoggedIn": true'; then
    # Deliberately does NOT sync the library here. Every other extension
    # leaves the DB empty at this point and lets the grid populate it on the
    # first read, via the empty-result retry in Zoom_getgames.
    echo "logged in; library will sync on first grid read" >> "${LOG}"
else
    MSG=$(echo "${RESULT}" | sed -n 's/.*"Error": "\([^"]*\)".*/\1/p')
    fail "${MSG:-Could not log in to ZOOM Platform. Check the email and password.}"
fi

# Same final step as every other extension: refresh the cached login state so
# the panel shows the new status when this window closes.
"${DECKY_PLUGIN_DIR}/scripts/gamevault.sh" Zoom loginstatus --flush-cache
