#!/usr/bin/env bash
# ZOOM Platform's only dependency is an installer script that bundles
# innoextract and pulls umu-launcher itself. Nothing needs a package manager,
# which matters on SteamOS where the filesystem is read-only by default.
#
# We use the DarthSidiousPT fork rather than the official script. The official
# one has not shipped since December 2024 and its bundled innoextract fails on
# anything packaged with a recent Inno Setup:
#
#     Warning: Unexpected setup loader revision: 2
#     Could not determine setup data version!
#
# which makes Windows installs of any modern title impossible. The fork carries
# innoextract 1.13-darth, reads those installers correctly, and handles
# multi-part .bin sets better. It is not an official ZOOM release.

RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
TARGET="${RUNTIME_DIR}/zoom-platform.sh"
RELEASE_API="https://api.github.com/repos/DarthSidiousPT/zoom-platform.sh/releases/latest"
FALLBACK_URL="https://zoom-platform.sh/zoom-platform.sh"

function uninstall() {
    echo "Removing the ZOOM installer script"
    rm -f "${TARGET}"
    echo "Installed games are left alone."
}

# Inno Setup builds a GUI by default, and a window spawned from the Decky
# backend is never surfaced in Game Mode — the install hangs forever on a dialog
# nobody can see. Upstream already implements the silent path (it watches for
# "Log closed." rather than the restart prompt) and only defaults it off because
# they could not reliably detect which installers have custom components.
#
# Trade-off: a game with optional components gets its defaults instead of
# asking. That is the right call here, because the alternative is a prompt the
# user cannot reach.
function patch_silent() {
    if grep -q '^VERYSILENT=0' "${TARGET}"; then
        sed -i 's/^VERYSILENT=0/VERYSILENT=1/' "${TARGET}"
        echo "Patched installer for silent mode (no GUI in Game Mode)."
    else
        echo "WARNING: VERYSILENT=0 not found; installs may hang on a hidden dialog."
    fi
}

function install() {
    mkdir -p "${RUNTIME_DIR}"

    echo "Looking up the latest zoom-platform.sh (DarthSidiousPT fork)"
    ASSET=$(curl -sL "${RELEASE_API}" \
        | grep -oE '"browser_download_url": *"[^"]*\.sh"' \
        | head -1 | cut -d'"' -f4)

    if [[ -z "${ASSET}" ]]; then
        echo "Could not reach the fork's releases; falling back to the official script."
        echo "Windows installs of recent games will likely fail with this one."
        ASSET="${FALLBACK_URL}"
    fi

    echo "Downloading ${ASSET}"
    if ! curl -fsSL "${ASSET}" -o "${TARGET}.tmp"; then
        echo "Download failed. Check the network connection and try again."
        rm -f "${TARGET}.tmp"
        return 1
    fi

    # A truncated download would otherwise be saved as a working installer and
    # fail much later, in the middle of someone's game install.
    if ! head -1 "${TARGET}.tmp" | grep -q '^#!'; then
        echo "Downloaded file does not look like a shell script; refusing to install it."
        rm -f "${TARGET}.tmp"
        return 1
    fi

    mv "${TARGET}.tmp" "${TARGET}"
    chmod +x "${TARGET}"
    patch_silent

    echo "Installed: ${TARGET}"
    "${TARGET}" --version 2>/dev/null || true

    # umu-launcher is fetched by the installer on first use, so warn rather than
    # fail if it is not present yet.
    command -v umu-run &>/dev/null \
        && echo "umu-run: OK" \
        || echo "umu-run: not on PATH (the installer downloads its own copy)"
}

if [ "$1" == "uninstall" ]; then
    echo "Uninstalling dependencies: ZOOM Platform extension"
    uninstall
else
    echo "Installing dependencies: ZOOM Platform extension"
    install
fi
