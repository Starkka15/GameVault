import datetime
import re
import json
import os
import sqlite3
import sys
import subprocess
import time

import GamesDb
from datetime import datetime, timedelta


class CmdException(Exception):
    pass


class Optima(GamesDb.GamesDb):
    """Ubisoft Connect library backed by optima-cli (ownership + Uplay R1 emu).

    Games are keyed by their numeric Ubisoft product id, which is used as the
    DB ShortName (EA used a slug; Ubisoft has no slug, just the product id).
    """

    def __init__(self, db_file, storeName, setNameConfig=None):
        super().__init__(db_file, storeName=storeName, setNameConfig=setNameConfig)
        self.storeURL = "https://www.ubisoft.com"

    optima_cmd = os.environ.get('OPTIMA_CMD', os.path.expanduser('~/.local/bin/optima-cli'))
    _ansi_re = re.compile(r'\x1b\[[0-9;]*m')

    def _strip_ansi(self, text):
        return self._ansi_re.sub('', text)

    def execute_shell(self, cmd):
        env = os.environ.copy()
        env['NO_COLOR'] = '1'
        result = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  shell=True, env=env).communicate()
        stdout = result[0].decode()
        stderr = result[1].decode()
        combined = self._strip_ansi(stdout + stderr)
        if combined.strip() == "":
            raise CmdException(f"Command produced no output: {cmd}")
        return combined

    def execute_shell_stdout(self, cmd):
        env = os.environ.copy()
        env['NO_COLOR'] = '1'
        result = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  shell=True, env=env).communicate()
        return self._strip_ansi(result[0].decode())

    # ---- games list -------------------------------------------------------

    def get_list(self, offline=False):
        """Fetch owned games from Ubisoft via `optima-cli list-games --json` and
        upsert them into the DB. optima-cli emits a JSON array of
        {product_id, name, installable}; only installable entries (a real
        Ubisoft build exists) are shown so Steam-linked/delisted copies don't
        clutter the library."""
        try:
            output = self.execute_shell_stdout(f"{self.optima_cmd} list-games --json")
        except Exception:
            output = ""
        # The JSON is the last non-empty line (any diagnostics precede it).
        games = []
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                try:
                    games = json.loads(line)
                    break
                except Exception:
                    continue
        if not games:
            # Distinguish "no games" from "not logged in / CLI missing".
            raise CmdException(
                "Failed to list Ubisoft games. Is optima-cli installed and are you logged in?")

        print(f"Found {len(games)} Ubisoft games", file=sys.stderr)
        conn = self.get_connection()
        c = conn.cursor()
        for g in games:
            if not g.get('installable', False):
                continue
            pid = str(g.get('product_id', '')).strip()
            name = g.get('name', pid)
            if not pid:
                continue
            c.execute("SELECT 1 FROM Game WHERE ShortName=?", (pid,))
            if c.fetchone() is None:
                vals = [
                    name, "", "", "", "", "", "Optima",
                    pid, "", "", "", "",
                    "", "", "", "", pid,
                ]
                cols = [
                    "Title", "Notes", "ApplicationPath", "ManualPath",
                    "Publisher", "RootFolder", "Source", "DatabaseID",
                    "Genre", "ConfigurationPath", "Developer", "ReleaseDate",
                    "Size", "InstallPath", "UmuId", "SteamClientID", "ShortName"
                ]
                placeholders = ', '.join(['?'] * len(cols))
                c.execute(f"INSERT INTO Game ({', '.join(cols)}) VALUES ({placeholders})", vals)
            else:
                c.execute("UPDATE Game SET Title=? WHERE ShortName=?", (name, pid))
        conn.commit()
        conn.close()

    # ---- install / uninstall ---------------------------------------------

    def download_game(self, product_id, install_dir):
        print(f"Installing Ubisoft product: {product_id}", file=sys.stderr)
        game_path = os.path.join(install_dir, str(product_id))
        os.makedirs(game_path, exist_ok=True)
        cmd = f"{self.optima_cmd} install {product_id} --path \"{game_path}\""
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        print(stderr.decode() + stdout.decode(), file=sys.stderr)
        if process.returncode != 0:
            raise CmdException(f"Failed to install Ubisoft product {product_id}")
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE Game SET RootFolder=?, InstallPath=? WHERE ShortName=?",
                  (game_path, game_path, str(product_id)))
        conn.commit()
        conn.close()

    def download_game_async(self, product_id, install_dir):
        game_path = os.path.join(install_dir, str(product_id))
        os.makedirs(game_path, exist_ok=True)
        cmd = f"{self.optima_cmd} install {product_id} --path \"{game_path}\""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE Game SET RootFolder=?, InstallPath=? WHERE ShortName=?",
                  (game_path, game_path, str(product_id)))
        conn.commit()
        conn.close()
        os.execvp("sh", ["sh", "-c", cmd])

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
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/optima/'))
            print(os.path.join(install_dir, game_id))

    def get_game_size(self, game_id, installed):
        size = ""
        if installed == 'true':
            conn = self.get_connection()
            c = conn.cursor()
            c.row_factory = sqlite3.Row
            c.execute("SELECT Size FROM Game WHERE ShortName=?", (game_id,))
            result = c.fetchone()
            conn.close()
            if result and bool(result['Size']):
                size = f"Size on Disk: {result['Size']}"
        return json.dumps({'Type': 'GameSize', 'Content': {'Size': size}})

    # ---- launch -----------------------------------------------------------

    def get_lauch_options(self, game_id, steam_command, name, offline=False):
        # The Steam shortcut runs optima-launcher.sh NATIVELY (Compatibility=False):
        # the launcher hands the game to `optima-cli launch <product_id>`, which
        # does its OWN umu/Proton work (Uplay R1 shim + prefix). We must NOT let
        # Steam wrap us in a second Proton — Exe=the launcher, Options=the id.
        launcher = os.environ['LAUNCHER']
        script_path = os.path.expanduser(launcher)

        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute("SELECT ApplicationPath, RootFolder, WorkingDir FROM Game WHERE ShortName=?", (game_id,))
        game = c.fetchone()
        conn.close()

        if game and game['RootFolder']:
            root_dir = game['RootFolder']
            working_dir = os.path.join(root_dir, game['WorkingDir']).replace("\\", "/") if game['WorkingDir'] else root_dir
        else:
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/optima/'))
            working_dir = os.path.join(install_dir, game_id) if install_dir else ""

        return json.dumps({
            'Type': 'LaunchOptions',
            'Content': {
                'Exe': f"\"{script_path}\"",
                'Options': f"{game_id}",
                'WorkingDir': f"\"{working_dir}\"" if working_dir else "",
                'Compatibility': False,
                'Name': name
            }
        })

    # ---- login status -----------------------------------------------------

    def get_login_status(self, flush_cache=False):
        cache_key = "optima-login"
        if flush_cache:
            self.clear_cache(cache_key)
        cache = self.get_cache(cache_key)
        if cache is not None:
            return cache

        auth_file = os.path.expanduser('~/.local/share/optima/auth.toml')
        if os.path.exists(auth_file):
            username = "Ubisoft User"
            try:
                output = self.execute_shell(f"{self.optima_cmd} whoami")
                for line in output.split('\n'):
                    m = re.match(r'\s*name:\s*(.+)$', line)
                    if m and m.group(1).strip():
                        username = m.group(1).strip()
                        break
            except Exception as e:
                print(f"whoami failed: {e}", file=sys.stderr)
            value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': username, 'LoggedIn': True}})
        else:
            value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': '', 'LoggedIn': False}})

        timeout = datetime.now() + timedelta(hours=1)
        try:
            self.add_cache(cache_key, value, timeout)
        except Exception as e:
            print(f"Error adding cache: {e}", file=sys.stderr)
        return value

    # ---- account profile form (email / username / password) ---------------

    def _current_profile(self):
        """Read the emu profile (email/username) from `optima-cli profile`.
        Password is never echoed back (masked), so it's left blank in the form."""
        email, username = "", ""
        try:
            output = self.execute_shell(f"{self.optima_cmd} profile")
            for line in output.split('\n'):
                m = re.match(r'\s*email:\s*(.+)$', line)
                if m and not m.group(1).strip().startswith('(unset'):
                    email = m.group(1).strip()
                m = re.match(r'\s*username:\s*(.+)$', line)
                if m and not m.group(1).strip().startswith('(unset'):
                    username = m.group(1).strip()
        except Exception as e:
            print(f"profile read failed: {e}", file=sys.stderr)
        return email, username

    def _profile_schema_path(self):
        runtime = os.environ.get('DECKY_PLUGIN_RUNTIME_DIR', '')
        plugin = os.environ.get('DECKY_PLUGIN_DIR', '')
        for base in (runtime, plugin):
            if base:
                p = os.path.join(base, 'conf_schemas', 'optimaprofile.json')
                if os.path.exists(p):
                    return p
        return os.path.join(plugin, 'conf_schemas', 'optimaprofile.json')

    def get_profile(self):
        """Emit the account form (IniEditor) with current email/username filled in."""
        with open(self._profile_schema_path()) as f:
            schema = json.load(f)
        email, username = self._current_profile()
        for section in schema.get('Sections', []):
            for opt in section.get('Options', []):
                if opt.get('Key') == 'Email':
                    opt['Value'] = email
                    opt['DefaultValue'] = email
                elif opt.get('Key') == 'Username':
                    opt['Value'] = username
                    opt['DefaultValue'] = username
                elif opt.get('Key') == 'Password':
                    opt['Value'] = ""
                    opt['DefaultValue'] = ""
        return json.dumps({'Type': 'IniContent', 'Content': schema})

    def save_profile(self, raw_json):
        """Parse the submitted account form and store it via `optima-cli profile`."""
        try:
            data = json.loads(raw_json)
        except Exception as e:
            return json.dumps({'Type': 'Error', 'Content': {'Message': f'Bad profile JSON: {e}'}})

        vals = {}
        for section in data.get('Sections', []):
            for opt in section.get('Options', []):
                vals[opt.get('Key')] = opt.get('Value', '')

        cmd = [self.optima_cmd, 'profile']
        # Email/username always applied (blank clears them, which is intended if
        # the user cleared the field). Password only applied when non-empty so a
        # blank field doesn't wipe an existing stored password.
        cmd += ['--email', vals.get('Email', '')]
        cmd += ['--username', vals.get('Username', '')]
        if vals.get('Password', ''):
            cmd += ['--password', vals['Password']]
        try:
            env = os.environ.copy()
            env['NO_COLOR'] = '1'
            subprocess.run(cmd, check=True, capture_output=True, env=env)
        except Exception as e:
            return json.dumps({'Type': 'Error', 'Content': {'Message': f'Failed to save profile: {e}'}})
        return json.dumps({'Type': 'Success', 'Content': {'Message': 'Ubisoft account saved'}})

    # ---- install progress -------------------------------------------------

    def get_last_progress_update(self, file_path):
        """Parse optima-cli install output. It prints per-file progress as
        `  [i/N] name` (every 25 files + the last), and ends with
        `Installed <name> to <dir>`."""
        step_re = re.compile(r"\[(\d+)/(\d+)\]")
        last_progress_update = None
        try:
            with open(file_path, "r") as f:
                lines = [self._strip_ansi(l) for l in f.readlines()]

            done = 0
            total = 0
            for line in reversed(lines):
                if m := step_re.search(line):
                    done = int(m.group(1))
                    total = int(m.group(2))
                    break

            is_complete = False
            is_error = False
            error_line = ""
            for line in lines[-8:]:
                ls = line.strip()
                ll = ls.lower()
                if ll.startswith("installed ") and " to " in ll:
                    is_complete = True
                    break
                # ONLY terminal failures. optima-cli retries demux drops itself
                # (`[install] run failed (...); reconnecting demux and resuming`)
                # and resumes — those lines are NOT fatal and must be ignored, or
                # the UI reports "failed" mid-download and the user re-taps (which
                # spawns a racing 2nd install). A real terminal error is anyhow's
                # top-level `Error:` line or the retry-cap message.
                if ll.startswith("[install]"):
                    continue
                if (ll.startswith("error:")
                        or "failed after 30 whole-run retries" in ll
                        or "is not in your owned games" in ll
                        or "no ubisoft cdn build" in ll):
                    is_error = True
                    error_line = ls

            if is_complete:
                last_progress_update = {"Percentage": 100, "Description": "Installation complete"}
            elif is_error:
                last_progress_update = {
                    "Percentage": 0, "Description": "Installation Failed.", "Error": error_line
                }
            elif total > 0:
                percent = min(99, (done / total) * 100.0)
                last_progress_update = {
                    "Percentage": percent,
                    "Description": f"Downloading files {done} / {total} ({percent:.1f}%)"
                }
            else:
                # Manifest signed, files not yet counted (big first files). Show
                # activity rather than the raw last log line (retry chatter).
                last_progress_update = {"Percentage": 0, "Description": "Preparing download…"}
        except Exception as e:
            print("Waiting for progress update", e, file=sys.stderr)
            time.sleep(1)

        return json.dumps({'Type': 'ProgressUpdate', 'Content': last_progress_update})
