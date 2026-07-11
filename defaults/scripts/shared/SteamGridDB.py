import json
import re
import sys
import difflib
import urllib.request
import urllib.parse


class SteamGridDB:
    BASE_URL = "https://www.steamgriddb.com/api/v2"
    PLATFORM_MAP = {"gog": "gog", "epic": "egs", "itchio": "itch"}

    # Maps SGDB endpoint → Images table Type
    IMAGE_ENDPOINTS = {
        "grids": {"params": "dimensions=600x900&types=static", "type": "vertical_cover"},
        "heroes": {"params": "types=static", "type": "horizontal_artwork"},
        "logos": {"params": "types=static", "type": "logo"},
        "icons": {"params": "types=static", "type": "square_icon"},
    }

    def __init__(self, api_key):
        self.api_key = api_key

    def _request(self, endpoint):
        url = f"{self.BASE_URL}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "GameVault/1.0",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=15)
            data = json.loads(response.read())
            if data.get("success"):
                return data.get("data", [])
        except Exception as e:
            print(f"SteamGridDB API error ({endpoint}): {e}", file=sys.stderr)
        return None

    @staticmethod
    def _norm(s):
        """Normalize a title for comparison: lowercase, drop everything non-alphanumeric,
        and strip a trailing version tag (v1.2, 0.3.4, build junk) that repack folder
        names often carry."""
        s = (s or "").lower()
        s = re.sub(r'[\s_\-]+v?\d+(\.\d+)*[a-z]?$', '', s)   # trailing version token
        return re.sub(r'[^a-z0-9]', '', s)

    @classmethod
    def _name_matches(cls, query, candidate):
        """Confident name-match guard. Only accept a SGDB candidate when we're sure it's
        the same game, so we never apply someone else's cover art. Rules (query = our
        title, candidate = SGDB name):
          - exact normalized equality → accept
          - candidate starts with query (SGDB carries a subtitle we lack, e.g. our
            'Voronica Cleans House' vs 'Voronica Cleans House: a Vore Adventure')
          - very high fuzzy ratio (punctuation/spacing differences only)
        A minimum query length gates the prefix/fuzzy paths so short tokens like 'MMA'
        can't latch onto 'MMA Simulator'."""
        q, c = cls._norm(query), cls._norm(candidate)
        if not q or not c:
            return False
        if q == c:
            return True
        if len(q) < 6:
            return False
        if c.startswith(q):
            return True
        return difflib.SequenceMatcher(None, q, c).ratio() >= 0.9

    def find_game(self, store_name, game_id, game_name):
        """Find a game on SGDB. Tries platform ID first, falls back to a NAME-guarded search
        (only returns a hit whose name confidently matches — see _name_matches)."""
        platform = self.PLATFORM_MAP.get(store_name)
        if platform and game_id:
            encoded_id = urllib.parse.quote(str(game_id), safe="")
            data = self._request(f"games/by-platform-id?platform={platform}&id={encoded_id}")
            if data and len(data) > 0:
                sgdb_id = data[0].get("id")
                if sgdb_id:
                    print(f"SteamGridDB: found game by platform {platform}/{game_id} → {sgdb_id}", file=sys.stderr)
                    return sgdb_id

        # Fallback: search by name, but only accept a confident match. Scan all
        # candidates (the right game isn't always the top autocomplete hit) and prefer
        # an exact normalized match over a prefix/fuzzy one.
        if game_name:
            encoded_name = urllib.parse.quote(game_name, safe="")
            data = self._request(f"search/autocomplete/{encoded_name}")
            if data:
                fallback = None
                for cand in data:
                    name = cand.get("name", "")
                    cid = cand.get("id")
                    if not cid or not self._name_matches(game_name, name):
                        continue
                    if self._norm(game_name) == self._norm(name):
                        print(f"SteamGridDB: name match '{game_name}' → '{name}' ({cid})", file=sys.stderr)
                        return cid
                    fallback = fallback or (cid, name)
                if fallback:
                    print(f"SteamGridDB: name match '{game_name}' → '{fallback[1]}' ({fallback[0]})", file=sys.stderr)
                    return fallback[0]

        print(f"SteamGridDB: no confident match for {store_name}/{game_id} '{game_name}'", file=sys.stderr)
        return None

    def get_images(self, sgdb_game_id):
        """Fetch image URLs for all slots. Returns {type: url} dict."""
        result = {}
        for endpoint, info in self.IMAGE_ENDPOINTS.items():
            data = self._request(f"{endpoint}/game/{sgdb_game_id}?{info['params']}")
            if data and len(data) > 0:
                url = data[0].get("url")
                if url:
                    result[info["type"]] = url
        return result
