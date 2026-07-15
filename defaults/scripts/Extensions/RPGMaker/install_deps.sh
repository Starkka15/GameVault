#!/usr/bin/env bash
# Installs the native RPG Maker runtimes into the plugin runtime dir (no root needed,
# unlike pacman on the read-only SteamOS root):
#   - NW.js (MV/MZ)        from the official portable linux-x64 tarball
#   - mkxp-z (VX Ace/XP/VX) from a prebuilt AppImage, extracted (avoids FUSE on SteamOS)

RT="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}/rpgmaker"
NWJS_VER="v0.72.0"
MKXPZ_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/mkxp-z-x86_64.AppImage"

# RPG Maker Run-Time Packages are fetched from RPG Maker's OWN official source
# (Degica/Kadokawa's CDN) at the moment the user runs Install Dependencies — i.e.
# the user is requesting the RTP from its publisher, and GameVault is only the
# fetch/extract agent. We do NOT re-host Enterbrain's proprietary assets.
# The downloads are Inno Setup installers, extracted on-device with innoextract
# (GPL — github.com/dscharrer/innoextract).
RTP_VXACE_URL="https://dl.komodo.jp/rpgmakerweb/run-time-packages/RPGVXAce_RTP.zip"
RTP_VX_URL="https://dl.komodo.jp/rpgmakerweb/run-time-packages/vx_rtp102e.zip"
RTP_XP_URL="https://dl.komodo.jp/rpgmakerweb/run-time-packages/xp_rtp104e.exe"
INNOEXTRACT_URL="https://github.com/dscharrer/innoextract/releases/download/1.9/innoextract-1.9-linux.tar.xz"
RTP_UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# curl with a cert-chain fallback: Degica's CDN (dl.komodo.jp) serves an incomplete
# TLS chain ("unable to get local issuer certificate"), so retry with relaxed
# validation. The RTP is static, public game-asset content, so this is acceptable.
_rtp_fetch() {  # $1=url  $2=out
    curl -sfL  -A "$RTP_UA" -o "$2" "$1" && return 0
    echo "  (secure fetch failed — retrying with relaxed cert validation for the official RTP host)"
    curl -sfLk -A "$RTP_UA" -o "$2" "$1"
}

# Fetch innoextract from its official OSS release (multi-arch bundle: a wrapper
# script that picks bin/amd64 on SteamOS). Cached under $RT/innoextract.
_ensure_innoextract() {
    IE="$RT/innoextract/innoextract"
    [ -x "$IE" ] && return 0
    echo "Fetching innoextract (RTP installer extractor)..."
    if _rtp_fetch "$INNOEXTRACT_URL" /tmp/gv-ie.tar.xz; then
        rm -rf /tmp/gv-ie && mkdir -p /tmp/gv-ie
        tar xf /tmp/gv-ie.tar.xz -C /tmp/gv-ie 2>/dev/null
        local d
        d="$(dirname "$(find /tmp/gv-ie -name innoextract -type f | head -1)")"
        if [ -n "$d" ] && [ -f "$d/innoextract" ]; then
            rm -rf "$RT/innoextract"; mv "$d" "$RT/innoextract"
            chmod +x "$RT/innoextract/innoextract" 2>/dev/null
            find "$RT/innoextract/bin" -type f -exec chmod +x {} \; 2>/dev/null
        fi
        rm -rf /tmp/gv-ie /tmp/gv-ie.tar.xz
    fi
    [ -x "$IE" ]
}

