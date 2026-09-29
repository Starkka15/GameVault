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



source "${DECKY_PLUGIN_DIR}/scripts/Extensions/Zoom/settings.sh"

echo "dbfile: ${DBFILE}"
SETTINGS=$($ZOOMCONF --get-env-settings $ID --dbfile $DBFILE --platform Proton --fork "" --version "" --dbfile $DBFILE)
echo "${SETTINGS}"
eval "${SETTINGS}"


if [[ "${RUNTIMES_ESYNC}" == "true" ]]; then
    export PROTON_NO_ESYNC=1
else
    export PROTON_NO_ESYNC=0
fi
if [[ "${RUNTIMES_FSYNC}" == "true" ]]; then
    export PROTON_NO_FSYNC=1
else
    export PROTON_NO_FSYNC=0
fi
if [[ "${RUNTIMES_VKD3D}" == "true" ]]; then
    export PROTON_USE_WINED3D=1
else
    export PROTON_USE_WINED3D=0
fi
if [[ "${RUNTIMES_VKD3D_PROTON}" == "true" ]]; then
    export PROTON_USE_WINED3D=0
    export PROTON_USE_WINED3D11=1
else
    export PROTON_USE_WINED3D11=0
fi
if [[ "${RUNTIMES_FSR}" == "true" ]]; then
    export WINE_FULLSCREEN_FSR=1
else
    export WINE_FULLSCREEN_FSR=0
fi
if [ -z "${RUNTIMES_FSR_STRENGTH}" ]; then
    unset WINE_FULLSCREEN_FSR_STRENGTH
else
    export WINE_FULLSCREEN_FSR_STRENGTH=${RUNTIMES_FSR_STRENGTH}
fi

if [[ "${RUNTIMES_LIMIT_FRAMERATE}" == "true" ]]; then
    export DXVK_FRAME_RATE=${RUNTIMES_FRAME_RATE}
fi
if [[ "${RUNTIMES_EASYANTICHEAT}" == "true" ]]; then
    echo "enabling easy anti cheat"
    export PROTON_EAC_RUNTIME="${HOME}/.steam/root/steamapps/common/Proton EasyAntiCheat Runtime/"
fi
if [[ "${RUNTIMES_BATTLEYE}" == "true"  ]]; then
    export PROTON_BATTLEYE_RUNTIME="${HOME}/.steam/root/steamapps/common/Proton BattlEye Runtime/"
fi

if [ -z "${RUNTIMES_PULSE_LATENCY_MSEC}" ]; then
    export PULSE_LATENCY_MSEC=$RUNTIMES_PULSE_LATENCY_MSEC

fi
if [[ "${RUNTIMES_RADV_PERFTEST}" == "" ]]; then
    unset RADV_PERFTEST
else
    export RADV_PERFTEST=$RUNTIMES_RADV_PERFTEST
fi
if [[ "${RUNTIMES_PROTON_FORCE_LARGE_ADDRESS_AWARE}" == "true" ]]; then
    export PROTON_FORCE_LARGE_ADDRESS_AWARE=1
else
    unset PROTON_FORCE_LARGE_ADDRESS_AWARE
fi

if [[ "${ADVANCED_VK_ICD_FILENAMES}" == "true" ]]; then
    export VK_ICD_FILENAMES="${HOME}/mesa/share/vulkan/icd.d/radeon_icd.x86_64.json"
fi
if [[ "${RUNTIMES_MESA_EXTENSION_MAX_YEAR}" == "" ]]; then
    unset MESA_EXTENSION_MAX_YEAR
else
    export MESA_EXTENSION_MAX_YEAR=$RUNTIMES_MESA_EXTENSION_MAX_YEAR
fi


CMD=${*}

echo "CMD: ${CMD}"


QUOTED_ARGS=""
for arg in "$@"; do
    QUOTED_ARGS+=" \"${arg}\""
done

ARGS=""
if [[ -f "${ARGS_SCRIPT}" ]]; then
    ARGS=$("${ARGS_SCRIPT}" "$ID")
fi
if [[ "${ADVANCED_IGNORE_ITCHIO_ARGS}" == "true" ]]; then
    ARGS="${ADVANCED_ARGUMENTS}"
else
    ARGS="${ARGS} ${ADVANCED_ARGUMENTS}"
fi


echo "ARGS: ${ARGS}" &>> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"
for arg in $ARGS; do
    QUOTED_ARGS+=" ${arg}"

done

pushd "${DECKY_PLUGIN_DIR}"
GAME_PATH=$($ZOOMCONF --get-game-dir "$ID" --dbfile $DBFILE)
popd
echo "game path: ${GAME_PATH}" &> "${GAME_PATH}/launcher.log"
export STEAM_COMPAT_INSTALL_PATH=${GAME_PATH}
if [[ "${ADVANCED_SET_STEAM_COMPAT_LIBRARY_PATHS}" == "true" ]]; then
    export STEAM_COMPAT_LIBRARY_PATHS=${STEAM_COMPAT_LIBRARY_PATHS}:${GAME_PATH}
fi
export PROTON_SET_GAME_DRIVE="gamedrive"

echo -e "Running: ${QUOTED_ARGS}" >> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"

UMU_ID=""

if [[ "${ITCHIO_ENABLE_UMU_FIXES}" != "false" ]]; then
    export STORE="zoom"
    UMU_ID=$($ZOOMCONF --get-umu-id "$ID" --dbfile $DBFILE)
    export UMU_ID="${UMU_ID}"
fi

if [[ "${UMU_ID}" == "" ]]; then
    unset UMU_ID
    unset STORE
fi

if [ -f "$HOME/.local/lib/liblsfg-vk.so" ]; then
    if [[ "${DISABLE_LSFGVK}" != "1" && "${DISABLE_LSFGVK}" != "true" ]]; then
        export LD_PRELOAD="$HOME/.local/lib/:${LD_PRELOAD}"
        echo "LSFG-VK enabled" &>> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"
    else
        echo "LSFG-VK disabled for this game" &>> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"
    fi
else
    echo "LSFG-VK not installed" &>> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"
fi

eval "$(echo -e "${ADVANCED_VARIABLES}")" &>> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"

eval "$(echo -e "$QUOTED_ARGS")"  &>> "${DECKY_PLUGIN_LOG_DIR}/${ID}.log"
