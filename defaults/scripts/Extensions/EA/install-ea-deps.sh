#!/usr/bin/env bash
# Resolve a game's runtime dependencies into the maxima Proton prefix via
# winetricks — ONCE. Verbs come from two sources, merged:
#   1. auto-scan of the install dir for bundled redists (dotnet/DirectX/VC++/PhysX)
#   2. explicit overrides in ea-dependencies.conf (for cases a game doesn't bundle)
#
# Usage:  install-ea-deps.sh <slug> [game_dir]
#
# One-time by design: on a fully successful resolution a marker is written and
# every later launch fast-exits on a single file test (no scan, no winetricks) for
# a quick start. A failed/incomplete run leaves NO marker, so it retries next
# launch. The marker is cleared on (re)install and uninstall (see EA store.sh).
set -u
ID="${1:-}"
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
export DECKY_PLUGIN_DIR="${DECKY_PLUGIN_DIR:-${HOME}/homebrew/plugins/GameVault}"
export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-${HOME}/homebrew/logs/GameVault}"
mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/${ID}.deps.log"
DEPFILE="${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/ea-dependencies.conf"
SCANNER="${DECKY_PLUGIN_DIR}/scripts/scan-winetricks-deps.sh"
STATE_DIR="${DECKY_PLUGIN_RUNTIME_DIR}/deps-state"
MARK="${STATE_DIR}/${ID}.done"

[[ -z "$ID" ]] && { echo "usage: install-ea-deps.sh <slug> [game_dir]"; exit 2; }

# --- Fast path: already resolved once -> skip everything for a quick launch. ---
[[ -f "$MARK" ]] && exit 0
mkdir -p "$STATE_DIR"

# --- Gather verbs: explicit conf + auto-scan of the install dir. ---
CONF_VERBS=""
if [[ -f "$DEPFILE" ]]; then
    CONF_VERBS=$(grep -E "^${ID}=" "$DEPFILE" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/#.*//')
fi
GAME_DIR="${2:-${INSTALL_DIR:-${HOME}/Games/ea/}${ID}}"
SCANNED=""
if [[ -f "$SCANNER" && -d "$GAME_DIR" ]]; then
    SCANNED=$(bash "$SCANNER" "$GAME_DIR" 2>/dev/null)
fi
VERBS=$(printf '%s %s\n' "$CONF_VERBS" "$SCANNED" | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' ')

# Nothing needed -> mark done so we never scan this game again.
if [[ -z "${VERBS// /}" ]]; then
    echo "[$(date)] no deps needed for '${ID}' (scanned '${GAME_DIR}')" >> "$LOG"
    : > "$MARK"
    exit 0
fi
echo "[$(date)] deps for '${ID}': conf=[${CONF_VERBS# }] scanned=[${SCANNED}] -> ${VERBS}" >> "$LOG"

# --- maxima's shared Proton prefix + the GE-Proton wine that created it. ---
# If the runtime isn't set up yet, skip WITHOUT marking so a later launch (after
# maxima installs Proton on first run) resolves the deps.
PFX="${MAXIMA_WINE_PREFIX:-${HOME}/.local/share/maxima/wine/prefix}"
PROTON_DIR="${HOME}/.local/share/maxima/wine/proton/files"
PROTON_WINE="${PROTON_DIR}/bin/wine"
if [[ ! -x "$PROTON_WINE" ]]; then
    echo "[$(date)] maxima Proton not set up yet; will retry next launch for '${ID}'" >> "$LOG"
    exit 0
fi

# Filter to verbs not already applied in this (shared) prefix — winetricks records
# each applied verb in <prefix>/winetricks.log.
WT_LOG="${PFX}/winetricks.log"
TODO=""
for v in $VERBS; do
    if [[ -f "$WT_LOG" ]] && grep -qx "$v" "$WT_LOG" 2>/dev/null; then continue; fi
    TODO="${TODO} ${v}"
done
if [[ -z "${TODO// /}" ]]; then
    echo "[$(date)] all deps already in prefix for '${ID}' (${VERBS}); marked done" >> "$LOG"
    : > "$MARK"
    exit 0
fi

# --- winetricks (single self-contained OSS script) fetched once into runtime. ---
WINETRICKS=$(command -v winetricks 2>/dev/null)
if [[ -z "$WINETRICKS" ]]; then
    WT_DIR="${DECKY_PLUGIN_RUNTIME_DIR}/bin"
    WINETRICKS="${WT_DIR}/winetricks"
    if [[ ! -x "$WINETRICKS" ]]; then
        mkdir -p "$WT_DIR"
        echo "[$(date)] fetching winetricks -> ${WINETRICKS}" >> "$LOG"
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks" -o "$WINETRICKS" >> "$LOG" 2>&1
        elif command -v wget >/dev/null 2>&1; then
            wget -q "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks" -O "$WINETRICKS" >> "$LOG" 2>&1
        fi
        if [[ ! -s "$WINETRICKS" ]]; then
            echo "[$(date)] winetricks download failed; will retry next launch (${VERBS})" >> "$LOG"
            rm -f "$WINETRICKS"
            exit 0     # no marker -> retry
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
# shellcheck disable=SC2086  # verbs must word-split into separate args
"$WINETRICKS" -q $TODO >> "$LOG" 2>&1
rc=$?

# Success = every needed verb is now recorded in the prefix's winetricks.log.
# Only then do we mark done; otherwise leave no marker so it retries next launch.
ok=1
for v in $VERBS; do
    grep -qx "$v" "$WT_LOG" 2>/dev/null || ok=0
done
if [[ "$ok" -eq 1 ]]; then
    : > "$MARK"
    echo "[$(date)] deps resolved for '${ID}' (winetricks rc=${rc}); marked done — future launches skip the check" >> "$LOG"
else
    echo "[$(date)] deps INCOMPLETE for '${ID}' (winetricks rc=${rc}); NOT marked, will retry next launch" >> "$LOG"
fi
exit 0
