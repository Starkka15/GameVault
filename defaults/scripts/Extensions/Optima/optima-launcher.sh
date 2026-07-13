#!/usr/bin/env bash
# Steam invokes this as:  optima-launcher.sh <product_id>
#
# The game is launched through `optima-cli launch <product_id>`, which writes the
# Uplay.toml/Uplay.ini, deploys the Uplay R1 DRM shim into the game folder, seeds
# the Ubisoft install registry + any shipped .reg, and runs the game exe under
# its OWN umu/Proton runtime. The Steam shortcut runs this script NATIVELY
# (Compatibility=false) — optima-cli does all the Proton work itself, so we do
# NOT want Steam to wrap us in a second Proton.
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="Extensions"
ID=$1

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/Optima/settings.sh"

mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/${ID}.log"

# Steam Game Mode launches with LC_ALL=C (POSIX). Force UTF-8 if not already, so
# multibyte paths encode correctly under Proton.
eff_locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$eff_locale" in
  *[Uu][Tt][Ff]*) : ;;
  *) export LANG=C.UTF-8 LC_ALL=C.UTF-8 ;;
esac

# Proton tuning from the GameVault UI (RUNTIMES_* -> PROTON_*/DXVK_*). optima-cli
# passes the environment through to umu/Proton, so these still apply.
SETTINGS=$($OPTIMACONF --get-env-settings "$ID" --dbfile "$DBFILE" --platform Proton --fork "" --version "" 2>/dev/null)
eval "${SETTINGS}" 2>/dev/null

[[ "${RUNTIMES_ESYNC}" == "true" ]] && export PROTON_NO_ESYNC=1 || export PROTON_NO_ESYNC=0
[[ "${RUNTIMES_FSYNC}" == "true" ]] && export PROTON_NO_FSYNC=1 || export PROTON_NO_FSYNC=0
if [[ "${RUNTIMES_VKD3D_PROTON}" == "true" ]]; then
    export PROTON_USE_WINED3D=0; export PROTON_USE_WINED3D11=1
elif [[ "${RUNTIMES_VKD3D}" == "true" ]]; then
    export PROTON_USE_WINED3D=1
else
    export PROTON_USE_WINED3D=0
fi
[[ "${RUNTIMES_FSR}" == "true" ]] && export WINE_FULLSCREEN_FSR=1 || export WINE_FULLSCREEN_FSR=0
[[ -n "${RUNTIMES_FSR_STRENGTH}" ]] && export WINE_FULLSCREEN_FSR_STRENGTH="${RUNTIMES_FSR_STRENGTH}"
[[ "${RUNTIMES_LIMIT_FRAMERATE}" == "true" ]] && export DXVK_FRAME_RATE="${RUNTIMES_FRAME_RATE}"
[[ "${RUNTIMES_PROTON_FORCE_LARGE_ADDRESS_AWARE}" == "true" ]] && export PROTON_FORCE_LARGE_ADDRESS_AWARE=1
[[ -n "${RUNTIMES_RADV_PERFTEST}" ]] && export RADV_PERFTEST="${RUNTIMES_RADV_PERFTEST}"

# Per-game launch args: DB Arguments (user-overridable in the UI) via get-optima-args.sh.
# optima-cli reads extra game args from OPTIMA_ARGS, so forward them that way.
ARGS=""
if [[ -f "${ARGS_SCRIPT}" ]]; then
    ARGS=$("${ARGS_SCRIPT}" "$ID")
fi
if [[ -n "${ADVANCED_IGNORE_EA_ARGS}" || -n "${ADVANCED_ARGUMENTS}" ]]; then
    if [[ "${ADVANCED_IGNORE_EA_ARGS}" == "true" ]]; then
        ARGS="${ADVANCED_ARGUMENTS}"
    else
        ARGS="${ARGS} ${ADVANCED_ARGUMENTS}"
    fi
fi
[[ -n "${ADVANCED_VARIABLES}" ]] && eval "$(echo -e "${ADVANCED_VARIABLES}")" 2>/dev/null
[[ -n "${ARGS// }" ]] && export OPTIMA_ARGS="${ARGS}"

# Resolve the install dir so optima-cli launches the right copy (matches what the
# store installed). Falls back to optima-cli's own default if absent.
GAME_DIR=$("$OPTIMACONF" --get-game-dir "$ID" --dbfile "$DBFILE" 2>/dev/null | tail -1)

echo "[$(date)] launching product '${ID}' via optima-cli (args: ${ARGS}, dir: ${GAME_DIR})" >> "$LOG"

if [[ -n "${GAME_DIR}" && -d "${GAME_DIR}" ]]; then
    exec "$OPTIMA_CMD" launch "$ID" --path "${GAME_DIR}" >> "$LOG" 2>&1
else
    exec "$OPTIMA_CMD" launch "$ID" >> "$LOG" 2>&1
fi
