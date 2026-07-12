#!/usr/bin/env bash

MAXIMA_BIN="${HOME}/.local/bin/maxima-cli"
MAXIMA_QRC="${HOME}/.local/bin/maxima-qrc-handler"
MAXIMA_BROWSER="${HOME}/.local/bin/open-browser"
MAXIMA_REPO="https://github.com/Starkka15/Maxima"

function install_login_helpers() {
    # 1. Browser wrapper — opens Firefox Flatpak (SteamOS) or system Firefox
    echo "Installing browser wrapper..."
    if flatpak list --app --columns=application 2>/dev/null | grep -q org.mozilla.firefox; then
        cat > "${MAXIMA_BROWSER}" << 'BROWSERSCRIPT'
#!/bin/bash
exec flatpak run org.mozilla.firefox "$@"
BROWSERSCRIPT
    elif command -v firefox &>/dev/null; then
        cat > "${MAXIMA_BROWSER}" << 'BROWSERSCRIPT'
#!/bin/bash
exec firefox "$@"
BROWSERSCRIPT
    else
        echo "Warning: Firefox not found. EA login may not work."
        return
    fi
    chmod +x "${MAXIMA_BROWSER}"
    echo "Browser wrapper installed at ${MAXIMA_BROWSER}"

    # 2. qrc:// protocol handler — catches EA OAuth redirect and forwards
    #    the auth code to maxima-cli's local TCP listener on port 31033
    echo "Installing qrc:// protocol handler..."
    cat > "${MAXIMA_QRC}" << 'HANDLER'
#!/bin/bash
URL="$1"
[ -z "$URL" ] && exit 1
CODE=$(echo "$URL" | grep -oP 'code=\K[^&]+')
[ -z "$CODE" ] && exit 1
curl -s "http://127.0.0.1:31033/auth?code=${CODE}" >/dev/null 2>&1
HANDLER
    chmod +x "${MAXIMA_QRC}"

    # 3. Register qrc:// as a custom protocol via .desktop file
    mkdir -p "${HOME}/.local/share/applications"
    cat > "${HOME}/.local/share/applications/maxima-qrc.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Maxima Launcher
MimeType=x-scheme-handler/qrc
Exec=${MAXIMA_QRC} %u
NoDisplay=true
StartupNotify=true
EOF

    if command -v xdg-mime &>/dev/null; then
        xdg-mime default maxima-qrc.desktop x-scheme-handler/qrc
        echo "qrc:// handler registered"
    else
        echo "Warning: xdg-mime not found, qrc handler may not work"
    fi
}

function uninstall() {
    echo "Uninstalling EA Play dependencies"
    rm -f "${MAXIMA_BIN}" 2>/dev/null
    rm -f "${MAXIMA_QRC}" 2>/dev/null
    rm -f "${MAXIMA_BROWSER}" 2>/dev/null
    rm -f "${HOME}/.local/share/applications/maxima-qrc.desktop" 2>/dev/null
    echo "Removed maxima-cli, browser wrapper, and qrc handler"
}

function install() {
    echo "Installing EA Play dependencies"

    mkdir -p "${HOME}/.local/bin"

    # Download maxima-cli (always update to latest)
    RELEASE_URL="${MAXIMA_REPO}/releases/latest/download/maxima-cli-linux-x86_64"
    echo "Downloading maxima-cli..."
    if curl -sL -o "${MAXIMA_BIN}.tmp" "${RELEASE_URL}" 2>/dev/null && [[ -s "${MAXIMA_BIN}.tmp" ]]; then
        if file "${MAXIMA_BIN}.tmp" | grep -q "ELF"; then
            mv "${MAXIMA_BIN}.tmp" "${MAXIMA_BIN}"
            chmod +x "${MAXIMA_BIN}"
            echo "maxima-cli installed"
        else
            rm -f "${MAXIMA_BIN}.tmp"
            echo "Downloaded file is not a valid binary"
        fi
    else
        rm -f "${MAXIMA_BIN}.tmp" 2>/dev/null
        echo "Download failed"
    fi

    # Fallback: build from source
    if [[ ! -f "${MAXIMA_BIN}" ]]; then
        if command -v cargo &>/dev/null; then
            echo "Building maxima-cli from source (this may take a while)..."
            TMPDIR=$(mktemp -d)
            git clone "${MAXIMA_REPO}.git" "${TMPDIR}/maxima" 2>/dev/null

            if [[ -d "${TMPDIR}/maxima" ]]; then
                cd "${TMPDIR}/maxima"

                if command -v rustup &>/dev/null; then
                    rustup toolchain install nightly 2>/dev/null
                fi

                cargo +nightly build --release --bin maxima-cli 2>&1 | tail -5

                if [[ -f "target/release/maxima-cli" ]]; then
                    cp "target/release/maxima-cli" "${MAXIMA_BIN}"
                    chmod +x "${MAXIMA_BIN}"
                    echo "maxima-cli built and installed"
                else
                    echo "Build failed."
                fi

                cd -
                rm -rf "${TMPDIR}"
            else
                echo "Failed to clone repository"
            fi
        else
            echo ""
            echo "Cannot install maxima-cli automatically."
            echo "Please install manually:"
            echo "  1. Install Rust nightly: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
            echo "  2. rustup toolchain install nightly"
            echo "  3. git clone ${MAXIMA_REPO}.git"
            echo "  4. cd Maxima && cargo +nightly build --release --bin maxima-cli"
            echo "  5. cp target/release/maxima-cli ~/.local/bin/"
        fi
    fi

    # Install login helpers (browser wrapper + qrc handler)
    if [[ -f "${MAXIMA_BIN}" ]]; then
        echo "maxima-cli: OK"
        install_login_helpers
    else
        echo "maxima-cli: NOT FOUND (EA Play will not work)"
    fi
}

if [ "$1" == "uninstall" ]; then
    echo "Uninstalling dependencies: EA Play extension"
    uninstall
else
    echo "Installing dependencies: EA Play extension"
    install
fi
