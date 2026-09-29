"""
ZOOM Platform store backend.

ZOOM ships no CLI and no documented API, so unlike GOG (gogdl) or Ubisoft
(optima-cli) this talks to the website's own JSON endpoints with a logged-in
session cookie. The endpoints were found by watching what the store's React
frontend calls:

    POST /login                            Laravel session login
    POST /two-factor-challenge             when the account has 2FA enabled
    GET  /public/profile/products          owned games, keyed by slug
    GET  /public/profile/product/{uuid}    one product, including its files
    POST /product/download/{file-uuid}     download counter (courtesy ping)

Installation itself is delegated to zoom-platform.sh, which embeds innoextract
and resolves the umu protonfix from the GUID inside the installer, so nothing
here needs to know about Proton.
"""

import http.cookiejar
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import GamesDb

BASE = "https://www.zoom-platform.com"
UA = "GameVault/ZOOM (+https://github.com/Starkka15/GameVault)"

# Presigned S3 links carry X-Amz-Expires and die quietly once it passes, so the
# product record is always re-fetched immediately before a download rather than
# cached alongside the game list.
CACHE_LIBRARY_SECONDS = 300

# Written to the progress log so the UI can tell a real failure from the noise
# Steam and ld.so leave in the same file.
ERROR_MARKER = "ZOOM-ERROR:"

# Printed only once the game is genuinely on disk and recorded, so the UI cannot
# mistake the end of the download for the end of the install.
DONE_MARKER = "ZOOM-INSTALL-COMPLETE"


class ZoomError(Exception):
    pass


