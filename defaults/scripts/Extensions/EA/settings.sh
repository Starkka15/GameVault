#!/usr/bin/env bash
EACONF="${DECKY_PLUGIN_DIR}/scripts/ea-config.py"
export PYTHONPATH="${DECKY_PLUGIN_DIR}/scripts/":"${DECKY_PLUGIN_DIR}/scripts/shared/":$PYTHONPATH

export LAUNCHER="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/ea-launcher.sh"
export ARGS_SCRIPT="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/get-ea-args.sh"

DBNAME="ea.db"
DBFILE="${DECKY_PLUGIN_RUNTIME_DIR}/ea.db"

export MAXIMA_CMD="${HOME}/.local/bin/maxima-cli"
export MAXIMA_DISABLE_QRC=1
# maxima-cli's launch-time "wine verification" queries GitHub for the latest
# GE-Proton release and matches an asset against the regex `GE-Proton\d+-\d+\.tar\.gz`.
# GloriousEggroll now ships the x86_64 tarball as `GE-Proton<ver>-x86_64.tar.gz`
# (the `-x86_64` suffix arrived after GE-Proton11-3, alongside the aarch64 builds),
# so that regex matches nothing on current releases and the check dies with
# "couldn't find suitable wine release" — aborting the launch even though a valid
# GE-Proton is already installed and the prefix is fully stood up.
#
# So: when a GE-Proton runtime is ALREADY present, skip the (broken, network-
# dependent) verification and launch with what's installed. A first-time user with
# no runtime yet still runs verification/bootstrap normally — the pinned GE-Proton
# in dependency-versions.toml has a plain-named x86_64 asset that still matches, so
# the initial download is unaffected. Proper fix belongs upstream in maxima-cli:
# widen the asset regex to accept the `-x86_64` suffix and make the update check
# non-fatal (fall back to the installed runtime when GitHub can't be resolved).
_maxima_proton_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/maxima/wine/proton"
if [[ -f "${_maxima_proton_dir}/version" ]]; then
    export MAXIMA_DISABLE_WINE_VERIFICATION=1
fi
unset _maxima_proton_dir
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
