#!/usr/bin/env bash
# Steam invokes this as:  rpgmaker-launcher.sh <game_id> <engine>
# It runs the game NATIVELY: NW.js for MV/MZ, mkxp-z for VX Ace/XP/VX. No Wine/Proton.
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
export DECKY_PLUGIN_DIR="${DECKY_PLUGIN_DIR:-${HOME}/homebrew/plugins/GameVault}"
export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-${HOME}/homebrew/logs/GameVault}"
export Extensions="${Extensions:-Extensions}"

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/RPGMaker/settings.sh"

ID="$1"
ENGINE="$2"
mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/rpgmaker-run.log"

GAME_DIR=$($RPGMAKERCONF --get-game-dir "$ID" --dbfile "$DBFILE")
if [ -z "$ENGINE" ]; then
    ENGINE=$($RPGMAKERCONF --get-args "$ID" --dbfile "$DBFILE")
fi

RT="$RPGMAKER_RUNTIME"
NW="$RT/nwjs/nw"
# RPG Maker MV/MZ render through pixi.js WebGL inside NW.js's Chromium. On Linux /
# SteamOS, Chromium's GPU blocklist frequently disables WebGL for the Mesa driver
# -> games die with "Your browser does not support WebGL". Force it on. Override the
# whole set with RPGMAKER_NW_FLAGS if a game needs software rendering, e.g.:
#   RPGMAKER_NW_FLAGS="--use-gl=swiftshader --enable-unsafe-swiftshader"
NW_FLAGS="${RPGMAKER_NW_FLAGS:---ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --disable-gpu-driver-bug-workarounds}"

run_nw(){
    # shellcheck disable=SC2086  # NW_FLAGS must word-split into separate args
    exec "$NW" $NW_FLAGS "$GAME_DIR" >> "$LOG" 2>&1
}
# mkxp-z: run the extracted binary directly (the AppImage's AppRun hardcodes usr/bin/mkxp-z
# but the binary sits at the AppDir root). Replicate AppRun's env: bundled libs + SRCDIR=cwd.
MKXPZ_BIN="$RT/mkxp-z/mkxp-z"
MKXPZ_LIBS="$RT/mkxp-z/usr/lib"

echo "[$(date)] launch id=$ID engine=$ENGINE dir=$GAME_DIR" >> "$LOG" 2>&1

if [ ! -d "$GAME_DIR" ]; then
    echo "Game folder not found: $GAME_DIR" >> "$LOG" 2>&1
    exit 1
fi

run_mkxpz(){
    cd "$GAME_DIR" || exit 1
    # Point mkxp-z at the bundled RTP so RTP-dependent games find stock assets.
    # Only write our config if the game has no mkxp.json of its own (don't clobber).
    local rtp_name=""
    case "$ENGINE" in
      vxace) rtp_name="RPGVXAce" ;;
      xp)    rtp_name="RPGXP" ;;
      vx)    rtp_name="RPGVX" ;;
    esac
    local rtp_dir="$RT/rtp/$rtp_name"
    if [ -n "$rtp_name" ] && [ -d "$rtp_dir" ] && [ ! -e "$GAME_DIR/mkxp.json" ]; then
        printf '{ "RTP": [ "%s" ] }\n' "$rtp_dir" > "$GAME_DIR/mkxp.json" 2>/dev/null \
            && echo "wrote mkxp.json RTP=$rtp_dir" >> "$LOG"
    fi
    exec env LD_LIBRARY_PATH="${MKXPZ_LIBS}:${LD_LIBRARY_PATH}" SRCDIR="$GAME_DIR" "$MKXPZ_BIN" >> "$LOG" 2>&1
}

case "$ENGINE" in
  mv|mz)
    run_nw
    ;;
  vxace|xp|vx)
    run_mkxpz
    ;;
  *)
    # Fallback: sniff the folder if the engine tag is missing.
    if [ -f "$GAME_DIR/package.json" ]; then
        run_nw
    else
        run_mkxpz
    fi
    ;;
esac
