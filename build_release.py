#!/usr/bin/env python3
"""Package GameVault.zip for a release.

Run `pnpm build` first, then `python build_release.py`. Writes out/GameVault.zip
with one top-level GameVault/ directory, laid out the way Decky installs it.

The zip is safe to build from a Windows checkout: every text file is written
with LF line endings and every file under scripts/ is marked executable, no
matter what the working tree looks like. A CRLF shebang ("python3\\r") makes the
script unrunnable on the Deck, which is what broke v1.3.0 and v1.3.1.
"""
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
TOP = "GameVault"
OUT = os.path.join(ROOT, "out", "GameVault.zip")

# (source relative to the repo, destination relative to GameVault/)
SOURCES = [
    ("dist", "dist"),
    ("defaults", ""),
    ("py_modules", "py_modules"),
    ("main.py", "main.py"),
    ("plugin.json", "plugin.json"),
    ("package.json", "package.json"),
    ("LICENSE", "LICENSE"),
    ("README.md", "README.md"),
]
SKIP_DIRS = {"__pycache__"}
SKIP_EXTS = {".pyc"}


def collect():
    files = []
    for src, dest in SOURCES:
        path = os.path.join(ROOT, src)
        if os.path.isfile(path):
            files.append((path, dest))
            continue
        if not os.path.isdir(path):
            sys.exit(f"missing: {src}")
        for base, dirs, names in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                if os.path.splitext(name)[1] in SKIP_EXTS:
                    continue
                full = os.path.join(base, name)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                files.append((full, f"{dest}/{rel}" if dest else rel))
    return files


def main():
    with open(os.path.join(ROOT, "package.json")) as f:
        version = json.load(f)["version"]

    with open(os.path.join(ROOT, "dist", "index.js"), "rb") as f:
        bundle = f.read()
    if b"__PLUGIN_VERSION__" in bundle:
        sys.exit("dist/index.js still contains __PLUGIN_VERSION__; rebuild it")
    if version.encode() not in bundle:
        sys.exit(f"dist/index.js was not built for {version}; run pnpm build")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    normalized = 0
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, rel in collect():
            with open(full, "rb") as f:
                data = f.read()
            # Anything without a NUL byte is text: force LF.
            if b"\0" not in data and b"\r\n" in data:
                data = data.replace(b"\r\n", b"\n")
                normalized += 1
            mode = 0o755 if rel.startswith("scripts/") else 0o644
            info = zipfile.ZipInfo(f"{TOP}/{rel}")
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, so the mode bits survive extraction
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, data)
            count += 1

    # Check what was actually written, not what we meant to write.
    problems = []
    with zipfile.ZipFile(OUT) as zf:
        for info in zf.infolist():
            name = info.filename
            if "\\" in name or not name.startswith(f"{TOP}/"):
                problems.append(f"bad path: {name}")
            data = zf.read(name)
            if b"\0" not in data and b"\r" in data:
                problems.append(f"carriage return in {name}")
            if data.startswith(b"#!") and not (info.external_attr >> 16) & 0o100:
                problems.append(f"not executable: {name}")
        pkg = json.loads(zf.read(f"{TOP}/package.json"))
        plugin = json.loads(zf.read(f"{TOP}/plugin.json"))
    if pkg.get("type") != "module":
        problems.append('package.json lacks "type": "module"')
    if plugin.get("api_version", 0) < 1:
        problems.append('plugin.json lacks "api_version": 1')
    if problems:
        os.remove(OUT)
        sys.exit("release zip rejected:\n  " + "\n  ".join(problems))

    print(f"GameVault {version}: {count} files, {normalized} converted to LF")
    print(OUT)


if __name__ == "__main__":
    main()
