#!/usr/bin/env bash
RPGMAKERCONF="${DECKY_PLUGIN_DIR}/scripts/rpgmaker-config.py"
export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH

export LAUNCHER="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/RPGMaker/rpgmaker-launcher.sh"
export ARGS_SCRIPT="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/RPGMaker/get-rpgmaker-args.sh"

DBNAME="rpgmaker.db"
DBFILE="${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker.db"

if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/rpgmakertabconfig.json" ]]; then
    TEMP="${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/rpgmakertabconfig.json"
else
    TEMP="${DECKY_PLUGIN_DIR}/conf_schemas/rpgmakertabconfig.json"
fi
SETTINGS=$($RPGMAKERCONF --generate-env-settings-json $TEMP --dbfile $DBFILE 2>/dev/null) || true
eval "${SETTINGS}" 2>/dev/null || true

# Scan / install location (SD-card aware, mirrors Itchio's settings.sh).
if [[ "${RPGMAKER_INSTALLLOCATION}" == "MicroSD" ]]; then
    NVME=$(lsblk --list | grep nvme0n1\ | awk '{ print $2}' | awk '{split($0, a,":"); print a[1]}')
    LINK=$(find /run/media -maxdepth 1 -type l)
    LINK_TARGET=$(readlink -f "${LINK}")
    MOUNT_POINT=$(lsblk --list --exclude "${NVME}" | grep part | sed -n 's/.*part //p')
    if [[ "${MOUNT_POINT}" == "${LINK_TARGET}" ]]; then
        INSTALL_DIR="${LINK}/Games/RPGMaker/"
    else
        INSTALL_DIR="/run/media/mmcblk0p1/Games/RPGMaker/"
    fi
else
    INSTALL_DIR="${HOME}/Games/RPGMaker/"
fi

if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker_overrides.sh" ]]; then
   source "${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker_overrides.sh"
fi

mkdir -p "${INSTALL_DIR}" 2>/dev/null
export INSTALL_DIR
# Native runtimes (installed by install_deps.sh).
export RPGMAKER_RUNTIME="${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker"
