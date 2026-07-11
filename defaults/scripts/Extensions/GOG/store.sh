#!/usr/bin/env bash

# Register actions with the gamevault.sh script
ACTIONS+=("update-umu-id" "download-saves" "upload-saves" "toggle-autosync" "lookup-protonfixes" "apply-protonfixes" "retrodetect-game-types" "getdlcs" "installdlc" "removedlc")

# Register GOG as a platform with the gamevault.sh script
PLATFORMS+=("GOG")


# only source the settings if the platform is GOG - this is to avoid conflicts with other plugins
if [[ "${PLATFORM}" == "GOG" ]]; then
    source "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/GOG/settings.sh"
fi

function GOG_init() {
    echo "[GOG_init] Starting. Checking .conf files in ${INSTALL_DIR} BEFORE list/retrodetect:" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    find "${INSTALL_DIR}" -maxdepth 2 -name "*.conf" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1 || echo "[GOG_init] No .conf files found" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    $GOGCONF --list --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    echo "[GOG_init] After --list. Checking .conf files:" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    find "${INSTALL_DIR}" -maxdepth 2 -name "*.conf" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1 || echo "[GOG_init] No .conf files found" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    $GOGCONF --retrodetect --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    echo "[GOG_init] After --retrodetect. Checking .conf files:" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    find "${INSTALL_DIR}" -maxdepth 2 -name "*.conf" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1 || echo "[GOG_init] No .conf files found" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
}

