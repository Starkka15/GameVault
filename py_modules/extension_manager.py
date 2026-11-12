"""Optional store extensions: catalog, install, update, remove, and the one-time
move of stores that used to ship inside GameVault.

An extension is a folder under <runtime>/scripts/Extensions/<id>/ with a
manifest.json. get-json.py and gamevault.sh already load anything there; this
module only puts folders in place and takes them away. The plugin folder (and the
stores built into it) is never touched, and neither is any store's database or
saved settings, so removing and reinstalling an extension keeps the user's login
and library.

The catalog is index.json in Starkka15/GameVault-Extensions. A file at
<runtime>/extensions-catalog holding another URL or a local path replaces it, for
testing a catalog before it is published.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import ssl
import tempfile
import time
import urllib.parse
import zipfile

import aiohttp
import decky

# What this GameVault offers extensions (the shared scripts, the dispatcher, the
# action contract). An extension that needs more says so with a higher "api".
EXTENSION_API = 1

CATALOG_URL = "https://raw.githubusercontent.com/Starkka15/GameVault-Extensions/main/index.json"
TRUSTED_PREFIX = "https://github.com/Starkka15/GameVault-Extensions/releases/download/"

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MIGRATED_MARKER = ".extensions-migrated"


def _ssl_context():
    ctx = ssl.create_default_context()
    for cafile in ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem"):
        if os.path.exists(cafile):
            try:
                ctx.load_verify_locations(cafile)
            except Exception:
                pass
    return ctx


def runtime_dir():
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "scripts", "Extensions")


def builtin_dir():
    return os.path.join(decky.DECKY_PLUGIN_DIR, "scripts", "Extensions")


def builtin_ids():
    base = builtin_dir()
    if not os.path.isdir(base):
        return []
    return sorted(
        d for d in os.listdir(base)
        if os.path.isfile(os.path.join(base, d, "static.json"))
    )


def read_manifest(folder):
    try:
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else None
    except Exception:
        return None


def installed():
    """Extensions installed in the runtime folder, keyed by id."""
    base = runtime_dir()
    found = {}
    if not os.path.isdir(base):
        return found
    for d in sorted(os.listdir(base)):
        folder = os.path.join(base, d)
        if d.startswith(".") or not os.path.isdir(folder):
            continue
        m = read_manifest(folder)
        if m and m.get("id") == d:
            found[d] = m
    return found


def version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def _override():
    path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "extensions-catalog")
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
        return value or None
    except OSError:
        return None


def _is_local(ref):
    return ref.startswith("file://") or ref.startswith("/")


def _local_path(ref):
    if ref.startswith("file://"):
        return urllib.parse.unquote(ref[len("file://"):])
    return ref


async def _fetch_bytes(url, timeout=60):
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=_ssl_context()),
        timeout=aiohttp.ClientTimeout(total=None, sock_read=timeout, sock_connect=30),
    ) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            return await response.read()


async def fetch_catalog():
    """The catalog as {"source": ..., "extensions": [entries]}. Raises on failure."""
    source = _override() or CATALOG_URL
    if _is_local(source):
        with open(_local_path(source), "rb") as f:
            raw = f.read()
    else:
        # Bypass GitHub's raw cache on a manual check: a fresh release shows at once.
        sep = "&" if "?" in source else "?"
        raw = await _fetch_bytes(f"{source}{sep}t={int(time.time())}")
    data = json.loads(raw.decode("utf-8"))
    entries = []
    for e in data.get("extensions", []):
        if not isinstance(e, dict):
            continue
        if not ID_RE.match(str(e.get("id", ""))):
            continue
        if not all(k in e for k in ("name", "version", "url", "sha256")):
            continue
        entries.append(e)
    return {"source": source, "extensions": entries}


def _check_url(entry, source):
    url = entry["url"]
    if _override():
        # A test catalog the user pointed GameVault at may serve from anywhere.
        return
    if not url.startswith(TRUSTED_PREFIX):
        raise RuntimeError(f"refusing {entry['id']}: {url} is not a GameVault-Extensions release")


async def _download(entry, source, dest):
    url = entry["url"]
    _check_url(entry, source)
    if _is_local(url):
        shutil.copyfile(_local_path(url), dest)
    elif "://" not in url and _is_local(source):
        # A relative entry in a local test catalog sits next to the catalog file.
        shutil.copyfile(os.path.join(os.path.dirname(_local_path(source)), url), dest)
    else:
        data = await _fetch_bytes(url, timeout=60)
        with open(dest, "wb") as f:
            f.write(data)
    with open(dest, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest.lower() != str(entry["sha256"]).lower():
        raise RuntimeError(
            f"{entry['id']}: download does not match the catalog checksum "
            f"(expected {entry['sha256'][:12]}…, got {digest[:12]}…)"
        )


def _extract(zip_path, ext_id, version, staging):
    """Unpack into staging/<ext_id> after checking every path. Returns that folder."""
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"{ext_id}: corrupt file in the zip ({bad})")
        for name in z.namelist():
            parts = name.split("/")
            if (
                "\\" in name
                or name.startswith("/")
                or ".." in parts
                or parts[0] != ext_id
            ):
                raise RuntimeError(f"{ext_id}: unexpected path in the zip: {name}")
        z.extractall(staging)
    folder = os.path.join(staging, ext_id)
    m = read_manifest(folder)
    if not m or m.get("id") != ext_id:
        raise RuntimeError(f"{ext_id}: the zip has no matching manifest.json")
    if str(m.get("version")) != str(version):
        raise RuntimeError(
            f"{ext_id}: the zip is version {m.get('version')}, the catalog says {version}"
        )
    for need in ("static.json", "store.sh"):
        if not os.path.isfile(os.path.join(folder, need)):
            raise RuntimeError(f"{ext_id}: the zip has no {need}")
    for root, _dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            os.chmod(p, 0o755 if f.endswith((".sh", ".py")) else 0o644)
    return folder


def _swap_in(ext_id, new_folder):
    base = runtime_dir()
    os.makedirs(base, exist_ok=True)
    target = os.path.join(base, ext_id)
    old = os.path.join(base, f".old-{ext_id}")
    if os.path.exists(old):
        shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(target):
        os.rename(target, old)
    try:
        shutil.move(new_folder, target)
    except Exception:
        if os.path.exists(old) and not os.path.exists(target):
            os.rename(old, target)
        raise
    shutil.rmtree(old, ignore_errors=True)
    return target


async def _run_deps(folder, env, log):
    script = os.path.join(folder, "install_deps.sh")
    if not os.path.isfile(script):
        return 0
    await log("Installing its dependencies…\n")
    proc = await asyncio.create_subprocess_exec(
        "bash", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd=decky.DECKY_PLUGIN_DIR,
        start_new_session=True,
    )
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        await log(line.decode(errors="replace"))
    return await proc.wait()


async def install(ext_id, env, log, catalog=None, run_deps=True):
    """Install or update one extension from the catalog. Returns its manifest.

    run_deps=False skips its install_deps.sh: the migration uses it, because a
    store that was built in already has its dependencies, and re-running them
    would only replace working binaries."""
    if not ID_RE.match(ext_id or ""):
        raise RuntimeError(f"not an extension id: {ext_id!r}")
    if ext_id in builtin_ids():
        raise RuntimeError(f"{ext_id} is built into GameVault")
    catalog = catalog or await fetch_catalog()
    entry = next((e for e in catalog["extensions"] if e["id"] == ext_id), None)
    if not entry:
        raise RuntimeError(f"{ext_id} is not in the extension catalog")
    if int(entry.get("api", 1)) > EXTENSION_API:
        raise RuntimeError(
            f"{entry['name']} {entry['version']} needs a newer GameVault; update GameVault first"
        )
    current = installed().get(ext_id)
    verb = "Updating" if current else "Installing"
    await log(f"{verb} {entry['name']} {entry['version']}…\n")
    with tempfile.TemporaryDirectory(prefix="gv-ext-") as tmp:
        zip_path = os.path.join(tmp, f"{ext_id}.zip")
        await _download(entry, catalog["source"], zip_path)
        await log("Download verified.\n")
        folder = _extract(zip_path, ext_id, entry["version"], os.path.join(tmp, "x"))
        target = _swap_in(ext_id, folder)
    code = await _run_deps(target, env, log) if run_deps else 0
    if code:
        await log(f"Warning: its dependency installer exited with code {code}.\n")
    await log(f"{entry['name']} {entry['version']} is installed.\n")
    return read_manifest(target)


def remove(ext_id):
    """Delete an installed extension's files. Its database and settings stay."""
    if not ID_RE.match(ext_id or ""):
        raise RuntimeError(f"not an extension id: {ext_id!r}")
    folder = os.path.join(runtime_dir(), ext_id)
    m = read_manifest(folder)
    if not m:
        raise RuntimeError(f"{ext_id} is not installed")
    for extra in m.get("owns", []) or []:
        if ID_RE.match(str(extra)):
            shutil.rmtree(os.path.join(runtime_dir(), extra), ignore_errors=True)
    shutil.rmtree(folder)
    return m


