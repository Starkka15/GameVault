#!/usr/bin/env python3
"""
Proton tools for GameVault:
  --install-ge-proton    Download and install latest GE-Proton
  --lookup ID --store S  Lookup known protonfixes for a game
  --apply ID --store S --shortname SN --dbfile DB --platform P  Apply fixes to game config
"""

import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import time
import tempfile
import urllib.request
import urllib.error


GE_PROTON_API = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"
UMU_PROTONFIXES_RAW = "https://raw.githubusercontent.com/Open-Wine-Components/umu-protonfixes/master"

STORE_MAP = {
    "gog": "gamefixes-gog",
    "epic": "gamefixes-egs",
    "egs": "gamefixes-egs",
    "ea": "gamefixes-egs",
    "itchio": "gamefixes-itchio",
    "amazon": "gamefixes-amazon",
}


def get_compat_dir():
    """Find or create the Steam compatibility tools directory."""
    candidates = [
        os.path.expanduser("~/.steam/steam/compatibilitytools.d"),
        os.path.expanduser("~/.steam/root/compatibilitytools.d"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    # Default: create the first one
    os.makedirs(candidates[0], exist_ok=True)
    return candidates[0]


def _select_arch_asset(assets):
    """Pick the GE-Proton .tar.gz matching this machine's architecture.

    GloriousEggroll ships both x86_64 and aarch64 tarballs. Releases up to
    GE-Proton11-3 name the x86_64 build plainly (GE-Proton11-3.tar.gz); newer
    ones suffix it (GE-Proton11-6-x86_64.tar.gz). The aarch64 build sorts first
    in the asset list, so taking the first .tar.gz installs the ARM build on an
    x86_64 Deck/Ally. Never cross-install: on x86_64 hosts we refuse aarch64.
    """
    import platform

    machine = platform.machine().lower()
    is_arm = machine in ("aarch64", "arm64")
    tarballs = [a for a in assets if a.get("name", "").endswith(".tar.gz")]

    def has(asset, *toks):
        name = asset.get("name", "").lower()
        return any(t in name for t in toks)

    if is_arm:
        return next((a for a in tarballs if has(a, "aarch64", "arm64")), None)
    # explicit x86_64 asset (new naming), else a plain asset with no arch suffix
    # (old naming); never fall through to the aarch64 build.
    return (next((a for a in tarballs if has(a, "x86_64", "amd64")), None)
            or next((a for a in tarballs if not has(a, "aarch64", "arm64")), None))


def install_ge_proton():
    """Download and install the latest GE-Proton release."""
    print("Fetching latest GE-Proton release info...")
    sys.stdout.flush()

    headers = {"User-Agent": "GameVault/1.0"}
    req = urllib.request.Request(GE_PROTON_API, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        release = json.loads(resp.read())
    except Exception as e:
        print(f"Error fetching release info: {e}")
        return

    tag = release.get("tag_name", "unknown")
    tarball_asset = _select_arch_asset(release.get("assets", []))

    if not tarball_asset:
        import platform
        print(f"Error: No GE-Proton .tar.gz asset for architecture "
              f"'{platform.machine()}' found in latest release.")
        return

    download_url = tarball_asset["browser_download_url"]
    file_size = tarball_asset["size"]
    file_size_mb = file_size / (1024 * 1024)

    compat_dir = get_compat_dir()
    install_path = os.path.join(compat_dir, tag)

    if os.path.isdir(install_path):
        print(f"{tag} is already installed at {install_path}")
        return

    # Check disk space
    stat = shutil.disk_usage(compat_dir)
    free_mb = stat.free / (1024 * 1024)
    needed_mb = file_size_mb * 3  # tarball + extracted
    if free_mb < needed_mb:
        print(f"Error: Not enough disk space. Need ~{needed_mb:.0f} MB, have {free_mb:.0f} MB free.")
        return

    print(f"Downloading {tag} ({file_size_mb:.0f} MB)...")
    sys.stdout.flush()

    tmp_file = os.path.join(tempfile.gettempdir(), tarball_asset["name"])

    last_report = [0]  # mutable for closure

    def progress_hook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        now = time.time()
        if total_size > 0 and (now - last_report[0] >= 2 or downloaded >= total_size):
            last_report[0] = now
            pct = min(100, downloaded * 100 // total_size)
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total_size / (1024 * 1024)
            print(f"Downloading {tag}... {pct}% ({dl_mb:.0f}/{tot_mb:.0f} MB)")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(download_url, tmp_file, reporthook=progress_hook)
    except Exception as e:
        print(f"Error downloading: {e}")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        return

    print(f"Extracting to {compat_dir}...")
    sys.stdout.flush()

    try:
        with tarfile.open(tmp_file, "r:gz") as tar:
            # Validate all paths before extraction (path traversal check)
            real_compat = os.path.realpath(compat_dir)
            for member in tar.getmembers():
                member_path = os.path.realpath(os.path.join(compat_dir, member.name))
                if not member_path.startswith(real_compat + os.sep) and member_path != real_compat:
                    raise Exception(f"Path traversal detected in tar: {member.name}")
            tar.extractall(path=compat_dir)
    except Exception as e:
        print(f"Error extracting: {e}")
        return
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    print(f"Successfully installed {tag}!")
    print("Restart Steam for the new compatibility tool to appear.")


def parse_protonfixes(source_code):
    """Parse a umu-protonfixes Python file and extract env vars and protontricks commands."""
    env_vars = []
    tricks = []
    notes = []

    # Match util.set_environment('KEY', 'VALUE')
    for m in re.finditer(r"""util\.set_environment\(\s*['"](.+?)['"]\s*,\s*['"](.+?)['"]\s*\)""", source_code):
        env_vars.append((m.group(1), m.group(2)))

    # Match util.protontricks('verb')
    for m in re.finditer(r"""util\.protontricks\(\s*['"](.+?)['"]\s*\)""", source_code):
        tricks.append(m.group(1))

    # Match util.disable_nvapi()
    if "util.disable_nvapi()" in source_code:
        notes.append("Disable NVAPI (set WINEDLLOVERRIDES for nvapi/nvapi64)")
        env_vars.append(("WINEDLLOVERRIDES", "nvapi,nvapi64=d"))

    # Match util.winedll_override(game, '*name', 'mode')
    for m in re.finditer(r"""util\.winedll_override\(.+?,\s*['"](.+?)['"]\s*,\s*['"](.+?)['"]\s*\)""", source_code):
        dll_name = m.group(1).lstrip("*")
        mode = m.group(2)
        notes.append(f"Wine DLL override: {dll_name}={mode}")

    # Match util.append_argument('arg')
    for m in re.finditer(r"""util\.append_argument\(\s*['"](.+?)['"]\s*\)""", source_code):
        notes.append(f"Launch argument: {m.group(1)}")

    return env_vars, tricks, notes


def get_umu_steam_id(shortname, db_file, store):
    """Look up the UMU ID from the database and extract the Steam App ID."""
    if not shortname or not db_file:
        return None
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
        import GameSet as gs
        game_set = gs.GameSet(db_file, store)
        umu_id = game_set.get_umu_id(shortname)
        if umu_id:
            # UMU IDs are like "umu-333980" — extract the numeric part
            steam_id = re.sub(r"^umu-", "", umu_id)
            return steam_id
    except Exception:
        pass
    return None


def fetch_protonfixes_source(game_id, store, shortname=None, db_file=None):
    """Fetch protonfixes source code, falling back to gamefixes-steam via UMU ID."""
    headers = {"User-Agent": "GameVault/1.0"}
    store_dir = STORE_MAP.get(store.lower())

    # Try store-specific directory first
    if store_dir:
        url = f"{UMU_PROTONFIXES_RAW}/{store_dir}/{game_id}.py"
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            source = resp.read().decode("utf-8")
            return source, f"{store}/{game_id}"
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return None, f"Error fetching protonfixes: {e}"
        except Exception as e:
            return None, f"Error fetching protonfixes: {e}"

    # Fallback: look up UMU ID and try gamefixes-steam
    steam_id = get_umu_steam_id(shortname or game_id, db_file, store)
    if steam_id:
        url = f"{UMU_PROTONFIXES_RAW}/gamefixes-steam/{steam_id}.py"
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            source = resp.read().decode("utf-8")
            return source, f"steam/{steam_id} (via UMU ID)"
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return None, f"Error fetching protonfixes: {e}"
        except Exception as e:
            return None, f"Error fetching protonfixes: {e}"

    return None, None


def lookup_protonfixes(game_id, store, shortname=None, db_file=None):
    """Fetch and parse protonfixes for a game from umu-protonfixes."""
    source_code, label = fetch_protonfixes_source(game_id, store, shortname, db_file)

    if source_code is None:
        if label:
            # label contains an error message
            return json.dumps({
                "Type": "Error",
                "Content": {"Message": label}
            })
        return json.dumps({
            "Type": "Success",
            "Content": {"Message": f"No known fixes found for {store}/{game_id}", "Toast": True}
        })

    env_vars, tricks, notes = parse_protonfixes(source_code)

    lines = [f"Proton fixes for {label}:"]
    if env_vars:
        lines.append("\nEnvironment variables:")
        for key, val in env_vars:
            lines.append(f"  {key}={val}")
    if tricks:
        lines.append("\nProtontricks verbs:")
        for trick in tricks:
            lines.append(f"  {trick}")
    if notes:
        lines.append("\nNotes:")
        for note in notes:
            lines.append(f"  {note}")
    if not env_vars and not tricks and not notes:
        lines.append("  (fix file exists but no parseable fixes found)")

    return json.dumps({
        "Type": "Success",
        "Content": {"Message": "\n".join(lines), "Toast": True}
    })


def apply_protonfixes(game_id, store, shortname, db_file, platform):
    """Fetch protonfixes and write env vars into the game's Advanced > Variables config."""
    source_code, label = fetch_protonfixes_source(game_id, store, shortname, db_file)

    if source_code is None:
        if label:
            return json.dumps({
                "Type": "Error",
                "Content": {"Message": label}
            })
        return json.dumps({
            "Type": "Success",
            "Content": {"Message": f"No known fixes to apply for {store}/{game_id}", "Toast": True}
        })

    env_vars, tricks, notes = parse_protonfixes(source_code)

    if not env_vars:
        msg = f"No environment variable fixes to apply for {store}/{game_id}."
        if tricks:
            msg += "\n\nProtontricks verbs found (apply manually):\n"
            msg += "\n".join(f"  {t}" for t in tricks)
        return json.dumps({
            "Type": "Success",
            "Content": {"Message": msg, "Toast": True}
        })

    # Build export lines
    new_exports = []
    for key, val in env_vars:
        new_exports.append(f"export {key}=\"{val}\"")

    # Read current config from DB and merge
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
        import GameSet as gs

        game_set = gs.GameSet(db_file, store)
        conn = game_set.get_connection()
        c = conn.cursor()

        # Find or create config_set for this game
        c.execute(
            "SELECT id FROM config_set WHERE ShortName=? AND forkname=? AND version=? AND platform=?",
            (shortname, "", "", platform),
        )
        row = c.fetchone()
        config_set_id = None
        if row:
            config_set_id = row[0]
        else:
            c.execute(
                "INSERT INTO config_set (ShortName, forkname, version, platform) VALUES (?, ?, ?, ?)",
                (shortname, "", "", platform),
            )
            config_set_id = c.lastrowid
            conn.commit()

        # Read current advanced > variables value
        c.execute(
            "SELECT value FROM configs WHERE config_set_id=? AND section='advanced' AND key='variables'",
            (config_set_id,),
        )
        row = c.fetchone()
        current_vars = row[0] if row else ""

        # Deduplicate: skip exports that already exist
        added = []
        for export_line in new_exports:
            if export_line not in current_vars:
                added.append(export_line)

        if not added:
            conn.close()
            return json.dumps({
                "Type": "Success",
                "Content": {"Message": "All fixes are already applied!", "Toast": True}
            })

        # Append new exports
        if current_vars and not current_vars.endswith("\n"):
            current_vars += "\n"
        current_vars += "\n".join(added)

        # Upsert
        if row:
            c.execute(
                "UPDATE configs SET value=? WHERE config_set_id=? AND section='advanced' AND key='variables'",
                (current_vars, config_set_id),
            )
        else:
            c.execute(
                "INSERT INTO configs (section, key, value, config_set_id) VALUES (?, ?, ?, ?)",
                ("advanced", "variables", current_vars, config_set_id),
            )
        conn.commit()
        conn.close()

        applied_str = "\n".join(f"  {a}" for a in added)
        msg = f"Applied {len(added)} fix(es):\n{applied_str}"
        if tricks:
            msg += "\n\nProtontricks verbs (apply manually):\n"
            msg += "\n".join(f"  {t}" for t in tricks)

        return json.dumps({
            "Type": "Success",
            "Content": {"Message": msg, "Toast": True}
        })

    except Exception as e:
        return json.dumps({
            "Type": "Error",
            "Content": {"Message": f"Error applying fixes: {e}"}
        })


def main():
    parser = argparse.ArgumentParser(description="Proton tools for GameVault")
    parser.add_argument("--install-ge-proton", action="store_true", help="Download and install latest GE-Proton")
    parser.add_argument("--lookup", metavar="GAME_ID", help="Lookup protonfixes for a game")
    parser.add_argument("--apply", metavar="GAME_ID", help="Apply protonfixes to a game's config")
    parser.add_argument("--store", help="Store name (gog, epic, itchio, amazon)")
    parser.add_argument("--shortname", help="Game shortname in the database")
    parser.add_argument("--dbfile", help="Path to the store's SQLite database")
    parser.add_argument("--platform", default="Proton", help="Platform config name")

    args = parser.parse_args()

    if args.install_ge_proton:
        install_ge_proton()
    elif args.lookup:
        print(lookup_protonfixes(args.lookup, args.store or "", args.shortname, args.dbfile))
    elif args.apply:
        if not args.store or not args.shortname or not args.dbfile:
            print(json.dumps({
                "Type": "Error",
                "Content": {"Message": "Missing required arguments: --store, --shortname, --dbfile"}
            }))
            return
        print(apply_protonfixes(args.apply, args.store, args.shortname, args.dbfile, args.platform))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
