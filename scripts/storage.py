"""Optional Supabase storage shared by collection and dispatch."""
from datetime import datetime, timezone

import requests

from .config import env


def enabled():
    url, key = env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY")
    if bool(url) != bool(key):
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set")
    return bool(url)


def request(method, table, **kwargs):
    if table not in ("news_drafts", "news_exclusions", "news_alert_state", "news_bot_settings"):
        raise ValueError("Unknown news table")
    response = requests.request(
        method, f"{env('SUPABASE_URL').rstrip('/')}/rest/v1/{table}",
        headers={
            "apikey": env("SUPABASE_SERVICE_ROLE_KEY"),
            "Authorization": f"Bearer {env('SUPABASE_SERVICE_ROLE_KEY')}",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }, timeout=25, **kwargs,
    )
    if not response.ok:
        raise RuntimeError(f"Supabase {table}: HTTP {response.status_code}")
    return response


def read(table, date):
    rows = request("GET", table, params={"date": f"eq.{date}", "select": "payload"}).json()
    return rows[0]["payload"] if rows else None


def save_draft(digest):
    request("POST", "news_drafts", params={"on_conflict": "date"}, json={
        "date": digest.date, "payload": digest.to_dict(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
