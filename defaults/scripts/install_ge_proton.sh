#!/usr/bin/env bash
# Download and install latest GE-Proton

set -e

API_URL="https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"

# Find or create compat tools directory
if [ -d "$HOME/.steam/steam/compatibilitytools.d" ]; then
    COMPAT_DIR="$HOME/.steam/steam/compatibilitytools.d"
elif [ -d "$HOME/.steam/root/compatibilitytools.d" ]; then
    COMPAT_DIR="$HOME/.steam/root/compatibilitytools.d"
else
    COMPAT_DIR="$HOME/.steam/steam/compatibilitytools.d"
    mkdir -p "$COMPAT_DIR"
fi

echo "Fetching latest GE-Proton release info..."

# Get release info
RELEASE_JSON=$(curl -sL -H "User-Agent: GameVault/1.0" "$API_URL")

TAG=$(echo "$RELEASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null)
if [ -z "$TAG" ]; then
    echo "Error: Could not fetch release info from GitHub."
    echo "Check your internet connection."
    exit 1
fi

echo "Latest release: $TAG"

# Check if already installed
if [ -d "$COMPAT_DIR/$TAG" ]; then
    echo "$TAG is already installed at $COMPAT_DIR/$TAG"
    echo "Done!"
    exit 0
fi

# Pick the asset matching THIS machine's architecture. GloriousEggroll ships
# both x86_64 and aarch64 tarballs; releases up to GE-Proton11-3 name the x86_64
# one plainly (GE-Proton11-3.tar.gz) while newer ones suffix it
# (GE-Proton11-6-x86_64.tar.gz). The aarch64 build sorts first in the asset list,
# so blindly taking the first .tar.gz installs the ARM build on an x86_64 Deck/Ally.
DOWNLOAD_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json, platform
machine = platform.machine().lower()
is_arm = machine in ('aarch64', 'arm64')
data = json.load(sys.stdin)
tarballs = [a for a in data.get('assets', []) if a['name'].endswith('.tar.gz')]
def has(a, *toks):
    n = a['name'].lower()
    return any(t in n for t in toks)
if is_arm:
    pick = next((a for a in tarballs if has(a, 'aarch64', 'arm64')), None)
else:
    # explicit x86_64 asset (new naming), else a plain asset with no arch suffix
    # (old naming); never fall through to the aarch64 build.
    pick = next((a for a in tarballs if has(a, 'x86_64', 'amd64')), None) or \
           next((a for a in tarballs if not has(a, 'aarch64', 'arm64')), None)
if pick:
    print(pick['browser_download_url'])
" 2>/dev/null)

if [ -z "$DOWNLOAD_URL" ]; then
    echo "Error: No GE-Proton .tar.gz asset for architecture '$(uname -m)' found in release."
    exit 1
fi

FILENAME="${TAG}.tar.gz"
TMP_FILE="/tmp/${FILENAME}"

echo "Downloading $TAG... This may take a few minutes (~500MB)."
echo "URL: $DOWNLOAD_URL"

# Download silently (progress bars use \r which doesn't stream over WebSocket)
curl -sL -o "$TMP_FILE" "$DOWNLOAD_URL"

echo "Download complete. Extracting to $COMPAT_DIR..."

# Extract
tar -xzf "$TMP_FILE" -C "$COMPAT_DIR"

# Clean up
rm -f "$TMP_FILE"

echo ""
echo "Successfully installed $TAG!"
echo "Restart Steam for the new compatibility tool to appear."
