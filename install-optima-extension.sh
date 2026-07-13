#!/bin/bash
# Standalone installer for the Ubisoft Connect (Optima) extension for GameVault.
# Copies the extension files into the GameVault plugin directory and fetches the
# optima-cli runtime + browser wrapper.

PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -d "${PLUGIN_DIR}" ]]; then
    echo "Error: GameVault plugin not found at ${PLUGIN_DIR}"
    echo "Please install GameVault first."
    exit 1
fi

echo "Installing Ubisoft Connect (Optima) extension for GameVault..."

mkdir -p "${PLUGIN_DIR}/scripts/Extensions/Optima"
mkdir -p "${PLUGIN_DIR}/conf_schemas"

echo "Copying extension scripts..."
for f in store.sh settings.sh static.json optima-launcher.sh get-optima-args.sh login.sh open-browser.sh install_deps.sh; do
    cp "${SCRIPT_DIR}/defaults/scripts/Extensions/Optima/${f}" "${PLUGIN_DIR}/scripts/Extensions/Optima/"
done

echo "Copying Python scripts..."
cp "${SCRIPT_DIR}/defaults/scripts/optima.py" "${PLUGIN_DIR}/scripts/"
cp "${SCRIPT_DIR}/defaults/scripts/optima-config.py" "${PLUGIN_DIR}/scripts/"

echo "Copying config schemas..."
cp "${SCRIPT_DIR}/defaults/conf_schemas/optimatabconfig.json" "${PLUGIN_DIR}/conf_schemas/"
cp "${SCRIPT_DIR}/defaults/conf_schemas/optimaprofile.json" "${PLUGIN_DIR}/conf_schemas/"

echo "Setting permissions..."
chmod +x "${PLUGIN_DIR}/scripts/Extensions/Optima/"*.sh
chmod +x "${PLUGIN_DIR}/scripts/optima.py"
chmod +x "${PLUGIN_DIR}/scripts/optima-config.py"

echo "Installing optima-cli + browser wrapper..."
"${PLUGIN_DIR}/scripts/Extensions/Optima/install_deps.sh"

echo ""
echo "Ubisoft Connect (Optima) extension installed successfully!"
echo "Restart Decky Loader to activate it, then open the Ubisoft Connect tab and Login."