# Fetch + extract one official RTP into $RT/rtp/<name>.
#   $1=name (RPGVXAce|RPGVX|RPGXP)  $2=url  $3=human label
_install_rtp() {
    local name="$1" url="$2" label="$3"
    [ -d "$RT/rtp/$name" ] && { echo "$label RTP already present"; return 0; }
    _ensure_innoextract || { echo "WARNING: innoextract unavailable; skipping $label RTP (RTP-dependent games may miss stock assets)."; return 1; }
    echo "Downloading $label RTP from the official RPG Maker source..."
    local tmp="/tmp/gv-rtp-$name"; rm -rf "$tmp"; mkdir -p "$tmp"
    local dl="$tmp/download"
    if ! _rtp_fetch "$url" "$dl"; then
        echo "WARNING: $label RTP download failed; RTP-dependent games may miss stock assets."
        rm -rf "$tmp"; return 1
    fi
    # The download is either a zip wrapping RTP*/Setup.exe, or a bare Inno .exe.
    local setup=""
    if unzip -tq "$dl" >/dev/null 2>&1; then
        unzip -oq "$dl" -d "$tmp/z"
        setup="$(find "$tmp/z" -iname 'setup.exe' | head -1)"
        [ -z "$setup" ] && setup="$(find "$tmp/z" -iname '*.exe' | head -1)"
    else
        setup="$dl"
    fi
    if [ -z "$setup" ] || [ ! -f "$setup" ]; then
        echo "WARNING: couldn't find the $label RTP installer inside the download."
        rm -rf "$tmp"; return 1
    fi
    "$RT/innoextract/innoextract" -e -s -d "$tmp/x" "$setup" >/dev/null 2>&1
    # innoextract lays the installed game files under an app/ subdir.
    local app="$tmp/x/app"; [ -d "$app" ] || app="$tmp/x"
    if [ -d "$app/Graphics" ] || [ -d "$app/Audio" ]; then
        mkdir -p "$RT/rtp"; rm -rf "$RT/rtp/$name"; mv "$app" "$RT/rtp/$name"
        echo "$label RTP installed (from official source)"
    else
        echo "WARNING: $label RTP extraction produced no assets."
        rm -rf "$tmp"; return 1
    fi
    rm -rf "$tmp"
}

