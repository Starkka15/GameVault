#!/usr/bin/env bash

OPTIMA_BIN="${HOME}/.local/bin/optima-cli"
OPTIMA_BROWSER="${HOME}/.local/bin/open-browser"
# The static-musl optima-cli is hosted on GameVault's `runtimes` release (same
# place as the mkxp-z / RTP runtimes). It's statically linked, so it runs on
# SteamOS regardless of the system glibc.
OPTIMA_URL="https://github.com/Starkka15/GameVault/releases/download/runtimes/optima-cli-linux-x86_64"

function install_login_helpers() {
    # Browser wrapper — optima-cli opens the Ubisoft WebAuth page via $BROWSER.
    echo "Installing browser wrapper..."
    if flatpak list --app --columns=application 2>/dev/null | grep -q org.mozilla.firefox; then
        cat > "${OPTIMA_BROWSER}" << 'BROWSERSCRIPT'
#!/bin/bash
exec flatpak run org.mozilla.firefox "$@"
BROWSERSCRIPT
    elif command -v firefox &>/dev/null; then
        cat > "${OPTIMA_BROWSER}" << 'BROWSERSCRIPT'
#!/bin/bash
exec firefox "$@"
BROWSERSCRIPT
    else
        echo "Warning: Firefox not found. Ubisoft Connect login may not open a browser."
        return
    fi
    chmod +x "${OPTIMA_BROWSER}"
    echo "Browser wrapper installed at ${OPTIMA_BROWSER}"
    # NOTE: no protocol-handler needed. optima-cli captures the session ticket via
    # a local HTTPS loopback on https://localhost.ubisoft.com:31034 that the SDK
    # posts back to directly — no custom URL scheme, no xdg-mime registration.
}

function uninstall() {
    echo "Uninstalling Ubisoft Connect (Optima) dependencies"
    rm -f "${OPTIMA_BIN}" 2>/dev/null
    rm -f "${OPTIMA_BROWSER}" 2>/dev/null
    echo "Removed optima-cli and browser wrapper"
}

function install() {
    echo "Installing Ubisoft Connect (Optima) dependencies"
    mkdir -p "${HOME}/.local/bin"

    # Download optima-cli (always update to latest)
    echo "Downloading optima-cli..."
    if curl -sL -o "${OPTIMA_BIN}.tmp" "${OPTIMA_URL}" 2>/dev/null && [[ -s "${OPTIMA_BIN}.tmp" ]]; then
        if file "${OPTIMA_BIN}.tmp" | grep -q "ELF"; then
            mv "${OPTIMA_BIN}.tmp" "${OPTIMA_BIN}"
            chmod +x "${OPTIMA_BIN}"
            echo "optima-cli installed"
        else
            rm -f "${OPTIMA_BIN}.tmp"
            echo "Downloaded file is not a valid binary"
        fi
    else
        rm -f "${OPTIMA_BIN}.tmp" 2>/dev/null
        echo "Download failed"
    fi

    if [[ -f "${OPTIMA_BIN}" ]]; then
        echo "optima-cli: OK"
        install_login_helpers
    else
        echo "optima-cli: NOT FOUND (Ubisoft Connect will not work)"
        echo "Manual install: download ${OPTIMA_URL} to ~/.local/bin/optima-cli and chmod +x it."
    fi
}

if [ "$1" == "uninstall" ]; then
    echo "Uninstalling dependencies: Ubisoft Connect (Optima) extension"
    uninstall
else
    echo "Installing dependencies: Ubisoft Connect (Optima) extension"
    install
fi
