#!/usr/bin/env bash
# Steam invokes this as:  ea-launcher.sh <slug>
#
# The game is launched through `maxima-cli launch <slug>`, which is the proven
# path: maxima starts its LSX server, requests the game license (EALS challenge),
# runs the EbisuSDK/Origin handshake, and launches the game exe under its OWN
# umu/Proton runtime. The Steam shortcut runs this script NATIVELY
# (Compatibility=false) -- maxima does all the Proton work itself, so we do NOT
# want Steam to wrap us in a second Proton.
#
# These need to be exported because it does not get executed in the context of
# the plugin.
export DECKY_PLUGIN_RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
export DECKY_PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
export DECKY_PLUGIN_LOG_DIR="${HOME}/homebrew/logs/GameVault"
export WORKING_DIR=$DECKY_PLUGIN_DIR
export Extensions="Extensions"
ID=$1

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/EA/settings.sh"

mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/${ID}.log"

# Steam Game Mode launches with LC_ALL=C (POSIX). Under a non-UTF-8 locale
# Chromium/Frostbite can't encode multibyte paths, breaking asset/URL loads.
# Force UTF-8 if the effective locale isn't already (LC_ALL > LC_CTYPE > LANG).
eff_locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$eff_locale" in
  *[Uu][Tt][Ff]*) : ;;
  *) export LANG=C.UTF-8 LC_ALL=C.UTF-8 ;;
esac

# Proton tuning from the GameVault UI (RUNTIMES_* -> PROTON_*/DXVK_*). maxima's
# umu/Proton runtime honours these standard vars, so the per-game toggles still
# apply even though we no longer drive Steam's Proton.
SETTINGS=$($EACONF --get-env-settings "$ID" --dbfile "$DBFILE" --platform Proton --fork "" --version "" 2>/dev/null)
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

# Per-game launch args: DB Arguments first (user-overridable in the UI), else
# the per-slug defaults in get-ea-args.sh (e.g. Battlefield -webmode tokens).
ARGS=""
if [[ -f "${ARGS_SCRIPT}" ]]; then
    ARGS=$("${ARGS_SCRIPT}" "$ID")
fi
if [[ "${ADVANCED_IGNORE_EA_ARGS}" == "true" ]]; then
    ARGS="${ADVANCED_ARGUMENTS}"
else
    ARGS="${ARGS} ${ADVANCED_ARGUMENTS}"
fi

# Optional per-game env overrides from the UI.
[[ -n "${ADVANCED_VARIABLES}" ]] && eval "$(echo -e "${ADVANCED_VARIABLES}")" 2>/dev/null

# Per-game Proton/Wine quirks (ea-quirks.conf) — applied LAST so they override
# the generic RUNTIMES_* mapping and UI vars. Home for game-specific knobs like
# esync/fsync-off for Frostbite titles that deadlock otherwise. Data-driven and
# community-extendable, same as ea-dependencies.conf.
QUIRKS_FILE="${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/ea-quirks.conf"
if [[ -f "${QUIRKS_FILE}" ]]; then
    QUIRKS=$(grep -E "^${ID}=" "${QUIRKS_FILE}" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/#.*//')
    if [[ -n "${QUIRKS// }" ]]; then
        echo "[$(date)] applying quirks for '${ID}': ${QUIRKS}" >> "$LOG"
        # shellcheck disable=SC2086  # each VAR=VAL is its own token
        export ${QUIRKS}
    fi
fi

# Install any runtime deps this game needs (ea-dependencies.conf -> winetricks,
# e.g. PhysX for Mass Effect 2) into the Proton prefix. No-op for games with
# none and idempotent for the rest, so it's safe to run every launch. Requires
# maxima's Proton to already be set up (happens on the first game launch), so a
# dep-only game may need a second launch on a brand-new prefix.
"${DECKY_PLUGIN_DIR}/scripts/${Extensions}/EA/install-ea-deps.sh" "$ID" >> "$LOG" 2>&1

# Self-heal the install-check registry key. `maxima-cli launch <slug>` gates on
# is_installed(), which resolves the game's [HKLM\...\Install Dir] key through
# the Wine prefix. A game installed by an older maxima (before it wrote that
# key) or after a prefix reset has files on disk but no key, so launch aborts
# "<offer> is not installed". register-install rewrites the key from the on-disk
# path — no download/verify/launch, idempotent — so the licensed slug launch
# below always sees it as installed. Skipped silently if maxima's Proton prefix
# isn't set up yet (first-ever launch does that, then this applies next time).
GAME_DIR=$("$EACONF" --get-game-dir "$ID" --dbfile "$DBFILE" 2>/dev/null | tail -1)
if [[ -n "${GAME_DIR}" && -d "${GAME_DIR}" ]]; then
    echo "[$(date)] registering install for '${ID}' at ${GAME_DIR}" >> "$LOG"
    "$MAXIMA_CMD" register-install "$ID" --path "${GAME_DIR}" >> "$LOG" 2>&1 \
        || echo "[$(date)] register-install returned non-zero (continuing)" >> "$LOG"
fi

echo "[$(date)] launching '${ID}' via maxima-cli launch (args: ${ARGS})" >> "$LOG"

# Trailing args after `--` are forwarded verbatim to the game exe by maxima.
# shellcheck disable=SC2086  # ARGS must word-split into separate tokens
if [[ -n "${ARGS// }" ]]; then
    exec "$MAXIMA_CMD" launch "$ID" -- ${ARGS} >> "$LOG" 2>&1
else
    exec "$MAXIMA_CMD" launch "$ID" >> "$LOG" 2>&1
fi
