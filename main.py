import asyncio
import os
import json
import ssl
import sys

from aiohttp import web
import shlex
import decky_plugin
import zipfile
import shutil
import aiohttp
import os
import concurrent.futures


def _make_ssl_context():
    """Create an SSL context that works on Steam Deck.
    Tries system CA certs first, then certifi, then falls back to no verification."""
    try:
        ctx = ssl.create_default_context()
        # Test that it has CA certs loaded
        if ctx.get_ca_certs():
            return ctx
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    # Last resort: disable verification (original behavior)
    return False


class Helper:
    websocket_port = 8765
    action_cache = {}
    working_directory = decky_plugin.DECKY_PLUGIN_RUNTIME_DIR
    dir_size_cache = {}  # path -> (size, timestamp)

    ws_loop = None
    app = None
    site = None
    runner = None
    wsServerIsRunning = False

    verbose = False

    lock = asyncio.Lock()

    @staticmethod
    async def pyexec_subprocess(
        cmd: str,
        input: str = "",
        unprivilege: bool = False,
        env=None,
        websocket=None,
        stream_output: bool = False,
        app_id="",
        game_id="",
    ):
        decky_plugin.logger.info(f"creating lock")
        async with Helper.lock:
            try:
                decky_plugin.logger.info(f"inside lock")
                if unprivilege:
                    cmd = f"sudo -u {decky_plugin.DECKY_USER} {cmd}"
                decky_plugin.logger.info(f"running cmd: {cmd}")
                if env is None:
                    env = Helper.get_environment()
                    env["APP_ID"] = app_id
                    env["SteamOverlayGameId"] = game_id
                    env["SteamGameId"] = game_id
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.PIPE,
                    shell=True,
                    env=env,
                    cwd=Helper.working_directory,
                    start_new_session=True,
                )
                if stream_output:

                    async def read_stream(stream, stream_type):
                        while True:
                            line = await stream.readline()
                            if line:
                                line = line.decode()
                                if stream_output:
                                    await websocket.send_str(
                                        json.dumps(
                                            {
                                                "status": "open",
                                                "data": line,
                                                "type": stream_type,
                                            }
                                        )
                                    )
                            else:
                                break

                    await asyncio.gather(
                        read_stream(proc.stdout, "stdout"),
                        read_stream(proc.stderr, "stderr"),
                    )
                    await proc.wait()
                    await websocket.send_str(
                        json.dumps({"status": "closed", "data": ""})
                    )
                    return {"returncode": proc.returncode}
                else:
                    try:
                        stdout, stderr = await proc.communicate(input.encode())
                        stdout = stdout.decode()
                        stderr = stderr.decode()
                        if Helper.verbose:
                            decky_plugin.logger.info(
                                f"Returncode: {proc.returncode}\nSTDOUT: {stdout[:300]}\nSTDERR: {stderr[:300]}"
                            )
                        return {
                            "returncode": proc.returncode,
                            "stdout": stdout,
                            "stderr": stderr,
                        }
                    finally:
                        # Ensure process is terminated and cleaned up
                        if proc.returncode is None:
                            try:
                                proc.terminate()
                                await asyncio.wait_for(proc.wait(), timeout=5.0)
                            except asyncio.TimeoutError:
                                proc.kill()
                                await proc.wait()
                            except Exception:
                                pass

            except Exception as e:
                decky_plugin.logger.error(f"Error in pyexec_subprocess: {e}")
                # Clean up process on error
                try:
                    if "proc" in locals() and proc.returncode is None:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                except Exception:
                    if "proc" in locals():
                        try:
                            proc.kill()
                            await proc.wait()
                        except Exception:
                            pass
                return None

    @staticmethod
    def get_environment(platform=""):
        env = {
            "DECKY_HOME": decky_plugin.DECKY_HOME,
            "DECKY_PLUGIN_DIR": decky_plugin.DECKY_PLUGIN_DIR,
            "DECKY_PLUGIN_LOG_DIR": decky_plugin.DECKY_PLUGIN_LOG_DIR,
            "DECKY_PLUGIN_NAME": "gamevault",
            "DECKY_PLUGIN_RUNTIME_DIR": decky_plugin.DECKY_PLUGIN_RUNTIME_DIR,
            "DECKY_PLUGIN_SETTINGS_DIR": decky_plugin.DECKY_PLUGIN_SETTINGS_DIR,
            "WORKING_DIR": Helper.working_directory,
            "CONTENT_SERVER": "http://localhost:1337/plugins",
            "DECKY_USER_HOME": decky_plugin.DECKY_USER_HOME,
            "HOME": os.path.abspath(decky_plugin.DECKY_USER_HOME),
            "PLATFORM": platform,
        }
        return env

    @staticmethod
    async def call_script(cmd: str, *args, input_data="", app_id="", game_id=""):
        try:
            decky_plugin.logger.info(f"call_script: {cmd} {args} {input_data}")
            encoded_args = [shlex.quote(arg) for arg in args]
            decky_plugin.logger.info(f"call_script: {cmd} {' '.join(encoded_args)}")
            decky_plugin.logger.info(f"input_data: {input_data}")
            decky_plugin.logger.info(f"args: {args}")
            cmd = f"{cmd} {' '.join(encoded_args)}"

            res = await Helper.pyexec_subprocess(
                cmd, input_data, app_id=app_id, game_id=game_id
            )
            if Helper.verbose:
                decky_plugin.logger.info(f"call_script result: {res['stdout'][:100]}")
            return res["stdout"]
        except Exception as e:
            decky_plugin.logger.error(f"Error in call_script: {e}")
            return None

    @staticmethod
    def get_action(actionSet, actionName):
        result = None
        if set := Helper.action_cache.get(actionSet):
            for action in set:
                if action["Id"] == actionName:
                    result = action
        if not result:
            file_path = os.path.join(Helper.working_directory, f"{actionSet}.json")
            if not os.path.exists(file_path):
                file_path = os.path.join(
                    decky_plugin.DECKY_PLUGIN_RUNTIME_DIR, ".cache", f"{actionSet}.json"
                )

            if os.path.exists(file_path):
                with open(file_path) as f:
                    data = json.load(f)
                    for action in data:
                        if action["Id"] == actionName:
                            result = action
        return result

    @staticmethod
    async def execute_action(
        actionSet, actionName, *args, input_data="", app_id="", game_id=""
    ):
        try:
            result = ""
            json_result = {}
            action = Helper.get_action(actionSet, actionName)
            cmd = action["Command"]
            if cmd:
                decky_plugin.logger.info(f"execute_action cmd: {cmd}")
                decky_plugin.logger.info(f"execute_action args: {args}")
                decky_plugin.logger.info(f"execute_action app_id: {app_id}")
                decky_plugin.logger.info(f"execute_action game_id: {game_id}")

                decky_plugin.logger.info(f"execute_action input_data: {input_data}")
                result = await Helper.call_script(
                    os.path.expanduser(cmd),
                    *args,
                    input_data=input_data,
                    app_id=app_id,
                    game_id=game_id,
                )
                if result is None:
                    return {
                        "Type": "Error",
                        "Content": {
                            "Message": "Script returned no output",
                            "ActionName": actionName,
                            "ActionSet": actionSet,
                        },
                    }
                if Helper.verbose:
                    decky_plugin.logger.info(f"execute_action result: {result}")
                try:
                    json_result = json.loads(result)
                    if json_result["Type"] == "ActionSet":
                        decky_plugin.logger.info(
                            f"Init action set {json_result['Content']['SetName']}"
                        )
                        Helper.write_action_set_to_cache(
                            json_result["Content"]["SetName"],
                            json_result["Content"]["Actions"],
                        )
                except Exception as e:
                    decky_plugin.logger.info("Error parsing json result", e)
                    json_result = {
                        "Type": "Error",
                        "Content": {
                            "Message": f"Error parsing json result {e}",
                            "Data": result,
                            "ActionName": actionName,
                            "ActionSet": actionSet,
                        },
                    }
                return json_result
            return {
                "Type": "Error",
                "Content": {
                    "Message": f"Action not found {actionSet}, {actionName}",
                    "Data": result[:300],
                },
                "ActionName": actionName,
                "ActionSet": actionSet,
            }

        except Exception as e:
            decky_plugin.logger.error(f"Error executing action: {e}")
            return {
                "Type": "Error",
                "Content": {
                    "Message": "Action not found",
                    "Data": str(e),
                    "ActionName": actionName,
                    "ActionSet": actionSet,
                },
            }

    @staticmethod
    def write_action_set_to_cache(setName, actionSet, writeToDisk: bool = False):
        # Prevent cache from growing unbounded - limit to 100 entries
        if len(Helper.action_cache) > 100:
            # Remove oldest entries (FIFO)
            oldest_keys = list(Helper.action_cache.keys())[:50]
            for key in oldest_keys:
                del Helper.action_cache[key]

        Helper.action_cache[setName] = actionSet
        if writeToDisk:
            cache_dir = os.path.join(decky_plugin.DECKY_PLUGIN_RUNTIME_DIR, ".cache")
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            file_path = os.path.join(cache_dir, f"{setName}.json")

            # if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                json.dump(actionSet, f)

    @staticmethod
    async def perform_self_update(download_url, websocket, sudo_password=""):
        """Download and install a plugin update, then restart Decky Loader."""
        import time as _time

        async def send(msg):
            await websocket.send_str(json.dumps({"status": "open", "data": msg, "type": "stdout"}))

        async def sudo_exec(cmd):
            """Run a command with sudo. Uses -S to read password from stdin if provided."""
            # Clear LD_LIBRARY_PATH to avoid Decky's bundled libs breaking /bin/sh
            clean_env = dict(os.environ)
            clean_env.pop("LD_LIBRARY_PATH", None)
            clean_env.pop("LD_PRELOAD", None)
            if sudo_password:
                proc = await asyncio.create_subprocess_shell(
                    f"sudo -S {cmd}",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=clean_env,
                )
                stdout, stderr = await proc.communicate((sudo_password + "\n").encode())
            else:
                proc = await asyncio.create_subprocess_shell(
                    f"sudo {cmd}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=clean_env,
                )
                stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode().strip()
                await send(f"sudo debug: rc={proc.returncode} stderr={err}\n")
                raise RuntimeError(f"sudo failed (rc={proc.returncode}): {err}")

        plugin_dir = decky_plugin.DECKY_PLUGIN_DIR
        tmp_zip = "/tmp/gamevault_update.zip"
        tmp_extract = "/tmp/gamevault_update_extract"
        backup_dir = f"/tmp/gamevault_backup_{int(_time.time())}"

        try:
            # Verify sudo access first
            await send("Verifying sudo access...\n")
            try:
                await sudo_exec("true")
            except RuntimeError:
                await send("ERROR: sudo authentication failed. Check your password.\n")
                await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
                return

            await send("===================================\n")
            await send("  GameVault Self-Update\n")
            await send("  Do not navigate away please...\n")
            await send("===================================\n\n")

            # Step 1: Download
            await send("[1/5] Downloading update...\n")
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=_make_ssl_context())) as session:
                    async with session.get(download_url, allow_redirects=True) as response:
                        if response.status != 200:
                            await send(f"ERROR: Download failed with status {response.status}. No changes made.\n")
                            await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
                            return
                        with open(tmp_zip, "wb") as f:
                            while True:
                                chunk = await response.content.readany()
                                if not chunk:
                                    break
                                f.write(chunk)
            except Exception as e:
                await send(f"ERROR: Download failed: {e}. No changes made.\n")
                await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
                return

            # Step 2: Validate zip
            await send("[2/5] Validating download...\n")
            try:
                with zipfile.ZipFile(tmp_zip, "r") as zf:
                    bad = zf.testzip()
                    if bad is not None:
                        await send(f"ERROR: Corrupt file in zip: {bad}. No changes made.\n")
                        os.remove(tmp_zip)
                        await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
                        return
            except zipfile.BadZipFile:
                await send("ERROR: Downloaded file is not a valid zip. No changes made.\n")
                os.remove(tmp_zip)
                await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
                return

            # Step 3: Backup
            await send(f"[3/5] Backing up to {backup_dir}...\n")
            await sudo_exec(f"cp -a {shlex.quote(plugin_dir)} {shlex.quote(backup_dir)}")
            await send("Backup created.\n")

            # Step 4: Extract to temp (no sudo needed), then sudo copy into plugin dir
            await send("[4/5] Installing update...\n")
            if os.path.exists(tmp_extract):
                shutil.rmtree(tmp_extract)
            os.makedirs(tmp_extract)

            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(tmp_extract)

            # GitHub zipball extracts into a subdirectory (owner-repo-hash/)
            subdirs = [d for d in os.listdir(tmp_extract) if os.path.isdir(os.path.join(tmp_extract, d))]
            if not subdirs:
                await send("ERROR: Could not find extracted directory. Backup preserved.\n")
                shutil.rmtree(tmp_extract, ignore_errors=True)
                os.remove(tmp_zip)
                await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
                return
            extracted_dir = os.path.join(tmp_extract, subdirs[0])

            # Remove replaceable dirs
            for dirname in ["dist", "scripts", "py_modules", "conf_schemas"]:
                target = os.path.join(plugin_dir, dirname)
                if os.path.exists(target):
                    await sudo_exec(f"rm -rf {shlex.quote(target)}")
                    await send(f"  Removed old {dirname}/\n")

            # Remove replaceable root files
            for fname in ["main.py", "plugin.json", "package.json", "LICENSE", "README.md"]:
                target = os.path.join(plugin_dir, fname)
                if os.path.exists(target):
                    await sudo_exec(f"rm -f {shlex.quote(target)}")

            # Copy new files into plugin dir
            await sudo_exec(f"cp -a {shlex.quote(extracted_dir)}/. {shlex.quote(plugin_dir)}/")

            # chmod scripts
            for scripts_subdir in ["scripts", os.path.join("defaults", "scripts")]:
                scripts_path = os.path.join(plugin_dir, scripts_subdir)
                if os.path.exists(scripts_path):
                    await sudo_exec(f"find {shlex.quote(scripts_path)} -type f -exec chmod 755 {{}} \\;")

            await send("[5/5] Update installed successfully!\n")

            # Cleanup temp files
            shutil.rmtree(tmp_extract, ignore_errors=True)
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)

            await send("\n===================================\n")
            await send("  Update complete!\n")
            await send("  Restarting Decky Loader...\n")
            await send("===================================\n")
            await websocket.send_str(json.dumps({"status": "closed", "data": ""}))

            # Restart Decky Loader
            await sudo_exec("systemctl restart plugin_loader.service")

        except Exception as e:
            decky_plugin.logger.error(f"Self-update failed: {e}")
            try:
                await send(f"\nERROR: {e}\n")
                await websocket.send_str(json.dumps({"status": "closed", "data": ""}))
            except Exception:
                pass

    @staticmethod
    async def ws_handler(request):
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)

        try:
            async for message in websocket:
                decky_plugin.logger.info(f"ws_handler message: {message.data}")
                data = json.loads(message.data)
                if data["action"] == "install_dependencies":
                    await Helper.pyexec_subprocess(
                        "./scripts/install_deps.sh",
                        websocket=websocket,
                        stream_output=True,
                    )
                if data["action"] == "uninstall_dependencies":
                    await Helper.pyexec_subprocess(
                        "./scripts/install_deps.sh uninstall",
                        websocket=websocket,
                        stream_output=True,
                    )
                if data["action"] == "install_ge_proton":
                    await Helper.pyexec_subprocess(
                        "./scripts/install_ge_proton.sh",
                        websocket=websocket,
                        stream_output=True,
                    )
                if data["action"] == "self_update":
                    download_url = data.get("download_url", "")
                    sudo_password = data.get("sudo_password", "")
                    # Only allow updates from our GitHub repo
                    if download_url and ("github.com/Starkka15/junkstore" in download_url or "github.com/ebenbruyns/junkstore" in download_url):
                        await Helper.perform_self_update(download_url, websocket, sudo_password)
                    elif download_url:
                        decky_plugin.logger.error(f"Rejected self-update from untrusted URL: {download_url}")

        except Exception as e:
            decky_plugin.logger.error(f"Error in ws_handler: {e}")
        finally:
            # Ensure websocket is properly closed
            if not websocket.closed:
                await websocket.close()

        return websocket

    async def start_ws_server():
        Helper.ws_loop = asyncio.get_event_loop()
        # Don't use ThreadPoolExecutor for async tasks - just call directly
        await Helper._start_ws_server_thread()

    @staticmethod
    async def _start_ws_server_thread():
        try:
            Helper.wsServerIsRunning = True
            port = 8765
            while Helper.wsServerIsRunning:
                try:
                    decky_plugin.logger.info(
                        f"Starting WebSocket server on port {port}"
                    )

                    # Helper.runner.setup()
                    Helper.app = web.Application()
                    Helper.app.router.add_get("/ws", Helper.ws_handler)
                    Helper.runner = web.AppRunner(Helper.app)
                    await Helper.runner.setup()
                    Helper.site = web.TCPSite(Helper.runner, "localhost", port)

                    Helper.websocket_port = port
                    await Helper.site.start()
                    break
                except OSError:
                    port += 1

            decky_plugin.logger.info("WebSocket server started")

        except Exception as e:
            decky_plugin.logger.error(f"Error in start_ws_server: {e}")

    async def stop_ws_server():
        try:
            decky_plugin.logger.info("Stopping WebSocket server")

            # Signal the server to stop
            Helper.wsServerIsRunning = False

            # Stop the site
            if Helper.site:
                decky_plugin.logger.info("Stopping site")
                await Helper.site.stop()
                decky_plugin.logger.info("Site stopped")

            # Cleanup the runner
            if Helper.runner:
                await Helper.runner.cleanup()
                decky_plugin.logger.info("Runner cleaned up")

            # Clear references
            Helper.site = None
            Helper.runner = None
            Helper.app = None

        except Exception as e:
            decky_plugin.logger.error(f"Error in stop_ws_server: {e}")
        finally:
            # Stop the event loop if it exists
            if Helper.ws_loop and Helper.ws_loop.is_running():
                Helper.ws_loop.stop()
            Helper.ws_loop = None
            Helper.wsServerIsRunning = False
            decky_plugin.logger.info("WebSocket server stopped")

    @staticmethod
    def get_installed_extensions():
        """
        Get list of installed extension directory names by checking for static.json files
        Searches in both plugin dir and runtime dir (data)
        Returns a list of unique extension names (directory names containing static.json)
        """
        extensions = set()

        # Search paths
        search_paths = [
            os.path.join(decky_plugin.DECKY_PLUGIN_DIR, "scripts", "Extensions"),
            os.path.join(
                decky_plugin.DECKY_PLUGIN_RUNTIME_DIR, "scripts", "Extensions"
            ),
        ]

        for base_path in search_paths:
            if not os.path.exists(base_path):
                continue

            try:
                # Walk through the Extensions directory
                for root, dirs, files in os.walk(base_path):
                    # If this directory contains static.json
                    if "static.json" in files:
                        # Get the directory name relative to Extensions
                        rel_path = os.path.relpath(root, base_path)
                        # If it's directly under Extensions (not the Extensions dir itself)
                        if rel_path != ".":
                            # Get just the top-level directory name
                            ext_name = rel_path.split(os.sep)[0]
                            extensions.add(ext_name)

            except Exception as e:
                decky_plugin.logger.error(
                    f"Error scanning extensions in {base_path}: {e}"
                )

        # Convert to sorted list
        result = sorted(list(extensions))
        decky_plugin.logger.info(f"Found installed extensions: {result}")
        return result


