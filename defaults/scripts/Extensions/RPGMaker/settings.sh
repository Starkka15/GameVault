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
# The drop folder is "AddedGames" (was "RPGMaker" pre-v1.1.6 — see migration below).
if [[ "${RPGMAKER_INSTALLLOCATION}" == "MicroSD" ]]; then
    NVME=$(lsblk --list | grep nvme0n1\ | awk '{ print $2}' | awk '{split($0, a,":"); print a[1]}')
    LINK=$(find /run/media -maxdepth 1 -type l)
    LINK_TARGET=$(readlink -f "${LINK}")
    MOUNT_POINT=$(lsblk --list --exclude "${NVME}" | grep part | sed -n 's/.*part //p')
    if [[ "${MOUNT_POINT}" == "${LINK_TARGET}" ]]; then
        INSTALL_DIR="${LINK}/Games/AddedGames/"
    else
        INSTALL_DIR="/run/media/mmcblk0p1/Games/AddedGames/"
    fi
else
    INSTALL_DIR="${HOME}/Games/AddedGames/"
fi

if [[ -f "${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker_overrides.sh" ]]; then
   source "${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker_overrides.sh"
fi

# --- v1.1.6 auto-migration: rename the old "RPGMaker" drop folder to "AddedGames" ---
# Move the old real directory's contents into the new one and leave a symlink behind so
# existing Steam shortcuts (StartDir) and not-yet-rescanned DB paths keep resolving. The
# DB rows themselves are re-homed identity-preserving in rpgmaker.py get_list(). Runs once
# (guarded by "-L": once RPGMaker is a symlink we skip). Sourced by every action AND by the
# launcher, so it fires even when a user launches an old shortcut without opening the tab.
OLD_DIR="${INSTALL_DIR%/}"; OLD_DIR="${OLD_DIR%/AddedGames}/RPGMaker"
if [[ -d "${OLD_DIR}" && ! -L "${OLD_DIR}" ]]; then
    mkdir -p "${INSTALL_DIR}" 2>/dev/null
    shopt -s dotglob nullglob
    for e in "${OLD_DIR}"/*; do
        base=$(basename "$e")
        [[ -e "${INSTALL_DIR%/}/$base" ]] || mv "$e" "${INSTALL_DIR%/}/"
    done
    shopt -u dotglob nullglob
    if rmdir "${OLD_DIR}" 2>/dev/null; then
        ln -s "${INSTALL_DIR%/}" "${OLD_DIR}" 2>/dev/null
    fi
    # Re-home DB rows (RootFolder/InstallPath/icons) to the new path in place, so games
    # reflect AddedGames immediately without waiting for a Refresh/rescan. Identity-
    # preserving (ShortName untouched) → existing Steam shortcuts keep working. Idempotent.
    "${RPGMAKERCONF}" --migrate-added-games --dbfile "${DBFILE}" >/dev/null 2>&1 || true
fi

mkdir -p "${INSTALL_DIR}" 2>/dev/null
export INSTALL_DIR
# Native runtimes (installed by install_deps.sh).
export RPGMAKER_RUNTIME="${DECKY_PLUGIN_RUNTIME_DIR}/rpgmaker"