def _db_path(manifest):
    db = manifest.get("database")
    if not db or os.sep in db or "/" in db:
        return None
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, db)


def profile_games(manifest):
    """(shortname, title, steam app id or None) for every game of this store that is
    installed or has a shortcut: what a full removal uninstalls."""
    path = _db_path(manifest)
    if not path or not os.path.isfile(path):
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(Game)")}
            where = "coalesce(SteamClientID,'') <> ''"
            if "InstallPath" in cols:
                where += " OR coalesce(InstallPath,'') <> ''"
            title = "Title" if "Title" in cols else "ShortName"
            rows = conn.execute(
                f"SELECT ShortName, {title}, SteamClientID FROM Game WHERE {where}"
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        decky.logger.warning(f"extension {manifest.get('id')}: reading games: {e}")
        return []
    out = []
    for short, name, app in rows:
        try:
            app = int(app) if app not in (None, "") else None
        except (TypeError, ValueError):
            app = None
        out.append((short, name or short, app))
    return out


def profile_files(manifest):
    """GameVault-side data of a store, relative to the runtime dir: its database
    (with SQLite's -wal/-shm), the usual overrides and tab settings, and whatever
    the manifest lists under "profile" (keys, cookies)."""
    files = []
    db = manifest.get("database")
    if db and _db_path(manifest):
        stem = db[:-3] if db.endswith(".db") else db
        files += [db, f"{db}-wal", f"{db}-shm", f"{stem}_overrides.sh",
                  f"conf_schemas/{stem}tabconfig.json"]
    files += [str(p) for p in manifest.get("profile", []) or []]
    root = os.path.realpath(decky.DECKY_PLUGIN_RUNTIME_DIR)
    safe = []
    for rel in files:
        full = os.path.realpath(os.path.join(root, rel))
        if (
            rel.startswith("/") or ".." in rel.replace("\\", "/").split("/")
            or not full.startswith(root + os.sep)
            or full.startswith(os.path.join(root, "scripts") + os.sep)
        ):
            decky.logger.warning(f"extension {manifest.get('id')}: ignoring profile path {rel!r}")
            continue
        if rel not in safe:
            safe.append(rel)
    return safe


def removal_summary(ext_id):
    m = installed().get(ext_id)
    if not m:
        raise RuntimeError(f"{ext_id} is not installed")
    return {
        "name": m.get("name", ext_id),
        "games": len(profile_games(m)),
    }


async def remove_profile(ext_id, run, log):
    """Remove an extension and everything of it: uninstall each of its games with
    the store's own Uninstall (files + shortcut id), sign out, delete the extension
    and its GameVault data. `run(platform, action, *args)` runs gamevault.sh and
    returns its stdout. Returns the Steam app ids whose shortcuts should go.

    If any game fails to uninstall, nothing else is touched, so the user can retry
    with the store still there to do it."""
    m = installed().get(ext_id)
    if not m:
        raise RuntimeError(f"{ext_id} is not installed")
    platform = m.get("platform", ext_id)
    games = profile_games(m)
    apps, failed = [], []
    for short, name, app in games:
        await log(f"Uninstalling {name}…\n")
        out = await run(platform, "uninstall", short)
        try:
            res = json.loads(out or "")
            ok = isinstance(res, dict) and res.get("Type") != "Error"
        except Exception:
            ok = False
        if ok:
            if app:
                apps.append(app)
        else:
            failed.append(name)
            await log(f"  could not uninstall {name}: {(out or 'no output').strip()[:200]}\n")
    if failed:
        raise RuntimeError(
            f"{len(failed)} game(s) did not uninstall ({', '.join(failed[:3])}"
            f"{'…' if len(failed) > 3 else ''}); nothing else was removed. "
            "Uninstall them from their game pages, then try again."
        )
    # A store's own cleanup for what its Uninstall leaves (download caches, the
    # user's folders of a local library). Optional: a store without a purge
    # action makes gamevault.sh print "Invalid action", which is ignored.
    out = await run(platform, "purge")
    try:
        res = json.loads(out or "")
        if isinstance(res, dict):
            msg = (res.get("Content") or {}).get("Message", "")
            await log(f"{'Cleanup problem' if res.get('Type') == 'Error' else 'Cleaned up'}: {msg}\n")
    except Exception:
        pass
    await log("Signing out…\n")
    await run(platform, "logout")
    remove(ext_id)
    root = decky.DECKY_PLUGIN_RUNTIME_DIR
    for rel in profile_files(m):
        p = os.path.join(root, rel)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
        except OSError as e:
            await log(f"  could not delete {rel}: {e}\n")
    await log(f"{m.get('name', ext_id)} and its {len(games)} game(s) removed.\n")
    return apps


def installed_games(manifest):
    """(shortname, steam app id) for every game of this store with a shortcut."""
    db = manifest.get("database")
    if not db or os.sep in db or "/" in db:
        return []
    path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, db)
    if not os.path.isfile(path):
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = conn.execute(
                "SELECT ShortName, SteamClientID FROM Game "
                "WHERE SteamClientID IS NOT NULL AND SteamClientID <> ''"
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        decky.logger.warning(f"extension {manifest.get('id')}: reading {db}: {e}")
        return []
    out = []
    for short, app in rows:
        try:
            out.append((short, int(app)))
        except (TypeError, ValueError):
            pass
    return out


def store_was_used(db):
    """True if this store has a library on this device (a migration candidate)."""
    path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, db)
    if not os.path.isfile(path):
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            (count,) = conn.execute("SELECT COUNT(*) FROM Game").fetchone()
        finally:
            conn.close()
        return count > 0
    except Exception:
        return False


