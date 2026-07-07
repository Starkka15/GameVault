#!/bin/bash
# Standalone installer for the RPG Maker extension for GameVault.
# Copies the RPG Maker extension files into the GameVault plugin directory and
# fetches the native runtimes (NW.js + mkxp-z).

PLUGIN_DIR="${HOME}/homebrew/plugins/GameVault"
RUNTIME_DIR="${HOME}/homebrew/data/GameVault"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -d "${PLUGIN_DIR}" ]]; then
    echo "Error: GameVault plugin not found at ${PLUGIN_DIR}"
    echo "Please install GameVault first."
    exit 1
fi

echo "Installing RPG Maker extension for GameVault..."

mkdir -p "${PLUGIN_DIR}/scripts/Extensions/RPGMaker"
mkdir -p "${PLUGIN_DIR}/conf_schemas"

echo "Copying extension scripts..."
for f in store.sh settings.sh static.json rpgmaker-launcher.sh get-rpgmaker-args.sh install_deps.sh; do
    cp "${SCRIPT_DIR}/defaults/scripts/Extensions/RPGMaker/${f}" "${PLUGIN_DIR}/scripts/Extensions/RPGMaker/"
done

echo "Copying Python scripts..."
cp "${SCRIPT_DIR}/defaults/scripts/rpgmaker.py" "${PLUGIN_DIR}/scripts/"
cp "${SCRIPT_DIR}/defaults/scripts/rpgmaker-config.py" "${PLUGIN_DIR}/scripts/"

echo "Copying config schema..."
cp "${SCRIPT_DIR}/defaults/conf_schemas/rpgmakertabconfig.json" "${PLUGIN_DIR}/conf_schemas/"

echo "Setting permissions..."
chmod +x "${PLUGIN_DIR}/scripts/Extensions/RPGMaker/"*.sh
chmod +x "${PLUGIN_DIR}/scripts/rpgmaker.py"
chmod +x "${PLUGIN_DIR}/scripts/rpgmaker-config.py"

echo ""
echo "Fetching native runtimes (NW.js + mkxp-z)... this downloads ~200 MB."
DECKY_PLUGIN_RUNTIME_DIR="${RUNTIME_DIR}" bash "${PLUGIN_DIR}/scripts/Extensions/RPGMaker/install_deps.sh"

echo ""
echo "RPG Maker extension installed."
echo "Copy your RPG Maker game folders into:  ${HOME}/Games/RPGMaker/"
echo "Then restart Decky Loader and open the RPG Maker tab in GameVault."
