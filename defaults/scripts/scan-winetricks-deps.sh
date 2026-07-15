#!/usr/bin/env bash
# Scan a game's install directory for bundled redistributables and print the
# matching winetricks verbs (space-separated, deduped).
#
# Rationale: games that need a runtime Proton doesn't provide almost always ship
# that runtime's installer inside their own tree (a `_CommonRedist/`,
# `RedistInstallers/`, `__Installer/` or `directx/redist/` folder) — because the
# store's own installer runs them at install time. Under our loaders we skip that
# vendor installer (e.g. EA's Touchup.exe), so those runtimes never land in the
# prefix. This scanner detects what the game bundled and maps it to the winetricks
# verb that installs the same thing, so the per-extension deps installer can apply
# it automatically instead of relying on a hand-maintained per-game list.
#
# Usage:   scan-winetricks-deps.sh <game_dir>
#   or source it and call: scan_winetricks_verbs <game_dir>
set -u

scan_winetricks_verbs() {
    local dir="$1"
    [ -n "$dir" ] && [ -d "$dir" ] || return 0
    local verbs=() n

    # --- .NET Desktop Runtime -------------------------------------------------
    # Modern launchers (e.g. the current C&C Generals re-release) are WPF/.NET
    # desktop apps and abort with "You must install .NET to run this application"
    # — Proton ships no .NET at all. Bundled as RedistInstallers/dotnetN.
    for n in 9 8 7 6; do
        if find "$dir" -maxdepth 5 -type d -iname "dotnet${n}" 2>/dev/null | grep -q .; then
            verbs+=("dotnetdesktop${n}")
        fi
    done
    # Fallback signal: a *.runtimeconfig.json names the framework + version.
    if [ ${#verbs[@]} -eq 0 ]; then
        local rc ver
        rc="$(find "$dir" -maxdepth 4 -iname '*.runtimeconfig.json' 2>/dev/null | head -1)"
        if [ -n "$rc" ]; then
            ver="$(grep -oiE '"version"[[:space:]]*:[[:space:]]*"[0-9]+' "$rc" 2>/dev/null | grep -oE '[0-9]+$' | head -1)"
            if [ -n "$ver" ]; then
                if grep -qi 'WindowsDesktop' "$rc" 2>/dev/null; then
                    verbs+=("dotnetdesktop${ver}")
                else
                    verbs+=("dotnet${ver}")
                fi
            fi
        fi
    fi

    # --- DirectX end-user runtime (d3dx9/11, d3dcompiler_43, XACT) ------------
    # DXVK provides d3d9/11 themselves but NOT the d3dx9_*/d3dx11_* helper DLLs or
    # XAudio/XACT that older games load — those come from the DirectX redist the
    # game bundles (directx/redist/*.cab or a DXSETUP.exe).
    if find "$dir" -maxdepth 6 \( -ipath '*directx*redist*' -o -iname 'DXSETUP.exe' -o -ipath '*_CommonRedist/DirectX*' \) 2>/dev/null | grep -q .; then
        verbs+=("d3dx9")   # winetricks d3dx9 also covers d3dcompiler_43
        find "$dir" -maxdepth 6 -iname '*d3dx11*' 2>/dev/null | grep -q . && verbs+=("d3dx11_43")
        find "$dir" -maxdepth 6 -iname '*xact*'   2>/dev/null | grep -q . && verbs+=("xact")
    fi

    # --- Visual C++ runtimes --------------------------------------------------
    if find "$dir" -maxdepth 6 \( -iname 'vc_redist*' -o -iname 'vcredist*' -o -ipath '*vcredist*' -o -ipath '*_CommonRedist/vcredist*' \) 2>/dev/null | grep -q .; then
        local hits added=0 pair pat verb
        hits="$(find "$dir" -maxdepth 6 \( -iname 'vc_redist*' -o -iname 'vcredist*' -o -ipath '*vcredist*' \) 2>/dev/null)"
        # Map any year folder/filename to its winetricks verb (2015-2022 unified).
        for pair in 2022:vcrun2022 2019:vcrun2022 2017:vcrun2022 2015:vcrun2022 \
                    2013:vcrun2013 2012:vcrun2012 2010:vcrun2010 2008:vcrun2008 2005:vcrun2005; do
            pat="${pair%%:*}"; verb="${pair##*:}"
            if printf '%s\n' "$hits" | grep -qi "$pat"; then verbs+=("$verb"); added=1; fi
        done
        # Unlabelled vc_redist.x64.exe (the unified 2015-2022 package) -> 2022.
        [ "$added" -eq 0 ] && verbs+=("vcrun2022")
    fi

    # --- NVIDIA PhysX (legacy System Software) --------------------------------
    if find "$dir" -maxdepth 6 -iname '*PhysX*' 2>/dev/null | grep -q .; then
        verbs+=("physx")
    fi

    # dedupe, preserve order, print space-separated
    [ ${#verbs[@]} -gt 0 ] || return 0
    printf '%s\n' "${verbs[@]}" | awk 'NF && !seen[$0]++' | tr '\n' ' ' | sed 's/ *$//'
}

# Standalone invocation.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    scan_winetricks_verbs "${1:-}"
    echo
fi
