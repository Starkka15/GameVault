#!/usr/bin/env python3
"""OAuth helper for store login flows (GOG, Amazon).

Opens a real browser (not Steam overlay) for login,
then uses kdialog/zenity to capture the redirect URL.
"""
import json
import os
import subprocess
import sys


def find_browser():
    """Find a real browser (not Steam overlay). Returns command list or None."""
    # Try Firefox flatpak first (most common on SteamOS)
    try:
        result = subprocess.run(
            ['flatpak', 'list', '--app', '--columns=application'],
            capture_output=True, text=True
        )
        if 'org.mozilla.firefox' in result.stdout:
            return ['flatpak', 'run', 'org.mozilla.firefox']
    except FileNotFoundError:
        pass

    # Try system Firefox
    for browser in ['firefox', 'chromium', 'chromium-browser', 'google-chrome']:
        try:
            subprocess.run(['which', browser], capture_output=True, check=True)
            return [browser]
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    return None


def open_url(url):
    """Open URL in a real browser, falling back to xdg-open."""
    browser = find_browser()
    if browser:
        print(f"Opening URL in {browser[0]}...")
        subprocess.Popen(browser + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("Opening URL with xdg-open...")
        subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_dialog(title, message):
    """Show a dialog to get user input. Tries kdialog, then zenity, then terminal."""
    # Try kdialog (KDE/SteamOS)
    try:
        result = subprocess.run(
            ['kdialog', '--title', title, '--inputbox', message],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try zenity (GNOME)
    try:
        result = subprocess.run(
            ['zenity', '--entry', '--title', title, '--text', message,
             '--width', '500'],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: terminal input
    try:
        return input(message + "\n> ").strip()
    except EOFError:
        return None


def extract_code_from_url(url, param_name):
    """Extract a query parameter from a URL."""
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        codes = params.get(param_name, [])
        return codes[0] if codes else None
    except Exception:
        return None


def gog_login(auth_tokens_path):
    """Handle GOG OAuth login flow — replaces lgogdownloader --gui-login."""
    from urllib.parse import urlparse, parse_qs, urlencode
    import urllib.request
    import urllib.error

    GOG_CLIENT_ID = '46899977096215655'
    GOG_CLIENT_SECRET = '9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9'
    REDIRECT_URI = 'https://embed.gog.com/on_login_success?origin=client'

    auth_url = (
        f'https://auth.gog.com/auth?client_id={GOG_CLIENT_ID}'
        '&redirect_uri=https%3A%2F%2Fembed.gog.com%2Fon_login_success%3Forigin%3Dclient'
        '&response_type=code&layout=galaxy'
    )

    open_url(auth_url)

    user_input = show_dialog(
        "GOG Login",
        "1. Log in to GOG in the browser window\n"
        "2. After login, you'll be redirected to a page\n"
        "3. Copy the ENTIRE URL from the address bar\n"
        "   (it will contain 'code=' in it)\n"
        "4. Paste it here and click OK"
    )

    if not user_input:
        print("No input received", file=sys.stderr)
        return False

    code = extract_code_from_url(user_input, 'code')
    if not code:
        code = user_input.strip()

    if not code:
        print("Could not extract authorization code", file=sys.stderr)
        return False

    print(f"Got authorization code ({len(code)} chars), exchanging for tokens...", file=sys.stderr)

    # GOG's token endpoint expects query parameters, not POST body
    token_url = 'https://auth.gog.com/token?' + urlencode({
        'client_id': GOG_CLIENT_ID,
        'client_secret': GOG_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    })

    req = urllib.request.Request(token_url)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"Token exchange failed: {e} — Response: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Token exchange failed: {e}", file=sys.stderr)
        return False

    import time
    gogdl_tokens = {
        'access_token': tokens['access_token'],
        'expires_in': tokens['expires_in'],
        'token_type': tokens['token_type'],
        'scope': tokens.get('scope', ''),
        'session_id': tokens.get('session_id', ''),
        'refresh_token': tokens['refresh_token'],
        'user_id': tokens.get('user_id', ''),
        'loginTime': int(time.time()),
    }

    auth_data = {GOG_CLIENT_ID: gogdl_tokens}

    os.makedirs(os.path.dirname(auth_tokens_path), exist_ok=True)
    with open(auth_tokens_path, 'w') as f:
        json.dump(auth_data, f, indent=2)

    print("GOG login successful, tokens saved.", file=sys.stderr)
    return True


def _nile_login_data(nile_bin):
    """Ask nile to start a login and return (login_data, result).

    nile prints the login JSON to stdout, but SteamOS mixes in LD_PRELOAD noise,
    so parse line-by-line rather than json.loads()-ing the whole stream."""
    result = subprocess.run(
        [nile_bin, 'auth', '--login', '--non-interactive'],
        capture_output=True, text=True
    )
    for output in (result.stdout, result.stderr):
        for line in (output or '').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict) and data.get('url'):
                return data, result
    return None, result


def amazon_login(nile_bin):
    """Handle Amazon two-step device registration login flow."""
    # Step 1: Get login data from nile
    print("Getting Amazon login data...")
    login_data, result = _nile_login_data(nile_bin)

    # nile refuses to start a login while a session already exists (it returns no
    # url, e.g. "You are already logged in"). A stale session can survive a
    # GameVault logout, which would otherwise make re-login impossible. Detecting
    # this by the ABSENCE of a url (not a specific message) keeps it robust across
    # nile versions/locales: force a clean logout — `nile auth --logout` deregisters
    # the device and clears its tokens — then retry once.
    if not login_data:
        print("No login url from nile; forcing a clean logout and retrying...", file=sys.stderr)
        subprocess.run([nile_bin, 'auth', '--logout'], capture_output=True, text=True)
        login_data, result = _nile_login_data(nile_bin)

    if not login_data or not login_data.get('url'):
        print(f"Failed to get login data from nile", file=sys.stderr)
        print(f"stdout: {result.stdout}", file=sys.stderr)
        print(f"stderr: {result.stderr}", file=sys.stderr)
        return False

    login_url = login_data['url']
    code_verifier = login_data.get('code_verifier', '')
    serial = login_data.get('serial', '')
    client_id = login_data.get('client_id', '')

    # Open in a real browser (Firefox) instead of Steam overlay
    open_url(login_url)

    user_input = show_dialog(
        "Amazon Games Login",
        "1. Log in to Amazon in the browser window\n"
        "2. Complete any 2FA/verification steps\n"
        "3. After redirect, copy the URL from the address bar\n"
        "   (tap the address bar, Select All, Copy)\n"
        "4. Paste it here and click OK"
    )

    if not user_input:
        print("No input received", file=sys.stderr)
        return False

    # Extract the authorization code from the URL
    code = extract_code_from_url(user_input, 'openid.oa2.authorization_code')
    if not code:
        # Maybe they pasted just the code
        code = user_input.strip()

    if not code:
        print("Could not extract authorization code", file=sys.stderr)
        return False

    print("Got authorization code, completing registration...")
    cmd = [
        nile_bin, 'register',
        '--code', code,
        '--code-verifier', code_verifier,
        '--serial', serial,
        '--client-id', client_id
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return True


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <store> <arg>")
        print(f"  {sys.argv[0]} amazon <nile_binary_path>")
        print(f"  {sys.argv[0]} gog <auth_tokens_path>")
        sys.exit(1)

    store = sys.argv[1]
    arg = sys.argv[2]

    if store == 'amazon':
        success = amazon_login(arg)
    elif store == 'gog':
        success = gog_login(arg)
    else:
        print(f"Unknown store: {store}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if success else 1)
