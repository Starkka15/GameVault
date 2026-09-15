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


class Amazon(GamesDb.GamesDb):
    def __init__(self, db_file, storeName, setNameConfig=None):
        super().__init__(db_file, storeName=storeName, setNameConfig=setNameConfig)
        self.storeURL = "https://gaming.amazon.com/"

    nile_cmd = os.path.expanduser(os.environ.get('NILE', '~/.local/bin/nile'))
    nile_config_dir = os.path.expanduser('~/.config/nile')

    def execute_shell(self, cmd):
        result = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  shell=True).communicate()[0].decode()

        if result.strip() == "":
            raise CmdException(f"Command produced no output (try installing dependencies from the About menu): {cmd}")
        return result

    def execute_shell_json(self, cmd):
        result = self.execute_shell(cmd)
        return json.loads(result)

    def get_list(self, offline=False):
        # Sync library first
        try:
            self.execute_shell(f"{self.nile_cmd} library sync")
        except CmdException:
            pass  # sync may fail offline, continue with cached data

        # Read from nile's library.json (synced above)
        library_path = os.path.join(self.nile_config_dir, 'library.json')
        if not os.path.exists(library_path):
            raise CmdException("Library not found. Try installing dependencies and logging in first.")

        with open(library_path, 'r') as f:
            games_list = json.load(f)

        id_list = []
        game_dict = {}
        for game in games_list:
            # Nile library.json uses nested product.id as the real game ID
            product = game.get('product', {})
            game_id = str(product.get('id', game.get('id', '')))
            if game_id:
                id_list.append(game_id)
                game_dict[game_id] = game

        left_overs = self.insert_data(id_list)
        print(f"left_overs: {left_overs}", file=sys.stderr)
        for game_id in left_overs:
            if game_id in game_dict:
                self.proccess_leftovers(game_dict[game_id])

    def proccess_leftovers(self, game):
        product = game.get('product', {})
        details = product.get('productDetail', {}).get('details', {})
        title = product.get('title', game.get('title', 'Unknown'))
        print(f"Processing leftover Amazon game: {title}", file=sys.stderr)
        conn = self.get_connection()
        c = conn.cursor()

        try:
            game_id = str(product.get('id', game.get('id', '')))
            shortname = game_id

            c.execute("SELECT * FROM Game WHERE ShortName=?", (shortname,))
            result = c.fetchone()
            if result is None:
                notes = details.get('shortDescription', '')
                publisher = details.get('publisher', '')
                developer = details.get('developer', '')
                release_date = details.get('releaseDate', '')
                icon_url = product.get('productDetail', {}).get('iconUrl', '')

                vals = [
                    title, notes, "", "", publisher, "", "Amazon",
                    game_id, "", "", developer, release_date,
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

                game_id_db = c.lastrowid
                if icon_url:
                    c.execute(
                        "INSERT INTO Images (GameID, ImagePath, FileName, SortOrder, Type) VALUES (?, ?, ?, ?, ?)",
                        (game_id_db, icon_url, '', 0, 'vertical_cover'))
                conn.commit()
        except Exception as e:
            print(f"Error parsing metadata for Amazon game: {title} {e}", file=sys.stderr)

        conn.close()

    def process_fuel_json(self, game_id):
        """Parse fuel.json from installed game to extract exe path and store in DB."""
        print(f"Processing fuel.json for Amazon game: {game_id}", file=sys.stderr)

        # Find the game's install path from nile's installed.json
        install_path = None
        installed_json = os.path.join(self.nile_config_dir, 'installed.json')
        if os.path.exists(installed_json):
            try:
                with open(installed_json, 'r') as f:
                    installed = json.load(f)
                for game in installed:
                    if str(game.get('id', '')) == str(game_id):
                        install_path = game.get('path', '')
                        break
            except Exception as e:
                print(f"Error reading installed.json: {e}", file=sys.stderr)

        # Fallback: search INSTALL_DIR
        if not install_path:
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/amazon/'))
            # Try to find fuel.json in subdirectories
            for entry in os.listdir(install_dir):
                candidate = os.path.join(install_dir, entry)
                if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, 'fuel.json')):
                    install_path = candidate
                    break

        if not install_path:
            print(f"Could not find install path for {game_id}", file=sys.stderr)
            return

        fuel_path = os.path.join(install_path, 'fuel.json')
        if not os.path.exists(fuel_path):
            print(f"No fuel.json found at {fuel_path}", file=sys.stderr)
            # Still update RootFolder so launch options have the install dir
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("UPDATE Game SET RootFolder=?, InstallPath=? WHERE ShortName=?",
                      (install_path, install_path, game_id))
            conn.commit()
            conn.close()
            return

        try:
            with open(fuel_path, 'r') as f:
                fuel = json.load(f)

            main = fuel.get('Main', {})
            exe_file = main.get('Command', '')
            args = ' '.join(main.get('Args', []))

            print(f"Exe file: {exe_file}", file=sys.stderr)
            print(f"Install path: {install_path}", file=sys.stderr)

            conn = self.get_connection()
            c = conn.cursor()
            c.execute("UPDATE Game SET ApplicationPath=?, RootFolder=?, Arguments=?, InstallPath=? WHERE ShortName=?",
                      (exe_file, install_path, args, install_path, game_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error parsing fuel.json for {game_id}: {e}", file=sys.stderr)

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
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/amazon/'))
            print(os.path.join(install_dir, game_id))

    def get_login_status(self, flush_cache=False):
        cache_key = "amazon-login"
        if flush_cache:
            self.clear_cache(cache_key)

        cache = self.get_cache(cache_key)
        print(f"cache: {cache}", file=sys.stderr)
        if cache is not None:
            return cache
        print(f"cache miss!", file=sys.stderr)

        # Ask nile directly — authoritative and version-proof. nile prints
        # {"Username": "...", "LoggedIn": true|false} to stdout. (The old code
        # checked for ~/.config/nile/user.json, but nile now stores its session in
        # current_user.json + an encrypted device file, so that path never existed
        # on current nile and login always looked "logged out".) SteamOS injects
        # LD_PRELOAD warnings, so parse line-by-line rather than the whole output.
        logged_in = False
        username = ''
        try:
            output = self.execute_shell(f"{self.nile_cmd} auth --status")
        except Exception as e:
            print(f"[login_status] nile auth --status failed: {e}", file=sys.stderr)
            output = ''
        for line in output.splitlines():
            line = line.strip()
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict) and 'LoggedIn' in data:
                logged_in = bool(data.get('LoggedIn'))
                if logged_in:
                    username = data.get('Username', '') or ''
                break
        value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': username, 'LoggedIn': logged_in}})

        timeout = datetime.now() + timedelta(hours=1)
        try:
            self.add_cache(cache_key, value, timeout)
        except Exception as e:
            print(f"Error adding cache: {e}", file=sys.stderr)
        return value

    def has_updates(self, game_id):
        try:
            # Sync library to get latest versions
            try:
                self.execute_shell(f"{self.nile_cmd} library sync")
            except CmdException:
                pass

            installed_json = os.path.join(self.nile_config_dir, 'installed.json')
            library_json = os.path.join(self.nile_config_dir, 'library.json')

            if not os.path.exists(installed_json) or not os.path.exists(library_json):
                return json.dumps({'Type': 'UpdateAvailable', 'Content': False})

            with open(installed_json, 'r') as f:
                installed = json.load(f)
            with open(library_json, 'r') as f:
                library = json.load(f)

            # Find installed version
            local_version = None
            for game in installed:
                if str(game.get('id', '')) == str(game_id):
                    local_version = game.get('version', '')
                    break

            if not local_version:
                return json.dumps({'Type': 'UpdateAvailable', 'Content': False})

            # Find remote version
            remote_version = None
            for game in library:
                product = game.get('product', {})
                if str(product.get('id', game.get('id', ''))) == str(game_id):
                    remote_version = product.get('version', game.get('version', ''))
                    break

            if not remote_version:
                return json.dumps({'Type': 'UpdateAvailable', 'Content': False})

            has_update = local_version != remote_version
            return json.dumps({'Type': 'UpdateAvailable', 'Content': has_update})
        except Exception as e:
            print(f"Error checking Amazon updates for {game_id}: {e}", file=sys.stderr)
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
                result = self.execute_shell_json(f"{self.nile_cmd} install --info --json {game_id}")
                download_size = result.get('download_size', result.get('size', 0))
                if download_size:
                    size = f"Download Size: {self.convert_bytes(int(download_size))}"
                else:
                    size = ""
            except Exception:
                size = ""
        return json.dumps({'Type': 'GameSize', 'Content': {'Size': size}})

    def get_lauch_options(self, game_id, steam_command, name, offline=False):
        launcher = os.environ['LAUNCHER']
        script_path = os.path.expanduser(launcher)

        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute("SELECT ApplicationPath, RootFolder, WorkingDir FROM Game WHERE ShortName=?", (game_id,))
        game = c.fetchone()
        conn.close()

        if game and game['RootFolder'] and game['ApplicationPath']:
            root_dir = game['RootFolder']
            working_dir = os.path.join(root_dir, game['WorkingDir']).replace("\\", "/") if game['WorkingDir'] else root_dir
            game_exe = os.path.join(root_dir, game['ApplicationPath']).replace("\\", "/")
        else:
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/amazon/'))
            game_exe = ""
            working_dir = os.path.join(install_dir, game_id) if install_dir else ""

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
                info = self.execute_shell_json(f"{self.nile_cmd} install --info --json {game_id}")
                title = info.get('title', '')
                download_size = info.get('download_size', info.get('size', 0))
                install_path = info.get('install_path', info.get('path', ''))
                size = self.convert_bytes(int(download_size)) if download_size else None
                if title:
                    c.execute(
                        "UPDATE Game SET Title=?, Size=?, InstallPath=? WHERE ShortName=?",
                        (title, size, install_path, game_id))
                conn.commit()
            except Exception as e:
                print(f"Error updating Amazon game details: {e}", file=sys.stderr)
        conn.close()

    # Nile progress format (individual lines):
    # Progress: 45.67 (no percent sign, just a number)
    # ETA: 01:30:00
    # Downloaded: 1024.50 MiB
    # Download	- 15.00 MiB/s
    # Disk	- 10.00 MiB/s

    def get_last_progress_update(self, file_path):
        progress_re = re.compile(r"Progress: (\d+\.?\d*) ")
        eta_re = re.compile(r"ETA: (\d+:\d+:\d+)")
        downloaded_re = re.compile(r"Downloaded: (\S+) MiB")
        download_speed_re = re.compile(r"Download\t- (\S+) MiB")
        last_progress_update = None

        try:
            with open(file_path, "r") as f:
                lines = f.readlines()

                percent = None
                eta = ""
                downloaded = ""
                speed = ""

                for line in reversed(lines):
                    if percent is None:
                        if match := progress_re.search(line):
                            percent = float(match.group(1))
                    if not eta:
                        if match := eta_re.search(line):
                            eta = match.group(1)
                    if not downloaded:
                        if match := downloaded_re.search(line):
                            downloaded = match.group(1)
                    if not speed:
                        if match := download_speed_re.search(line):
                            speed = match.group(1)
                    if percent is not None and eta and downloaded and speed:
                        break

                # Check recent lines for completion/error messages
                is_complete = False
                is_error = False
                error_line = ""
                if lines:
                    for line in lines[-5:]:
                        ll = line.strip().lower()
                        if "download complete" in ll or "finished" in ll or "done" in ll or "100%" in line:
                            is_complete = True
                            break
                        if "error" in ll or "failed" in ll:
                            is_error = True
                            error_line = line.strip()

                if is_complete:
                    last_progress_update = {
                        "Percentage": 100,
                        "Description": "Installation complete"
                    }
                elif percent is not None:
                    if percent >= 100:
                        percent = 99
                    desc = f"Downloaded {downloaded} MiB ({percent}%)"
                    if speed:
                        desc += f"\nSpeed: {speed} MiB/s"
                    if eta:
                        desc += f"\nETA: {eta}"
                    last_progress_update = {
                        "Percentage": percent,
                        "Description": desc
                    }
                elif is_error:
                    last_progress_update = {
                        "Percentage": 0,
                        "Description": "Installation Failed.",
                        "Error": error_line
                    }
                elif lines:
                    last_progress_update = {
                        "Percentage": 0,
                        "Description": lines[-1].strip()
                    }
        except Exception as e:
            print("Waiting for progress update", e, file=sys.stderr)
            time.sleep(1)

        return json.dumps({'Type': 'ProgressUpdate', 'Content': last_progress_update})