# Stores that were built in before extensions moved out, with their databases.
# Only these are installed automatically, and only where they have a library.
FORMERLY_BUILT_IN = {
    "EA": "ea.db",
    "Itchio": "itchio.db",
    "Zoom": "zoom.db",
    "RPGMaker": "rpgmaker.db",
    "Optima": "optima.db",
}


async def migrate(env):
    """Once per device: reinstall the stores people were using before they left
    the GameVault zip. Returns the ids installed. Retries on the next start if the
    catalog could not be reached or an install failed."""
    marker = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, MIGRATED_MARKER)
    if os.path.exists(marker):
        return []
    have = set(installed()) | set(builtin_ids())
    todo = [
        i for i, db in FORMERLY_BUILT_IN.items()
        if i not in have and store_was_used(db)
    ]
    done = []
    if todo:
        try:
            catalog = await fetch_catalog()
        except Exception as e:
            decky.logger.warning(f"extension migration: catalog unreachable ({e}); will retry")
            return []

        async def log(msg):
            decky.logger.info(f"extension migration: {msg.rstrip()}")

        failed = False
        for ext_id in todo:
            try:
                await install(ext_id, env, log, catalog, run_deps=False)
                done.append(ext_id)
            except Exception as e:
                failed = True
                decky.logger.error(f"extension migration: {ext_id}: {e}")
        if failed:
            return done
    with open(marker, "w") as f:
        f.write(" ".join(done) + "\n")
    return done
