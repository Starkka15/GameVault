import json
import os
import re
import sys
import sqlite3
import hashlib

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
            shortname = "rpgm_" + hashlib.md5(os.path.realpath(folder).encode()).hexdigest()[:12]
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

    def _detect_engine_at(self, folder):
        has_pkg = os.path.isfile(os.path.join(folder, "package.json"))
        www = os.path.join(folder, "www")
        data_root = os.path.join(folder, "data")
        js_root = os.path.join(folder, "js")

        if has_pkg and os.path.isdir(www):
            engine, base, app_rel = "mv", www, "www/index.html"
        elif has_pkg and (os.path.isdir(data_root) or os.path.isdir(js_root)):
            engine, base, app_rel = "mz", folder, "index.html"
        else:
            engine = self._detect_rgss(folder)
            if engine is None:
                return None
            base, app_rel = folder, ""

        return {
            'engine': engine,
            'app_rel': app_rel,
            'title': self._read_title(engine, base, folder),
            'icon': self._find_icon(engine, base, folder),
        }

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
        c.execute("SELECT RootFolder, ConfigurationPath FROM Game WHERE ShortName=?", (game_id,))
        game = c.fetchone()
        conn.close()

        working_dir = game['RootFolder'] if game and game['RootFolder'] else ""
        engine = game['ConfigurationPath'] if game and game['ConfigurationPath'] else ""

        return json.dumps({
            'Type': 'LaunchOptions',
            'Content': {
                'Exe': f"\"{launcher}\"",
                'Options': f"{game_id} {engine}".strip(),
                'WorkingDir': f"\"{working_dir}\"" if working_dir else "",
                'Compatibility': False,   # native for BOTH nwjs (MV/MZ) and mkxp-z (RGSS)
                'Name': name,
            }
        })

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