# import requests


class Plugin:
    async def _main(self):
        decky_plugin.logger.info("GameVault starting up...")
        try:
            Helper.action_cache = {}
            if os.path.exists(
                os.path.join(decky_plugin.DECKY_PLUGIN_RUNTIME_DIR, "init.json")
            ):
                Helper.working_directory = decky_plugin.DECKY_PLUGIN_RUNTIME_DIR
            else:
                Helper.working_directory = decky_plugin.DECKY_PLUGIN_DIR

            decky_plugin.logger.info(
                f"plugin: {decky_plugin.DECKY_PLUGIN_NAME} dir: {decky_plugin.DECKY_PLUGIN_RUNTIME_DIR}"
            )
            # pass cmd argument to _call_script method
            decky_plugin.logger.info("GameVault initializing")
            result = await Helper.execute_action("init", "init")
            decky_plugin.logger.info("GameVault initialized")
            if Helper.verbose:
                decky_plugin.logger.info(f"init result: {result}")
            await Helper.start_ws_server()
            decky_plugin.logger.info("GameVault started")

        except Exception as e:
            decky_plugin.logger.error(f"Error in _main: {e}")

    async def reload(self):
        try:
            Helper.action_cache = {}
            if os.path.exists(
                os.path.join(decky_plugin.DECKY_PLUGIN_RUNTIME_DIR, "init.json")
            ):
                Helper.working_directory = decky_plugin.DECKY_PLUGIN_RUNTIME_DIR
            else:
                Helper.working_directory = decky_plugin.DECKY_PLUGIN_DIR

            decky_plugin.logger.info(
                f"plugin: {decky_plugin.DECKY_PLUGIN_NAME} dir: {decky_plugin.DECKY_PLUGIN_RUNTIME_DIR}"
            )
            # pass cmd argument to _call_script method
            result = await Helper.execute_action("init", "init")
            if Helper.verbose:
                decky_plugin.logger.info(f"init result: {result}")
        except Exception as e:
            decky_plugin.logger.error(f"Error in _main: {e}")

    async def get_websocket_port(self):
        return Helper.websocket_port

    async def get_plugin_version(self):
        try:
            pkg_path = os.path.join(decky_plugin.DECKY_PLUGIN_DIR, "package.json")
            with open(pkg_path, "r") as f:
                data = json.load(f)
            return data.get("version", "unknown")
        except Exception as e:
            decky_plugin.logger.error(f"Error reading plugin version: {e}")
            return "unknown"

    async def check_for_update(self):
        try:
            pkg_path = os.path.join(decky_plugin.DECKY_PLUGIN_DIR, "package.json")
            with open(pkg_path, "r") as f:
                data = json.load(f)
            current_version = data.get("version", "0.0.0")

            api_url = "https://api.github.com/repos/Starkka15/junkstore/releases/latest"
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=_make_ssl_context())
            ) as session:
                async with session.get(api_url, headers={"Accept": "application/vnd.github.v3+json"}) as response:
                    if response.status != 200:
                        return {
                            "Type": "Error",
                            "Content": {"Message": f"GitHub API returned status {response.status}"},
                        }
                    release = await response.json()

            latest_tag = release.get("tag_name", "")
            latest_version = latest_tag.lstrip("v")

            def version_tuple(v):
                # Tolerate non-version tags (e.g. "runtimes"): return None instead of crashing.
                parts = []
                for x in v.split("."):
                    digits = "".join(c for c in x if c.isdigit())
                    if digits == "":
                        return None
                    parts.append(int(digits))
                return tuple(parts) if parts else None

            lv = version_tuple(latest_version)
            cv = version_tuple(current_version)
            update_available = bool(lv and cv and lv > cv)

            # Find the built GameVault.zip release asset (not the source zipball)
            download_url = ""
            for asset in release.get("assets", []):
                if asset.get("name", "").endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

            return {
                "Type": "UpdateCheck",
                "Content": {
                    "current_version": current_version,
                    "latest_version": latest_version,
                    "update_available": update_available,
                    "download_url": download_url,
                    "release_name": release.get("name", ""),
                    "release_body": release.get("body", ""),
                },
            }
        except Exception as e:
            decky_plugin.logger.error(f"Error checking for update: {e}")
            return {
                "Type": "Error",
                "Content": {"Message": str(e)},
            }

    # ...

    async def execute_action(
        self, actionSet, actionName, inputData="", gameId="", appId="", *args, **kwargs
    ):
        try:
            decky_plugin.logger.info(f"execute_action: {actionSet} {actionName} ")
            decky_plugin.logger.info(f"execute_action args: {args}")
            if Helper.verbose:
                decky_plugin.logger.info(f"execute_action kwargs: {kwargs}")

            if isinstance(inputData, (dict, list)):
                inputData = json.dumps(inputData)

            result = await Helper.execute_action(
                actionSet,
                actionName,
                *args,
                *kwargs.values(),
                input_data=inputData,
                game_id=gameId,
                app_id=appId,
            )
            if Helper.verbose:
                decky_plugin.logger.info(f"execute_action result: {result}")
            return result
        except Exception as e:
            decky_plugin.logger.error(f"Error in execute_action: {e}")
            return None

    async def download_custom_backend(self, url, backup: bool = False):
        try:
            runtime_dir = decky_plugin.DECKY_PLUGIN_RUNTIME_DIR
            decky_plugin.logger.info(f"Downloading file from {url}")

            # Create a temporary file to save the downloaded zip file
            temp_file = "/tmp/custom_backend.zip"
            # disabling ssl verfication for testing, github doesn't seem to have a valid ssl cert, seems wrong
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=_make_ssl_context())
            ) as session:
                decky_plugin.logger.info(f"Downloading {url}")
                async with session.get(url, allow_redirects=True) as response:
                    decky_plugin.logger.debug(f"Response status: {response}")
                    # assert response.status == 200
                    with open(temp_file, "wb") as f:
                        while True:
                            chunk = await response.content.readany()
                            if not chunk:
                                break
                            f.write(chunk)
            decky_plugin.logger.debug(f"Downloaded {temp_file} from {url}")
            # Extract the contents of the zip file to the runtime directory

            if backup:
                # Find the latest backup folder
                decky_plugin.logger.info("Creating backup")
                backup_dir = os.path.join(runtime_dir, "backup")
                backup_count = 1
                while os.path.exists(f"{backup_dir} {backup_count}"):
                    backup_count += 1
                latest_backup_dir = f"{backup_dir} {backup_count}"
                decky_plugin.logger.info(f"Creating backup at {latest_backup_dir}")

                # Create the latest backup folder
                os.makedirs(latest_backup_dir, exist_ok=True)

                # Move non-backup files to the latest backup folder
                for item in os.listdir(runtime_dir):
                    item_path = os.path.join(runtime_dir, item)
                    if (
                        os.path.isfile(item_path) or os.path.isdir(item_path)
                    ) and not item.startswith("backup"):
                        if item.endswith(".db"):
                            shutil.copy(item_path, latest_backup_dir)
                        else:
                            shutil.move(item_path, latest_backup_dir)
                decky_plugin.logger.info("Backup completed successfully")

            with zipfile.ZipFile(temp_file, "r") as zip_ref:
                # Validate all paths before extraction (path traversal check)
                for member in zip_ref.namelist():
                    member_path = os.path.realpath(os.path.join(runtime_dir, member))
                    if not member_path.startswith(os.path.realpath(runtime_dir) + os.sep) and member_path != os.path.realpath(runtime_dir):
                        raise Exception(f"Path traversal detected in zip: {member}")
                zip_ref.extractall(runtime_dir)
                scripts_dir = os.path.join(
                    decky_plugin.DECKY_PLUGIN_RUNTIME_DIR, "scripts"
                )
                for root, dirs, files in os.walk(scripts_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        os.chmod(file_path, 0o755)

            # Clear action cache so new scripts are picked up
            Helper.action_cache.clear()
            decky_plugin.logger.info("Download and extraction completed successfully")

        except Exception as e:
            decky_plugin.logger.error(f"Error in download_custom_backend: {e}")
        finally:
            # Clean up temp file
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    decky_plugin.logger.info(f"Cleaned up temp file: {temp_file}")
                except Exception as e:
                    decky_plugin.logger.warning(f"Failed to remove temp file: {e}")

    async def get_storage_stats(self):
        try:
            runtime_dir = decky_plugin.DECKY_PLUGIN_RUNTIME_DIR
            home = os.path.abspath(decky_plugin.DECKY_USER_HOME)

            STORES = {
                "GOG": "gog.db",
                "Epic": "epic.db",
                "Amazon": "amazon.db",
                "itch.io": "itchio.db",
            }

            def parse_size(size_str):
                if not size_str or not isinstance(size_str, str):
                    return 0
                try:
                    parts = size_str.strip().split()
                    if len(parts) != 2:
                        return 0
                    value = float(parts[0])
                    unit = parts[1].upper()
                    if unit == "GB": return int(value * 1024**3)
                    elif unit == "MB": return int(value * 1024**2)
                    elif unit == "KB": return int(value * 1024)
                    return 0
                except Exception:
                    return 0

            def fmt_bytes(size):
                if size >= 1024**3: return f"{size / 1024**3:.2f} GB"
                elif size >= 1024**2: return f"{size / 1024**2:.2f} MB"
                elif size >= 1024: return f"{size / 1024:.2f} KB"
                return f"{size} bytes"

            import time as _time
            def dir_size(path):
                """Calculate total size of a directory by walking it. Cached for 5 minutes."""
                now = _time.time()
                cached = Helper.dir_size_cache.get(path)
                if cached and (now - cached[1]) < 300:
                    return cached[0]
                total = 0
                try:
                    for dirpath, _, filenames in os.walk(path):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            try:
                                total += os.path.getsize(fp)
                            except OSError:
                                pass
                except OSError:
                    pass
                Helper.dir_size_cache[path] = (total, now)
                return total

            stores = []
            all_games = []

            for store_name, db_filename in STORES.items():
                db_path = os.path.join(runtime_dir, db_filename)
                if not os.path.exists(db_path):
                    continue
                try:
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.row_factory = sqlite3.Row
                    c = conn.cursor()
                    c.execute(
                        "SELECT ShortName, Title, Size, InstallPath, RootFolder FROM Game "
                        "WHERE SteamClientID IS NOT NULL AND SteamClientID <> ''"
                    )
                    games = c.fetchall()
                    conn.close()

                    store_total = 0
                    for g in games:
                        sb = parse_size(g["Size"])
                        size_label = g["Size"]

                        # If no size in DB, calculate from install directory
                        if sb == 0:
                            game_dir = g["RootFolder"] or g["InstallPath"]
                            if game_dir and os.path.isdir(game_dir):
                                sb = dir_size(game_dir)
                                size_label = fmt_bytes(sb) if sb > 0 else None

                        store_total += sb
                        all_games.append({
                            "shortname": g["ShortName"],
                            "store": store_name,
                            "title": g["Title"] or g["ShortName"],
                            "size": size_label or "Unknown",
                            "size_bytes": sb,
                        })
                    stores.append({
                        "name": store_name,
                        "size": fmt_bytes(store_total),
                        "size_bytes": store_total,
                        "count": len(games),
                    })
                except Exception as e:
                    decky_plugin.logger.error(f"Error reading {store_name} DB: {e}")

            all_games.sort(key=lambda g: g["size_bytes"], reverse=True)
            stores.sort(key=lambda s: s["size_bytes"], reverse=True)
            total_used = sum(s["size_bytes"] for s in stores)

            disk_spaces = []
            try:
                usage = shutil.disk_usage(home)
                disk_spaces.append({
                    "location": "Internal Storage",
                    "path": home,
                    "free": fmt_bytes(usage.free),
                    "free_bytes": usage.free,
                    "total": fmt_bytes(usage.total),
                    "total_bytes": usage.total,
                    "used_percent": round((usage.used / usage.total) * 100, 1),
                })
            except Exception:
                pass

            sd_paths = ["/run/media/mmcblk0p1"]
            try:
                for entry in os.scandir("/run/media"):
                    if entry.is_symlink() or entry.is_dir():
                        sd_paths.append(entry.path)
            except Exception:
                pass

            seen = set()
            for p in sd_paths:
                if os.path.exists(p) and os.path.ismount(p):
                    try:
                        usage = shutil.disk_usage(p)
                        if usage.total in seen:
                            continue
                        seen.add(usage.total)
                        disk_spaces.append({
                            "location": "MicroSD Card",
                            "path": p,
                            "free": fmt_bytes(usage.free),
                            "free_bytes": usage.free,
                            "total": fmt_bytes(usage.total),
                            "total_bytes": usage.total,
                            "used_percent": round((usage.used / usage.total) * 100, 1),
                        })
                    except Exception:
                        pass

            return {
                "Type": "StorageStats",
                "Content": {
                    "total_used": fmt_bytes(total_used),
                    "total_used_bytes": total_used,
                    "total_games": sum(s["count"] for s in stores),
                    "stores": stores,
                    "games": all_games,
                    "disk_spaces": disk_spaces,
                }
            }
        except Exception as e:
            decky_plugin.logger.error(f"Error in get_storage_stats: {e}")
            return {
                "Type": "Error",
                "Content": {"Message": str(e)},
            }

    async def get_logs(self):
        log_dir = decky_plugin.DECKY_PLUGIN_LOG_DIR
        log_files = []
        for file in os.listdir(log_dir):
            if file.endswith(".log"):
                file_path = os.path.join(log_dir, file)
                try:
                    with open(file_path, "r") as f:
                        content = f.read()
                        log_files.append({"FileName": file, "Content": content})
                except Exception:
                    pass
        log_files.sort(key=lambda x: x["FileName"], reverse=True)
        console_log = os.path.join(
            decky_plugin.DECKY_USER_HOME, ".local/share/Steam/logs/console_log.txt"
        )
        if os.path.exists(console_log):
            try:
                with open(console_log, "r") as f:
                    content = f.read()
                    log_files.append({"FileName": "console_log.txt", "Content": content})
            except Exception:
                pass

        return log_files

    async def _unload(self):
        try:
            decky_plugin.logger.info("Starting plugin unload...")

            # Stop WebSocket server
            await Helper.stop_ws_server()

            # Cancel all pending asyncio tasks except this one
            current_task = asyncio.current_task()
            tasks = [task for task in asyncio.all_tasks() if not task.done() and task is not current_task]
            if tasks:
                decky_plugin.logger.info(f"Cancelling {len(tasks)} pending tasks...")
                for task in tasks:
                    task.cancel()
                # Wait for all tasks to complete cancellation
                await asyncio.gather(*tasks, return_exceptions=True)

            # Clear the action cache
            Helper.action_cache.clear()

            decky_plugin.logger.info("GameVault out!")
        except Exception as e:
            decky_plugin.logger.error(f"Error during unload: {e}")

    async def _migration(self):
        plugin_dir = "GameVault"
        decky_plugin.logger.info("Migrating")
        # Here's a migration example for logs:
        # - `~/.config/decky-template/template.log` will be migrated to `decky_plugin.DECKY_PLUGIN_LOG_DIR/template.log`
        decky_plugin.migrate_logs(
            os.path.join(
                decky_plugin.DECKY_USER_HOME, ".config", plugin_dir, "template.log"
            )
        )
        # Here's a migration example for settings:
        # - `~/homebrew/settings/template.json` is migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/template.json`
        # - `~/.config/decky-template/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/`
        decky_plugin.migrate_settings(
            os.path.join(decky_plugin.DECKY_HOME, "settings", "template.json"),
            os.path.join(decky_plugin.DECKY_USER_HOME, ".config", plugin_dir),
        )
        # Here's a migration example for runtime data:
        # - `~/homebrew/template/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_RUNTIME_DIR/`
        # - `~/.local/share/decky-template/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_RUNTIME_DIR/`
        decky_plugin.migrate_runtime(
            os.path.join(decky_plugin.DECKY_HOME, plugin_dir),
            os.path.join(decky_plugin.DECKY_USER_HOME, ".local", "share", plugin_dir),
        )
