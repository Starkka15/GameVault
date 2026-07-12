#!/usr/bin/env bash

# Register actions with the gamevault.sh script
ACTIONS+=("update-umu-id")

# Register EA as a platform with the gamevault.sh script
PLATFORMS+=("EA")


# only source the settings if the platform is EA - this is to avoid conflicts with other plugins
if [[ "${PLATFORM}" == "EA" ]]; then
    source "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/settings.sh"
fi

function EA_init() {
    $EACONF --list --dbfile $DBFILE &> /dev/null
}

function EA_refresh() {
    TEMP=$(EA_init)
    echo "{\"Type\": \"RefreshContent\", \"Content\": {\"Message\": \"Refreshed\"}}"
}
function EA_getgames(){
    if [ -z "${1}" ]; then
        FILTER=""
    else
        FILTER="${1}"
    fi
    if [ -z "${2}" ]; then
        INSTALLED="false"
    else
        INSTALLED="${2}"
    fi
     if [ -z "${3}" ]; then
        LIMIT="true"
    else
        LIMIT="${3}"
    fi
    IMAGE_PATH=""
    TEMP=$($EACONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" --dbfile $DBFILE)
    echo $TEMP >> $DECKY_PLUGIN_LOG_DIR/debug.log
    if echo "$TEMP" | jq -e '.Content.Games | length == 0' &>/dev/null; then
        if [[ $FILTER == "" ]] && [[ $INSTALLED == "false" ]]; then
            TEMP=$(EA_init)
            TEMP=$($EACONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" --dbfile $DBFILE)
        fi
    fi
    echo $TEMP
}
function EA_saveplatformconfig(){
    cat | $EACONF --parsejson "${1}" --dbfile $DBFILE --platform Proton --fork "" --version "" --dbfile $DBFILE
}
function EA_getplatformconfig(){
    TEMP=$($EACONF --confjson "${1}" --platform Proton --fork "" --version "" --dbfile $DBFILE)
    echo $TEMP
}

function EA_cancelinstall(){
    PID=$(cat "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null)
    if [[ -n "${PID}" ]]; then
        kill $PID 2>/dev/null
        wait $PID 2>/dev/null
    fi
    rm "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"${1} installation Cancelled\"}}"
}

function EA_download(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    GAME_PATH="${INSTALL_DIR}/${1}"
    mkdir -p "${GAME_PATH}"
    # Run maxima-cli directly so progress output flows to the log file
    # maxima-cli writes all output (including progress) to stdout
    eaupdategamedetailsaftercmd "${1}" "${GAME_PATH}" $MAXIMA_CMD install --path "${GAME_PATH}" "${1}" > $PROGRESS_LOG 2>&1 &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Downloading\"}}"
}

function EA_install(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    rm $PROGRESS_LOG &>> ${DECKY_PLUGIN_LOG_DIR}/${1}.log

    RESULT=$($EACONF --addsteamclientid "${1}" "${2}" --dbfile $DBFILE)
    TEMP=$($EACONF --update-umu-id "${1}" ea --dbfile $DBFILE)
    ARGS=$($ARGS_SCRIPT "${1}")
    TEMP=$($EACONF --launchoptions "${1}" "${ARGS}" "" --dbfile $DBFILE)
    echo $TEMP
    exit 0
}

function EA_getlaunchoptions(){
    ARGS=$($ARGS_SCRIPT "${1}")
    TEMP=$($EACONF --launchoptions "${1}" "${ARGS}" "" --dbfile $DBFILE)
    echo $TEMP
    exit 0
}

function EA_uninstall(){
    GAME_DIR=$($EACONF --get-game-dir "${1}" --dbfile $DBFILE)
    if [ -d "${GAME_DIR}" ]; then
        rm -rf "${GAME_DIR}"
    fi
    TEMP=$($EACONF --clearsteamclientid "${1}" --dbfile $DBFILE)
    echo $TEMP

}
function EA_getgamedetails(){
    IMAGE_PATH=""
    TEMP=$($EACONF --getgamedata "${1}" "${IMAGE_PATH}" --dbfile $DBFILE --forkname "Proton" --version "null" --platform "Windows")
    echo $TEMP
    exit 0
}

function EA_getgamesize(){
    TEMP=$($EACONF --get-game-size "${1}" "${2}"  --dbfile $DBFILE)
    echo $TEMP
}

function EA_getprogress()
{
    TEMP=$($EACONF --getprogress "${DECKY_PLUGIN_LOG_DIR}/${1}.progress" --dbfile $DBFILE)
    echo $TEMP
}
function EA_loginstatus(){
    if [[ -z $1 ]]; then
        FLUSH_CACHE=""
    else
        FLUSH_CACHE="--flush-cache"
    fi
    TEMP=$($EACONF --getloginstatus --dbfile $DBFILE $FLUSH_CACHE)
    echo $TEMP

}

function EA_login(){
    get_steam_env
    launchoptions "${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "EA Play Login"
}
function EA_login-launch-options(){
    get_steam_env
    loginlaunchoptions  "${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "EA Play Login"
}


function EA_logout(){
    rm -f "${HOME}/.local/share/maxima/auth.toml" 2>/dev/null
    EA_loginstatus --flush-cache
}

function EA_update-umu-id(){
    TEMP=$($EACONF --update-umu-id "${1}" ea --dbfile $DBFILE)
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"Umu Id updated\"}}"
}

function EA_run-exe(){
    get_steam_env
    SETTINGS=$($EACONF --get-env-settings $ID --dbfile $DBFILE)
    eval "${SETTINGS}"
    STEAM_ID="${1}"
    GAME_SHORTNAME="${2}"
    GAME_EXE="${3}"
    ARGS="${4}"
    if [[ $4 == true ]]; then
        ARGS="some value"
    else
        ARGS=""
    fi
    COMPAT_TOOL="${5}"
    GAME_PATH=$($EACONF --get-game-dir $GAME_SHORTNAME --dbfile $DBFILE)
    launchoptions "\\\"${GAME_PATH}/${GAME_EXE}\\\""  "${ARGS}  &> ${DECKY_PLUGIN_LOG_DIR}/run-exe.log" "${GAME_PATH}" "Run exe" true "${COMPAT_TOOL}"
}
function EA_get-exe-list(){
    get_steam_env
    STEAM_ID="${1}"
    GAME_SHORTNAME="${2}"
    GAME_PATH=$($EACONF --get-game-dir $GAME_SHORTNAME --dbfile $DBFILE)
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

function EA_getsetting(){
    TEMP=$($EACONF --getsetting $1 --dbfile $DBFILE)
    echo $TEMP
}
function EA_savesetting(){
    $EACONF --savesetting $1 $2 --dbfile $DBFILE
}
function EA_getjsonimages(){

    TEMP=$($EACONF --get-base64-images "${1}" --dbfile $DBFILE --offline)
    echo $TEMP
}
function EA_gettabconfig(){
    if [[ ! -d "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas" ]]; then
        mkdir -p "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas"
    fi
    if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/eatabconfig.json" ]]; then
        TEMP=$(cat "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/eatabconfig.json")
    else
        TEMP=$(cat "${DECKY_PLUGIN_DIR}/conf_schemas/eatabconfig.json")
    fi
    echo "{\"Type\":\"IniContent\", \"Content\": ${TEMP}}"
}
function EA_savetabconfig(){

    cat > "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/eatabconfig.json"
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"EA tab config saved\"}}"

}

function eaupdategamedetailsaftercmd() {
    game=$1
    game_path=$2
    shift 2
    "$@"
    # Update DB with install path first so detect_executable can find the game dir
    python3 -c "
import sys, sqlite3
conn = sqlite3.connect('$DBFILE')
c = conn.cursor()
c.execute('UPDATE Game SET RootFolder=?, InstallPath=? WHERE ShortName=?', ('$game_path', '$game_path', '$game'))
conn.commit()
conn.close()
" &> /dev/null
    # Update game details and detect executable
    $EACONF --update-game-details $game --dbfile $DBFILE &> /dev/null
}
