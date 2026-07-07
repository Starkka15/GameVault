#!/usr/bin/env bash
# Steam invokes this as:  rpgmaker-launcher.sh <game_id> <engine>
# It runs the game NATIVELY: NW.js for MV/MZ, mkxp-z for VX Ace/XP/VX. No Wine/Proton.
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
export DECKY_PLUGIN_DIR="${DECKY_PLUGIN_DIR:-${HOME}/homebrew/plugins/GameVault}"
export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-${HOME}/homebrew/logs/GameVault}"
export Extensions="${Extensions:-Extensions}"

# Steam Game Mode launches with LC_ALL=C (POSIX). Under a non-UTF-8 locale Chromium
# can't encode multibyte paths (e.g. "Kirumi 決定版") into a file:// URL, so NW.js fails
# to load index.html -> "Your file couldn't be accessed". Check the EFFECTIVE locale
# (LC_ALL overrides LC_CTYPE overrides LANG) and force UTF-8 if it isn't already. Game
# Mode sets LC_ALL=C *and* LANG=en_US.UTF-8, so we must look at LC_ALL, not just LANG.
eff_locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$eff_locale" in
  *[Uu][Tt][Ff]*) : ;;
  *) export LANG=C.UTF-8 LC_ALL=C.UTF-8 ;;
esac

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
# RPG Maker MV/MZ render through pixi.js WebGL inside NW.js's Chromium. Getting a GL
# context under Steam Game Mode (gamescope) on RADV is finicky and games disagree:
#   - --enable-webgl + --ignore-gpu-blocklist: undo Chromium's WebGL blocklist.
#   - SwiftShader software GL SEGFAULTS under gamescope's Vulkan WSI -> never use it.
#   - Out-of-process GPU + Vulkan: some games render, but others crash the GPU process
#     ("CreateCommandBuffer", exit_code=512).
#   - In-process GPU + Vulkan: "Vulkan not supported with in process gpu" -> EGL_BAD_CONFIG.
#   => The combo with no fatal signature for any game tested: IN-process GPU + the GL
#      (radeonsi) ANGLE backend. --in-process-gpu removes the crashing GPU-IPC boundary;
#      --use-angle=gl avoids the vulkan-in-process conflict. Still hardware (radeonsi).
# Override per-game via RPGMAKER_NW_FLAGS in the Steam launch options if one misbehaves.
NW_FLAGS="${RPGMAKER_NW_FLAGS:---ignore-gpu-blocklist --enable-webgl --in-process-gpu --use-gl=angle --use-angle=gl}"

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
