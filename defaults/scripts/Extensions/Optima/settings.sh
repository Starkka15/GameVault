#!/usr/bin/env bash
OPTIMACONF="${DECKY_PLUGIN_DIR}/scripts/optima-config.py"
export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH

export LAUNCHER="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/Optima/optima-launcher.sh"
export ARGS_SCRIPT="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/Optima/get-optima-args.sh"

DBNAME="optima.db"
DBFILE="${DECKY_PLUGIN_RUNTIME_DIR}/optima.db"

export OPTIMA_CMD="${HOME}/.local/bin/optima-cli"
export NO_COLOR=1
# The Ubisoft Uplay R1 emu inside optima-cli is fed the account profile; the game
# runs fully offline for single-player. Nothing to skip/bootstrap here — optima-cli
# stands up its own Proton prefix (reusing maxima's umu/Proton bundle if present).

if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/optimatabconfig.json" ]]; then
    TEMP="${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/optimatabconfig.json"
else
    TEMP="${DECKY_PLUGIN_DIR}/conf_schemas/optimatabconfig.json"
fi
SETTINGS=$($OPTIMACONF --generate-env-settings-json $TEMP --dbfile $DBFILE 2>/dev/null) || true
eval "${SETTINGS}" 2>/dev/null || true

if [[ "${OPTIMA_INSTALLLOCATION}" == "SSD" ]]; then
    INSTALL_DIR="${HOME}/Games/optima/"
elif [[ "${OPTIMA_INSTALLLOCATION}" == "MicroSD" ]]; then
    NVME=$(lsblk --list | grep nvme0n1\ |awk '{ print $2}' |  awk '{split($0, a,":"); print a[1]}')
    LINK=$(find /run/media -maxdepth 1  -type l )
    LINK_TARGET=$(readlink -f "${LINK}")
    MOUNT_POINT=$(lsblk --list --exclude "${NVME}" | grep part |  sed -n 's/.*part //p')
    if [[ "${MOUNT_POINT}" == "${LINK_TARGET}" ]]; then
        INSTALL_DIR="${LINK}/Games/optima/"
    else
        INSTALL_DIR="/run/media/mmcblk0p1/Games/optima/"
    fi
else
    INSTALL_DIR="${HOME}/Games/optima/"
fi

# Optionally propagate a preferred Proton (e.g. UMU-Proton-9.0-4e) to optima-cli.
# Set OPTIMA_PROTON in optima_overrides.sh to pin a version per device.
if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/optima_overrides.sh" ]]; then
   source "${DECKY_PLUGIN_RUNTIME_DIR}/optima_overrides.sh"
fi

export INSTALL_DIR
