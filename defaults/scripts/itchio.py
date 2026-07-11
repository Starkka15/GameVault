import datetime
import re
import json
import os
import sqlite3
import sys
import subprocess
import time
import zipfile
import tarfile
import shutil
import stat
import struct
import urllib.request
import urllib.error
import html as html_module

import GamesDb
from datetime import datetime, timedelta


class CmdException(Exception):
    pass


class Itchio(GamesDb.GamesDb):
    def __init__(self, db_file, storeName, setNameConfig=None):
        super().__init__(db_file, storeName=storeName, setNameConfig=setNameConfig)
        self.storeURL = "https://itch.io/"

    api_key_path = os.path.join(
        os.environ.get('DECKY_PLUGIN_RUNTIME_DIR', ''), 'itchio_api_key')

    def _get_api_key(self):
        """Read stored API key from file."""
        if os.path.exists(self.api_key_path):
            with open(self.api_key_path, 'r') as f:
                return f.read().strip()
        return None

    def api_request(self, endpoint, use_bearer=False):
        """Make authenticated API request to itch.io."""
        api_key = self._get_api_key()
        if not api_key:
            raise CmdException("Not logged in. Please set your itch.io API key.")

        if use_bearer:
            # Bearer token auth for api.itch.io endpoints
            url = endpoint
            headers = {
                'Authorization': f'Bearer {api_key}',
                'User-Agent': 'Mozilla/5.0'
            }
        else:
            # Key-in-URL auth for itch.io/api/1/KEY/ endpoints
            url = f"https://itch.io/api/1/{api_key}/{endpoint}"
            headers = {'User-Agent': 'Mozilla/5.0'}

        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req, timeout=60)
        data = response.read()
        return json.loads(data)

    def get_list(self, offline=False):
        """Fetch owned games from itch.io API and populate database."""
        api_key = self._get_api_key()
        if not api_key:
            raise CmdException("Not logged in.")

        all_games = []
        download_keys = {}  # game_id -> download_key_id
        page = 1
        while True:
            try:
                data = self.api_request(
                    f"https://api.itch.io/profile/owned-keys?page={page}",
                    use_bearer=True)
            except Exception as e:
                print(f"Error fetching page {page}: {e}", file=sys.stderr)
                break

            owned_keys = data.get('owned_keys', [])
            if not owned_keys:
                break

            for key_entry in owned_keys:
                game = key_entry.get('game', {})
                if game and game.get('id'):
                    all_games.append(game)
                    # Store the download key ID for this game
                    dk_id = key_entry.get('id')
                    if dk_id:
                        download_keys[str(game['id'])] = str(dk_id)

            page += 1

        print(f"Found {len(all_games)} itch.io games", file=sys.stderr)

        # Try insert_data with gamesdb lookup first
        id_list = [str(g['id']) for g in all_games]
        game_dict = {str(g['id']): g for g in all_games}

        left_overs = self.insert_data(id_list)
        print(f"left_overs: {left_overs}", file=sys.stderr)

        for game_id in left_overs:
            if game_id in game_dict:
                self.proccess_leftovers(game_dict[game_id], download_keys.get(game_id, ''))

        # Update download key IDs for all games (including ones from GamesDb)
        conn = self.get_connection()
        c = conn.cursor()
        for game_id, dk_id in download_keys.items():
            c.execute("UPDATE Game SET ManualPath=? WHERE ShortName=?", (dk_id, game_id))
        conn.commit()
        conn.close()

        # Optionally import games from the user's itch.io Collections (issue #3). Owned
        # games are fetched first (above), so overlapping titles keep their download key;
        # collection-only games are added keyless and install via the direct uploads path.
        if os.environ.get('ITCHIO_IMPORTCOLLECTIONS', 'false').strip().lower() in ('true', '1', 'on'):
            try:
                self._import_collections(set(id_list))
            except Exception as e:
                print(f"itch.io collection import failed: {e}", file=sys.stderr)

    def proccess_leftovers(self, game_data, download_key_id=''):
        """Insert game from itch.io API data that wasn't found in GamesDb."""
        title = game_data.get('title', 'Unknown')
        print(f"Processing leftover itch.io game: {title}", file=sys.stderr)
        conn = self.get_connection()
        c = conn.cursor()

        try:
            game_id = str(game_data.get('id', ''))
            shortname = game_id

            c.execute("SELECT * FROM Game WHERE ShortName=?", (shortname,))
            result = c.fetchone()
            if result is None:
                notes = game_data.get('short_text', '')

                vals = [
                    title, notes, "", download_key_id, "",  "", "Itchio",
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

                game_id_db = c.lastrowid
                cover_url = game_data.get('cover_url', '')
                if cover_url:
                    c.execute(
                        "INSERT INTO Images (GameID, ImagePath, FileName, SortOrder, Type) VALUES (?, ?, ?, ?, ?)",
                        (game_id_db, cover_url, '', 0, 'vertical_cover'))
                conn.commit()
        except Exception as e:
            print(f"Error parsing metadata for itch.io game: {title} {e}", file=sys.stderr)

        conn.close()

    def _get_collections(self):
        """List the user's itch.io collections ({id, title}). NOTE: the profile/collections
        endpoint ignores ?page and returns the full list every time, so we terminate when a
        page yields no NEW collection ids (works whether or not it actually paginates)."""
        collections = []
        seen = set()
        page = 1
        while True:
            try:
                data = self.api_request(
                    f"https://api.itch.io/profile/collections?page={page}",
                    use_bearer=True)
            except Exception as e:
                print(f"Error fetching collections page {page}: {e}", file=sys.stderr)
                break
            cols = data.get('collections', [])
            # itch's PHP API serializes an empty array as {} and may key results by id;
            # accept either a list or a dict-of-objects.
            if isinstance(cols, dict):
                cols = list(cols.values())
            if not cols:
                break
            new = [c for c in cols if isinstance(c, dict) and c.get('id') not in seen]
            if not new:
                break
            for c in new:
                seen.add(c.get('id'))
            collections.extend(new)
            page += 1
        return collections

    def _get_collection_games(self, collection_id):
        """All game objects in a collection (paginated). Each collection-game entry wraps
        a full 'game' object (id/title/cover_url/short_text) — same shape as owned-keys."""
        games = []
        seen = set()
        page = 1
        while True:
            try:
                data = self.api_request(
                    f"https://api.itch.io/collections/{collection_id}/collection-games?page={page}",
                    use_bearer=True)
            except Exception as e:
                print(f"Error fetching collection {collection_id} page {page}: {e}", file=sys.stderr)
                break
            entries = data.get('collection_games', [])
            if isinstance(entries, dict):
                entries = list(entries.values())
            if not entries:
                break
            added = 0
            for entry in entries:
                g = entry.get('game') if isinstance(entry, dict) else None
                gid = g.get('id') if g else None
                if gid and gid not in seen:
                    seen.add(gid)
                    games.append(g)
                    added += 1
            if added == 0:   # page repeated / no new games -> stop
                break
            page += 1
        return games

    def _import_collections(self, skip_ids):
        """Insert every game from the user's collections that isn't already in the library.
        skip_ids = game ids already handled (owned) so we don't touch their download keys;
        proccess_leftovers also re-checks the DB, so overlaps are safe either way."""
        collections = self._get_collections()
        print(f"Importing from {len(collections)} itch.io collection(s)", file=sys.stderr)
        seen = set(str(x) for x in skip_ids)
        added = 0
        for col in collections:
            cid = col.get('id')
            if not cid:
                continue
            title = col.get('title', cid)
            games = self._get_collection_games(cid)
            print(f"  collection '{title}' ({cid}): {len(games)} game(s)", file=sys.stderr)
            for game in games:
                gid = str(game.get('id', ''))
                if not gid or gid in seen:
                    continue
                seen.add(gid)
                self.proccess_leftovers(game, '')
                added += 1
        print(f"Imported {added} collection game(s)", file=sys.stderr)
        return added

    def get_collections(self):
        """JSON list of the user's collections (id + title + game count). For debugging /
        a future collection picker."""
        cols = []
        for col in self._get_collections():
            cols.append({
                'Id': str(col.get('id', '')),
                'Title': col.get('title', ''),
                'GamesCount': col.get('games_count', 0),
            })
        return json.dumps({'Type': 'Collections', 'Content': {'Collections': cols}})

    def _get_download_key(self, game_id):
        """Get the download key ID for a game from the database."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT ManualPath FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        conn.close()
        if result and result[0] and result[0].isdigit():
            return result[0]
        return None

    def _get_uploads(self, game_id):
        """Get uploads for a game. Tries direct endpoint first, falls back to download key."""
        # Try direct game uploads endpoint first
        try:
            data = self.api_request(f"game/{game_id}/uploads")
            uploads = data.get('uploads', [])
            if uploads:
                print(f"Got {len(uploads)} uploads via direct endpoint", file=sys.stderr)
                return uploads
        except Exception as e:
            print(f"Direct uploads endpoint failed: {e}", file=sys.stderr)

        # Fall back to download key endpoint
        dk_id = self._get_download_key(game_id)
        if dk_id:
            try:
                data = self.api_request(f"download-key/{dk_id}/uploads")
                uploads = data.get('uploads', [])
                if uploads:
                    print(f"Got {len(uploads)} uploads via download key", file=sys.stderr)
                    return uploads
            except Exception as e:
                print(f"Download key uploads endpoint failed: {e}", file=sys.stderr)

        return []

    def _pick_upload(self, uploads):
        """Pick the best upload for download. Prefer Linux > Windows > other."""
        linux_uploads = []
        windows_uploads = []
        other_uploads = []

        for u in uploads:
            if u.get('p_linux'):
                linux_uploads.append(u)
            elif u.get('p_windows'):
                windows_uploads.append(u)
            else:
                other_uploads.append(u)

        # Prefer Linux, then Windows, then anything
        candidates = linux_uploads or windows_uploads or other_uploads
        if not candidates:
            candidates = uploads

        # Among candidates, prefer largest file (more likely to be the full game)
        candidates.sort(key=lambda u: u.get('size', 0) or 0, reverse=True)
        return candidates[0] if candidates else None

    def download_game(self, game_id, install_dir):
        """Download a game from itch.io and extract it."""
        print(f"Downloading itch.io game {game_id}", file=sys.stderr)

        # Get uploads for this game (tries direct, falls back to download key)
        uploads = self._get_uploads(game_id)
        if not uploads:
            raise CmdException(f"No downloads available for game {game_id}")

        upload = self._pick_upload(uploads)
        if not upload:
            raise CmdException(f"No suitable download found for game {game_id}")

        upload_id = upload['id']
        filename = upload.get('filename', f'game_{game_id}')
        total_size = upload.get('size', 0) or 0
        is_linux = upload.get('p_linux', False)
        is_windows = upload.get('p_windows', False)

        platform_type = "linux" if is_linux else "windows"

        print(f"Selected upload: {filename} ({self.convert_bytes(total_size) if total_size else 'unknown size'}), platform: {platform_type}", file=sys.stderr)

        # Get download URL (try with download key if available)
        dl_url = ''
        dk_id = self._get_download_key(game_id)
        download_endpoint = f"upload/{upload_id}/download"
        if dk_id:
            download_endpoint += f"?download_key_id={dk_id}"

        try:
            dl_data = self.api_request(download_endpoint)
            dl_url = dl_data.get('url', '')
        except urllib.error.HTTPError as e:
            if e.code == 303 or e.code == 302:
                dl_url = e.headers.get('Location', '')
            else:
                raise CmdException(f"Failed to get download URL: {e}")

        if not dl_url:
            raise CmdException("No download URL returned")

        # Create game directory
        game_dir = os.path.join(install_dir, f"itchio_{game_id}")
        os.makedirs(game_dir, exist_ok=True)

        # Download file with progress
        download_path = os.path.join(game_dir, filename)
        print(f"Downloading to: {download_path}", file=sys.stderr)

        req = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=300)

        actual_size = int(response.headers.get('Content-Length', total_size) or total_size)
        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        last_report = 0

        with open(download_path, 'wb') as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                # Report progress in nile-compatible format
                now = time.time()
                if now - last_report >= 0.5:  # Report every 0.5s
                    if actual_size > 0:
                        percent = min((downloaded / actual_size) * 100, 99.99)
                        downloaded_mib = downloaded / (1024 * 1024)
                        speed_mib = downloaded_mib / max(now - last_report, 0.01) if last_report > 0 else 0
                        print(f"Progress: {percent:.2f} ", file=sys.stderr)
                        print(f"Downloaded: {downloaded_mib:.2f} MiB", file=sys.stderr)
                        if speed_mib > 0:
                            print(f"Download\t- {speed_mib:.2f} MiB/s", file=sys.stderr)
                    last_report = now

        print("Download Complete", file=sys.stderr)

        # Extract if it's an archive
        extracted_dir = self.extract_archive(download_path, game_dir)

        # Update database
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE Game SET RootFolder=?, InstallPath=?, ConfigurationPath=? WHERE ShortName=?",
                  (extracted_dir or game_dir, game_dir, platform_type, game_id))
        if actual_size > 0:
            c.execute("UPDATE Game SET Size=? WHERE ShortName=?",
                      (self.convert_bytes(actual_size), game_id))
        conn.commit()
        conn.close()

        print(f"Game {game_id} downloaded to {game_dir}", file=sys.stderr)

    def extract_archive(self, file_path, dest_dir):
        """Detect archive type and extract. Returns path to extracted content directory."""
        if not os.path.exists(file_path):
            return None

        # Detect format by magic bytes
        file_type = None
        with open(file_path, 'rb') as f:
            header = f.read(8)

        if header[:4] == b'PK\x03\x04':
            file_type = 'zip'
        elif header[:6] == b'Rar!\x1a\x07':
            file_type = 'rar'
        elif header[:6] == b'\x37\x7a\xbc\xaf\x27\x1c':
            file_type = '7z'
        elif header[:3] == b'\x1f\x8b\x08':
            file_type = 'tar.gz'
        elif header[:3] == b'BZh':
            file_type = 'tar.bz2'
        elif header[:6] == b'\xfd7zXZ\x00':
            file_type = 'tar.xz'

        # Fallback to extension detection
        if file_type is None:
            lower = file_path.lower()
            if lower.endswith('.zip'):
                file_type = 'zip'
            elif lower.endswith('.rar'):
                file_type = 'rar'
            elif lower.endswith('.7z'):
                file_type = '7z'
            elif lower.endswith('.tar.gz') or lower.endswith('.tgz'):
                file_type = 'tar.gz'
            elif lower.endswith('.tar.bz2'):
                file_type = 'tar.bz2'
            elif lower.endswith('.tar.xz'):
                file_type = 'tar.xz'
            elif lower.endswith('.tar'):
                file_type = 'tar'

        if file_type is None:
            # Not an archive - might be a standalone binary
            print(f"Not an archive, treating as standalone file: {file_path}", file=sys.stderr)
            # Make it executable
            os.chmod(file_path, os.stat(file_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            return dest_dir

        extract_dir = os.path.join(dest_dir, 'game')
        os.makedirs(extract_dir, exist_ok=True)

        print(f"Extracting {file_type} archive: {file_path}", file=sys.stderr)

        try:
            if file_type == 'zip':
                with zipfile.ZipFile(file_path, 'r') as zf:
                    # Validate no path traversal
                    for member in zf.namelist():
                        member_path = os.path.realpath(os.path.join(extract_dir, member))
                        if not member_path.startswith(os.path.realpath(extract_dir) + os.sep) and member_path != os.path.realpath(extract_dir):
                            raise CmdException(f"Path traversal detected in zip: {member}")
                    zf.extractall(extract_dir)

            elif file_type in ('tar.gz', 'tar.bz2', 'tar.xz', 'tar'):
                mode = {
                    'tar.gz': 'r:gz',
                    'tar.bz2': 'r:bz2',
                    'tar.xz': 'r:xz',
                    'tar': 'r:'
                }[file_type]
                with tarfile.open(file_path, mode) as tf:
                    # Validate no path traversal
                    for member in tf.getmembers():
                        member_path = os.path.realpath(os.path.join(extract_dir, member.name))
                        if not member_path.startswith(os.path.realpath(extract_dir) + os.sep) and member_path != os.path.realpath(extract_dir):
                            raise CmdException(f"Path traversal detected in tar: {member.name}")
                    tf.extractall(extract_dir)

            elif file_type == 'rar':
                unrar_cmd = 'unrar'
                if not shutil.which(unrar_cmd):
                    raise CmdException("unrar not installed. Install it from the About menu (Install Dependencies).")
                subprocess.run([unrar_cmd, 'x', '-o+', file_path, extract_dir + '/'],
                               check=True, capture_output=True)

            elif file_type == '7z':
                sz_cmd = shutil.which('7z') or shutil.which('7za')
                if not sz_cmd:
                    raise CmdException("7z not installed. Install it from the About menu (Install Dependencies).")
                subprocess.run([sz_cmd, 'x', f'-o{extract_dir}', '-y', file_path],
                               check=True, capture_output=True)

            print(f"Extraction complete to {extract_dir}", file=sys.stderr)

            # Clean up archive file to save space
            os.remove(file_path)

            # If extraction produced a single subdirectory, use that as the root
            entries = os.listdir(extract_dir)
            if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
                return os.path.join(extract_dir, entries[0])
            return extract_dir

        except Exception as e:
            print(f"Extraction failed: {e}", file=sys.stderr)
            return dest_dir

    def detect_executable(self, game_id):
        """Detect the main executable in an installed game directory."""
        conn = self.get_connection()
        c = conn.cursor()
        c.row_factory = sqlite3.Row
        c.execute("SELECT RootFolder, InstallPath, ConfigurationPath FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()

        if not result:
            conn.close()
            print(f"Game {game_id} not found in database", file=sys.stderr)
            return

        game_dir = result['RootFolder'] or result['InstallPath']
        platform_type = result['ConfigurationPath'] or 'linux'

        if not game_dir or not os.path.exists(game_dir):
            conn.close()
            print(f"Game directory not found: {game_dir}", file=sys.stderr)
            return

        exe_path = None
        exe_relative = None

        # 1. Check for .itch.toml manifest
        itch_toml = self._find_itch_toml(game_dir)
        if itch_toml:
            exe_relative = self._parse_itch_toml(itch_toml, game_dir)
            if exe_relative:
                print(f"Found executable from .itch.toml: {exe_relative}", file=sys.stderr)

        # 2. Scan for ELF binaries (Linux native)
        if not exe_relative:
            elf_files = self._find_elf_binaries(game_dir)
            if elf_files:
                exe_relative = os.path.relpath(elf_files[0], game_dir)
                platform_type = 'linux'
                print(f"Found ELF binary: {exe_relative}", file=sys.stderr)

        # 3. Scan for executable .sh scripts
        if not exe_relative:
            sh_files = self._find_sh_scripts(game_dir)
            if sh_files:
                exe_relative = os.path.relpath(sh_files[0], game_dir)
                platform_type = 'linux'
                print(f"Found .sh script: {exe_relative}", file=sys.stderr)

        # 4. Scan for .exe files (Windows/Proton)
        if not exe_relative:
            exe_files = self._find_exe_files(game_dir)
            if exe_files:
                exe_relative = os.path.relpath(exe_files[0], game_dir)
                platform_type = 'windows'
                print(f"Found .exe file: {exe_relative}", file=sys.stderr)

        # 5. Scan for index.html (HTML5 web game)
        if not exe_relative:
            html_file = self._find_index_html(game_dir)
            if html_file:
                exe_relative = os.path.relpath(html_file, game_dir)
                platform_type = 'html'
                print(f"Found HTML5 game: {exe_relative}", file=sys.stderr)

        if exe_relative:
            c2 = conn.cursor()
            c2.execute("UPDATE Game SET ApplicationPath=?, RootFolder=?, ConfigurationPath=? WHERE ShortName=?",
                       (exe_relative, game_dir, platform_type, game_id))
            conn.commit()
            print(f"Executable set: {exe_relative} (platform: {platform_type})", file=sys.stderr)
        else:
            print(f"No executable found for game {game_id} in {game_dir}", file=sys.stderr)

        conn.close()

    def _find_itch_toml(self, game_dir):
        """Find .itch.toml file in game directory."""
        for root, dirs, files in os.walk(game_dir):
            if '.itch.toml' in files:
                return os.path.join(root, '.itch.toml')
            # Don't recurse too deep
            depth = root.replace(game_dir, '').count(os.sep)
            if depth >= 3:
                dirs.clear()
        return None

    def _parse_itch_toml(self, toml_path, game_dir):
        """Parse .itch.toml to find the game executable path."""
        try:
            with open(toml_path, 'r') as f:
                content = f.read()

            # Simple TOML parser for [[actions]] sections
            in_actions = False
            current_path = None
            current_platform = None

            for line in content.split('\n'):
                line = line.strip()
                if line == '[[actions]]':
                    # Save previous action if any
                    if current_path and (current_platform is None or
                                         current_platform == 'linux' or
                                         current_platform == ''):
                        toml_dir = os.path.dirname(toml_path)
                        full_path = os.path.join(toml_dir, current_path)
                        if os.path.exists(full_path):
                            return os.path.relpath(full_path, game_dir)
                    in_actions = True
                    current_path = None
                    current_platform = None
                elif in_actions:
                    if line.startswith('path'):
                        # path = "game.exe"
                        match = re.match(r'path\s*=\s*"([^"]*)"', line)
                        if match:
                            current_path = match.group(1)
                    elif line.startswith('platform'):
                        match = re.match(r'platform\s*=\s*"([^"]*)"', line)
                        if match:
                            current_platform = match.group(1)

            # Handle last action
            if current_path:
                toml_dir = os.path.dirname(toml_path)
                full_path = os.path.join(toml_dir, current_path)
                if os.path.exists(full_path):
                    return os.path.relpath(full_path, game_dir)

        except Exception as e:
            print(f"Error parsing .itch.toml: {e}", file=sys.stderr)

        return None

    def _find_elf_binaries(self, game_dir):
        """Find ELF binaries in game directory."""
        elf_files = []
        skip_dirs = {'__MACOSX', '.git', 'lib', 'lib64', 'lib32'}
        for root, dirs, files in os.walk(game_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, 'rb') as fh:
                        magic = fh.read(4)
                    if magic == b'\x7fELF':
                        # Check it's executable
                        st = os.stat(filepath)
                        if st.st_mode & stat.S_IEXEC:
                            elf_files.append(filepath)
                except (IOError, OSError):
                    continue
            # Limit depth
            depth = root.replace(game_dir, '').count(os.sep)
            if depth >= 3:
                dirs.clear()

        # Sort: prefer files in root directory, then by name length (shorter = more likely main exe)
        elf_files.sort(key=lambda p: (p.replace(game_dir, '').count(os.sep), len(os.path.basename(p))))
        return elf_files

    def _find_sh_scripts(self, game_dir):
        """Find executable .sh scripts in game directory."""
        sh_files = []
        skip_dirs = {'__MACOSX', '.git'}
        for root, dirs, files in os.walk(game_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f.endswith('.sh'):
                    filepath = os.path.join(root, f)
                    st = os.stat(filepath)
                    if st.st_mode & stat.S_IEXEC:
                        sh_files.append(filepath)
            depth = root.replace(game_dir, '').count(os.sep)
            if depth >= 3:
                dirs.clear()

        # Prefer files named start.sh, run.sh, launch.sh, game.sh or in root
        def sort_key(p):
            name = os.path.basename(p).lower()
            depth = p.replace(game_dir, '').count(os.sep)
            priority = 10
            if name in ('start.sh', 'run.sh', 'launch.sh', 'game.sh', 'play.sh'):
                priority = 0
            return (depth, priority, len(name))

        sh_files.sort(key=sort_key)
        return sh_files

    def _find_index_html(self, game_dir):
        """Find index.html in game directory (HTML5 web game)."""
        for root, dirs, files in os.walk(game_dir):
            if 'index.html' in files:
                return os.path.join(root, 'index.html')
            depth = root.replace(game_dir, '').count(os.sep)
            if depth >= 3:
                dirs.clear()
        return None

    def _find_exe_files(self, game_dir):
        """Find .exe files in game directory."""
        exe_files = []
        skip_dirs = {'__MACOSX', '.git', 'redist', 'Redist', '_CommonRedist',
                     'DirectX', 'dotnet', 'vcredist', 'DotNetFX'}
        skip_names = {'unins000.exe', 'UnityCrashHandler32.exe',
                      'UnityCrashHandler64.exe', 'CrashReportClient.exe',
                      'UEPrereqSetup_x64.exe', 'DXSETUP.exe'}

        for root, dirs, files in os.walk(game_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f.lower().endswith('.exe') and f not in skip_names:
                    exe_files.append(os.path.join(root, f))
            depth = root.replace(game_dir, '').count(os.sep)
            if depth >= 3:
                dirs.clear()

        # Sort: prefer files in root directory, then by name length
        exe_files.sort(key=lambda p: (p.replace(game_dir, '').count(os.sep), len(os.path.basename(p))))
        return exe_files

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
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/itchio/'))
            print(os.path.join(install_dir, f"itchio_{game_id}"))

    def _fetch_html(self, url):
        """Fetch a URL and return the response body as string."""
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})
        response = urllib.request.urlopen(req, timeout=15)
        return response.read().decode()

    def _fetch_browse_json(self, url):
        """Fetch an itch.io browse page with format=json and return the HTML content."""
        data = json.loads(self._fetch_html(url))
        return data.get('content', '')

    def _parse_game_cells(self, page_html, seen_ids=None):
        """Parse game cells from itch.io HTML. Returns list of game dicts and updated seen_ids set."""
        if seen_ids is None:
            seen_ids = set()
        games = []
        for match in re.finditer(
            r'<div[^>]*data-game_id="(\d+)"[^>]*>(.*?)</div></div></div>',
            page_html, re.DOTALL
        ):
            game_id = match.group(1)
            if game_id in seen_ids:
                continue
            seen_ids.add(game_id)
            cell_html = match.group(2)

            title_match = re.search(r'class="title game_link"[^>]*>([^<]+)<', cell_html)
            title = html_module.unescape(title_match.group(1).strip()) if title_match else ''

            img_match = re.search(r'data-lazy_src="([^"]+)"', cell_html)
            if not img_match:
                img_match = re.search(r'<img[^>]*src="([^"]+)"', cell_html)
            cover = img_match.group(1) if img_match else ''

            # Extract price tag
            price_match = re.search(r'class="price_value">([^<]*)<', cell_html)
            price = price_match.group(1).strip() if price_match else ''

            # Build display title with price indicator
            if price == '$0' or price == '':
                prefix = '[FREE] '
            elif 'demo' in title.lower():
                prefix = '[DEMO] '
            else:
                prefix = f'[{price}] '
            display_title = prefix + title

            games.append({
                'ID': 0,
                'Name': display_title,
                'ShortName': game_id,
                'SteamClientID': '',
                'Images': [cover] if cover else []
            })
        return games, seen_ids

    def browse_games(self, filter_text=''):
        """Browse/search itch.io games including NSFW content."""
        seen_ids = set()
        all_games = []

        if filter_text:
            # Search: SFW results from /search + NSFW client-side title filter
            search_html = self._fetch_html(
                f'https://itch.io/search?q={urllib.parse.quote(filter_text)}')
            games, seen_ids = self._parse_game_cells(search_html, seen_ids)
            all_games.extend(games)

            # Also fetch NSFW browse page and filter by title client-side
            try:
                nsfw_html = self._fetch_browse_json(
                    'https://itch.io/games/tag-nsfw?format=json')
                nsfw_games, seen_ids = self._parse_game_cells(nsfw_html, seen_ids)
                filter_lower = filter_text.lower()
                for g in nsfw_games:
                    if filter_lower in g['Name'].lower():
                        all_games.append(g)
            except Exception:
                pass
        else:
            # Browse: merge SFW + NSFW feeds
            sfw_html = self._fetch_browse_json('https://itch.io/games?format=json')
            games, seen_ids = self._parse_game_cells(sfw_html, seen_ids)
            all_games.extend(games)

            try:
                nsfw_html = self._fetch_browse_json(
                    'https://itch.io/games/tag-nsfw?format=json')
                nsfw_games, seen_ids = self._parse_game_cells(nsfw_html, seen_ids)
                all_games.extend(nsfw_games)
            except Exception:
                pass

        return json.dumps({
            'Type': 'GameGrid',
            'Content': {
                'NeedsLogin': False,
                'Games': all_games,
                'storeURL': 'https://itch.io/'
            }
        })

    def get_browse_details(self, game_id):
        """Get details for a browsed game. Adds to library first if needed."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM Game WHERE ShortName=?", (game_id,))
        if c.fetchone() is None:
            conn.close()
            # Add to library first
            self.add_browse_to_library(game_id)
        else:
            conn.close()
        # Now return details using the standard method
        result = self.get_game_data(game_id, '', False, 'Windows', 'Proton', 'null')
        if result is None:
            # Fallback minimal response
            return json.dumps({'Type': 'GameDetails', 'Content': {
                'Name': f'itch.io Game {game_id}',
                'Description': '<p>Could not load game details.</p>',
                'ShortName': game_id,
                'SteamClientID': '',
                'HasDosConfig': False,
                'HasBatFiles': False,
                'Editors': [],
                'Images': []
            }}, indent=2)
        return result

    def add_browse_to_library(self, game_id):
        """Scrape an itch.io game page by ID and add it to the local library."""
        # Check if already in DB
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM Game WHERE ShortName=?", (game_id,))
        if c.fetchone() is not None:
            conn.close()
            return json.dumps({'Type': 'Success', 'Content': {'Message': 'Game already in your library. Go to the itch.io tab to download it.'}})

        # Fetch game metadata - try API first, fall back to scraping the game page
        title = f'itch.io Game {game_id}'
        description = ''
        cover_url = ''
        page_url = ''

        try:
            api_key = self._get_api_key()
            if api_key:
                req = urllib.request.Request(f'https://itch.io/api/1/{api_key}/game/{game_id}',
                                             headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=10)
                api_data = json.loads(resp.read().decode())
                game_info = api_data.get('game', {})
                title = game_info.get('title', title)
                description = game_info.get('short_text', '')
                cover_url = game_info.get('cover_url', '')
                page_url = game_info.get('url', '')
        except Exception as e:
            print(f"API lookup failed for game {game_id}: {e}", file=sys.stderr)

        # If API didn't give us a real title, use itch.io embed page (no auth needed)
        if title == f'itch.io Game {game_id}':
            try:
                embed_url = f'https://itch.io/embed/{game_id}'
                req = urllib.request.Request(embed_url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=10)
                embed_html = resp.read().decode()
                t = re.search(r'<title>([^<]+)</title>', embed_html)
                if t:
                    raw_title = html_module.unescape(t.group(1))
                    raw_title = re.sub(r'\s*-\s*itch\.io$', '', raw_title)
                    raw_title = re.sub(r'\s+by\s+.+$', '', raw_title)
                    title = raw_title
                img = re.search(r'<img[^>]*src="(https://img\.itch\.zone/[^"]+)"', embed_html)
                if img:
                    cover_url = img.group(1)
                desc = re.search(r'class="widget_text_block">([^<]+)<', embed_html)
                if desc:
                    description = html_module.unescape(desc.group(1).strip())
            except Exception as e:
                print(f"Embed page lookup failed for game {game_id}: {e}", file=sys.stderr)

        vals = [
            title, description, "", page_url, "", "", "Itchio",
            game_id, "", "", "", "",
            "", "", "", "", game_id,
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
        game_db_id = c.lastrowid
        if cover_url:
            c.execute(
                "INSERT INTO Images (GameID, ImagePath, FileName, SortOrder, Type) VALUES (?, ?, ?, ?, ?)",
                (game_db_id, cover_url, '', 0, 'vertical_cover'))
        conn.commit()
        conn.close()
        return json.dumps({'Type': 'Success', 'Content': {'Message': f'{title} added to your library. Go to the itch.io tab to download it.'}})

    def get_login_status(self, flush_cache=False):
        cache_key = "itchio-login"
        if flush_cache:
            self.clear_cache(cache_key)

        cache = self.get_cache(cache_key)
        print(f"cache: {cache}", file=sys.stderr)
        if cache is not None:
            return cache
        print(f"cache miss!", file=sys.stderr)

        api_key = self._get_api_key()
        if api_key:
            try:
                data = self.api_request("me")
                username = data.get('user', {}).get('username', 'itch.io User')
                value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': username, 'LoggedIn': True}})
            except Exception as e:
                print(f"API key validation failed: {e}", file=sys.stderr)
                value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': '', 'LoggedIn': False}})
        else:
            value = json.dumps({'Type': 'LoginStatus', 'Content': {'Username': '', 'LoggedIn': False}})

        timeout = datetime.now() + timedelta(hours=1)
        try:
            self.add_cache(cache_key, value, timeout)
        except Exception as e:
            print(f"Error adding cache: {e}", file=sys.stderr)
        return value

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
                uploads = self._get_uploads(game_id)
                upload = self._pick_upload(uploads) if uploads else None
                if upload and upload.get('size'):
                    size = f"Download Size: {self.convert_bytes(int(upload['size']))}"
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
        c.execute("SELECT ApplicationPath, RootFolder, WorkingDir, ConfigurationPath FROM Game WHERE ShortName=?", (game_id,))
        game = c.fetchone()
        conn.close()

        is_windows = False
        if game and game['RootFolder'] and game['ApplicationPath']:
            root_dir = game['RootFolder']
            working_dir = os.path.join(root_dir, game['WorkingDir']).replace("\\", "/") if game['WorkingDir'] else root_dir
            if game['ConfigurationPath'] == 'html':
                # HTML5 game — set exe to index.html path, launcher handles opening in browser
                game_exe = os.path.join(root_dir, game['ApplicationPath']).replace("\\", "/")
                is_windows = False
            else:
                game_exe = os.path.join(root_dir, game['ApplicationPath']).replace("\\", "/")
                is_windows = (game['ConfigurationPath'] == 'windows')
        else:
            install_dir = os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/itchio/'))
            game_exe = ""
            working_dir = os.path.join(install_dir, f"itchio_{game_id}") if install_dir else ""

        return json.dumps(
            {
                'Type': 'LaunchOptions',
                'Content':
                {
                    'Exe': f"\"{game_exe}\"" if game_exe else "\"\"",
                    'Options': f"{script_path} {game_id}%command%",
                    'WorkingDir': f"\"{working_dir}\"" if working_dir else "",
                    'Compatibility': is_windows,
                    'Name': name
                }
            })

    def update_game_details(self, game_id):
        """Update game details from itch.io API."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM Game WHERE ShortName=?", (game_id,))
        result = c.fetchone()
        if result is not None:
            try:
                uploads = self._get_uploads(game_id)
                upload = self._pick_upload(uploads) if uploads else None
                if upload and upload.get('size'):
                    size = self.convert_bytes(int(upload['size']))
                    c.execute("UPDATE Game SET Size=? WHERE ShortName=?", (size, game_id))
                    conn.commit()
            except Exception as e:
                print(f"Error updating itch.io game details: {e}", file=sys.stderr)
        conn.close()

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