function GOG_refresh() {
    TEMP=$(GOG_init)
    echo "{\"Type\": \"RefreshContent\", \"Content\": {\"Message\": \"Refreshed\"}}"
}
function GOG_getgames(){
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
    TEMP=$($GOGCONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" --dbfile "$DBFILE")
    echo "$TEMP" >> $DECKY_PLUGIN_LOG_DIR/debug.log
    if echo "$TEMP" | jq -e '.Content.Games | length == 0' &>/dev/null; then
        if [[ $FILTER == "" ]] && [[ $INSTALLED == "false" ]]; then
            TEMP=$(GOG_init)
            TEMP=$($GOGCONF --getgameswithimages "${IMAGE_PATH}" "${FILTER}" "${INSTALLED}" "${LIMIT}" "true" --dbfile "$DBFILE")
        fi
    fi
    echo "$TEMP"
}
function GOG_saveplatformconfig(){
    cat | $GOGCONF --parsejson "${1}" --dbfile "$DBFILE" --platform Proton --fork "" --version "" --dbfile "$DBFILE"
}
function GOG_getplatformconfig(){
    TEMP=$($GOGCONF --confjson "${1}" --platform Proton --fork "" --version "" --dbfile "$DBFILE")
    echo "$TEMP"
}

function GOG_cancelinstall(){
    PID=$(cat "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null)
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    if [[ -n "${PID}" ]]; then
        kill "${PID}" 2>/dev/null
        sleep 2
        kill -9 "${PID}" 2>/dev/null
    fi
    rm "${DECKY_PLUGIN_LOG_DIR}/${1}.pid" 2>/dev/null
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"${1} installation Cancelled\"}}"
}

function GOG_download(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    mkdir -p "${INSTALL_DIR}"
    # GOG_INSTALLDLCS (from the "Install DLCs with game" tab setting): "true" grabs all
    # DLCs with the base game (default); anything else installs base-only so DLCs can be
    # added one-by-one later via the DLC manager. --skip-dlcs is gogdl's explicit "no DLCs".
    if [[ "${GOG_INSTALLDLCS:-true}" == "true" ]]; then
        DLC_FLAG="--with-dlcs"
    else
        DLC_FLAG="--skip-dlcs"
    fi
    gogupdategamedetailsaftercmd $1 $GOGDL --auth-config-path "${AUTH_TOKENS}" download $1 --platform windows --path "${INSTALL_DIR}" --lang "${GOG_LANGUAGE:-en}" ${DLC_FLAG} 2> $PROGRESS_LOG > "${DECKY_PLUGIN_LOG_DIR}/${1}.output" &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Downloading\"}}"

}

function GOG_getdlcs(){
    $GOGCONF --getdlcs "${1}" --dbfile "$DBFILE"
}

function GOG_installdlc(){
    # $1 = game id (short name), $2 = dlc id. Downloads just this DLC into the
    # existing install (gogdl verifies/skips already-present base chunks). Reuses
    # the game's own .progress file so the existing GetProgress polling tracks it.
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    mkdir -p "${INSTALL_DIR}"
    # gogdl gotcha: --dlcs is only a FILTER; the DLC-download enable flag lives on
    # --with-dlcs (shared dest 'dlcs'). Without --with-dlcs, get_dlcs_user_owns()
    # short-circuits to [] ("Owned dlcs []" -> "Nothing to do"). Pass BOTH: enable
    # DLC downloading, then restrict it to just this one DLC id.
    $GOGDL --auth-config-path "${AUTH_TOKENS}" download $1 --platform windows --path "${INSTALL_DIR}" --lang "${GOG_LANGUAGE:-en}" --with-dlcs --dlcs "${2}" 2> $PROGRESS_LOG > "${DECKY_PLUGIN_LOG_DIR}/${1}.output" &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Installing DLC\"}}"
}

function GOG_removedlc(){
    # $1 = game id, $2 = dlc id. Deletes the DLC's files (not shared with base/other DLCs).
    $GOGCONF --removedlc "${1}" "${2}" --dbfile "$DBFILE"
}

function GOG_update(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    gogupdategamedetailsaftercmd $1 $GOGDL --auth-config-path "${AUTH_TOKENS}" update $1 --platform windows --path "${INSTALL_DIR}" --lang "${GOG_LANGUAGE:-en}" >> "${DECKY_PLUGIN_LOG_DIR}/${1}.log" 2>> $PROGRESS_LOG &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Updating\"}}"

}

function GOG_verify(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    $GOGDL --auth-config-path "${AUTH_TOKENS}" repair $1 --platform windows --path "${INSTALL_DIR}" >> "${DECKY_PLUGIN_LOG_DIR}/${1}.log" 2>> $PROGRESS_LOG &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Verifying\"}}"

}
function GOG_repair(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    gogupdategamedetailsaftercmd $1 $GOGDL --auth-config-path "${AUTH_TOKENS}" repair $1 --platform windows --path "${INSTALL_DIR}" >> "${DECKY_PLUGIN_LOG_DIR}/${1}.log" 2>> $PROGRESS_LOG &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    echo "{\"Type\": \"Progress\", \"Content\": {\"Message\": \"Repairing\"}}"

}

function GOG_install(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    INSTALL_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.log"
    rm $PROGRESS_LOG &>> ${INSTALL_LOG}

    echo "[GOG_install] Starting install for game_id=${1} steam_shortcut_id=${2}" >> ${INSTALL_LOG} 2>&1

    # Find and process goggame-{id}.info to extract exe path
    INFO_FILENAME="goggame-${1}.info"
    pushd "${INSTALL_DIR}" &>> ${INSTALL_LOG} || { echo "[GOG_install] ERROR: Cannot cd to ${INSTALL_DIR}" >> ${INSTALL_LOG}; return 1; }
    GAME_INFO=$(find . -type f -name "$INFO_FILENAME" -print -quit)
    echo "[GOG_install] INSTALL_DIR=${INSTALL_DIR}" >> ${INSTALL_LOG} 2>&1
    echo "[GOG_install] Looking for ${INFO_FILENAME}, found: '${GAME_INFO}'" >> ${INSTALL_LOG} 2>&1
    echo "Game info: ${GAME_INFO}" >> /dev/stderr

    # Determine game dir from info file path and snapshot .conf files
    if [[ -n "${GAME_INFO}" ]]; then
        GAME_SUBDIR=$(dirname "${GAME_INFO}")
        echo "[GOG_install] CHECKPOINT A (after download, before process-info): .conf files in ${INSTALL_DIR}/${GAME_SUBDIR}/" >> ${INSTALL_LOG} 2>&1
        ls -la "${INSTALL_DIR}/${GAME_SUBDIR}/"*.conf >> ${INSTALL_LOG} 2>&1 || echo "[GOG_install] CHECKPOINT A: NO .conf files found" >> ${INSTALL_LOG} 2>&1
        echo "[GOG_install] CHECKPOINT A: full ls of ${INSTALL_DIR}/${GAME_SUBDIR}/" >> ${INSTALL_LOG} 2>&1
        ls "${INSTALL_DIR}/${GAME_SUBDIR}/" >> ${INSTALL_LOG} 2>&1
    fi
    popd &>> ${INSTALL_LOG}

    if [[ -n "${GAME_INFO}" ]]; then
        echo "[GOG_install] Processing info file: ${GAME_INFO}" >> ${INSTALL_LOG} 2>&1
        $GOGCONF --process-info-file "${GAME_INFO}" --dbfile "$DBFILE" 2>> ${INSTALL_LOG}

        pushd "${INSTALL_DIR}" &>> ${INSTALL_LOG}
        echo "[GOG_install] CHECKPOINT B (after process-info): .conf files:" >> ${INSTALL_LOG} 2>&1
        ls -la "${INSTALL_DIR}/${GAME_SUBDIR}/"*.conf >> ${INSTALL_LOG} 2>&1 || echo "[GOG_install] CHECKPOINT B: NO .conf files found" >> ${INSTALL_LOG} 2>&1
        popd &>> ${INSTALL_LOG}
    else
        echo "[GOG_install] WARNING: No goggame info file found for ${1}" >> ${INSTALL_LOG} 2>&1
    fi

    echo "[GOG_install] Adding steam client ID: game=${1} shortcut=${2}" >> ${INSTALL_LOG} 2>&1
    RESULT=$($GOGCONF --addsteamclientid "${1}" "${2}" --dbfile "$DBFILE")
    echo "[GOG_install] addsteamclientid result: ${RESULT}" >> ${INSTALL_LOG} 2>&1

    if [[ -n "${GAME_SUBDIR}" ]]; then
        pushd "${INSTALL_DIR}" &>> ${INSTALL_LOG}
        echo "[GOG_install] CHECKPOINT C (after addsteamclientid): .conf files:" >> ${INSTALL_LOG} 2>&1
        ls -la "${INSTALL_DIR}/${GAME_SUBDIR}/"*.conf >> ${INSTALL_LOG} 2>&1 || echo "[GOG_install] CHECKPOINT C: NO .conf files found" >> ${INSTALL_LOG} 2>&1
        popd &>> ${INSTALL_LOG}
    fi

    TEMP=$($GOGCONF --update-umu-id "${1}" gog --dbfile "$DBFILE")
    echo "[GOG_install] update-umu-id result: ${TEMP}" >> ${INSTALL_LOG} 2>&1

    ARGS=$($ARGS_SCRIPT "${1}")
    echo "[GOG_install] ARGS_SCRIPT returned: ${ARGS}" >> ${INSTALL_LOG} 2>&1

    echo "[GOG_install] Requesting launch options for game=${1}" >> ${INSTALL_LOG} 2>&1
    TEMP=$($GOGCONF --launchoptions "${1}" "${ARGS}" "" --dbfile "$DBFILE" 2>> ${INSTALL_LOG})
    echo "[GOG_install] Launch options result: ${TEMP}" >> ${INSTALL_LOG} 2>&1

    if [[ -n "${GAME_SUBDIR}" ]]; then
        pushd "${INSTALL_DIR}" &>> ${INSTALL_LOG}
        echo "[GOG_install] CHECKPOINT D (after launchoptions): .conf files:" >> ${INSTALL_LOG} 2>&1
        ls -la "${INSTALL_DIR}/${GAME_SUBDIR}/"*.conf >> ${INSTALL_LOG} 2>&1 || echo "[GOG_install] CHECKPOINT D: NO .conf files found" >> ${INSTALL_LOG} 2>&1
        popd &>> ${INSTALL_LOG}
    fi

    echo "$TEMP"
    exit 0
}

function GOG_getlaunchoptions(){
    ARGS=$($ARGS_SCRIPT "${1}")
    TEMP=$($GOGCONF --launchoptions "${1}" "${ARGS}" "" --dbfile "$DBFILE")
    echo "$TEMP"
    exit 0
}

function GOG_uninstall(){
    GAME_DIR=$($GOGCONF --get-game-dir "${1}" --dbfile "$DBFILE")
    if [ -d "${GAME_DIR}" ]; then
        rm -rf "${GAME_DIR}"
    fi
    # Clean up gogdl's installed manifest so it doesn't think the game is still installed
    GOGDL_MANIFEST="${HOME}/.var/app/com.github.heroic_games_launcher.heroic-gogdl/config/heroic_gogdl/manifests/${1}"
    if [ -f "${GOGDL_MANIFEST}" ]; then
        rm -f "${GOGDL_MANIFEST}"
    fi
    TEMP=$($GOGCONF --clearsteamclientid "${1}" --dbfile "$DBFILE")
    echo "$TEMP"

}
function GOG_getgamedetails(){
    IMAGE_PATH=""
    TEMP=$($GOGCONF --getgamedata "${1}" "${IMAGE_PATH}" --dbfile "$DBFILE" --forkname "Proton" --version "null" --platform "Windows")
    echo "$TEMP"
    exit 0
}

function GOG_checkupdate(){
    TEMP=$($GOGCONF --has-updates "${1}" --dbfile "$DBFILE")
    echo "$TEMP"
}
function GOG_getgamesize(){
    TEMP=$($GOGCONF --get-game-size "${1}" "${2}"  --dbfile "$DBFILE")
    echo "$TEMP"
}

function GOG_getprogress()
{
    TEMP=$($GOGCONF --getprogress "${DECKY_PLUGIN_LOG_DIR}/${1}.progress" --dbfile "$DBFILE")
    echo "$TEMP"
}
function GOG_loginstatus(){
    if [[ -z $1 ]]; then
        FLUSH_CACHE=""
    else
        FLUSH_CACHE="--flush-cache"
    fi
    TEMP=$($GOGCONF --getloginstatus --dbfile "$DBFILE" $FLUSH_CACHE)
    echo "$TEMP"

}

function GOG_login(){
    get_steam_env
    launchoptions "${DECKY_PLUGIN_DIR}/scripts/Extensions/GOG/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "GOG Login"
}
function GOG_login-launch-options(){
    get_steam_env
    loginlaunchoptions  "${DECKY_PLUGIN_DIR}/scripts/Extensions/GOG/login.sh" "" "${DECKY_PLUGIN_LOG_DIR}" "GOG Login"
}


function GOG_logout(){
    rm -f "${AUTH_TOKENS}" 2>/dev/null
    rm -f "${DBFILE}" 2>/dev/null
    GOG_loginstatus --flush-cache
}

function GOG_toggle-autosync(){
    TEMP=$($GOGCONF --toggle-autosync "${1}" --dbfile "$DBFILE")
    echo "$TEMP"
}
function GOG_update-umu-id(){
    TEMP=$($GOGCONF --update-umu-id "${1}" gog --dbfile "$DBFILE")
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"Umu Id updated\"}}"
}

function GOG_download-saves(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    STEAM_CLIENT_ID="${2}"
    if [[ -z "${STEAM_CLIENT_ID}" ]]; then
        echo '{"Type": "Error", "Content": {"Message": "No SteamClientID - launch game once first"}}'
        return
    fi
    pushd "${DECKY_PLUGIN_DIR}" > /dev/null
    $GOGCONF --sync-saves "${1}" --skip-upload --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/${1}.log" 2>> $PROGRESS_LOG &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    popd > /dev/null
    echo '{"Type": "Progress", "Content": {"Message": "Downloading Saves"}}'
}

function GOG_upload-saves(){
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    STEAM_CLIENT_ID="${2}"
    if [[ -z "${STEAM_CLIENT_ID}" ]]; then
        echo '{"Type": "Error", "Content": {"Message": "No SteamClientID - launch game once first"}}'
        return
    fi
    pushd "${DECKY_PLUGIN_DIR}" > /dev/null
    $GOGCONF --sync-saves "${1}" --skip-download --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/${1}.log" 2>> $PROGRESS_LOG &
    echo $! > "${DECKY_PLUGIN_LOG_DIR}/${1}.pid"
    popd > /dev/null
    echo '{"Type": "Progress", "Content": {"Message": "Uploading Saves"}}'
}

function GOG_run-exe(){
    get_steam_env
    SETTINGS=$($GOGCONF --get-env-settings "$ID" --dbfile "$DBFILE")
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
    GAME_PATH=$($GOGCONF --get-game-dir "$GAME_SHORTNAME" --dbfile "$DBFILE")
    launchoptions "\\\"${GAME_PATH}/${GAME_EXE}\\\""  "${ARGS}  &> ${DECKY_PLUGIN_LOG_DIR}/run-exe.log" "${GAME_PATH}" "Run exe" true "${COMPAT_TOOL}"
}
function GOG_get-exe-list(){
    get_steam_env
    STEAM_ID="${1}"
    GAME_SHORTNAME="${2}"
    GAME_PATH=$($GOGCONF --get-game-dir "$GAME_SHORTNAME" --dbfile "$DBFILE")
    export STEAM_COMPAT_DATA_PATH="${HOME}/.local/share/Steam/steamapps/compatdata/${STEAM_ID}"
    export STEAM_COMPAT_CLIENT_INSTALL_PATH="${GAME_PATH}"
    cd "${STEAM_COMPAT_CLIENT_INSTALL_PATH}"
    JSON="{\"Type\": \"FileContent\", \"Content\": {\"PathRoot\": \"${GAME_PATH}\", \"Files\": ["
    SEP=""

    while IFS= read -r -d '' FILE; do
        JSON="${JSON}${SEP}{\"Path\": \"${FILE}\"}"
        SEP=","
    done < <(find . \( -name "*.exe" -o -iname "*.bat" -o -iname "*.msi" \) -print0)

    JSON="${JSON}]}}"
    echo "$JSON"
}

function GOG_getsetting(){
    TEMP=$($GOGCONF --getsetting "$1" --dbfile "$DBFILE")
    echo "$TEMP"
}
function GOG_savesetting(){
    $GOGCONF --savesetting "$1" "$2" --dbfile "$DBFILE"
}
function GOG_getjsonimages(){

    TEMP=$($GOGCONF --get-base64-images "${1}" --dbfile "$DBFILE" --offline)
    echo "$TEMP"
}
function GOG_gettabconfig(){
    if [[ ! -d "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas" ]]; then
        mkdir -p "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas"
    fi
    if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/gogtabconfig.json" ]]; then
        TEMP=$(cat "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/gogtabconfig.json")
    else
        TEMP=$(cat "${DECKY_PLUGIN_DIR}/conf_schemas/gogtabconfig.json")
    fi
    # Inject current SteamGridDB API key from shared file
    SGDB_KEY=""
    if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/steamgriddb_api_key" ]]; then
        SGDB_KEY=$(cat "${DECKY_PLUGIN_RUNTIME_DIR}/steamgriddb_api_key")
    fi
    TEMP=$(echo "$TEMP" | jq --arg key "$SGDB_KEY" \
      '(.Sections[] | select(.Name=="SteamGridDB") .Options[] | select(.Key=="SteamGridDBApiKey")).Value = $key')
    echo "{\"Type\":\"IniContent\", \"Content\": ${TEMP}}"
}
function GOG_savetabconfig(){
    CONFIG=$(cat)
    echo "$CONFIG" > "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/gogtabconfig.json"
    # Extract and save SteamGridDB API key to shared location
    SGDB_KEY=$(echo "$CONFIG" | jq -r '.Sections[] | select(.Name=="SteamGridDB") | .Options[] | select(.Key=="SteamGridDBApiKey") | .Value // empty')
    if [[ -n "$SGDB_KEY" ]]; then
        echo "$SGDB_KEY" > "${DECKY_PLUGIN_RUNTIME_DIR}/steamgriddb_api_key"
    fi
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"GOG tab config saved\"}}"
}

function GOG_lookup-protonfixes(){
    TEMP=$(python3 "${DECKY_PLUGIN_DIR}/scripts/proton_tools.py" --lookup "${1}" --store gog --shortname "${1}" --dbfile "$DBFILE")
    echo "$TEMP"
}

function GOG_apply-protonfixes(){
    TEMP=$(python3 "${DECKY_PLUGIN_DIR}/scripts/proton_tools.py" --apply "${1}" --store gog --shortname "${1}" --dbfile "$DBFILE" --platform Proton)
    echo "$TEMP"
}

function GOG_retrodetect-game-types(){
    $GOGCONF --retrodetect --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/detection.log" 2>&1
    echo "{\"Type\": \"Success\", \"Content\": {\"Message\": \"Game types retrodetected\"}}"
}

function gogupdategamedetailsaftercmd() {
    game=$1
    shift
    "$@"

    # gogdl puts support files (DOSBox confs, etc.) in gog-support/<id>/app/
    # instead of the game root. Copy them into the game directory so they're
    # where the goggame info file expects them.
    GAME_DIR=$($GOGCONF --get-game-dir "$game" --dbfile "$DBFILE" 2>/dev/null)
    if [[ -z "${GAME_DIR}" ]]; then
        # Fallback: find the game folder via the goggame info file
        INFO_FILE=$(find "${INSTALL_DIR}" -maxdepth 2 -name "goggame-${game}.info" -print -quit 2>/dev/null)
        if [[ -n "${INFO_FILE}" ]]; then
            GAME_DIR=$(dirname "${INFO_FILE}")
        fi
    fi

    SUPPORT_DIR="${GAME_DIR}/gog-support/${game}/app"
    if [[ -d "${SUPPORT_DIR}" ]]; then
        echo "[post-download] Found gog-support dir: ${SUPPORT_DIR}" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
        echo "[post-download] Contents:" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
        ls -la "${SUPPORT_DIR}/" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
        cp -rn "${SUPPORT_DIR}/"* "${GAME_DIR}/" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
        echo "[post-download] Copied support files to ${GAME_DIR}/" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
    else
        echo "[post-download] No gog-support dir at ${SUPPORT_DIR}" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
    fi

    "$GOGCONF" --update-game-details "$game" --dbfile "$DBFILE" >> "${DECKY_PLUGIN_LOG_DIR}/${game}.log" 2>&1
}
