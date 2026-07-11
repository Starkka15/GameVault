#!/usr/bin/env bash
# Installs the native RPG Maker runtimes into the plugin runtime dir (no root needed,
# unlike pacman on the read-only SteamOS root):
#   - NW.js (MV/MZ)        from the official portable linux-x64 tarball
#   - mkxp-z (VX Ace/XP/VX) from a prebuilt AppImage, extracted (avoids FUSE on SteamOS)

RT="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}/rpgmaker"
NWJS_VER="v0.72.0"
MKXPZ_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/mkxp-z-x86_64.AppImage"
RTP_VXACE_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/RPGVXAce-RTP.tar.gz"
RTP_XP_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/RPGXP-RTP.tar.gz"

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

    # --- VX Ace RTP (stock assets for RTP-dependent games) ---
    if [ ! -d "$RT/rtp/RPGVXAce" ]; then
        echo "Downloading VX Ace RTP (~190 MB)..."
        mkdir -p "$RT/rtp"
        if curl -sfL -o /tmp/gv-rtp-vxace.tar.gz "$RTP_VXACE_URL"; then
            tar xzf /tmp/gv-rtp-vxace.tar.gz -C "$RT/rtp"
            rm -f /tmp/gv-rtp-vxace.tar.gz
            echo "VX Ace RTP installed"
        else
            echo "WARNING: VX Ace RTP download failed; RTP-dependent VX Ace games may miss stock assets."
        fi
    else
        echo "VX Ace RTP already present"
    fi

    # --- XP RTP (stock audio for RPG Maker XP games; graphics ship in-game) ---
    if [ ! -d "$RT/rtp/RPGXP" ]; then
        echo "Downloading XP RTP (~9 MB)..."
        mkdir -p "$RT/rtp"
        if curl -sfL -o /tmp/gv-rtp-xp.tar.gz "$RTP_XP_URL"; then
            tar xzf /tmp/gv-rtp-xp.tar.gz -C "$RT/rtp"
            rm -f /tmp/gv-rtp-xp.tar.gz
            echo "XP RTP installed"
        else
            echo "WARNING: XP RTP download failed; RTP-dependent XP games may miss stock sounds."
        fi
    else
        echo "XP RTP already present"
    fi

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
