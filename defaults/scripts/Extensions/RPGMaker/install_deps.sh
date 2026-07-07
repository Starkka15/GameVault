#!/usr/bin/env bash
# Installs the native RPG Maker runtimes into the plugin runtime dir (no root needed,
# unlike pacman on the read-only SteamOS root):
#   - NW.js (MV/MZ)        from the official portable linux-x64 tarball
#   - mkxp-z (VX Ace/XP/VX) from a prebuilt AppImage, extracted (avoids FUSE on SteamOS)

RT="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}/rpgmaker"
NWJS_VER="v0.72.0"
MKXPZ_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/mkxp-z-x86_64.AppImage"
RTP_VXACE_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/RPGVXAce-RTP.tar.gz"

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
