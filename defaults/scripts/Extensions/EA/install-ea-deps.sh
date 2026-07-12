#!/usr/bin/env bash
# Install a game's runtime dependencies (from ea-dependencies.conf) into the
# maxima Proton prefix using winetricks + GE-Proton's own wine.
#
# Usage:  install-ea-deps.sh <slug>
#
# Idempotent: only verbs not already recorded in the prefix's winetricks.log are
# installed, so it's cheap to call on every launch and a no-op once done.
set -u
ID="${1:-}"
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
export DECKY_PLUGIN_DIR="${DECKY_PLUGIN_DIR:-${HOME}/homebrew/plugins/GameVault}"
export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-${HOME}/homebrew/logs/GameVault}"
mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/${ID}.deps.log"
DEPFILE="${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/ea-dependencies.conf"

[[ -z "$ID" ]] && { echo "usage: install-ea-deps.sh <slug>"; exit 2; }
[[ -f "$DEPFILE" ]] || { echo "no dependency file"; exit 0; }

# Verbs listed for this slug (first matching line; strip inline comments/spaces).
VERBS=$(grep -E "^${ID}=" "$DEPFILE" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/#.*//')
if [[ -z "${VERBS// /}" ]]; then
    echo "[$(date)] no deps listed for '${ID}'" >> "$LOG"
    exit 0
fi

# maxima's shared Proton prefix + the GE-Proton wine that created it. (When
# maxima gains per-game prefixes this path becomes per-game; the rest is the
# same.) If the runtime isn't set up yet, skip quietly — the game's first
# maxima-cli launch installs Proton, after which this runs on a later launch.
PFX="${MAXIMA_WINE_PREFIX:-${HOME}/.local/share/maxima/wine/prefix}"
PROTON_DIR="${HOME}/.local/share/maxima/wine/proton/files"
PROTON_WINE="${PROTON_DIR}/bin/wine"
if [[ ! -x "$PROTON_WINE" ]]; then
    echo "[$(date)] maxima Proton runtime not present yet; skipping deps for '${ID}'" >> "$LOG"
    exit 0
fi
# Filter to verbs not already installed in this prefix (winetricks records each
# applied verb in <prefix>/winetricks.log).
TODO=""
WT_LOG="${PFX}/winetricks.log"
for v in $VERBS; do
    if [[ -f "$WT_LOG" ]] && grep -qx "$v" "$WT_LOG" 2>/dev/null; then
        continue
    fi
    TODO="${TODO} ${v}"
done
if [[ -z "${TODO// /}" ]]; then
    echo "[$(date)] deps already present for '${ID}' (${VERBS})" >> "$LOG"
    exit 0
fi

# SteamOS/Ally ships no winetricks and its rootfs is read-only, so we can't
# pacman it. winetricks is a single self-contained bash script, so fetch it into
# our writable runtime dir once and reuse it. (Verbs like physx are plain silent
# .exe installers run through wine — no cabextract/7z needed.)
WINETRICKS=$(command -v winetricks 2>/dev/null)
if [[ -z "$WINETRICKS" ]]; then
    WT_DIR="${DECKY_PLUGIN_RUNTIME_DIR}/bin"
    WINETRICKS="${WT_DIR}/winetricks"
    if [[ ! -x "$WINETRICKS" ]]; then
        mkdir -p "$WT_DIR"
        echo "[$(date)] winetricks not present; downloading to ${WINETRICKS}" >> "$LOG"
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks" -o "$WINETRICKS" >> "$LOG" 2>&1
        elif command -v wget >/dev/null 2>&1; then
            wget -q "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks" -O "$WINETRICKS" >> "$LOG" 2>&1
        fi
        if [[ ! -s "$WINETRICKS" ]]; then
            echo "[$(date)] failed to download winetricks; cannot install deps (${VERBS})" >> "$LOG"
            rm -f "$WINETRICKS"
            exit 0
        fi
        chmod +x "$WINETRICKS"
    fi
fi

echo "[$(date)] installing deps for '${ID}':${TODO}" >> "$LOG"
export WINEPREFIX="$PFX"
export WINE="$PROTON_WINE"
export WINESERVER="${PROTON_DIR}/bin/wineserver"
# Don't let mono/gecko installer prompts block an unattended run.
export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
# winetricks needs HOME writable for its cache; steamos default HOME is fine.
# shellcheck disable=SC2086  # verbs must word-split into separate args
"$WINETRICKS" -q $TODO >> "$LOG" 2>&1
rc=$?
echo "[$(date)] winetricks rc=${rc} for '${ID}' (${TODO})" >> "$LOG"
exit 0
