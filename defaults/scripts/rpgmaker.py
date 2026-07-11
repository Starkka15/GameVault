import json
import os
import re
import sys
import sqlite3
import hashlib
import subprocess

import GamesDb


class CmdException(Exception):
    pass


class Rpgmaker(GamesDb.GamesDb):
    """Local-folder scanner for RPG Maker games (MV/MZ via NW.js, VX Ace/XP/VX via mkxp-z).

    Unlike the store extensions there is no download/login/web API: the user copies game
    folders into INSTALL_DIR and this class scans them, detects the engine, and upserts a
    Game row. The engine tag is stored in ConfigurationPath and read by the launcher.
    """

    def __init__(self, db_file, storeName, setNameConfig=None):
        super().__init__(db_file, storeName=storeName, setNameConfig=setNameConfig)
        # No storefront — grid must omit storeURL.
        self.storeURL = None

    def _install_dir(self):
        return os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/rpgmaker/'))

    # ------------------------------------------------------------------ scan --
    def get_list(self, offline=False):
        install_dir = self._install_dir()
        if not os.path.isdir(install_dir):
            print(f"RPGMaker scan dir does not exist: {install_dir}", file=sys.stderr)
            return ""
        conn = self.get_connection()
        c = conn.cursor()
        seen = set()
        for entry in sorted(os.listdir(install_dir)):
            folder = os.path.join(install_dir, entry)
            if not os.path.isdir(folder):
                continue
            info = self._detect_engine(folder)
            if info is None:
                continue
            folder = info['root']  # resolve nested game roots (dist folders wrap the game one level down)
            real = os.path.realpath(folder)
            shortname = "rpgm_" + hashlib.md5(real.encode()).hexdigest()[:12]
            # v1.1.6 rename migration: the drop folder moved RPGMaker -> AddedGames, which
            # changes realpath and thus the derived ShortName. If a row already exists under
            # the OLD (RPGMaker-path) ShortName, adopt it so the row is re-homed in place —
            # keeps the game's Steam shortcut (baked with the old id) working and avoids a
            # duplicate entry. Only kicks in for games actually under an AddedGames path.
            sep = os.sep
            if sep + "AddedGames" + sep in real:
                old_real = real.replace(sep + "AddedGames" + sep, sep + "RPGMaker" + sep)
                old_shortname = "rpgm_" + hashlib.md5(old_real.encode()).hexdigest()[:12]
                if old_shortname != shortname:
                    c.execute("SELECT id FROM Game WHERE ShortName=?", (old_shortname,))
                    if c.fetchone():
                        shortname = old_shortname
            seen.add(shortname)
            size = self.convert_bytes(self._dir_size(folder))
            c.execute("SELECT id FROM Game WHERE ShortName=?", (shortname,))
            row = c.fetchone()
            if row is None:
                cols = ["Title", "Source", "RootFolder", "InstallPath", "ApplicationPath",
                        "ConfigurationPath", "Arguments", "Size", "GameType", "DatabaseID", "ShortName"]
                vals = [info['title'], "RPGMaker", folder, folder, info['app_rel'],
                        info['engine'], info['engine'], size, "native", shortname, shortname]
                c.execute(f"INSERT INTO Game ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})", vals)
                gid = c.lastrowid
                if info['icon']:
                    c.execute("INSERT INTO Images (GameID, ImagePath, FileName, SortOrder, Type) VALUES (?, ?, ?, ?, ?)",
                              (gid, "file://" + info['icon'], '', 0, 'square_icon'))
                print(f"RPGMaker added: {info['title']} [{info['engine']}]", file=sys.stderr)
            else:
                gid = row[0]
                c.execute("""UPDATE Game SET Title=?, RootFolder=?, InstallPath=?, ApplicationPath=?,
                             ConfigurationPath=?, Arguments=?, Size=? WHERE id=?""",
                          (info['title'], folder, folder, info['app_rel'], info['engine'],
                           info['engine'], size, gid))
            conn.commit()

        # Prune rows whose folder disappeared (keep ones the user added to Steam).
        c.execute("SELECT ShortName, RootFolder, SteamClientID FROM Game WHERE Source='RPGMaker'")
        for sn, rf, scid in c.fetchall():
            if sn not in seen and (not rf or not os.path.isdir(rf)) and not scid:
                c.execute("DELETE FROM Images WHERE GameID=(SELECT id FROM Game WHERE ShortName=?)", (sn,))
                c.execute("DELETE FROM Game WHERE ShortName=?", (sn,))
        conn.commit()
        conn.close()
        return ""

    def _dir_size(self, path):
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    # -------------------------------------------------------------- detection --
    def _detect_engine(self, folder):
        # Try the folder itself, then one level down: distribution archives often
        # wrap the real game dir (e.g. "Egads RPG - Windows/Egads RPG/",
        # "Vore Town 1.10.1 Windows/Vore Town/"). Pick the first nested game root.
        info = self._detect_engine_at(folder)
        if info is not None:
            info['root'] = folder
            return info
        # Standard RPG Maker asset dirs are never game roots — skip them so a
        # stray RGSSNxx.dll under System/ can't be mistaken for the game
        # (the Game.ini at the parent is the real engine marker).
        SKIP = {"system", "audio", "graphics", "fonts", "data", "movies", "save"}
        try:
            subs = [os.path.join(folder, d) for d in sorted(os.listdir(folder))
                    if os.path.isdir(os.path.join(folder, d)) and d.lower() not in SKIP]
        except OSError:
            return None
        for sub in subs:
            info = self._detect_engine_at(sub)
            if info is not None:
                info['root'] = sub
                return info
        return None

    # Files/dirs that must never be treated as a launchable Windows/Linux game exe.
    _EXE_SKIP = ("unins", "vcredist", "vc_redist", "dxsetup", "dxwebsetup", "oalinst",
                 "notification_helper", "crashpad", "crashreport", "crashhandler", "nwjc",
                 "chromedriver", "ffmpegsumo", "d3dcompiler", "python", "pythonw", "dotnet",
                 "setup", "config", "settings", "cheat", "trainer", "readme")

    def _detect_engine_at(self, folder):
        # --- manual override: a `.gvengine` file (one word) forces the engine tag,
        #     for when auto-detection guesses wrong. Drop it in the game folder. ---
        override = self._engine_override(folder)
        if override:
            return self._engine_info(override, folder)

        # Detection cascade (order matters, per design):
        #   RPG Maker -> ScummVM -> DOS -> Linux -> Electron -> Windows(Proton).
        # ScummVM is tried before DOS because some ScummVM games also ship a DOSBox
        # conf that would otherwise win.
        rm = self._detect_rpgmaker(folder)
        if rm:
            return rm
        if self._detect_scummvm(folder):
            return self._engine_info("scummvm", folder)
        dos = self._detect_dos(folder)
        if dos:
            return self._engine_info("dos", folder, app_rel=dos)
        lin = self._detect_linux(folder)
        if lin:
            return self._engine_info("linux", folder, app_rel=lin)
        el = self._detect_electron(folder)
        if el is not None:
            return self._engine_info("electron", folder, app_rel=el)
        win = self._detect_windows(folder)
        if win:
            return self._engine_info("windows", folder, app_rel=win)
        return None

    def _engine_override(self, folder):
        marker = os.path.join(folder, ".gvengine")
        if not os.path.isfile(marker):
            return None
        try:
            eng = open(marker, encoding="utf-8", errors="ignore").read().strip().lower()
        except OSError:
            return None
        valid = {"mv", "mz", "vxace", "xp", "vx", "scummvm", "dos", "linux",
                 "electron", "windows"}
        return eng if eng in valid else None

    def _engine_info(self, engine, folder, app_rel=None):
        # MV serves from www/; everything else roots at the folder.
        base = folder
        if engine == "mv" and os.path.isdir(os.path.join(folder, "www")):
            base = os.path.join(folder, "www")
        if app_rel is None:
            app_rel = {"mv": "www/index.html", "mz": "index.html"}.get(engine, "")
        return {
            'engine': engine,
            'app_rel': app_rel,
            'title': self._read_title(engine, base, folder),
            'icon': self._find_icon(engine, base, folder),
        }

    def _listdir(self, folder):
        try:
            # Skip macOS AppleDouble sidecars ("._Foo") and .DS_Store that ride
            # along in zips/tars from Mac uploaders — they're never game files.
            return [f for f in os.listdir(folder)
                    if not f.startswith("._") and f != ".DS_Store"]
        except OSError:
            return []

    # -- RPG Maker (strong signatures so generic NW.js/Electron isn't mislabelled) --
    def _detect_rpgmaker(self, folder):
        www = os.path.join(folder, "www")
        has_pkg = os.path.isfile(os.path.join(folder, "package.json"))
        # MV: www/js/rpg_core.js, or (package.json + www/data/System.json)
        if os.path.isfile(os.path.join(www, "js", "rpg_core.js")) or \
           (has_pkg and os.path.isfile(os.path.join(www, "data", "System.json"))):
            return self._engine_info("mv", folder)
        # MZ: js/rmmz_core.js, or (package.json + data/System.json + js/)
        if os.path.isfile(os.path.join(folder, "js", "rmmz_core.js")) or \
           (has_pkg and os.path.isfile(os.path.join(folder, "data", "System.json"))
            and os.path.isdir(os.path.join(folder, "js"))):
            return self._engine_info("mz", folder)
        # RGSS (VX Ace / XP / VX)
        engine = self._detect_rgss(folder)
        if engine:
            return self._engine_info(engine, folder)
        # Looser fallback (original heuristic): a package.json NW.js app with a www/
        # or data/ dir is almost certainly MV/MZ. Better to run it under NW.js than
        # let it fall through to Windows/Proton.
        if has_pkg and os.path.isdir(www):
            return self._engine_info("mv", folder)
        if has_pkg and (os.path.isdir(os.path.join(folder, "data"))
                        or os.path.isdir(os.path.join(folder, "js"))):
            return self._engine_info("mz", folder)
        return None

    # -- ScummVM: ask the ScummVM flatpak to detect it (read-only, no --add). --
    _scummvm_available = None

    def _detect_scummvm(self, folder):
        if not self._flatpak_installed("org.scummvm.ScummVM"):
            return False
        try:
            env = dict(os.environ, SDL_VIDEODRIVER="dummy")
            r = subprocess.run(
                ["flatpak", "run", f"--filesystem={folder}", "org.scummvm.ScummVM",
                 "--detect", f"--path={folder}"],
                capture_output=True, text=True, timeout=25, env=env)
            # A hit is a row whose first token is an "<engine>:<gameid>" target
            # (e.g. "scumm:monkey"). Header ("GameID"), rules ("---") and the
            # "WARNING: ScummVM could not find any game" line must NOT match.
            gid_re = re.compile(r"^[a-z0-9]+:[a-z0-9_.-]+$")
            for line in r.stdout.splitlines():
                s = line.strip()
                if s and gid_re.match(s.split()[0]):
                    print(f"[detect] ScummVM game in {folder}: {s}", file=sys.stderr)
                    return True
        except Exception as e:
            print(f"[detect] ScummVM probe failed on {folder}: {type(e).__name__}: {e}",
                  file=sys.stderr)
        return False

    # -- DOS: a dosbox*.conf (root or DOSBOX subfolder), else a .bat/.com. --
    def _detect_dos(self, folder):
        files = self._listdir(folder)
        confs = sorted(f for f in files
                       if f.lower().endswith(".conf") and "dosbox" in f.lower())
        if confs:
            return confs[0]
        for sub in files:
            subp = os.path.join(folder, sub)
            if os.path.isdir(subp) and sub.lower() in ("dosbox", "dosbox_files", "dosbox files"):
                subconfs = sorted(f for f in self._listdir(subp)
                                  if f.lower().endswith(".conf"))
                if subconfs:
                    return os.path.join(sub, subconfs[0])
        # A bare .bat is NOT a DOS signal (many Windows games ship one); only a
        # 16-bit .com executable counts on its own.
        for f in sorted(files):
            if f.lower().endswith(".com"):
                return f
        return None

    # -- Linux native: Unity .x86_64, Ren'Py .sh, generic ELF, or a lone .sh. --
    def _detect_linux(self, folder):
        files = self._listdir(folder)
        base = os.path.basename(folder.rstrip("/")).lower()

        def prefer_named(cands, strip):
            return sorted(cands, key=lambda f: (f[:-strip].lower() != base, len(f), f))[0]

        x64 = [f for f in files if f.endswith(".x86_64")]
        if x64:
            return prefer_named(x64, 7)
        x86 = [f for f in files if f.endswith(".x86")]
        if x86:
            return prefer_named(x86, 4)
        # Ren'Py: <name>.sh alongside a renpy/ dir or lib/py?-linux-*
        libdir = os.path.join(folder, "lib")
        renpy = os.path.isdir(os.path.join(folder, "renpy")) or \
            any(d.startswith(("py3-linux", "py2-linux")) for d in self._listdir(libdir))
        shs = [f for f in files if f.endswith(".sh")]
        if renpy and shs:
            return prefer_named(shs, 3)
        # generic native ELF at the top level. Don't require the exec bit — unzip
        # often strips it (the launcher chmod+x's before running). Exclude shared
        # libs; prefer a binary named like the folder, else the largest.
        elfs = []
        for f in files:
            if f.endswith(".so") or ".so." in f:
                continue
            p = os.path.join(folder, f)
            if os.path.isfile(p) and self._is_elf(p):
                try:
                    elfs.append((f, os.path.getsize(p)))
                except OSError:
                    elfs.append((f, 0))
        if elfs:
            elfs.sort(key=lambda t: (t[0].lower() != base, -t[1], t[0]))
            return elfs[0][0]
        if shs:
            return sorted(shs)[0]
        return None

    # -- Electron / NW.js: returns "" (run runtime on folder) or "index.html". --
    def _detect_electron(self, folder):
        files = self._listdir(folder)
        low = {f.lower() for f in files}
        res = os.path.join(folder, "resources")
        if os.path.isdir(res):
            r = {f.lower() for f in self._listdir(res)}
            if r & {"app.asar", "app", "app.nw"}:
                return ""
        if "package.nw" in low:
            return ""
        if "index.html" in low and "package.json" in low:
            return "index.html"
        return None

    # -- Windows (Proton): best PE .exe, skipping installers/redists/helpers. --
    def _detect_windows(self, folder):
        files = self._listdir(folder)
        base = os.path.basename(folder.rstrip("/")).lower()
        exes = []
        for f in files:
            if not f.lower().endswith(".exe"):
                continue
            if any(s in f.lower() for s in self._EXE_SKIP):
                continue
            if self._is_pe(os.path.join(folder, f)):
                exes.append(f)
        if not exes:
            return None
        exes.sort(key=lambda f: (f[:-4].lower() != base, len(f), f))
        return exes[0]

    # ------------------------------------------------------------- detect utils --
    def _flatpak_installed(self, app_id):
        if Rpgmaker._scummvm_available is None:
            try:
                r = subprocess.run(["flatpak", "list", "--app", "--columns=application"],
                                   capture_output=True, text=True, timeout=10)
                Rpgmaker._flatpak_apps = set(r.stdout.split())
            except Exception:
                Rpgmaker._flatpak_apps = set()
            Rpgmaker._scummvm_available = True  # sentinel: probe has run once
        return app_id in getattr(Rpgmaker, "_flatpak_apps", set())

    @staticmethod
    def _is_elf(path):
        try:
            with open(path, "rb") as fh:
                return fh.read(4) == b"\x7fELF"
        except OSError:
            return False

    @staticmethod
    def _is_pe(path):
        try:
            with open(path, "rb") as fh:
                if fh.read(2) != b"MZ":
                    return False
                fh.seek(0x3C)
                off = int.from_bytes(fh.read(4), "little")
                fh.seek(off)
                return fh.read(4) == b"PE\x00\x00"
        except OSError:
            return False

    def _detect_rgss(self, folder):
        try:
            files = os.listdir(folder)
        except OSError:
            return None
        for f in files:
            low = f.lower()
            if low.endswith(".rvproj2"):
                return "vxace"
            if low.endswith(".rvproj"):
                return "vx"
            if low.endswith(".rxproj"):
                return "xp"
        for f in files:
            m = re.match(r"RGSS(\d)\d\d\.dll$", f, re.I)
            if m:
                return {"3": "vxace", "2": "vx", "1": "xp"}.get(m.group(1))
        ini = os.path.join(folder, "Game.ini")
        if os.path.isfile(ini):
            try:
                txt = open(ini, encoding="utf-8", errors="ignore").read()
            except OSError:
                txt = ""
            # Library value may carry a path prefix, e.g. "System\RGSS301.dll";
            # match the RGSSNxx dll anywhere in the value, not just after "=".
            m = re.search(r"Library\s*=.*RGSS(\d)\d\d", txt, re.I)
            if m:
                return {"3": "vxace", "2": "vx", "1": "xp"}.get(m.group(1))
        return None

    def _read_title(self, engine, base, folder):
        if engine in ("mv", "mz"):
            sysjson = os.path.join(base, "data", "System.json")
            try:
                title = json.load(open(sysjson, encoding="utf-8")).get("gameTitle")
                if title:
                    return title
            except Exception:
                pass
        ini = os.path.join(folder, "Game.ini")
        if os.path.isfile(ini):
            try:
                m = re.search(r"^\s*Title\s*=\s*(.+)$",
                              open(ini, encoding="utf-8", errors="ignore").read(), re.M)
                if m:
                    return m.group(1).strip()
            except OSError:
                pass
        return os.path.basename(folder.rstrip("/"))

    def _find_icon(self, engine, base, folder):
        if engine in ("mv", "mz"):
            p = os.path.join(base, "icon", "icon.png")
            if os.path.isfile(p):
                return os.path.realpath(p)
        return None

    def migrate_added_games_paths(self):
        """v1.1.6 one-time re-home: rewrite RootFolder/InstallPath and icon paths from the
        old 'Games/RPGMaker' drop folder to 'Games/AddedGames', in place (ShortName is left
        untouched so existing Steam shortcuts keep working). Idempotent — REPLACE on already
        migrated paths is a no-op. Called from settings.sh right after the folder is moved,
        so the DB reflects the new location without waiting for a full rescan/Refresh."""
        old, new = '/Games/RPGMaker/', '/Games/AddedGames/'
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE Game SET RootFolder=REPLACE(RootFolder,?,?), "
                  "InstallPath=REPLACE(InstallPath,?,?) WHERE Source='RPGMaker'",
                  (old, new, old, new))
        c.execute("UPDATE Images SET ImagePath=REPLACE(ImagePath,?,?) "
                  "WHERE GameID IN (SELECT id FROM Game WHERE Source='RPGMaker')",
                  (old, new))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------ launch/info --
    def get_game_dir(self, game_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT RootFolder, InstallPath FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        conn.close()
        if result and result[0]:
            print(result[0])
        elif result and result[1]:
            print(result[1])
        else:
            print(os.path.join(self._install_dir(), game_id))

    def get_lauch_options(self, game_id, steam_command, name, offline=False):
        launcher = os.path.expanduser(os.environ['LAUNCHER'])
        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute("SELECT RootFolder, ApplicationPath, ConfigurationPath FROM Game WHERE ShortName=?",
                  (game_id,))
        game = c.fetchone()
        conn.close()

        root = game['RootFolder'] if game and game['RootFolder'] else ""
        app_rel = game['ApplicationPath'] if game and game['ApplicationPath'] else ""
        engine = game['ConfigurationPath'] if game and game['ConfigurationPath'] else ""

        # --- ScummVM / DOS: native via flatpak (mirror the GOG branch). No Proton. --
        if engine in ("scummvm", "dos"):
            if engine == "scummvm":
                flatpak_id = "org.scummvm.ScummVM"
                args = f"--path=\"{root}\" --auto-detect"
                work = root
            else:
                flatpak_id = "io.github.dosbox-staging"
                conf_abs = os.path.normpath(os.path.join(root, app_rel)) if app_rel else ""
                args = f"-conf \"{conf_abs}\" -exit" if conf_abs else ""
                work = os.path.dirname(conf_abs) if conf_abs else root
            options = f"run --filesystem=\"{root}\" {flatpak_id} {args}".strip()
            return json.dumps({'Type': 'LaunchOptions', 'Content': {
                'Exe': '"/usr/bin/flatpak"',
                'Options': options,
                'WorkingDir': f"\"{work}\"" if work else "",
                'Compatibility': False,
                'Name': name,
            }})

        # --- Windows: run the .exe under Proton (compat tool set by the frontend). --
        if engine == "windows":
            exe_abs = os.path.join(root, app_rel).replace("\\", "/") if app_rel else ""
            work = os.path.dirname(exe_abs) if exe_abs else root
            return json.dumps({'Type': 'LaunchOptions', 'Content': {
                'Exe': f"\"{exe_abs}\"" if exe_abs else "\"\"",
                'Options': "%command%",
                'WorkingDir': f"\"{work}\"" if work else "",
                'Compatibility': True,
                'Name': name,
            }})

        # --- Native launcher: MV/MZ (NW.js), RGSS (mkxp-z), Linux, Electron. --
        return json.dumps({'Type': 'LaunchOptions', 'Content': {
            'Exe': f"\"{launcher}\"",
            'Options': f"{game_id} {engine}".strip(),
            'WorkingDir': f"\"{root}\"" if root else "",
            'Compatibility': False,
            'Name': name,
        }})

    def get_game_size(self, game_id, installed):
        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute("SELECT Size FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        conn.close()
        size = f"Size on Disk: {result['Size']}" if result and result['Size'] else ""
        return json.dumps({'Type': 'GameSize', 'Content': {'Size': size}})

    def get_login_status(self, flush_cache=False):
        # No auth for a local scanner — always "logged in".
        return json.dumps({'Type': 'Status', 'Content': {'LoggedIn': True, 'Username': 'Local'}})
