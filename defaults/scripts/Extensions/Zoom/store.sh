#!/usr/bin/env bash

# Register extra actions with the gamevault.sh script
ACTIONS+=("login-launch-options" "check-update")

# Register Zoom as a platform with the gamevault.sh script
PLATFORMS+=("Zoom")

# Only source the settings when this platform is the one being driven, so the
# exported LAUNCHER/INSTALL_DIR do not leak into another store's run.
if [[ "${PLATFORM}" == "Zoom" ]]; then
    source "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/Zoom/settings.sh"
fi

function Zoom_init() {
    # Errors used to go to /dev/null, so a failed sync was indistinguishable
    # from an empty library and the grid just stayed blank.
    $ZOOMCONF --list --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/zoom-init.log" 2>&1
}

function Zoom_refresh() {
    TEMP=$($ZOOMCONF --list --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_getgames() {
    if [ -z "${1}" ]; then FILTER=""; else FILTER="${1}"; fi
    if [ -z "${2}" ]; then INSTALLED="false"; else INSTALLED="${2}"; fi
    if [ -z "${3}" ]; then LIMIT="true"; else LIMIT="${3}"; fi

    TEMP=$($ZOOMCONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" "" --dbfile "$DBFILE")

    # An empty library on an unfiltered view means it was never synced, so
    # pull it once and re-query rather than showing an empty store. Tested
    # with jq so a formatting change cannot silently disable the retry.
    EMPTY=false
    if command -v jq &>/dev/null; then
        echo "$TEMP" | jq -e '.Content.Games | length == 0' &>/dev/null && EMPTY=true
    else
        case "$TEMP" in *'"Games": []'*) EMPTY=true ;; esac
    fi

    if [[ "$EMPTY" == "true" ]] && [[ "$FILTER" == "" ]] && [[ "$INSTALLED" == "false" ]]; then
        Zoom_init
        TEMP=$($ZOOMCONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" "" --dbfile "$DBFILE")
    fi
    echo "${TEMP}"
}

function Zoom_login() {
    get_steam_env
    launchoptions "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/Zoom/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "ZOOM Platform Login"
}

# The frontend always asks for this before Login, so it must exist even though
# ZOOM needs no browser handoff — a missing action returns null and the login
# panel crashes trying to read it.
function Zoom_login-launch-options() {
    get_steam_env
    loginlaunchoptions "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/Zoom/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "ZOOM Platform Login"
}

function Zoom_logout() {
    TEMP=$($ZOOMCONF --logout --dbfile "$DBFILE")
    rm -f "${DBFILE}" 2>/dev/null
    Zoom_loginstatus true
}

function Zoom_loginstatus() {
    if [[ "${1}" == "true" ]]; then FLUSH_CACHE="--flush-cache"; else FLUSH_CACHE=""; fi
    TEMP=$($ZOOMCONF --getloginstatus --dbfile "$DBFILE" $FLUSH_CACHE)
    echo "${TEMP}"
}

function Zoom_download() {
    mkdir -p "${DECKY_PLUGIN_LOG_DIR}"
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    PID_FILE="${DECKY_PLUGIN_LOG_DIR}/${1}.pid"

    # Refuse to start a second copy. Two downloads write to the same staging
    # file and the same progress log, which corrupts the archive and makes the
    # percentage jump around as they interleave.
    if [[ -f "${PID_FILE}" ]]; then
        OLD_PID=$(cat "${PID_FILE}" 2>/dev/null)
        if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
            echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Already installing\"}}"
            return 0
        fi
        rm -f "${PID_FILE}"
    fi

    # Start from an empty log every time. A leftover log from a previous run
    # is read as the current state, so a finished or failed install would be
    # reported before the new one had written a single line.
    # zoom-platform.sh runs the Windows installer through Proton, and Inno Setup
    # always builds a GUI (its silent mode is hardcoded off upstream). Without
    # Steam's display environment Wine has no window handle and the install dies
    # with "Error reading FPreparingMemo.Lines.Strings ... Invalid window handle".
    get_steam_env

    : > "${PROGRESS_LOG}"
    $ZOOMCONF --install-game "${1}" --install-dir "${INSTALL_DIR}" --dbfile "$DBFILE" \
        2>> "$PROGRESS_LOG" > "${DECKY_PLUGIN_LOG_DIR}/${1}.output" &
    echo $! > "${PID_FILE}"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Downloading\"}}"
}

# Called AFTER the download finishes, with the Steam shortcut id in $2.
# Persists that id (this is what "installed" means to the UI), records the
# launcher, and returns LaunchOptions so the shortcut can be configured.
function Zoom_install() {          # $1 = shortname, $2 = steamClientID
    rm -f "${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    $ZOOMCONF --detect-executable "${1}" --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/zoom-init.log" 2>&1
    $ZOOMCONF --addsteamclientid "${1}" "${2}" --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/zoom-init.log" 2>&1
    $ZOOMCONF --update-umu-id "${1}" zoom --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/zoom-init.log" 2>&1
    ARGS=$("$ARGS_SCRIPT" "${1}" 2>/dev/null)
    TEMP=$($ZOOMCONF --launchoptions "${1}" "${ARGS}" "" --dbfile "$DBFILE")
    echo "${TEMP}"
    exit 0
}

function Zoom_uninstall() {
    TEMP=$($ZOOMCONF --uninstall-game "${1}" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_getprogress() {
    TEMP=$($ZOOMCONF --getprogress "${DECKY_PLUGIN_LOG_DIR}/${1}.progress" --dbfile "$DBFILE")
    # Once the run has finished, drop the pid file so the next install is not
    # refused by a lock nobody holds.
    PID_FILE="${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    if [[ -f "${PID_FILE}" ]]; then
        OLD_PID=$(cat "${PID_FILE}" 2>/dev/null)
        if [[ -z "${OLD_PID}" ]] || ! kill -0 "${OLD_PID}" 2>/dev/null; then
            rm -f "${PID_FILE}"
        fi
    fi
    echo "${TEMP}"
}

function Zoom_cancelinstall() {
    PID=$(cat "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null)
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    if [[ -n "${PID}" ]]; then
        # Kill the whole process group: the python downloader may have
        # zoom-platform.sh as a child by this point.
        kill -- -"${PID}" 2>/dev/null || kill "${PID}" 2>/dev/null
        sleep 2
        kill -9 -- -"${PID}" 2>/dev/null || kill -9 "${PID}" 2>/dev/null
        rm -f "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    fi
    # Say so in the log the UI is polling, or it keeps showing the last
    # percentage forever.
    echo "ZOOM-ERROR: Install cancelled" >> "${PROGRESS_LOG}"
    echo "{\"Type\": \"CancelInstall\", \"Content\": {\"Message\": \"Install cancelled\"}}"
}

function Zoom_check-update() {
    TEMP=$($ZOOMCONF --check-update "${1}" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_getgamesize() {
    TEMP=$($ZOOMCONF --get-game-size "${1}" "${2}" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_getgamedetails() {
    TEMP=$($ZOOMCONF --getgamedata "${1}" "${IMAGE_PATH}" --dbfile "$DBFILE" --forkname "Proton" --version "null" --platform "Windows")
    echo "${TEMP}"
}

function Zoom_getjsonimages() {
    TEMP=$($ZOOMCONF --get-base64-images "${1}" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_getlaunchoptions() {
    ARGS="${2}"
    TEMP=$($ZOOMCONF --launchoptions "${1}" "${ARGS}" "" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_getsetting() {
    TEMP=$($ZOOMCONF --getsetting "${1}" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_savesetting() {
    TEMP=$($ZOOMCONF --savesetting "${1}" "${2}" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_gettabconfig() {
    TEMP=$($ZOOMCONF --confjson "${1}" --platform Proton --fork "" --version "" --dbfile "$DBFILE")
    echo "${TEMP}"
}

function Zoom_savetabconfig() {
    cat | $ZOOMCONF --parsejson "${1}" --dbfile "$DBFILE" --platform Proton --fork "" --version ""
}
