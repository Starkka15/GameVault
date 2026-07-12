#!/usr/bin/env bash
EACONF="${DECKY_PLUGIN_DIR}/scripts/ea-config.py"
export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH

export LAUNCHER="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/ea-launcher.sh"
export ARGS_SCRIPT="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/get-ea-args.sh"

DBNAME="ea.db"
DBFILE="${DECKY_PLUGIN_RUNTIME_DIR}/ea.db"

export MAXIMA_CMD="${HOME}/.local/bin/maxima-cli"
export MAXIMA_DISABLE_QRC=1
# NOTE: MAXIMA_SKIP_BOOTSTRAP / MAXIMA_DISABLE_WINE_VERIFICATION are deliberately
# NOT set here. `maxima-cli launch` needs the bootstrap (umu/GE-Proton runtime)
# and wine verification to stand up the prefix it runs the game in; setting them
# would break the launch path. They only ever applied to the install-only flow.
# Skip the EA Touchup.exe installer step at end of install: under Proton the
# DirectX/XAudio/vcredist redists it registers are already provided, we resolve
# the game exe ourselves (not via its registry key), and some titles' Touchup
# exits non-zero (Battlefield Hardline) which otherwise aborts the install.
# Makes the install "wrap-up" instant instead of a slow/fragile wine step.
export MAXIMA_SKIP_TOUCHUP=1
export NO_COLOR=1

if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/eatabconfig.json" ]]; then
    TEMP="${DECKY_PLUGIN_RUNTIME_DIR}/conf_schemas/eatabconfig.json"
else
    TEMP="${DECKY_PLUGIN_DIR}/conf_schemas/eatabconfig.json"
fi
SETTINGS=$($EACONF --generate-env-settings-json $TEMP --dbfile $DBFILE 2>/dev/null) || true
eval "${SETTINGS}" 2>/dev/null || true

if [[ "${EA_INSTALLLOCATION}" == "SSD" ]]; then
    INSTALL_DIR="${HOME}/Games/ea/"
elif [[ "${EA_INSTALLLOCATION}" == "MicroSD" ]]; then
    NVME=$(lsblk --list | grep nvme0n1\ |awk '{ print $2}' |  awk '{split($0, a,":"); print a[1]}')
    LINK=$(find /run/media -maxdepth 1  -type l )
    LINK_TARGET=$(readlink -f "${LINK}")
    MOUNT_POINT=$(lsblk --list --exclude "${NVME}" | grep part |  sed -n 's/.*part //p')
    if [[ "${MOUNT_POINT}" == "${LINK_TARGET}" ]]; then
        INSTALL_DIR="${LINK}/Games/ea/"
    else
        INSTALL_DIR="/run/media/mmcblk0p1/Games/ea/"
    fi
else
    INSTALL_DIR="${HOME}/Games/"
fi

if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/ea_overrides.sh" ]]; then
   source "${DECKY_PLUGIN_RUNTIME_DIR}/ea_overrides.sh"
fi

export INSTALL_DIR