function install() {
    mkdir -p "$RT"

    # --- NW.js (MV / MZ) ---
    if [ ! -x "$RT/nwjs/nw" ]; then
        echo "Downloading NW.js ${NWJS_VER}..."
        if curl -sfL -o /tmp/gv-nwjs.tar.gz "https://dl.nwjs.io/${NWJS_VER}/nwjs-${NWJS_VER}-linux-x64.tar.gz"; then
            tar xzf /tmp/gv-nwjs.tar.gz -C /tmp
            rm -rf "$RT/nwjs"
            mv "/tmp/nwjs-${NWJS_VER}-linux-x64" "$RT/nwjs"
            rm -f /tmp/gv-nwjs.tar.gz
            chmod +x "$RT/nwjs/nw"
            echo "NW.js installed"
        else
            echo "WARNING: NW.js download failed; MV/MZ games will not launch."
        fi
    else
        echo "NW.js already present"
    fi

    # --- codec-enabled libffmpeg.so for NW.js ---
    # Stock NW.js ships a codec-FREE libffmpeg (no proprietary H.264/AAC), so RPG
    # Maker MV title/cutscene videos (.mp4/.webm H.264 — e.g. NLT's Treasure of
    # Nadia / Genesis Order) decode to a BLACK screen. Swap in the community
    # codec build matching NWJS_VER. Idempotent via the .codecfree.bak marker.
    if [ -x "$RT/nwjs/nw" ] && [ ! -f "$RT/nwjs/lib/libffmpeg.so.codecfree.bak" ]; then
        echo "Installing codec-enabled libffmpeg.so (H.264/AAC for MV videos)..."
        FFMPEG_URL="https://github.com/nwjs-ffmpeg-prebuilt/nwjs-ffmpeg-prebuilt/releases/download/${NWJS_VER#v}/${NWJS_VER#v}-linux-x64.zip"
        if curl -sfL -o /tmp/gv-nwff.zip "$FFMPEG_URL"; then
            rm -rf /tmp/gv-nwff && mkdir -p /tmp/gv-nwff
            if unzip -o /tmp/gv-nwff.zip -d /tmp/gv-nwff >/dev/null 2>&1 && [ -f /tmp/gv-nwff/libffmpeg.so ]; then
                cp "$RT/nwjs/lib/libffmpeg.so" "$RT/nwjs/lib/libffmpeg.so.codecfree.bak"
                cp /tmp/gv-nwff/libffmpeg.so "$RT/nwjs/lib/libffmpeg.so"
                chmod 700 "$RT/nwjs/lib/libffmpeg.so"
                echo "codec libffmpeg installed (MV videos will play)"
            else
                echo "WARNING: libffmpeg extract failed; MV video titles may be black."
            fi
            rm -f /tmp/gv-nwff.zip
        else
            echo "WARNING: codec libffmpeg download failed; MV video titles may be black."
        fi
    else
        echo "codec libffmpeg already present"
    fi

    # --- mkxp-z (VX Ace / XP / VX) ---
    if [ ! -x "$RT/mkxp-z/mkxp-z" ]; then
        echo "Downloading mkxp-z..."
        if curl -sfL -o /tmp/gv-mkxpz.AppImage "$MKXPZ_URL"; then
            chmod +x /tmp/gv-mkxpz.AppImage
            rm -rf "$RT/mkxp-z" /tmp/squashfs-root
            ( cd /tmp && ./gv-mkxpz.AppImage --appimage-extract >/dev/null 2>&1 )
            if [ -d /tmp/squashfs-root ]; then
                mv /tmp/squashfs-root "$RT/mkxp-z"
                echo "mkxp-z installed"
            else
                echo "WARNING: mkxp-z extract failed; VX Ace games will not launch."
            fi
            rm -f /tmp/gv-mkxpz.AppImage
        else
            echo "WARNING: mkxp-z download failed; VX Ace games will not launch until the runtime is published."
        fi
    else
        echo "mkxp-z already present"
    fi

    # --- RPG Maker RTPs (stock assets for RTP-dependent games) ---
    # Fetched from RPG Maker's official publisher CDN at the user's request (they
    # ran Install Dependencies) and extracted on-device — GameVault is the fetch
    # agent, not a re-host of Enterbrain's assets. Self-contained games ("without
    # RTP", the majority) don't need these at all; the launcher only wires an RTP
    # path when a game lacks its own assets.
    _install_rtp RPGVXAce "$RTP_VXACE_URL" "VX Ace"
    _install_rtp RPGVX    "$RTP_VX_URL"    "VX"
    _install_rtp RPGXP    "$RTP_XP_URL"    "XP"

    # --- ScummVM + DOSBox (My Added Games: classic/adventure/DOS titles) ---
    # Reuse the same flatpak apps the GOG extension launches; the scanner probes
    # ScummVM at scan time and both launch natively (no Proton). Install per-user
    # (SteamOS root is immutable). Non-fatal: skip if flatpak/flathub unavailable.
    if command -v flatpak >/dev/null 2>&1; then
        if ! flatpak list --app --columns=application 2>/dev/null | grep -q '^org.scummvm.ScummVM$'; then
            echo "Installing ScummVM flatpak..."
            flatpak install --user -y --noninteractive flathub org.scummvm.ScummVM \
                || echo "WARNING: ScummVM flatpak install failed; ScummVM games won't be detected/launch."
        else
            echo "ScummVM flatpak already present"
        fi
        if ! flatpak list --app --columns=application 2>/dev/null | grep -q '^io.github.dosbox-staging$'; then
            echo "Installing DOSBox Staging flatpak..."
            flatpak install --user -y --noninteractive flathub io.github.dosbox-staging \
                || echo "WARNING: DOSBox Staging flatpak install failed; DOS games won't launch."
        else
            echo "DOSBox Staging flatpak already present"
        fi
    else
        echo "flatpak not found; skipping ScummVM/DOSBox (My Added Games classic titles will not launch)."
    fi
}

function uninstall() {
    echo "Removing RPG Maker native runtimes"
    rm -rf "$RT"
}

if [ "$1" == "uninstall" ]; then
    echo "Uninstalling dependencies: RPG Maker extension"
    uninstall
else
    echo "Installing dependencies: RPG Maker extension"
    install
fi
