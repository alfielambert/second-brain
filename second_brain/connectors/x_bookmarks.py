"""
x_bookmarks - flagship connector. OAuth 2.0 PKCE against the live X API,
incremental fetch (stops as soon as it reaches a tweet it's already seen),
no MCP dependency, works with your own X developer app.

Every new bookmark becomes one weak claim (claim_type=signal,
operation=weak_inference, confidence=low) - saving a tweet is evidence a
topic matters, not yet an asserted fact. KEP always routes these to
"signal", so running this connector never produces approval spam. If you
want richer claim extraction (deciding a bookmark is actually a fact,
decision, or hypothesis), that's exactly the kind of judgement call the
Claude Code layer is for - see claude/README.md.

The first run opens a browser for authorization. Subsequent runs reuse the
stored token and refresh it automatically.

Setup: create a `.env` at your vault root containing:
    X_CLIENT_ID=your_client_id_here
(get one free at https://developer.x.com - a "public client" App with the
"bookmark.read tweet.read users.read offline.access" scopes is enough).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

try:
    import requests
    from dotenv import load_dotenv
except ImportError:
    requests = None  # imported lazily so `second-brain init` doesn't require it

from second_brain import claimstore, health

NAME = "x_bookmarks"
REDIRECT_URI = "http://localhost:3000/callback"
SCOPES = "bookmark.read tweet.read users.read offline.access"
AUTH_ENDPOINT = "https://x.com/i/oauth2/authorize"
TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"
PORT = 3000
MAX_RESULTS_PER_PAGE = 20


def _tokens_path(vault_root: Path) -> Path:
    return vault_root / ".tokens.json"


def _seen_ids_path(vault_root: Path) -> Path:
    return vault_root / "ClaimStore" / "state" / "x_bookmarks_seen.json"


def _load_client_id(vault_root: Path) -> str:
    load_dotenv(vault_root / ".env")
    return os.environ.get("X_CLIENT_ID", "")


def _load_tokens(vault_root: Path) -> Optional[dict]:
    path = _tokens_path(vault_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_tokens(vault_root: Path, tokens: dict) -> None:
    _tokens_path(vault_root).write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def _refresh_access_token(client_id: str, refresh_token: str) -> Optional[dict]:
    resp = requests.post(TOKEN_ENDPOINT, data={
        "grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id,
    })
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_at": time.time() + data.get("expires_in", 7200) - 60,
    }


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


_callback: dict = {}
_received = threading.Event()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _callback["code"] = params.get("code", [None])[0]
        _callback["state"] = params.get("state", [None])[0]
        _callback["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Authenticated. You can close this tab.</h1>")
        _received.set()

    def log_message(self, *_):
        pass


def _authenticate(client_id: str) -> dict:
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })

    _received.clear()
    _callback.clear()
    server = HTTPServer(("localhost", PORT), _CallbackHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Opening browser for X authorization...")
    print(f"If it does not open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    _received.wait(timeout=120)
    server.shutdown()
    if not _received.is_set():
        raise RuntimeError("Timed out waiting for X authorization (120s).")
    if _callback.get("error"):
        raise RuntimeError(f"Error from X: {_callback['error']}")
    if _callback.get("state") != state:
        raise RuntimeError("state mismatch on X OAuth callback - possible CSRF, aborting.")

    resp = requests.post(TOKEN_ENDPOINT, data={
        "grant_type": "authorization_code", "code": _callback["code"],
        "redirect_uri": REDIRECT_URI, "code_verifier": verifier, "client_id": client_id,
    })
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": time.time() + data.get("expires_in", 7200) - 60,
    }


def _get_valid_token(vault_root: Path, client_id: str) -> str:
    tokens = _load_tokens(vault_root)
    if tokens:
        if time.time() < tokens.get("expires_at", 0):
            return tokens["access_token"]
        if tokens.get("refresh_token"):
            refreshed = _refresh_access_token(client_id, tokens["refresh_token"])
            if refreshed:
                _save_tokens(vault_root, refreshed)
                return refreshed["access_token"]
    token_data = _authenticate(client_id)
    _save_tokens(vault_root, token_data)
    return token_data["access_token"]


def _get_user_id(token: str) -> str:
    resp = requests.get("https://api.x.com/2/users/me", headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        raise RuntimeError(f"users/me failed ({resp.status_code}): {resp.text}")
    return resp.json()["data"]["id"]


def _expand_urls(text: str, url_entities: list[dict]) -> str:
    for entity in url_entities:
        short = entity.get("url", "")
        if short:
            text = text.replace(short, entity.get("expanded_url", short))
    return text


def _extract_tags(entities: dict) -> list[str]:
    return [
        (h.get("tag") or h.get("text", "")).lower()
        for h in entities.get("hashtags", []) if h.get("tag") or h.get("text")
    ]


def discover(vault_root: Path, limit: Optional[int] = None) -> list[dict]:
    """Fetch new bookmarks from the live X API, stopping at ones already seen."""
    if requests is None:
        raise RuntimeError("Missing dependency: pip install requests python-dotenv")
    client_id = _load_client_id(vault_root)
    if not client_id:
        raise RuntimeError(f"X_CLIENT_ID not set. Create {vault_root / '.env'} with X_CLIENT_ID=...")

    seen_path = _seen_ids_path(vault_root)
    known_ids = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()

    token = _get_valid_token(vault_root, client_id)
    user_id = _get_user_id(token)

    headers = {"Authorization": f"Bearer {token}"}
    params = {"max_results": MAX_RESULTS_PER_PAGE, "expansions": "author_id",
              "tweet.fields": "created_at,text,entities", "user.fields": "username"}
    results: list[dict] = []

    while True:
        resp = requests.get(f"https://api.x.com/2/users/{user_id}/bookmarks", headers=headers, params=params)
        if resp.status_code == 429:
            print("Rate limited (429) - wait 15 minutes and re-run.", file=sys.stderr)
            break
        if resp.status_code != 200:
            raise RuntimeError(f"bookmarks API error ({resp.status_code}): {resp.text}")

        payload = resp.json()
        tweets = payload.get("data", [])
        if not tweets:
            break
        author_lookup = {u["id"]: u["username"] for u in payload.get("includes", {}).get("users", [])}

        last_was_known = False
        for tweet in tweets:
            tweet_id = tweet.get("id", "")
            if tweet_id in known_ids:
                last_was_known = True
                continue
            last_was_known = False
            results.append({"tweet": tweet, "author_username": author_lookup.get(tweet.get("author_id", ""), "unknown")})
            if limit is not None and len(results) >= limit:
                return results

        if last_was_known:
            break
        next_token = payload.get("meta", {}).get("next_token")
        if not next_token:
            break
        params["pagination_token"] = next_token

    return results


def fetch(item: dict) -> dict:
    return item  # discover() already returns full tweet content


def normalise(raw: dict) -> dict:
    tweet = raw["tweet"]
    author = raw["author_username"]
    tweet_id = tweet.get("id", "")
    entities = tweet.get("entities", {})
    text = _expand_urls(tweet.get("text", ""), entities.get("urls", []))
    return {
        "source": {
            "id": tweet_id,
            "type": "tweet",
            "occurred_at": tweet.get("created_at"),
            "title": text.split("\n")[0][:80],
            "url": f"https://x.com/{author}/status/{tweet_id}" if tweet_id else None,
        },
        "text": text,
        "author": author,
        "tags": _extract_tags(entities),
    }


def extract_claims(normalised: dict) -> list[dict]:
    return [{
        "connector": NAME,
        "source": normalised["source"],
        "claim_type": "signal",
        "entities": [],
        "content": normalised["text"][:500],
        "evidence": [{"text": normalised["text"], "speaker": normalised["author"], "location": normalised["source"]["url"]}],
        "confidence": "low",
        "operation": "weak_inference",
    }]


def update_cursor(vault_root: Path, item: dict) -> None:
    seen_path = _seen_ids_path(vault_root)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    known = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    known.add(item["tweet"]["id"])
    seen_path.write_text(json.dumps(sorted(known)))


def get_health(vault_root: Path) -> dict:
    return health.get_state(NAME, vault_root=vault_root)
