#!/usr/bin/env bash

# Register custom actions with the gamevault.sh allowlist. `getprofile`/
# `saveprofile` drive the Uplay account form (email/username/password); the rest
# are the standard store actions.
ACTIONS+=("update-umu-id" "getprofile" "saveprofile")

# Register Optima (Ubisoft Connect) as a platform with gamevault.sh
PLATFORMS+=("Optima")

# Only source settings when the active platform is Optima — avoids clobbering
# other extensions' vars.
if [[ "${PLATFORM}" == "Optima" ]]; then
    source "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/Optima/settings.sh"
fi

# Games are keyed by Ubisoft numeric product id — that IS the ShortName in the DB.
# Every function receives the product id where EA received a slug.

function Optima_init() {
    $OPTIMACONF --list --dbfile $DBFILE &> /dev/null
}

function Optima_refresh() {
    TEMP=$(Optima_init)
    echo "{\"Type\": \"RefreshContent\", \"Content\": {\"Message\": \"Refreshed\"}}"
}

function Optima_getgames(){
    if [ -z "${1}" ]; then FILTER=""; else FILTER="${1}"; fi
    if [ -z "${2}" ]; then INSTALLED="false"; else INSTALLED="${2}"; fi
    if [ -z "${3}" ]; then LIMIT="true"; else LIMIT="${3}"; fi
    IMAGE_PATH=""
    TEMP=$($OPTIMACONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" --dbfile $DBFILE)
    echo $TEMP >> $DECKY_PLUGIN_LOG_DIR/debug.log
    if echo "$TEMP" | jq -e '.Content.Games | length == 0' &>/dev/null; then
        if [[ $FILTER == "" ]] && [[ $INSTALLED == "false" ]]; then
            TEMP=$(Optima_init)
            TEMP=$($OPTIMACONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" --dbfile $DBFILE)
        fi
    fi
    echo $TEMP
}

function Optima_saveplatformconfig(){
    cat | $OPTIMACONF --parsejson "${1}" --dbfile $DBFILE --platform Proton --fork "" --version "" --dbfile $DBFILE
}

function Optima_getplatformconfig(){
    TEMP=$($OPTIMACONF --confjson "${1}" --platform Proton --fork "" --version "" --dbfile $DBFILE)
    echo $TEMP
}

function Optima_cancelinstall(){
    PID=$(cat "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null)
    if [[ -n "${PID}" ]]; then
        kill $PID 2>/dev/null
        wait $PID 2>/dev/null
    fi
    rm "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"${1} installation Cancelled\"}}"
}

function Optima_download(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    PID_FILE="${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    # Guard: if an install for this product is already running, DON'T spawn a
    # second one. Two optima-cli writers race on the same .optima-part files and
    # one renames a temp out from under the other → "No such file or directory
    # (os error 2)". Re-taps (e.g. after a transient progress blip) must be no-ops.
    if [[ -f "${PID_FILE}" ]]; then
        OLD_PID=$(cat "${PID_FILE}" 2>/dev/null)
        if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
            echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Downloading\"}}"
            return
        fi
    fi
    GAME_PATH="${INSTALL_DIR}/${1}"
    mkdir -p "${GAME_PATH}"
    # optima-cli writes its per-file progress ("[i/N] name") to stdout.
    optimaupdategamedetailsaftercmd "${1}" "${GAME_PATH}" $OPTIMA_CMD install "${1}" --path "${GAME_PATH}" > $PROGRESS_LOG 2>&1 &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Downloading\"}}"
}

function Optima_install(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    rm $PROGRESS_LOG &>> ${DECKY_PLUGIN_LOG_DIR}/${1}.log

    RESULT=$($OPTIMACONF --addsteamclientid "${1}" "${2}" --dbfile $DBFILE)
    TEMP=$($OPTIMACONF --update-umu-id "${1}" optima --dbfile $DBFILE)
    ARGS=$($ARGS_SCRIPT "${1}")
    TEMP=$($OPTIMACONF --launchoptions "${1}" "${ARGS}" "" --dbfile $DBFILE)
    echo $TEMP
    exit 0
}

function Optima_getlaunchoptions(){
    ARGS=$($ARGS_SCRIPT "${1}")
    TEMP=$($OPTIMACONF --launchoptions "${1}" "${ARGS}" "" --dbfile $DBFILE)
    echo $TEMP
    exit 0
}

function Optima_uninstall(){
    GAME_DIR=$($OPTIMACONF --get-game-dir "${1}" --dbfile $DBFILE)
    if [ -d "${GAME_DIR}" ]; then
        rm -rf "${GAME_DIR}"
    fi
    TEMP=$($OPTIMACONF --clearsteamclientid "${1}" --dbfile $DBFILE)
    echo $TEMP
}

function Optima_getgamedetails(){
    IMAGE_PATH=""
    TEMP=$($OPTIMACONF --getgamedata "${1}" "${IMAGE_PATH}" --dbfile $DBFILE --forkname "Proton" --version "null" --platform "Windows")
    echo $TEMP
    exit 0
}

function Optima_getgamesize(){
    TEMP=$($OPTIMACONF --get-game-size "${1}" "${2}" --dbfile $DBFILE)
    echo $TEMP
}

function Optima_getprogress(){
    TEMP=$($OPTIMACONF --getprogress "${DECKY_PLUGIN_LOG_DIR}/${1}.progress" --dbfile $DBFILE)
    echo $TEMP
}

function Optima_loginstatus(){
    if [[ -z $1 ]]; then FLUSH_CACHE=""; else FLUSH_CACHE="--flush-cache"; fi
    TEMP=$($OPTIMACONF --getloginstatus --dbfile $DBFILE $FLUSH_CACHE)
    echo $TEMP
}

# Browser login: hands login.sh to Steam so it runs in a graphical session where
# optima-cli can open the Ubisoft WebAuth page (localhost.ubisoft.com). That flow
# captures the session ticket AND the email/username/password profile in one go.
function Optima_login(){
    get_steam_env
    launchoptions "${DECKY_PLUGIN_DIR}/scripts/Extensions/Optima/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "Ubisoft Connect Login"
}
function Optima_login-launch-options(){
    get_steam_env
    loginlaunchoptions "${DECKY_PLUGIN_DIR}/scripts/Extensions/Optima/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "Ubisoft Connect Login"
}

function Optima_logout(){
    rm -f "${HOME}/.local/share/optima/auth.toml" 2>/dev/null
    Optima_loginstatus --flush-cache
}

# Account form (email / username / password) → the Uplay player profile the emu
# feeds each game. IniEditor GetContent/SaveContent, handled in Python.
function Optima_getprofile(){
    TEMP=$($OPTIMACONF --get-profile --dbfile $DBFILE)
    echo $TEMP
}
function Optima_saveprofile(){
    cat | $OPTIMACONF --save-profile --dbfile $DBFILE
}

function Optima_update-umu-id(){
    TEMP=$($OPTIMACONF --update-umu-id "${1}" optima --dbfile $DBFILE)
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"Umu Id updated\"}}"
}

function Optima_run-exe(){
    get_steam_env
    SETTINGS=$($OPTIMACONF --get-env-settings $ID --dbfile $DBFILE)
    eval "${SETTINGS}"
    STEAM_ID="${1}"
    GAME_SHORTNAME="${2}"
    GAME_EXE="${3}"
    ARGS="${4}"
    if [[ $4 == true ]]; then ARGS="some value"; else ARGS=""; fi
    COMPAT_TOOL="${5}"
    GAME_PATH=$($OPTIMACONF --get-game-dir $GAME_SHORTNAME --dbfile $DBFILE)
    launchoptions "\\\"${GAME_PATH}/${GAME_EXE}\\\"" "${ARGS}  &> ${DECKY_PLUGIN_LOG_DIR}/run-exe.log" "${GAME_PATH}" "Run exe" true "${COMPAT_TOOL}"
}

function Optima_get-exe-list(){
    get_steam_env
    STEAM_ID="${1}"
    GAME_SHORTNAME="${2}"
    GAME_PATH=$($OPTIMACONF --get-game-dir $GAME_SHORTNAME --dbfile $DBFILE)
    export STEAM_COMPAT_DATA_PATH="${HOME}/.local/share/Steam/steamapps/compatdata/${STEAM_ID}"
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${GAME_PATH}"
    cd "${STEAM_COMPAT_CLIENT_INSTALL_PATH}"
    JSON="{\"Type\": \"FileContent\", \"Content\": {\"PathRoot\": \"${GAME_PATH}\", \"Files\": ["
    SEP=""
    while IFS= read -r -d '' FILE; do
        JSON="${JSON}${SEP}{\"Path\": \"${FILE}\"}"
        SEP=","
    done < <(find . \( -name "*.exe" -o -iname "*.bat" -o -iname "*.msi" -o -iname "*.sh" \) -print0)
    JSON="${JSON}]}}"
    echo "$JSON"
}

function Optima_getsetting(){
    TEMP=$($OPTIMACONF --getsetting $1 --dbfile $DBFILE)
    echo $TEMP
}
function Optima_savesetting(){
    $OPTIMACONF --savesetting $1 $2 --dbfile $DBFILE
}

function Optima_getjsonimages(){
    TEMP=$($OPTIMACONF --get-base64-images "${1}" --dbfile $DBFILE --offline)
    echo $TEMP
}

function Optima_gettabconfig(){
    if [[ ! -d "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas" ]]; then
        mkdir -p "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas"
    fi
    if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/optimatabconfig.json" ]]; then
        TEMP=$(cat "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/optimatabconfig.json")
    else
        TEMP=$(cat "${DECKY_PLUGIN_DIR}/conf_schemas/optimatabconfig.json")
    fi
    echo "{\"Type\":\"IniContent\", \"Content\": ${TEMP}}"
}
function Optima_savetabconfig(){
    cat > "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/optimatabconfig.json"
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"Optima tab config saved\"}}"
}

function optimaupdategamedetailsaftercmd() {
    game=$1
    game_path=$2
    shift 2
    "$@"
    # Record the install path so get_game_dir / launch find the game. optima-cli
    # auto-detects the launch exe from the product configuration, so no separate
    # executable-detection step is needed.
    python3 -c "
import sys, sqlite3
conn = sqlite3.connect('$DBFILE')
c = conn.cursor()
c.execute('UPDATE Game SET RootFolder=?, InstallPath=? WHERE ShortName=?', ('$game_path', '$game_path', '$game'))
conn.commit()
conn.close()
" &> /dev/null
}
