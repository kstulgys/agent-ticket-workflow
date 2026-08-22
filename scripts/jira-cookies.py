#!/usr/bin/env python3
"""Decrypt the logged-in GLOBEX Atlassian session from Chrome -> /tmp/jira-state.json.

Why this exists: this environment has no Atlassian MCP, so every Jira read/write
goes through the user's live browser session + the Jira REST API. This script
produces the cookie state you inject into a browser tab (page.setCookie) and,
from the same file, the Cookie header you use to download attachments.

Usage:
    python3 scripts/jira-cookies.py        # writes /tmp/jira-state.json, prints a summary

Requires: secretstorage + cryptography (`pip install --user secretstorage cryptography`
if missing) and an unlocked gnome login keyring (DISPLAY + DBUS present in a desktop
session). Read-only on Chrome's cookie DB.

Security: /tmp/jira-state.json holds LIVE session tokens. Delete it when you finish
(`rm -f /tmp/jira-state.json`) and close the browser — the workflow does this each turn.
"""

import glob
import hashlib
import json
import os
import sqlite3
import sys

import secretstorage
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHROME = os.path.expanduser("~/.config/google-chrome")
TARGET = "globex.atlassian.net"
OUT = "/tmp/jira-state.json"


def chrome_key() -> bytes:
    """AES key Chrome derives from the keyring secret 'Chrome Safe Storage'."""
    con = secretstorage.dbus_init()
    for coll in secretstorage.get_all_collections(con):
        for item in coll.get_all_items():
            if item.get_attributes().get("application") == "chrome":
                return hashlib.pbkdf2_hmac("sha1", item.get_secret(), b"saltysalt", 1, 16)
    sys.exit("Chrome keyring secret not found (is the login keyring unlocked?)")


def find_profile() -> str:
    """Return the Cookies DB of the profile that holds the globexnl session.

    Don't hardcode 'Profile 4' — the Example profile moves. Pick whichever profile
    actually has the tenant.session.token for globexnl.
    """
    for db in glob.glob(f"{CHROME}/*/Cookies"):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            hit = con.execute(
                "SELECT 1 FROM cookies WHERE host_key LIKE ? AND name='tenant.session.token'",
                (f"%{TARGET}",),
            ).fetchone()
            con.close()
            if hit:
                return db
        except sqlite3.Error:
            continue
    sys.exit(f"No Chrome profile has a {TARGET} session — log in to Jira in Chrome first.")


def main() -> None:
    key = chrome_key()
    db = find_profile()

    def dec(v: bytes) -> str:
        if v[:3] == b"v11":
            d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
            p = d.update(v[3:]) + d.finalize()
            p = p[: -p[-1]]
            return p[32:].decode("utf-8", "replace")  # strip 32-byte sha256 domain prefix (Chrome >= v24)
        return v.decode("utf-8", "replace")

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    state = {"cookies": [], "origins": []}
    for h, n, pa, sec, ho, exp, sm, ev in con.execute(
        "SELECT host_key,name,path,is_secure,is_httponly,expires_utc,samesite,encrypted_value "
        "FROM cookies WHERE host_key LIKE '%atlassian%'"
    ):
        state["cookies"].append(
            {
                "name": n,
                "value": dec(ev),
                "domain": h,
                "path": pa,
                "expires": (exp / 1_000_000 - 11644473600) if exp else -1,
                "httpOnly": bool(ho),
                "secure": bool(sec),
                "sameSite": {0: "None", 1: "Lax", 2: "Strict"}.get(sm, "Lax"),
            }
        )
    json.dump(state, open(OUT, "w"))
    has_token = any(
        c["name"] == "tenant.session.token" and TARGET in c["domain"] for c in state["cookies"]
    )
    print(
        f"profile={os.path.dirname(db)!r} cookies={len(state['cookies'])} "
        f"{TARGET}_token={'yes' if has_token else 'MISSING'} -> {OUT}"
    )
    if not has_token:
        sys.exit(1)


if __name__ == "__main__":
    main()