class Zoom(GamesDb.GamesDb):
    def __init__(self, db_file, storeName="Zoom", setNameConfig=None):
        super().__init__(db_file, storeName, setNameConfig)
        self.cookie_file = os.path.join(os.path.dirname(db_file), "zoom-cookies.txt")
        self.jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
        if os.path.exists(self.cookie_file):
            try:
                self.jar.load(ignore_discard=True, ignore_expires=True)
            except Exception as e:
                print(f"Could not load ZOOM cookies: {e}", file=sys.stderr)
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    # ---- plumbing ---------------------------------------------------------

    def _save_cookies(self):
        try:
            self.jar.save(ignore_discard=True, ignore_expires=True)
            os.chmod(self.cookie_file, 0o600)
        except Exception as e:
            print(f"Could not save ZOOM cookies: {e}", file=sys.stderr)

    def _cookie(self, name):
        for c in self.jar:
            if c.name == name:
                return urllib.parse.unquote(c.value)
        return None

    def _request(self, path, data=None, headers=None, method=None, raw=False):
        url = path if path.startswith("http") else BASE + path
        body = None
        hdrs = {
            "User-Agent": UA,
            "Accept": "application/json, text/html;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        }
        # Laravel accepts the CSRF token as a header, which saves scraping it
        # out of a client-rendered page.
        xsrf = self._cookie("XSRF-TOKEN")
        if xsrf:
            hdrs["X-XSRF-TOKEN"] = xsrf
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        if headers:
            hdrs.update(headers)

        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        resp = self.opener.open(req, timeout=60)
        self._save_cookies()
        if raw:
            return resp
        text = resp.read().decode("utf-8", "replace")
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # ---- auth -------------------------------------------------------------

    def _prime(self):
        """Fetch the login page so Laravel issues a session and XSRF cookie."""
        try:
            self._request("/login", headers={"Accept": "text/html"})
        except urllib.error.HTTPError:
            pass

    @staticmethod
    def _wants_two_factor(body, landed_on):
        """
        Decide whether the account still needs a second factor.

        Two shapes to handle. Every request here carries
        X-Requested-With: XMLHttpRequest, so Laravel treats the login as AJAX
        and Fortify replies with JSON — {"two_factor": true} — instead of
        redirecting to the challenge page. Checking only the final URL therefore
        never fired, and an account with 2FA enabled was told its password was
        wrong.

        The redirect form is still checked, in case that header is ever dropped
        or the site stops answering as JSON.
        """
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and parsed.get("two_factor"):
                return True
        except (TypeError, ValueError):
            pass
        return "two-factor" in (landed_on or "")

    def login(self, email, password):
        self._prime()
        landed_on = ""
        body = ""
        try:
            resp = self._request(
                "/login", data={"email": email, "password": password}, raw=True)
            # Both the final URL and the response body matter — see
            # _wants_two_factor for why the body is the one that actually fires.
            landed_on = resp.geturl() or ""
            body = resp.read().decode("utf-8", "replace")
            resp.close()
        except urllib.error.HTTPError as e:
            if e.code == 422:
                return self._status_json(False, error="Wrong email or password.")
            if e.code == 419:
                # Stale CSRF token; one retry from a fresh page clears it.
                self._prime()
                try:
                    resp = self._request(
                        "/login", data={"email": email, "password": password}, raw=True)
                    landed_on = resp.geturl() or ""
                    body = resp.read().decode("utf-8", "replace")
                    resp.close()
                except urllib.error.HTTPError as e2:
                    return self._status_json(False, error=f"Login failed ({e2.code}).")
            else:
                return self._status_json(False, error=f"Login failed ({e.code}).")
        except urllib.error.URLError as e:
            return self._status_json(False, error=f"Cannot reach ZOOM: {e.reason}")

        # Ground truth beats guessing: if the library reads, the session works.
        # Sniffing the page for "two-factor" was wrong — every page embeds the
        # site's route table, which names the two-factor route whether or not
        # the account uses it.
        status = self.get_login_status(flush_cache=True)
        if '"LoggedIn": true' in status:
            self.save_setting("zoom_username", email.split("@")[0])
            return status

        if self._wants_two_factor(body, landed_on):
            return json.dumps({
                "Type": "LoginStatus",
                "Content": {"Username": "", "LoggedIn": False, "TwoFactorRequired": True},
            })
        return self._status_json(
            False, error="Login did not take. Check the email and password.")

    def two_factor(self, code):
        """Second step for accounts with 2FA turned on."""
        field = "recovery_code" if len(str(code).strip()) > 6 else "code"
        try:
            self._request("/two-factor-challenge", data={field: str(code).strip()})
        except urllib.error.HTTPError as e:
            return self._status_json(False, error=f"Two-factor check failed ({e.code}).")
        return self.get_login_status(flush_cache=True)

    def logout(self):
        try:
            self._request("/logout", data={})
        except urllib.error.HTTPError:
            pass
        try:
            os.remove(self.cookie_file)
        except OSError:
            pass
        self.jar.clear()
        self.clear_cache("zoom-login")
        return self._status_json(False)

    def _setting_value(self, name, default=""):
        raw = self.get_setting(name)
        try:
            return json.loads(raw).get("Content", {}).get("value", "") or default
        except (TypeError, ValueError):
            return default

    def _status_json(self, logged_in, username="", error=""):
        content = {"Username": username, "LoggedIn": bool(logged_in)}
        if error:
            content["Error"] = error
        return json.dumps({"Type": "LoginStatus", "Content": content})

    def get_login_status(self, flush_cache=False):
        if flush_cache:
            self.clear_cache("zoom-login")
        else:
            cached = self.get_cache("zoom-login")
            if cached:
                return cached

        try:
            data = self._request("/public/profile/products")
        except urllib.error.HTTPError as e:
            # Unauthenticated requests are redirected to the login page, which
            # surfaces here as a 401/403 or as HTML rather than JSON.
            if e.code in (401, 403, 419):
                return self._status_json(False)
            return self._status_json(False, error=f"ZOOM returned {e.code}.")
        except urllib.error.URLError as e:
            return self._status_json(False, error=f"Cannot reach ZOOM: {e.reason}")

        if not isinstance(data, dict):
            return self._status_json(False)

        username = self._setting_value("zoom_username", "ZOOM")
        value = self._status_json(True, username)
        self.add_cache("zoom-login", value, 3600)
        return value

    # ---- library ----------------------------------------------------------

    def _owned(self):
        data = self._request("/public/profile/products")
        if not isinstance(data, dict):
            raise ZoomError("Not logged in to ZOOM.")
        return data

    def get_list(self):
        """Refresh the local Game table from the account library."""
        owned = self._owned()
        conn = self.get_connection()
        c = conn.cursor()
        seen = []

        for slug, entry in owned.items():
            product = entry.get("product") or {}
            # The UUID is what every other endpoint takes; the slug is only a
            # display/lookup convenience, so the UUID is the stable key.
            uuid = product.get("id")
            if not uuid:
                continue
            seen.append(uuid)
            title = product.get("name") or slug
            notes = product.get("blurb") or ""
            publisher = (product.get("publisher") or {}).get("name") or ""
            release = product.get("release_date") or ""

            c.execute("SELECT id FROM Game WHERE ShortName=?", (uuid,))
            row = c.fetchone()
            if row is None:
                cols = [
                    "Title", "Notes", "ApplicationPath", "ManualPath",
                    "Publisher", "RootFolder", "Source", "DatabaseID",
                    "Genre", "ConfigurationPath", "Developer", "ReleaseDate",
                    "Size", "InstallPath", "UmuId", "SteamClientID", "ShortName",
                ]
                vals = [
                    title, notes, "", "", publisher, "", "Zoom", uuid,
                    "", "", publisher, release, "", "", "", "", uuid,
                ]
                c.execute(
                    f"INSERT INTO Game ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
                    vals,
                )
                game_db_id = c.lastrowid
                art = product.get("search_image") or ""
                if art:
                    c.execute(
                        "INSERT INTO Images (GameID, ImagePath, FileName, SortOrder, Type)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (game_db_id, art, "", 0, "vertical_cover"),
                    )
            else:
                c.execute(
                    "UPDATE Game SET Title=?, Notes=?, Publisher=?, ReleaseDate=? WHERE id=?",
                    (title, notes, publisher, release, row[0]),
                )
            conn.commit()

        # A refund or a revoked key should remove the row rather than leave a
        # game the account no longer owns sitting in the grid.
        if seen:
            placeholders = ",".join(["?"] * len(seen))
            c.execute(
                f"DELETE FROM Game WHERE Source='Zoom' AND InstallPath='' "
                f"AND ShortName NOT IN ({placeholders})",
                seen,
            )
            conn.commit()
        conn.close()
        return seen

    def get_product(self, uuid):
        data = self._request(f"/public/profile/product/{uuid}")
        if not isinstance(data, dict):
            raise ZoomError(f"No product data for {uuid}.")
        return data

    # ---- installer selection ---------------------------------------------

    @staticmethod
    def _version_key(f):
        return (f.get("version") or "", f.get("lang") or "")

    def pick_installer_set(self, product, prefer_native=True):
        """
        Choose which files make up one installable release.

        ZOOM splits a large game into a small .exe plus numbered .bin payloads
        that innoextract expects to find beside it, so this returns the whole
        set ordered by part_num, never just the executable.
        """
        files = product.get("files") or {}
        if prefer_native and files.get("linux"):
            group = files["linux"]
            kind = "linux"
        elif files.get("windows"):
            group = files["windows"]
            kind = "windows"
        else:
            raise ZoomError("This game has no Windows or Linux installer.")

        by_release = {}
        for f in group:
            by_release.setdefault(self._version_key(f), []).append(f)

        # Newest version wins; English is only a tiebreak when versions match.
        def release_rank(key):
            version, lang = key
            parts = tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)
            return (parts, lang.lower() == "english")

        best = max(by_release.keys(), key=release_rank)
        chosen = sorted(by_release[best], key=lambda f: int(f.get("part_num") or 0))
        return kind, best[0], chosen

    # ---- download ---------------------------------------------------------

    def download_game(self, uuid, install_dir):
        """
        Fetch every part of the installer into a staging directory, then hand
        the first part to zoom-platform.sh.
        """
        product = self.get_product(uuid)
        prefer_native = self._setting_value("zoom_prefer_native", "true") == "true"
        kind, version, files = self.pick_installer_set(product, prefer_native)
        title = product.get("name") or uuid

        staging = os.path.join(install_dir, ".zoom-downloads", uuid)
        os.makedirs(staging, exist_ok=True)

        total = 0
        for f in files:
            total += self._parse_size(f.get("file_size"))
        print(f"Downloading {title} ({kind}, v{version}) — {len(files)} file(s)", file=sys.stderr)

        downloaded_total = 0
        paths = []
        for f in files:
            name = f.get("name")
            dest = os.path.join(staging, name)
            url = f.get("file_url")
            if not url:
                raise ZoomError(f"No download URL for {name}.")
            downloaded_total = self._download_file(url, dest, downloaded_total, total)
            paths.append(dest)
            self._ping_download(f.get("id"))

        print("Download Complete", file=sys.stderr)
        return paths, kind, version

    def _download_file(self, url, dest, running, grand_total):
        # Resume a part that was already partly fetched, since these are
        # multi-gigabyte files on hardware that sleeps.
        existing = os.path.getsize(dest) if os.path.exists(dest) else 0
        headers = {"User-Agent": UA}
        if existing:
            headers["Range"] = f"bytes={existing}-"

        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            if e.code == 416:  # already complete
                return running + existing
            if e.code == 403:
                raise ZoomError(
                    "The download link expired before it could be used. "
                    "Refresh the library and try again."
                )
            raise

        mode = "ab" if existing and resp.status == 206 else "wb"
        if mode == "wb":
            existing = 0

        last_report = time.time()
        got = existing
        with open(dest, mode) as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                now = time.time()
                if now - last_report >= 0.5:
                    done = running + got
                    if grand_total > 0:
                        percent = min(done / grand_total * 100, 99.99)
                        print(f"Progress: {percent:.2f} ", file=sys.stderr)
                    print(f"Downloaded: {done / (1024 * 1024):.2f} MiB", file=sys.stderr)
                    last_report = now
        return running + got

    def _ping_download(self, file_id):
        """Courtesy hit so the account's download counter stays accurate."""
        if not file_id:
            return
        try:
            self._request(f"/product/download/{file_id}", data={})
        except Exception:
            pass

    @staticmethod
    def _parse_size(text):
        if not text:
            return 0
        m = re.match(r"([\d.]+)\s*([KMGT]?B)", str(text).strip(), re.I)
        if not m:
            return 0
        value = float(m.group(1))
        unit = m.group(2).upper()
        return int(value * {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit])

    # ---- install ----------------------------------------------------------

    def install_game(self, uuid, install_dir, installer_script):
        paths, kind, version = self.download_game(uuid, install_dir)
        product = self.get_product(uuid)
        title = product.get("name") or uuid
        target = os.path.join(install_dir, self._safe_dir(title))
        os.makedirs(target, exist_ok=True)

        if kind == "linux":
            # A native build arrives as one archive. Downloading it and calling
            # the install done leaves an empty directory and a library entry
            # that launches nothing, so unpack it here — zoom-platform.sh is for
            # Windows installers and cannot help with this.
            print("Native Linux build — unpacking, no Proton needed.", file=sys.stderr)
            self._extract_archive(paths[0], target)
            self._record_install(uuid, target, version, "linux")
            print(DONE_MARKER, file=sys.stderr)
            if self._setting_value("zoom_keep_installers", "false") != "true":
                try:
                    os.remove(paths[0])
                except OSError:
                    pass
            return target

        first = paths[0]
        print(f"Running installer: {os.path.basename(first)}", file=sys.stderr)
        result = subprocess.run(
            [installer_script, "-i", first, "-d", target],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.returncode != 0:
            raise ZoomError(f"zoom-platform.sh failed with code {result.returncode}.")

        self._record_install(uuid, target, version)
        print(DONE_MARKER, file=sys.stderr)
        # The staging copies are dead weight once the game is unpacked, and
        # these are gigabytes on a handheld.
        if self._setting_value("zoom_keep_installers", "false") != "true":
            for p in paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
        return target

    def _extract_archive(self, archive, target):
        """
        Unpack a native build. ZOOM ships .tar.xz for Linux and .zip for macOS;
        both are handled so a mac-only title is not silently broken either.
        """
        import shutil
        import tarfile
        import zipfile

        os.makedirs(target, exist_ok=True)
        name = os.path.basename(archive).lower()
        print(f"Extracting {os.path.basename(archive)}", file=sys.stderr)

        if name.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".tgz", ".tar")):
            with tarfile.open(archive) as tf:
                tf.extractall(target, filter="data")
        elif name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(target)
        else:
            raise ZoomError(f"Do not know how to unpack {os.path.basename(archive)}.")

        # Archives usually hold a single top-level folder; lift its contents up
        # so the install directory is the game directory rather than a wrapper.
        entries = [e for e in os.listdir(target) if not e.startswith(".")]
        if len(entries) == 1:
            inner = os.path.join(target, entries[0])
            if os.path.isdir(inner):
                for item in os.listdir(inner):
                    shutil.move(os.path.join(inner, item), os.path.join(target, item))
                os.rmdir(inner)

        # Tarballs preserve the executable bit; zips do not, so restore it for
        # anything that looks like the launcher.
        for root, _dirs, files in os.walk(target):
            for f in files:
                if f.endswith((".sh", ".x86_64", ".x86", ".AppImage")) or "." not in f:
                    path = os.path.join(root, f)
                    try:
                        os.chmod(path, os.stat(path).st_mode | 0o111)
                    except OSError:
                        pass
        print("Extraction complete", file=sys.stderr)

    # Launcher names that are never the game itself.
    SKIP_EXE = (
        "unins", "uninstall", "vcredist", "dxsetup", "directx", "dotnet",
        "setup", "crashhandler", "crashreport", "oalinst", "python",
    )

    def _fix_renpy_launcher(self, script, root):
        """
        Ren'Py resolves its binary from the launcher's own filename:

            BASEFILE=$(basename "$SCRIPT" .sh)
            exec "$ROOT/lib/$PYTHON-$PLATFORM/$BASEFILE"

        A game normally ships <Game>.sh next to the generic start.sh, so
        BASEFILE matches the binary in lib/. Some stores package only
        start.sh, which then looks for a binary called "start" that does not
        exist and dies with "platform files not found".

        If that is the case, find the real binary and create a launcher named
        after it. The binary is left alone; only a correctly-named wrapper is
        added, which is exactly what the missing file would have been.
        """
        if os.path.basename(script) != "start.sh":
            return script

        lib = os.path.join(root, "lib")
        if not os.path.isdir(lib):
            return script

        # Ren'Py's own helpers live here too and are never the game.
        ignore = {"python", "pythonw", "zsync", "zsyncmake", "renpy"}
        for entry in sorted(os.listdir(lib)):
            platform_dir = os.path.join(lib, entry)
            if not os.path.isdir(platform_dir) or "linux" not in entry:
                continue
            if os.path.exists(os.path.join(platform_dir, "start")):
                return script  # the generic name works here after all
            for name in sorted(os.listdir(platform_dir)):
                full = os.path.join(platform_dir, name)
                if (name.lower() in ignore or "." in name
                        or not os.path.isfile(full) or not os.access(full, os.X_OK)):
                    continue
                wrapper = os.path.join(root, name + ".sh")
                if not os.path.exists(wrapper):
                    import shutil
                    shutil.copy2(script, wrapper)
                    os.chmod(wrapper, 0o755)
                print(f"Ren'Py launcher renamed for binary '{name}'", file=sys.stderr)
                return wrapper
        return script

    def detect_executable(self, uuid):
        """
        Find the launcher inside an installed game and record it.

        ApplicationPath is stored RELATIVE to RootFolder, because
        get_lauch_options joins the two. Shallower wins: a game's own start.sh
        sits at the top level, while engine copies of the same name are buried.
        """
        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute(
            "SELECT InstallPath, RootFolder, ConfigurationPath FROM Game WHERE ShortName=?",
            (uuid,))
        row = c.fetchone()
        conn.close()
        if not row:
            return json.dumps({"Type": "Error", "Content": {"Message": "Unknown game."}})

        root = row["RootFolder"] or row["InstallPath"] or ""
        kind = row["ConfigurationPath"] or "windows"
        if not root or not os.path.isdir(root):
            return json.dumps({"Type": "Error", "Content": {"Message": "Not installed."}})

        # A Windows install puts the game inside a Proton prefix, so most of the
        # tree is Wine's own system files. Walking it finds hundreds of .exe
        # files that are not the game.
        prefix_junk = (
            os.path.join("drive_c", "windows"),
            os.path.join("drive_c", "Program Files"),
            os.path.join("drive_c", "Program Files (x86)"),
            os.path.join("drive_c", "ProgramData"),
            os.path.join("drive_c", "users"),
            os.path.join("drive_c", "openxr"),
            os.path.join("drive_c", "vrclient"),
            os.path.join("drive_c", "proton_shortcuts"),
            "dosdevices",
        )

        candidates = []
        for dirpath, _dirs, files in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            if any(rel_dir == j or rel_dir.startswith(j + os.sep) for j in prefix_junk):
                continue
            depth = dirpath[len(root):].count(os.sep)
            for name in files:
                low = name.lower()
                if any(low.startswith(s) for s in self.SKIP_EXE):
                    continue
                full = os.path.join(dirpath, name)
                rank = None
                if kind == "linux":
                    if low == "start.sh":
                        rank = 0
                    elif low.endswith(".sh"):
                        rank = 1
                    elif low.endswith((".x86_64", ".x86", ".appimage")):
                        rank = 2
                    elif "." not in name and os.access(full, os.X_OK):
                        rank = 3
                else:
                    if low.endswith(".exe"):
                        rank = 0
                if rank is not None:
                    candidates.append((rank, depth, len(name), full))

        # zoom-platform.sh writes a ready-made launcher for the installed game.
        # Using it means the game runs exactly as the installer intended, and it
        # already invokes umu itself — so Steam must NOT also wrap it in Proton.
        shortcut_dir = os.path.join(root, "drive_c", "zoom_shortcuts")
        launcher = None
        if os.path.isdir(shortcut_dir):
            shortcuts = sorted(
                f for f in os.listdir(shortcut_dir) if f.lower().endswith(".sh"))
            if shortcuts:
                launcher = os.path.join(shortcut_dir, shortcuts[0])

        if launcher:
            chosen = launcher
            kind = "umu"          # recorded so Compatibility comes back false
        else:
            if not candidates:
                return json.dumps(
                    {"Type": "Error", "Content": {"Message": "No executable found."}})
            candidates.sort()
            chosen = self._fix_renpy_launcher(candidates[0][3], root)
        relative = os.path.relpath(chosen, root)

        conn = self.get_connection()
        c = conn.cursor()
        c.execute(
            "UPDATE Game SET ApplicationPath=?, ConfigurationPath=? WHERE ShortName=?",
            (relative, kind, uuid))
        conn.commit()
        conn.close()
        print(f"Detected executable: {relative}", file=sys.stderr)
        return json.dumps(
            {"Type": "Success", "Content": {"Message": f"Executable: {relative}", "Toast": False}})

    def _record_install(self, uuid, path, version, kind="windows"):
        conn = self.get_connection()
        c = conn.cursor()
        # ConfigurationPath carries the build type; get_lauch_options reads it to
        # decide whether Steam needs a compatibility tool.
        c.execute(
            "UPDATE Game SET InstallPath=?, RootFolder=?, Size=?, ConfigurationPath=? WHERE ShortName=?",
            (path, path, self._dir_size(path), kind, uuid),
        )
        conn.commit()
        conn.close()
        self.save_setting(f"zoom_version_{uuid}", version)

    def uninstall_game(self, uuid):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT InstallPath FROM Game WHERE ShortName=?", (uuid,))
        row = c.fetchone()
        path = row[0] if row else ""
        if path and os.path.isdir(path):
            import shutil
            shutil.rmtree(path, ignore_errors=True)
        # Clear every field the install set. Leaving SteamClientID behind makes
        # the game read as installed again on the next reload, because the UI
        # decides that from this column alone.
        c.execute(
            "UPDATE Game SET InstallPath='', RootFolder='', Size='',"
            " ApplicationPath='', ConfigurationPath='', SteamClientID=''"
            " WHERE ShortName=?",
            (uuid,),
        )
        conn.commit()
        conn.close()
        return json.dumps({"Type": "Uninstall", "Content": {"Message": "Uninstalled"}})

    def update_available(self, uuid):
        """A game is out of date when the store's newest release differs."""
        installed = self._setting_value(f"zoom_version_{uuid}")
        if not installed:
            return False
        try:
            product = self.get_product(uuid)
            _, version, _ = self.pick_installer_set(product)
        except Exception:
            return False
        return version != installed

    @staticmethod
    def _safe_dir(name):
        return re.sub(r"[^\w\-. ]+", "", name).strip() or "zoom-game"

    @staticmethod
    def _dir_size(path):
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return str(total)

    # ---- contracts the framework expects each store to provide -------------
    # GamesDb does not supply these; every store implements its own because the
    # shapes differ (itch.io reads uploads, GOG reads gogdl, ZOOM reads files).

    def get_game_size(self, game_id, installed):
        if installed == 'true':
            conn = self.get_connection()
            c = conn.cursor()
            c.row_factory = sqlite3.Row
            c.execute("SELECT Size FROM Game WHERE ShortName=?", (game_id,))
            row = c.fetchone()
            conn.close()
            raw = row['Size'] if row and row['Size'] else ""
            try:
                size = f"Size on Disk: {self.convert_bytes(int(raw))}" if raw else ""
            except (TypeError, ValueError):
                size = f"Size on Disk: {raw}" if raw else ""
        else:
            try:
                product = self.get_product(game_id)
                _kind, _version, files = self.pick_installer_set(product)
                total = sum(self._parse_size(f.get("file_size")) for f in files)
                size = f"Download Size: {self.convert_bytes(total)}" if total else ""
            except Exception:
                size = ""
        return json.dumps({'Type': 'GameSize', 'Content': {'Size': size}})

    def get_lauch_options(self, game_id, steam_command, name, offline=False):
        script_path = os.path.expanduser(os.environ.get('LAUNCHER', ''))

        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute(
            "SELECT ApplicationPath, RootFolder, InstallPath, ConfigurationPath"
            " FROM Game WHERE ShortName=?", (game_id,))
        game = c.fetchone()
        conn.close()

        root_dir = ""
        game_exe = ""
        # A native Linux build runs directly; everything else goes through umu,
        # which is what ConfigurationPath records at install time.
        is_windows = True
        if game:
            root_dir = game['RootFolder'] or game['InstallPath'] or ""
            if game['ApplicationPath']:
                game_exe = os.path.join(root_dir, game['ApplicationPath']).replace("\\", "/")
            # 'linux' is a native build; 'umu' is the installer's own launcher,
            # which calls umu-run itself. Either way Steam must not add Proton.
            if game['ConfigurationPath'] in ('linux', 'umu'):
                is_windows = False
        if not root_dir:
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/zoom/'))
            root_dir = install_dir

        return json.dumps({
            'Type': 'LaunchOptions',
            'Content': {
                'Exe': f"\"{game_exe}\"" if game_exe else "\"\"",
                'Options': f"{script_path} {game_id}%command%",
                'WorkingDir': f"\"{root_dir}\"" if root_dir else "",
                'Compatibility': is_windows,
                'Name': name,
            },
        })

    def get_last_progress_update(self, file_path):
        progress_re = re.compile(r"Progress: (\d+\.?\d*) ")
        downloaded_re = re.compile(r"Downloaded: (\S+) MiB")
        # Anything the runtime prints into our log that is not ours. Steam's
        # overlay preload warning lands there before the first byte is fetched.
        noise_re = re.compile(r"ld\.so|LD_PRELOAD|gameoverlayrenderer", re.I)
        last_progress_update = {"Percentage": 0, "Description": "Starting…"}

        try:
            with open(file_path, "r") as f:
                lines = f.readlines()

            percent = None
            downloaded = ""
            for line in reversed(lines):
                if percent is None:
                    if match := progress_re.search(line):
                        percent = float(match.group(1))
                if not downloaded:
                    if match := downloaded_re.search(line):
                        downloaded = match.group(1)
                if percent is not None and downloaded:
                    break

            is_complete = False
            is_error = False
            error_line = ""
            installing = False
            for line in lines:
                stripped = line.strip()
                # Only our own markers count. Anything else in this file was put
                # there by Steam, ld.so or the installer's own chatter, and
                # matching on a bare "error" made overlay noise look like a
                # failed install before the download had even started.
                if stripped.startswith(ERROR_MARKER):
                    is_error = True
                    error_line = stripped[len(ERROR_MARKER):].strip()
                elif stripped == DONE_MARKER:
                    is_complete = True
                    is_error = False
                    error_line = ""
                elif "Download Complete" in stripped:
                    # Downloads finished; extraction is still to come.
                    installing = True

            if is_complete:
                last_progress_update = {"Percentage": 100, "Description": "Installation complete"}
            elif installing and not is_error:
                # No percentage available from innoextract, so hold just short of
                # the end rather than claiming a finish that has not happened.
                last_progress_update = {
                    "Percentage": 99,
                    "Description": "Download complete — installing, this can take a few minutes",
                }
            elif is_error:
                last_progress_update = {
                    "Percentage": 0, "Description": "Installation Failed.", "Error": error_line}
            elif percent is not None:
                last_progress_update = {
                    "Percentage": min(percent, 99),
                    "Description": f"Downloaded {downloaded} MiB ({percent}%)" if downloaded
                    else f"Downloading ({percent}%)",
                }
            else:
                # Fall back to the last line that is actually ours, so the user
                # is not shown an unrelated linker warning as a status.
                useful = [
                    l.strip() for l in lines
                    if l.strip() and not noise_re.search(l)
                ]
                if useful:
                    last_progress_update = {"Percentage": 0, "Description": useful[-1]}
        except Exception as e:
            print("Waiting for progress update", e, file=sys.stderr)
            time.sleep(1)

        return json.dumps({'Type': 'ProgressUpdate', 'Content': last_progress_update})
