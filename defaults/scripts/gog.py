import datetime
import re
import json
import os
import glob
import zipfile
import sqlite3
import sys
import subprocess
import time
import urllib.request
import urllib.error

import GamesDb
from datetime import datetime, timedelta


class CmdException(Exception):
    pass


class GOG(GamesDb.GamesDb):
    def __init__(self, db_file, storeName, setNameConfig=None):
        super().__init__(db_file, storeName=storeName, setNameConfig=setNameConfig)
        self.storeURL = "https://www.gog.com/"

    GOG_CLIENT_ID = '46899977096215655'
    GOG_CLIENT_SECRET = '9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9'

    gogdl_cmd = os.environ.get('GOGDL', '/bin/flatpak run com.github.heroic_games_launcher.heroic-gogdl')
    auth_tokens = os.environ.get('AUTH_TOKENS', os.path.expanduser('~/homebrew/data/GameVault/gog_auth.json'))

    def execute_shell(self, cmd, timeout=120):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  shell=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise CmdException(f"Command timed out after {timeout}s: {cmd}")
        result = stdout.decode()

        if result.strip() == "":
            raise CmdException(f"Command produced no output (try installing dependencies from the About menu): {cmd}")
        return result

    def execute_shell_json(self, cmd):
        result = self.execute_shell(cmd)
        return json.loads(result)

    def _get_auth_token(self):
        """Read access_token from gog_auth.json, refreshing if expired."""
        if not os.path.exists(self.auth_tokens):
            raise CmdException("GOG auth tokens not found. Please log in first.")

        with open(self.auth_tokens, 'r') as f:
            auth_data = json.load(f)

        # gogdl format: {client_id: {access_token, refresh_token, loginTime, expires_in, ...}}
        token_info = None
        for key, val in auth_data.items():
            if isinstance(val, dict) and val.get('access_token'):
                token_info = val
                break

        if not token_info:
            raise CmdException("No valid tokens in auth file. Please log in again.")

        # Check expiry
        login_time = token_info.get('loginTime', 0)
        expires_in = token_info.get('expires_in', 0)
        if login_time and expires_in and (time.time() > login_time + expires_in):
            print("GOG token expired, refreshing...", file=sys.stderr)
            self._refresh_token()
            # Re-read after refresh
            with open(self.auth_tokens, 'r') as f:
                auth_data = json.load(f)
            for key, val in auth_data.items():
                if isinstance(val, dict) and val.get('access_token'):
                    token_info = val
                    break

        return token_info['access_token']

    def _refresh_token(self):
        """Refresh GOG auth tokens using the refresh_token."""
        with open(self.auth_tokens, 'r') as f:
            auth_data = json.load(f)

        token_info = None
        client_key = None
        for key, val in auth_data.items():
            if isinstance(val, dict) and val.get('refresh_token'):
                token_info = val
                client_key = key
                break

        if not token_info:
            raise CmdException("No refresh token found. Please log in again.")

        from urllib.parse import urlencode
        refresh_url = 'https://auth.gog.com/token?' + urlencode({
            'client_id': self.GOG_CLIENT_ID,
            'client_secret': self.GOG_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': token_info['refresh_token'],
        })

        req = urllib.request.Request(refresh_url)
        resp = urllib.request.urlopen(req, timeout=30)
        new_tokens = json.loads(resp.read())

        token_info['access_token'] = new_tokens['access_token']
        token_info['expires_in'] = new_tokens['expires_in']
        token_info['refresh_token'] = new_tokens['refresh_token']
        token_info['token_type'] = new_tokens['token_type']
        token_info['scope'] = new_tokens.get('scope', '')
        token_info['session_id'] = new_tokens.get('session_id', '')
        token_info['user_id'] = new_tokens.get('user_id', token_info.get('user_id', ''))
        token_info['loginTime'] = int(time.time())

        auth_data[client_key] = token_info
        with open(self.auth_tokens, 'w') as f:
            json.dump(auth_data, f, indent=2)

        print("GOG tokens refreshed.", file=sys.stderr)

    def get_list(self, offline=False):
        # Use GOG API to get owned game IDs
        access_token = self._get_auth_token()
        req = urllib.request.Request(
            'https://embed.gog.com/user/data/games',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        owned_ids = [str(gid) for gid in data.get('owned', [])]

        left_overs = self.insert_data(owned_ids)
        print(f"left_overs: {left_overs}", file=sys.stderr)

        # Fetch titles for new games from the public GOG API
        # Only add actual games — skip DLC, packs/bundles, and delisted products (404)
        for game_id in left_overs:
            gamename = ''
            try:
                prod_req = urllib.request.Request(
                    f'https://api.gog.com/products/{game_id}',
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                prod_resp = urllib.request.urlopen(prod_req, timeout=10)
                prod_data = json.loads(prod_resp.read())
                game_type = prod_data.get('game_type', '')
                if game_type != 'game':
                    print(f"Skipping {game_type}: {prod_data.get('title', game_id)}", file=sys.stderr)
                    continue
                gamename = prod_data.get('title', '')
            except urllib.error.HTTPError as e:
                print(f"Skipping {game_id}: HTTP {e.code}", file=sys.stderr)
                continue
            except Exception as e:
                print(f"Could not fetch product {game_id}: {e}", file=sys.stderr)
                continue
            self.proccess_leftovers_simple(game_id, gamename)

    def proccess_leftovers_simple(self, game_id, gamename):
        """Insert a new GOG game into the DB with minimal info (ID + title)."""
        print(f"Processing leftover GOG game: {gamename} ({game_id})", file=sys.stderr)
        conn = self.get_connection()
        c = conn.cursor()

        try:
            shortname = str(game_id)
            c.execute("SELECT id FROM Game WHERE ShortName=?", (shortname,))
            result = c.fetchone()
            if result is None:
                vals = [
                    gamename, "", "", "", "", "", "GOG",
                    game_id, "", "", "", "",
                    "", "", "", "", shortname,
                ]
                cols_with_pk = [
                    "Title", "Notes", "ApplicationPath", "ManualPath",
                    "Publisher", "RootFolder", "Source", "DatabaseID",
                    "Genre", "ConfigurationPath", "Developer", "ReleaseDate",
                    "Size", "InstallPath", "UmuId", "SteamClientID", "ShortName"
                ]
                placeholders = ', '.join(['?' for _ in range(len(cols_with_pk))])
                tmp = f"INSERT INTO Game ({', '.join(cols_with_pk)}) VALUES ({placeholders})"
                c.execute(tmp, vals)
                conn.commit()
        except Exception as e:
            print(f"Error inserting GOG game: {gamename} {e}", file=sys.stderr)

        conn.close()

    @staticmethod
    def detect_game_type(exe_path):
        """Classify game type based on exe path. Returns 'dosbox', 'scummvm', or 'windows'."""
        if not exe_path:
            print(f"[detect_game_type] exe_path is empty/None -> windows", file=sys.stderr)
            return 'windows'
        exe_lower = exe_path.lower()
        if 'dosbox' in exe_lower:
            print(f"[detect_game_type] Found 'dosbox' in {exe_path!r} -> dosbox", file=sys.stderr)
            return 'dosbox'
        if 'scummvm' in exe_lower:
            print(f"[detect_game_type] Found 'scummvm' in {exe_path!r} -> scummvm", file=sys.stderr)
            return 'scummvm'
        print(f"[detect_game_type] No match in {exe_path!r} -> windows", file=sys.stderr)
        return 'windows'

    @staticmethod
    def detect_and_add_scummvm_game(game_path):
        """Detect a ScummVM game, add it to ScummVM's library, return the target ID or None.

        Uses --add to register the game. If already added, falls back to --detect
        to find the game ID, then looks up the target via --list-targets.
        """
        print(f"[ScummVM detect] Starting detection for: {game_path}", file=sys.stderr)
        print(f"[ScummVM detect] Path exists: {os.path.exists(game_path)}, is dir: {os.path.isdir(game_path)}", file=sys.stderr)
        try:
            contents = os.listdir(game_path) if os.path.isdir(game_path) else []
            print(f"[ScummVM detect] Directory contents ({len(contents)} items): {contents[:30]}", file=sys.stderr)
        except Exception as e:
            print(f"[ScummVM detect] Could not list directory: {e}", file=sys.stderr)

        # Check if ScummVM flatpak is installed
        try:
            flatpak_check = subprocess.run(
                ['flatpak', 'list', '--app', '--columns=application'],
                capture_output=True, text=True, timeout=10)
            scummvm_installed = 'org.scummvm.ScummVM' in flatpak_check.stdout
            print(f"[ScummVM detect] ScummVM flatpak installed: {scummvm_installed}", file=sys.stderr)
            if not scummvm_installed:
                print(f"[ScummVM detect] ABORT: ScummVM flatpak not installed", file=sys.stderr)
                return None
        except Exception as e:
            print(f"[ScummVM detect] Could not check flatpak list: {e}", file=sys.stderr)

        # ScummVM CLI commands need a dummy video driver — there's no display
        # when running as a Decky backend service
        cli_env = dict(os.environ, SDL_VIDEODRIVER='dummy')

        try:
            # Try --add first
            add_cmd = ['flatpak', 'run', f'--filesystem={game_path}',
                       'org.scummvm.ScummVM', '--add', f'--path={game_path}']
            print(f"[ScummVM detect] Running --add cmd: {' '.join(add_cmd)}", file=sys.stderr)
            result = subprocess.run(add_cmd, capture_output=True, text=True, timeout=15, env=cli_env)
            print(f"[ScummVM detect] --add returncode: {result.returncode}", file=sys.stderr)
            print(f"[ScummVM detect] --add stdout: {result.stdout.strip()!r}", file=sys.stderr)
            print(f"[ScummVM detect] --add stderr: {result.stderr.strip()!r}", file=sys.stderr)
            output = result.stdout + result.stderr

            # Check for Target: line (new addition)
            for line in result.stdout.splitlines():
                if line.strip().startswith('Target:'):
                    target_id = line.split(':', 1)[1].strip()
                    print(f"[ScummVM detect] SUCCESS: added game, target={target_id}", file=sys.stderr)
                    return target_id

            # If "already been added" — detect the game ID, then find its target
            if 'already been added' in output:
                print(f"[ScummVM detect] Game already added, trying --detect", file=sys.stderr)
                detect_cmd = ['flatpak', 'run', f'--filesystem={game_path}',
                              'org.scummvm.ScummVM', '--detect', f'--path={game_path}']
                print(f"[ScummVM detect] Running --detect cmd: {' '.join(detect_cmd)}", file=sys.stderr)
                detect_result = subprocess.run(detect_cmd, capture_output=True, text=True, timeout=15, env=cli_env)
                print(f"[ScummVM detect] --detect returncode: {detect_result.returncode}", file=sys.stderr)
                print(f"[ScummVM detect] --detect stdout: {detect_result.stdout.strip()!r}", file=sys.stderr)
                print(f"[ScummVM detect] --detect stderr: {detect_result.stderr.strip()!r}", file=sys.stderr)

                # Parse detect output: "stark:tlj  The Longest Journey...  /path"
                game_id = None
                for line in detect_result.stdout.splitlines():
                    line = line.strip()
                    print(f"[ScummVM detect] --detect line: {line!r}", file=sys.stderr)
                    if line and not line.startswith('GameID') and not line.startswith('---'):
                        game_id = line.split()[0]  # e.g. "stark:tlj"
                        print(f"[ScummVM detect] Parsed game_id: {game_id}", file=sys.stderr)
                        break

                if game_id:
                    # Find the target that matches this game ID via --list-targets
                    print(f"[ScummVM detect] Looking up target for game_id={game_id}", file=sys.stderr)
                    targets_cmd = ['flatpak', 'run', 'org.scummvm.ScummVM', '--list-targets']
                    print(f"[ScummVM detect] Running --list-targets cmd: {' '.join(targets_cmd)}", file=sys.stderr)
                    targets_result = subprocess.run(targets_cmd, capture_output=True, text=True, timeout=15, env=cli_env)
                    print(f"[ScummVM detect] --list-targets returncode: {targets_result.returncode}", file=sys.stderr)
                    print(f"[ScummVM detect] --list-targets stdout: {targets_result.stdout.strip()!r}", file=sys.stderr)
                    matched_target = None
                    for line in targets_result.stdout.splitlines():
                        line = line.strip()
                        if line and not line.startswith('Target') and not line.startswith('---'):
                            target_id = line.split()[0]
                            # Match target against detected game_id (e.g. game_id="stark:tlj" matches target containing "tlj")
                            game_short = game_id.split(':')[-1] if ':' in game_id else game_id
                            if game_short in target_id or game_id in target_id:
                                print(f"[ScummVM detect] SUCCESS: matched target={target_id} for game_id={game_id}", file=sys.stderr)
                                return target_id
                            if matched_target is None:
                                matched_target = target_id  # Keep first as fallback
                    if matched_target:
                        print(f"[ScummVM detect] WARNING: no exact match, using first target={matched_target}", file=sys.stderr)
                        return matched_target
                    print(f"[ScummVM detect] FAIL: no matching target found in --list-targets", file=sys.stderr)
                else:
                    print(f"[ScummVM detect] FAIL: --detect returned no game_id", file=sys.stderr)
            else:
                print(f"[ScummVM detect] Not a ScummVM game (no 'already been added' and no Target: line)", file=sys.stderr)

        except subprocess.TimeoutExpired as e:
            print(f"[ScummVM detect] TIMEOUT: {e}", file=sys.stderr)
        except FileNotFoundError:
            print(f"[ScummVM detect] FAIL: 'flatpak' command not found in PATH", file=sys.stderr)
        except Exception as e:
            print(f"[ScummVM detect] FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    def process_info_file(self, file_path):
        """Parse goggame-{id}.info to extract exe path, args, working dir and store in DB."""
        print(f"Processing info file: {file_path}", file=sys.stderr)
        conn = self.get_connection()
        c = conn.cursor()
        install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/gog/'))
        file_path = os.path.realpath(os.path.join(install_dir, file_path))
        print(f"File path: {file_path}", file=sys.stderr)
        with open(file_path, 'r') as f:
            data = json.load(f)
            exe_file = ""
            args = ""
            working_dir = ""

            play_tasks = data.get('playTasks', [])
            if not play_tasks:
                print(f"[process_info] WARNING: No playTasks in info file (DLC or malformed?)", file=sys.stderr)
                conn.close()
                return

            # First pass: grab the primary/game task
            for task in play_tasks:
                if ('category' in task and task['category'] == 'game') or ('isPrimary' in task and task['isPrimary']):
                    exe_file = task.get('path', '')
                    if task.get('arguments'):
                        args = task['arguments']
                    if task.get('workingDir'):
                        working_dir = task['workingDir']
                    break

            game_type = self.detect_game_type(exe_file)
            print(f"[process_info] Primary task exe: {exe_file!r}, detected type: {game_type}", file=sys.stderr)

            # If the primary task isn't DOSBox/ScummVM, scan all tasks —
            # GOG often sets a Windows wrapper as primary while bundling DOSBox
            if game_type == 'windows':
                print(f"[process_info] Primary is windows, scanning {len(play_tasks)} playTasks for emulator tasks", file=sys.stderr)
                for i, task in enumerate(play_tasks):
                    task_path = task.get('path', '')
                    task_type = self.detect_game_type(task_path)
                    print(f"[process_info]   playTask[{i}]: path={task_path!r} type={task_type} category={task.get('category', 'none')} isPrimary={task.get('isPrimary', False)}", file=sys.stderr)
                    if task_type != 'windows':
                        exe_file = task_path
                        args = task.get('arguments', '')
                        working_dir = task.get('workingDir', '')
                        game_type = task_type
                        print(f"[process_info] Found {game_type} task in playTask[{i}]: {exe_file}", file=sys.stderr)
                        break

            root_dir = os.path.abspath(os.path.dirname(file_path))

            # Last resort: if still windows, ask ScummVM if it recognizes the game
            if game_type == 'windows':
                print(f"[process_info] Still windows after playTask scan, trying ScummVM detection on: {root_dir}", file=sys.stderr)
                scummvm_target = self.detect_and_add_scummvm_game(root_dir)
                if scummvm_target:
                    game_type = 'scummvm'
                    args = scummvm_target
                    print(f"[process_info] ScummVM registered target: {scummvm_target}", file=sys.stderr)
                else:
                    print(f"[process_info] ScummVM detection returned None — keeping type=windows", file=sys.stderr)

            print(f"[process_info] Final: exe={exe_file!r} root_dir={root_dir} game_type={game_type} args={args!r} working_dir={working_dir!r}", file=sys.stderr)
            game_id = data.get('gameId')
            if not game_id:
                print(f"[process_info] WARNING: No gameId in info file", file=sys.stderr)
                conn.close()
                return

            print(f"Game id: {game_id}", file=sys.stderr)
            c.execute("update Game set ApplicationPath = ?, RootFolder = ?, Arguments =?, WorkingDir =?, GameType =? where DatabaseID = ?", (exe_file, root_dir, args, working_dir, game_type, game_id))
            conn.commit()

        conn.close()

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
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/gog/'))
            print(os.path.join(install_dir, game_id))

    def get_game_type(self, game_id):
        """Get the GameType for a game from the DB."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT GameType FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result and result[0] else 'windows'

    def retrodetect_game_types(self):
        """Scan installed games and update GameType based on ApplicationPath and goggame info files."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT ShortName, ApplicationPath, RootFolder, DatabaseID FROM Game WHERE ApplicationPath IS NOT NULL AND ApplicationPath != '' AND (GameType IS NULL OR GameType = 'windows')")
        rows = c.fetchall()
        print(f"[retrodetect] Found {len(rows)} games with type=windows or NULL to scan", file=sys.stderr)
        updated = 0
        for row in rows:
            shortname, app_path, root_folder, db_id = row
            game_type = self.detect_game_type(app_path)
            print(f"[retrodetect] {shortname} (db_id={db_id}): app_path={app_path!r} -> {game_type}, root_folder={root_folder!r}", file=sys.stderr)

            # If ApplicationPath isn't DOSBox/ScummVM, scan the goggame info file
            # for non-primary tasks that reference them (e.g. Quake bundles GLQuake as
            # primary but has DOSBox as a secondary task)
            if game_type == 'windows' and root_folder:
                info_file = os.path.join(root_folder, f'goggame-{db_id}.info')
                print(f"[retrodetect] {shortname}: checking info file: {info_file} (exists={os.path.exists(info_file)})", file=sys.stderr)
                if os.path.exists(info_file):
                    try:
                        with open(info_file, 'r') as f:
                            data = json.load(f)
                        tasks = data.get('playTasks', [])
                        print(f"[retrodetect] {shortname}: info file has {len(tasks)} playTasks", file=sys.stderr)
                        for i, task in enumerate(tasks):
                            task_path = task.get('path', '')
                            task_type = self.detect_game_type(task_path)
                            print(f"[retrodetect] {shortname}:   playTask[{i}]: path={task_path!r} type={task_type}", file=sys.stderr)
                            if task_type != 'windows':
                                game_type = task_type
                                new_args = task.get('arguments', '')
                                new_working_dir = task.get('workingDir', '')
                                c.execute("UPDATE Game SET ApplicationPath=?, Arguments=?, WorkingDir=?, GameType=? WHERE ShortName=?",
                                          (task_path, new_args, new_working_dir, game_type, shortname))
                                updated += 1
                                print(f"[retrodetect] {shortname} -> {game_type} (from info file playTask[{i}])", file=sys.stderr)
                                break
                    except Exception as e:
                        print(f"[retrodetect] {shortname}: error reading {info_file}: {e}", file=sys.stderr)

            # Last resort: ask ScummVM if it recognizes the game
            if game_type == 'windows' and root_folder and os.path.isdir(root_folder):
                print(f"[retrodetect] {shortname}: still windows, trying ScummVM detection on {root_folder}", file=sys.stderr)
                scummvm_target = self.detect_and_add_scummvm_game(root_folder)
                if scummvm_target:
                    game_type = 'scummvm'
                    c.execute("UPDATE Game SET Arguments=?, GameType=? WHERE ShortName=?",
                              (scummvm_target, game_type, shortname))
                    updated += 1
                    print(f"[retrodetect] {shortname} -> scummvm (target={scummvm_target})", file=sys.stderr)
                else:
                    print(f"[retrodetect] {shortname}: ScummVM detection returned None", file=sys.stderr)

            if game_type != 'windows':
                c.execute("UPDATE Game SET GameType=? WHERE ShortName=? AND (GameType IS NULL OR GameType = 'windows')", (game_type, shortname))
                if c.rowcount > 0:
                    updated += 1
                    print(f"[retrodetect] {shortname} -> {game_type}", file=sys.stderr)
        conn.commit()
        conn.close()
        print(f"[retrodetect] Done. Updated {updated} games out of {len(rows)} scanned", file=sys.stderr)

    def get_login_status(self, flush_cache=False):
        cache_key = "gog-login"
        if flush_cache:
            self.clear_cache(cache_key)

        cache = self.get_cache(cache_key)
        print(f"cache: {cache}", file=sys.stderr)
        if cache is not None:
            return cache
        print(f"cache miss!", file=sys.stderr)

        # Check if auth tokens file exists and has valid tokens
        if os.path.exists(self.auth_tokens):
            try:
                with open(self.auth_tokens, 'r') as f:
                    auth_data = json.load(f)
                # Auth tokens format: {client_id: {access_token, refresh_token, ...}}
                has_tokens = False
                access_token = None
                if isinstance(auth_data, dict):
                    for key, val in auth_data.items():
                        if isinstance(val, dict) and (val.get('access_token') or val.get('refresh_token')):
                            has_tokens = True
                            access_token = val.get('access_token')
                            break
                if has_tokens:
                    username = 'GOG User'
                    if access_token:
                        try:
                            req = urllib.request.Request(
                                'https://embed.gog.com/userData.json',
                                headers={'Authorization': f'Bearer {access_token}'})
                            resp = urllib.request.urlopen(req, timeout=5)
                            user_data = json.loads(resp.read())
                            username = user_data.get('username', username)
                        except Exception:
                            pass
                    value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': username, 'LoggedIn': True}})
                else:
                    value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': '', 'LoggedIn': False}})
            except Exception:
                value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': '', 'LoggedIn': False}})
        else:
            value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': '', 'LoggedIn': False}})

        timeout = datetime.now() + timedelta(hours=1)
        try:
            self.add_cache(cache_key, value, timeout)
        except Exception as e:
            print(f"Error adding cache: {e}", file=sys.stderr)
        return value

    def has_updates(self, game_id):
        try:
            # Get remote build info
            remote_info = self.execute_shell_json(
                f"{self.gogdl_cmd} --auth-config-path {self.auth_tokens} info {game_id} --os windows")
            remote_build = remote_info.get('buildId', '')

            # Get local build info from goggame-{id}.info
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("SELECT RootFolder FROM Game WHERE ShortName=?", (game_id,))
            result = c.fetchone()
            conn.close()

            if not result or not result[0]:
                return json.dumps({'Type': 'UpdateAvailable', 'Content': False})

            info_file = os.path.join(result[0], f'goggame-{game_id}.info')
            if not os.path.exists(info_file):
                return json.dumps({'Type': 'UpdateAvailable', 'Content': False})

            with open(info_file, 'r') as f:
                local_info = json.load(f)
            local_build = local_info.get('buildId', '')

            has_update = remote_build != local_build and remote_build != '' and local_build != ''
            return json.dumps({'Type': 'UpdateAvailable', 'Content': has_update})
        except Exception as e:
            print(f"Error checking GOG updates for {game_id}: {e}", file=sys.stderr)
            return json.dumps({'Type': 'UpdateAvailable', 'Content': False})

    def get_game_size(self, game_id, installed):
        if installed == 'true':
            conn = self.get_connection()
            c = conn.cursor()
            c.row_factory = sqlite3.Row
            c.execute("SELECT Size FROM Game WHERE ShortName=?", (game_id,))
            result = c.fetchone()
            conn.close()
            if result and bool(result['Size']):
                disk_size = result['Size']
                size = f"Size on Disk: {disk_size}"
            else:
                size = ""
        else:
            try:
                result = self.execute_shell_json(
                    f"{self.gogdl_cmd} --auth-config-path {self.auth_tokens} info {game_id} --os windows")
                # gogdl info returns size as nested dict: {"size": {"*": {"disk_size": N, "download_size": N}, "en-US": {...}}}
                # Sum the "*" (language-independent) entry + selected language entry
                size_data = result.get('size', {})
                lang = os.environ.get('GOG_LANGUAGE', 'en-US')
                disk_size = 0
                download_size = 0
                if isinstance(size_data, dict):
                    for key in ('*', lang):
                        entry = size_data.get(key, {})
                        if isinstance(entry, dict):
                            disk_size += entry.get('disk_size', 0)
                            download_size += entry.get('download_size', 0)
                    # Fallback: if selected language not found, use first non-* entry
                    if disk_size == size_data.get('*', {}).get('disk_size', 0) and len(size_data) > 1:
                        for key, entry in size_data.items():
                            if key != '*' and isinstance(entry, dict):
                                disk_size += entry.get('disk_size', 0)
                                download_size += entry.get('download_size', 0)
                                break
                if disk_size:
                    disk_size_str = f"Install Size: {self.convert_bytes(int(disk_size))}"
                    download_size_str = f"Download Size: {self.convert_bytes(int(download_size))}" if download_size else ""
                    size = disk_size_str + (f" ({download_size_str})" if download_size_str else "")
                else:
                    size = ""
            except Exception as e:
                print(f"GOG get_game_size error for {game_id}: {e}", file=sys.stderr)
                size = ""
        return json.dumps({'Type': 'GameSize', 'Content': {'Size': size}})

    @staticmethod
    def _gogdl_manifest_path(game_id):
        """Path to gogdl/Heroic's cached build manifest for a game (its record of what
        is installed). Same location GOG store.sh uninstall clears."""
        return os.path.join(
            os.path.expanduser('~'),
            '.var/app/com.github.heroic_games_launcher.heroic-gogdl/config/heroic_gogdl/manifests',
            str(game_id))

    def _prune_dlc_from_gogdl_cache(self, game_id, dlc_id):
        """Strip a DLC's depots/product/HGLdlcs entry from gogdl's cached manifest so a
        later reinstall sees the DLC as a fresh delta. gogdl diffs the requested manifest
        against THIS cache (never the disk), so if the cache still lists the removed DLC's
        depots, `download --with-dlcs --dlcs <id>` computes 'Nothing to do' and downloads
        nothing. Pruning here restores the small-delta reinstall path."""
        path = self._gogdl_manifest_path(game_id)
        if not os.path.isfile(path):
            return
        dlc_id = str(dlc_id)
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[remove_dlc] cannot read gogdl cache {path}: {e}", file=sys.stderr)
            return
        changed = False
        for key, id_field in (('depots', 'productId'), ('products', 'productId'), ('HGLdlcs', 'id')):
            lst = data.get(key)
            if isinstance(lst, list):
                pruned = [x for x in lst if str(x.get(id_field)) != dlc_id]
                if len(pruned) != len(lst):
                    data[key] = pruned
                    changed = True
        if changed:
            try:
                with open(path, 'w') as f:
                    json.dump(data, f)
                print(f"[remove_dlc] pruned DLC {dlc_id} from gogdl cache {path}", file=sys.stderr)
            except OSError as e:
                print(f"[remove_dlc] cannot write gogdl cache {path}: {e}", file=sys.stderr)

    def _game_root(self, game_id):
        """Resolve a game's on-disk install folder from the DB (RootFolder, else InstallPath)."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT RootFolder, InstallPath FROM Game WHERE ShortName=?", (game_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        return row[0] or row[1] or None

    def get_dlcs(self, game_id):
        """List a game's DLCs (from gogdl info) plus whether each is installed.
        Installed = a goggame-<dlcid>.info metadata file exists in the game's RootFolder."""
        try:
            info = self.execute_shell_json(
                f"{self.gogdl_cmd} --auth-config-path {self.auth_tokens} info {game_id} --os windows")
        except Exception as e:
            print(f"[get_dlcs] gogdl info failed for {game_id}: {e}", file=sys.stderr)
            return json.dumps({'Type': 'DlcList', 'Content': {'Dlcs': [], 'Error': str(e)}})

        root = self._game_root(game_id)
        lang = os.environ.get('GOG_LANGUAGE', 'en-US')
        out = []
        for dlc in (info.get('dlcs') or []):
            dlc_id = str(dlc.get('id', ''))
            if not dlc_id:
                continue
            title = dlc.get('title') or f"DLC {dlc_id}"
            # size is {lang: {download_size, disk_size}}; prefer selected lang, then '*', then first
            size_bytes = 0
            size_data = dlc.get('size') or {}
            if isinstance(size_data, dict):
                entry = size_data.get(lang) or size_data.get('*')
                if not entry and size_data:
                    entry = next(iter(size_data.values()))
                if isinstance(entry, dict):
                    size_bytes = entry.get('disk_size', 0) or 0
            installed = bool(root and glob.glob(os.path.join(root, f'goggame-{dlc_id}.info')))
            out.append({
                'Id': dlc_id,
                'Title': title,
                'Size': self.convert_bytes(int(size_bytes)) if size_bytes else '',
                'Installed': installed,
            })
        print(f"[get_dlcs] {game_id}: {len(out)} DLC(s), root={root}", file=sys.stderr)
        return json.dumps({'Type': 'DlcList', 'Content': {'Dlcs': out}})

    @staticmethod
    def _hashdb_files(hashdb_path, lenient=False):
        """Extract the file paths recorded in a goggame-*.hashdb.
        The hashdb is a ZIP (PK\\x03\\x04) wrapping a binary manifest. Each file entry
        stores its MD5 as 32 ASCII-hex chars immediately followed by the Windows path
        (e.g. '0007d98a...aac71Mod\\Player\\...\\x.png'), so a printable-ASCII run is
        '<md5><path>'. Strip the leading 32-hex prefix, then keep path-like strings.

        lenient=False (default): only CONCRETE files — a run with a path separator + a
        file extension, or a bare filename + extension. These are the deletion candidates.
        lenient=True: also include extensionless path/name tokens (e.g. Unity content-bin
        files named by hash). Used to build the 'keep' set of base + other-DLC files; a
        false positive here only PREVENTS a deletion, which is the safe direction."""
        files = set()
        if not os.path.isfile(hashdb_path):
            return files
        blob = b''
        try:
            with zipfile.ZipFile(hashdb_path) as z:
                for name in z.namelist():
                    blob += z.read(name)
        except (zipfile.BadZipFile, OSError) as e:
            print(f"[_hashdb_files] {hashdb_path}: {e}", file=sys.stderr)
            return files
        hex32_re = re.compile(r'^[0-9a-fA-F]{32}')
        ext_re = re.compile(r'\.[A-Za-z0-9]{1,5}$')
        name_re = re.compile(r'^[\w .\-()]+$')
        for m in re.finditer(rb'[ -~]{4,}', blob):
            s = m.group().decode('ascii', 'ignore').strip()
            # Strip a leading MD5 (32 hex) if a real path/filename follows it.
            if hex32_re.match(s) and len(s) > 32:
                rest = s[32:]
                if '\\' in rest or '/' in rest or name_re.match(rest):
                    s = rest
            has_sep = ('\\' in s or '/' in s)
            if has_sep and ext_re.search(s):
                files.add(s)
            elif (not has_sep) and name_re.match(s) and ext_re.search(s):
                files.add(s)
            elif lenient and (has_sep or name_re.match(s)):
                files.add(s)
        return files

    def remove_dlc(self, game_id, dlc_id):
        """Remove an installed DLC's files without touching the base game or other DLCs.
        File list comes from goggame-<dlcid>.hashdb; a file is deleted only if it is NOT
        also referenced by the base game or any OTHER installed DLC hashdb. Then the
        goggame-<dlcid>.* metadata is removed and now-empty dirs are pruned."""
        game_id = str(game_id)
        dlc_id = str(dlc_id)
        root = self._game_root(game_id)
        if not root or not os.path.isdir(root):
            return json.dumps({'Type': 'Error', 'Content': {'Message': f'Game folder not found for {game_id}'}})

        def norm(p):
            return p.replace('\\', '/').lstrip('/').lower()

        dlc_hashdb = os.path.join(root, f'goggame-{dlc_id}.hashdb')
        dlc_files = self._hashdb_files(dlc_hashdb)
        print(f"[remove_dlc] {game_id}/{dlc_id}: {len(dlc_files)} files from {dlc_hashdb}", file=sys.stderr)

        # Paths owned by the base game + every OTHER DLC — these must be preserved.
        # Use the LENIENT scan so extensionless base files (Unity content bins) are
        # captured; over-inclusion here only protects files, never deletes them.
        keep = set()
        for hp in glob.glob(os.path.join(root, 'goggame-*.hashdb')):
            if os.path.basename(hp) == f'goggame-{dlc_id}.hashdb':
                continue
            keep |= self._hashdb_files(hp, lenient=True)
        keep_norm = {norm(x) for x in keep}

        removed = 0
        for rel in dlc_files:
            if norm(rel) in keep_norm:
                continue
            parts = rel.replace('\\', '/').lstrip('/').split('/')
            target = self._find_case_insensitive(os.path.join(root, *parts))
            if os.path.isfile(target):
                try:
                    os.remove(target)
                    removed += 1
                except OSError as e:
                    print(f"[remove_dlc] could not remove {target}: {e}", file=sys.stderr)

        # Drop the DLC metadata files (info / hashdb / id / script).
        for meta in glob.glob(os.path.join(root, f'goggame-{dlc_id}.*')):
            try:
                os.remove(meta)
            except OSError:
                pass

        # Prune now-empty directories bottom-up (never the game root itself).
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            if os.path.realpath(dirpath) == os.path.realpath(root):
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                pass

        # Keep gogdl's manifest cache honest so a later reinstall re-downloads the DLC
        # (otherwise gogdl diffs against a cache that still claims the DLC is present).
        self._prune_dlc_from_gogdl_cache(game_id, dlc_id)

        print(f"[remove_dlc] {game_id}/{dlc_id}: removed {removed} file(s)", file=sys.stderr)
        return json.dumps({'Type': 'Success', 'Content': {
            'Title': 'DLC Removed', 'Message': f'Removed DLC ({removed} files)'}})

    @staticmethod
    def _find_case_insensitive(path):
        """Find a file by path using case-insensitive matching on each component.
        Returns the actual on-disk path, or the original path if not found."""
        if os.path.exists(path):
            return path
        # Walk from root, matching each path component case-insensitively
        parts = os.path.normpath(path).split(os.sep)
        # Start from root or first component
        if parts[0] == '':
            current = os.sep
            parts = parts[1:]
        else:
            current = parts[0]
            parts = parts[1:]
        for part in parts:
            candidate = os.path.join(current, part)
            if os.path.exists(candidate):
                current = candidate
                continue
            # Case-insensitive search in parent directory
            try:
                entries = os.listdir(current)
                matched = False
                for entry in entries:
                    if entry.lower() == part.lower():
                        current = os.path.join(current, entry)
                        matched = True
                        break
                if not matched:
                    print(f"[dosbox_args] Case-insensitive lookup failed: no match for {part!r} in {current}", file=sys.stderr)
                    return path  # Give up, return original
            except Exception as e:
                print(f"[dosbox_args] Case-insensitive lookup error in {current}: {e}", file=sys.stderr)
                return path
        return current

    @staticmethod
    def _resolve_dosbox_args(raw_args, root_dir, working_dir_rel):
        """Resolve DOSBox -conf relative paths to absolute.

        Strips Windows-only flags (-noconsole, -c "exit") that break native DOSBox Staging.
        The GOG autoexec's relative paths (mount c "..", imgmount d "..\\game.cue") work
        because WorkingDir is set to the DOSBOX subfolder.
        Uses case-insensitive file lookup since GOG games come from Windows.
        """
        print(f"[dosbox_args] Input: raw_args={raw_args!r} root_dir={root_dir!r} working_dir_rel={working_dir_rel!r}", file=sys.stderr)
        if working_dir_rel:
            base_dir = os.path.join(root_dir, working_dir_rel).replace("\\", "/")
        else:
            base_dir = root_dir
        print(f"[dosbox_args] base_dir={base_dir}", file=sys.stderr)

        resolved = []
        remaining = raw_args
        # Match -conf with double-quoted, single-quoted, or unquoted paths
        conf_pattern = re.compile(r'-conf\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))')
        while True:
            match = conf_pattern.search(remaining)
            if not match:
                break
            conf_rel = (match.group(1) or match.group(2) or match.group(3)).replace("\\", "/")
            conf_abs = os.path.normpath(os.path.join(base_dir, conf_rel))
            if not os.path.exists(conf_abs):
                conf_abs_ci = GOG._find_case_insensitive(conf_abs)
                print(f"[dosbox_args] Resolved conf: {conf_rel!r} -> {conf_abs} (exists=False), case-insensitive -> {conf_abs_ci} (exists={os.path.exists(conf_abs_ci)})", file=sys.stderr)
                conf_abs = conf_abs_ci
            else:
                print(f"[dosbox_args] Resolved conf: {conf_rel!r} -> {conf_abs} (exists=True)", file=sys.stderr)
            resolved.append(f'-conf "{conf_abs}"')
            remaining = remaining[match.end():]

        result = ' '.join(resolved)
        if not resolved:
            print(f"[dosbox_args] WARNING: No -conf flags found in raw_args={raw_args!r}", file=sys.stderr)
            # Fallback: scan game directory for .conf files
            if os.path.isdir(base_dir):
                confs = [f for f in os.listdir(base_dir) if f.lower().endswith('.conf') and 'dosbox' in f.lower()]
                if confs:
                    result = ' '.join(f'-conf "{os.path.join(base_dir, c)}"' for c in sorted(confs))
                    print(f"[dosbox_args] Fallback: found conf files in {base_dir}: {confs} -> {result}", file=sys.stderr)
        print(f"[dosbox_args] Final resolved args: {result!r}", file=sys.stderr)
        return result

    @staticmethod
    def _resolve_scummvm_args(raw_args, root_dir):
        """Build ScummVM launch args. Handles both GOG-bundled (-c ini) and detected (target ID)."""
        if '-c ' in raw_args:
            # GOG-bundled ScummVM: -c scummvm.ini game-id
            resolved = []
            ini_match = re.search(r'-c\s+"?([^"\s]+)"?', raw_args)
            if ini_match:
                ini_rel = ini_match.group(1).replace("\\", "/")
                ini_abs = os.path.normpath(os.path.join(root_dir, ini_rel))
                if os.path.exists(ini_abs):
                    resolved.append(f'-c "{ini_abs}"')
            # Game ID is the last non-flag argument
            game_id_match = re.search(r'(?:^|\s)([a-z][a-z0-9_:-]+)\s*$', raw_args)
            if game_id_match:
                resolved.append(game_id_match.group(1))
            return ' '.join(resolved)
        else:
            # ScummVM target ID from --add (e.g. tlj-win) — game is already registered
            return raw_args.strip()

    def get_lauch_options(self, game_id, steam_command, name, offline=False):
        launcher = os.environ['LAUNCHER']
        script_path = os.path.expanduser(launcher)

        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute("SELECT ApplicationPath, RootFolder, WorkingDir, GameType, Arguments FROM Game WHERE ShortName=?", (game_id,))
        game = c.fetchone()
        conn.close()

        print(f"[launch] game_id={game_id} name={name!r}", file=sys.stderr)
        if game:
            print(f"[launch] DB row: ApplicationPath={game['ApplicationPath']!r} RootFolder={game['RootFolder']!r} WorkingDir={game['WorkingDir']!r} GameType={game['GameType']!r} Arguments={game['Arguments']!r}", file=sys.stderr)
        else:
            print(f"[launch] WARNING: No DB row found for game_id={game_id}", file=sys.stderr)

        if game and game['RootFolder'] and game['ApplicationPath']:
            root_dir = game['RootFolder']
            working_dir = os.path.join(root_dir, game['WorkingDir']).replace("\\", "/") if game['WorkingDir'] else root_dir
            game_exe = os.path.join(root_dir, game['ApplicationPath']).replace("\\", "/")
        else:
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/gog/'))
            game_exe = ""
            working_dir = os.path.join(install_dir, game_id) if install_dir else ""

        game_type = game['GameType'] if game and game['GameType'] else 'windows'
        raw_args = game['Arguments'] if game and game['Arguments'] else ''
        print(f"[launch] Resolved: game_type={game_type} raw_args={raw_args!r}", file=sys.stderr)

        # DOSBox and ScummVM games launch natively — no Proton needed
        # Use "flatpak run --filesystem=<path>" so the sandbox can access game files
        # (SteamOS is immutable, so system-level overrides don't work)
        if game_type in ('dosbox', 'scummvm'):
            flatpak_ids = {
                'dosbox': 'io.github.dosbox-staging',
                'scummvm': 'org.scummvm.ScummVM',
            }
            flatpak_id = flatpak_ids[game_type]
            print(f"[launch] Native {game_type} launch via flatpak: {flatpak_id}", file=sys.stderr)

            if game_type == 'dosbox':
                working_dir_rel = game['WorkingDir'] if game and game['WorkingDir'] else ''
                print(f"[launch][dosbox] working_dir_rel={working_dir_rel!r} root_dir={root_dir!r}", file=sys.stderr)
                # Case-insensitive working dir lookup (goggame says "DOSBOX" but folder may be "DOSBox")
                if working_dir_rel:
                    candidate = os.path.join(root_dir, working_dir_rel)
                    print(f"[launch][dosbox] Checking working dir candidate: {candidate} (exists={os.path.isdir(candidate)})", file=sys.stderr)
                    if not os.path.isdir(candidate):
                        # Try case-insensitive match
                        try:
                            entries = os.listdir(root_dir)
                            print(f"[launch][dosbox] Case-insensitive search in {root_dir}: looking for {working_dir_rel!r} among {entries}", file=sys.stderr)
                            for entry in entries:
                                if entry.lower() == working_dir_rel.lower() and os.path.isdir(os.path.join(root_dir, entry)):
                                    print(f"[launch][dosbox] Case-insensitive match: {working_dir_rel!r} -> {entry!r}", file=sys.stderr)
                                    working_dir_rel = entry
                                    break
                        except Exception as e:
                            print(f"[launch][dosbox] Case-insensitive search failed: {e}", file=sys.stderr)
                    native_working_dir = os.path.join(root_dir, working_dir_rel).replace("\\", "/")
                else:
                    native_working_dir = root_dir
                print(f"[launch][dosbox] native_working_dir={native_working_dir}", file=sys.stderr)
                resolved_args = self._resolve_dosbox_args(raw_args, root_dir, working_dir_rel)
                print(f"[launch][dosbox] resolved_args={resolved_args!r} (from raw_args={raw_args!r})", file=sys.stderr)

            else:
                resolved_args = self._resolve_scummvm_args(raw_args, root_dir)
                native_working_dir = root_dir
                print(f"[launch][scummvm] resolved_args={resolved_args!r} native_working_dir={native_working_dir}", file=sys.stderr)

            # Exe = flatpak, Options = run --filesystem=<game_dir> <app_id> <game_args>
            options = f"run --filesystem=\"{root_dir}\" {flatpak_id} {resolved_args}"

            launch_result = {
                'Type': 'LaunchOptions',
                'Content': {
                    'Exe': '"/usr/bin/flatpak"',
                    'Options': options,
                    'WorkingDir': f"\"{native_working_dir}\"",
                    'Compatibility': False,
                    'Name': name
                }
            }
            print(f"[launch] Returning native launch: {json.dumps(launch_result)}", file=sys.stderr)

            return json.dumps(launch_result)

        return json.dumps(
            {
                'Type': 'LaunchOptions',
                'Content':
                {
                    'Exe': f"\"{game_exe}\"" if game_exe else "\"\"",
                    'Options': f"{script_path} {game_id}%command%",
                    'WorkingDir': f"\"{working_dir}\"" if working_dir else "",
                    'Compatibility': True,
                    'Name': name
                }
            })

    def update_game_details(self, game_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        if result is not None:
            try:
                info = self.execute_shell_json(
                    f"{self.gogdl_cmd} --auth-config-path {self.auth_tokens} info {game_id} --os windows")
                title = info.get('title', '')
                disk_size = info.get('disk_size', info.get('size', 0))
                install_path = info.get('install_path', info.get('folder_name', ''))
                size = self.convert_bytes(int(disk_size)) if disk_size else None
                if title:
                    c.execute(
                        "UPDATE Game SET Title=?, Size=?, InstallPath=? WHERE ShortName=?",
                        (title, size, install_path, game_id))
                conn.commit()
            except Exception as e:
                print(f"Error updating GOG game details: {e}", file=sys.stderr)
        conn.close()

    def get_client_id(self, game_id):
        """Get the Galaxy clientId for a game from the GOG builds API manifest.

        This is the same approach gogdl uses internally (saves.py get_auth_ids).
        """
        try:
            builds_url = f"https://content-system.gog.com/products/{game_id}/os/windows/builds?generation=2"
            req = urllib.request.Request(builds_url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=10)
            builds = json.loads(response.read())

            meta_url = builds['items'][0]['link']
            req = urllib.request.Request(meta_url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=10)
            import zlib
            data = zlib.decompress(response.read())
            meta = json.loads(data)
            return meta.get('clientId')
        except Exception as e:
            print(f"Error getting clientId from builds API: {e}", file=sys.stderr)
            return None

    def get_save_paths(self, game_id):
        """Query GOG remote config API for cloud save locations, resolve against Steam prefix."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT SteamClientID, RootFolder FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        conn.close()

        if not result or not result[0]:
            return []

        steam_client_id = result[0]
        root_folder = result[1] or ''
        prefix = os.path.expanduser(
            f"~/.local/share/Steam/steamapps/compatdata/{steam_client_id}/pfx")

        # Try goggame-{id}.info first (fast, local), then builds API (network)
        client_id = None
        info_file = os.path.join(root_folder, f'goggame-{game_id}.info')
        if os.path.exists(info_file):
            try:
                with open(info_file) as f:
                    info = json.load(f)
                    client_id = info.get('clientId')
            except Exception as e:
                print(f"Error reading info file: {e}", file=sys.stderr)

        if not client_id:
            client_id = self.get_client_id(game_id)

        if not client_id:
            print(f"Could not determine clientId for game {game_id}", file=sys.stderr)
            return []

        # Query GOG remote config for save locations
        try:
            url = f"https://remote-config.gog.com/components/galaxy_client/clients/{client_id}?component_version=2.0.45"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=10)
            config = json.loads(response.read())
        except Exception as e:
            print(f"Error querying GOG remote config: {e}", file=sys.stderr)
            return []

        # API returns 'Windows' (capital W)
        saves_info = config.get('content', {}).get('Windows', {}).get('cloudStorage', {})
        locations = saves_info.get('locations', [])

        if not locations:
            print(f"No cloud save locations for game {game_id}", file=sys.stderr)
            return []

        # Map GOG folder variables to paths inside the Steam prefix
        folder_map = {
            'INSTALL': root_folder,
            'APPLICATION_DATA_LOCAL': os.path.join(prefix, 'drive_c/users/steamuser/AppData/Local'),
            'APPLICATION_DATA_LOCAL_LOW': os.path.join(prefix, 'drive_c/users/steamuser/AppData/LocalLow'),
            'APPLICATION_DATA_ROAMING': os.path.join(prefix, 'drive_c/users/steamuser/AppData/Roaming'),
            'SAVED_GAMES': os.path.join(prefix, 'drive_c/users/steamuser/Saved Games'),
            'DOCUMENTS': os.path.join(prefix, 'drive_c/users/steamuser/Documents'),
        }

        resolved = []
        for loc in locations:
            # API uses 'location' field with <?VAR?> syntax
            path_template = loc.get('location', loc.get('path', ''))
            name = loc.get('name', '__default')

            # Replace <?VAR_NAME?> folder variable placeholders
            resolved_path = path_template
            for var_name, var_path in folder_map.items():
                placeholder = f'<?{var_name}?>'
                if placeholder in resolved_path:
                    resolved_path = resolved_path.replace(placeholder, var_path)
                    break
                # Also handle bare variable prefix (no <? ?> wrapper)
                if resolved_path.startswith(var_name):
                    resolved_path = resolved_path.replace(var_name, var_path, 1)
                    break

            # Convert backslashes to forward slashes
            resolved_path = resolved_path.replace('\\', '/')
            resolved.append({'name': name, 'path': resolved_path})

        return resolved

    def sync_saves(self, game_id, skip_upload=False, skip_download=False):
        """Orchestrate gogdl save-sync for each save location."""
        import shlex
        locations = self.get_save_paths(game_id)
        if not locations:
            print(f"No save locations found for game {game_id}", file=sys.stderr)
            return

        for loc in locations:
            cmd = (f'{self.gogdl_cmd} --auth-config-path {shlex.quote(self.auth_tokens)} save-sync '
                   f'{shlex.quote(loc["path"])} {shlex.quote(str(game_id))} --os windows --ts 0 --name {shlex.quote(loc["name"])}')
            if skip_upload:
                cmd += ' --skip-upload'
            if skip_download:
                cmd += ' --skip-download'
            print(f"Running save sync: {cmd}", file=sys.stderr)
            subprocess.run(cmd, shell=True)

    # Actual gogdl progress format (multiline):
    # = Progress: 45.67 500/1200, Running for: 00:15:30, ETA: 00:20:00
    # [PROGRESS] INFO: = Downloaded: 450.50 MiB, Written: 450.50 MiB
    # + Download - 45.50 MiB/s (raw: ...)

    def toggle_autosync(self, game_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT CloudSaveAutoSync FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        current = result[0] if result and result[0] else 0
        new_val = 0 if current else 1
        c.execute("UPDATE Game SET CloudSaveAutoSync=? WHERE ShortName=?", (new_val, game_id))
        conn.commit()
        conn.close()
        state = "enabled" if new_val else "disabled"
        return json.dumps({'Type': 'Success', 'Content': {'Message': f'Cloud save auto-sync {state}'}})

    def get_autosync_enabled(self, game_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT CloudSaveAutoSync FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        conn.close()
        return '1' if result and result[0] else '0'

    def get_last_progress_update(self, file_path):
        progress_re = re.compile(
            r"= Progress: (\d+\.\d+) (\d+)/(\d+), Running for: (\d+:\d+:\d+), ETA: (\d+:\d+:\d+)\n\[PROGRESS\] INFO: = Downloaded: (\d+\.\d+) MiB, Written: (\d+\.\d+) MiB")
        speed_re = re.compile(r"\+ Download.*- (\d+\.\d+) (.*/s) \(raw")
        last_progress_update = None

        try:
            with open(file_path, "r") as f:
                lines = f.readlines()

                for i in range(len(lines) - 5):
                    if match := progress_re.search(''.join(lines[i: i + 6])):
                        downloaded = round(float(match.group(2)), 2)
                        total_dl_size = round(float(match.group(3)), 2)
                        speed = "0.0"
                        if match2 := speed_re.search(''.join(lines[i: i + 6])):
                            speed = f"{round(float(match2.group(1)), 2)} {match2.group(2)}"

                        percent = round(float(match.group(1)), 0)
                        if percent == 100:
                            percent = 99
                        if match.group(2) == match.group(3):
                            percent = 100
                        last_progress_update = {
                            "Percentage": percent,
                            "Description": f"Downloaded {self.convert_bytes(downloaded)}/{self.convert_bytes(total_dl_size)} ({percent}%)\nSpeed: {speed}"
                        }

                if lines:
                    if lines[-1].strip().startswith("[PROGRESS] INFO: Finished installation process"):
                        last_progress_update = {
                            "Percentage": 100,
                            "Description": "Finished installation process"
                        }
                    if lines[-1].strip().endswith("INFO: Nothing to do"):
                        last_progress_update = {
                            "Percentage": 100,
                            "Description": "Nothing to do. Exiting..."
                        }
                    if any(line.strip().endswith("INFO: All files look good") for line in lines[-2:]):
                        last_progress_update = {
                            "Percentage": 100,
                            "Description": "Verification finished successfully."
                        }
                    if any(line.strip().endswith("Unable to proceed. Not enough disk space") for line in lines[-2:]):
                        try:
                            with open(file_path.replace(".progress", ".output"), "r") as f:
                                content = f.readlines()
                            content = '<br />'.join(content)
                        except Exception:
                            content = "Installation Failed. Reason unknown, check logs for details."
                        last_progress_update = {
                            "Percentage": 0,
                            "Description": "Installation Failed.",
                            "Error": content
                        }

                    # gogdl's progress-bar worker can crash with "ValueError: Queue
                    # ... is closed" the instant a download finishes (a race between
                    # closing the write queue and the bar's final .get()). The game
                    # files are fully written by then, but the traceback replaces the
                    # final "Finished"/"All files look good" line, so otherwise the
                    # frontend never sees 100% and the install hangs at 99% (finalize
                    # never runs -> no shortcut). Treat the crash signature as done so
                    # GOG_install's finalize proceeds; that step is gated on the
                    # goggame-*.info file, which only exists on a completed download,
                    # so a genuinely-incomplete download still can't produce a bad row.
                    joined = ''.join(lines)
                    crash_finish = "progressbar.py" in joined and "is closed" in joined
                    if crash_finish and not (last_progress_update and last_progress_update.get("Error")):
                        last_progress_update = {
                            "Percentage": 100,
                            "Description": "Download complete (finalizing)."
                        }

                    if last_progress_update is None:
                        last_progress_update = {
                            "Percentage": 0,
                            "Description": lines[-1].strip()
                        }
        except Exception as e:
            print("Waiting for progress update", e, file=sys.stderr)
            time.sleep(1)

        return json.dumps({'Type': 'ProgressUpdate', 'Content': last_progress_update})
