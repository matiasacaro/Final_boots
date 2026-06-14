#!/usr/bin/env python3
"""
Muestra los partidos de Copa del Mundo 2026 de hoy y los próximos.
Uso: python schedule.py
     python schedule.py --next 5       (ver próximos 5 partidos)
     python schedule.py --all          (ver todos los partidos del torneo)
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"

FOOTBALL_API = "https://api.football-data.org/v4"
COMPETITION = "WC"

# Argentina = UTC-3
TZ_OFFSET = timedelta(hours=-3)

STATUS_LABEL = {
    "SCHEDULED": "📅 Programado",
    "TIMED":     "🕐 Confirmado",
    "IN_PLAY":   "🔴 EN VIVO (1T)",
    "PAUSED":    "🔴 ENTRETIEMPO",
    "EXTRA_TIME":"🔴 PRÓRROGA",
    "PENALTY_SHOOTOUT": "🔴 PENALES",
    "FINISHED":  "✅ Finalizado",
    "POSTPONED": "⚠️  Postergado",
    "CANCELLED": "❌ Cancelado",
    "SUSPENDED": "⛔ Suspendido",
}


def load_config():
    if not CONFIG_FILE.exists():
        print("❌ config.json no encontrado. Ejecuta primero: python setup.py")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def api_get(api_key, path, params=None):
    headers = {"X-Auth-Token": api_key}
    r = requests.get(f"{FOOTBALL_API}{path}", headers=headers, params=params, timeout=15)
    if r.status_code == 429:
        print("⚠️  Límite de API alcanzado. Esperá un minuto.")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


def fmt_time(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        dt_arg = dt + TZ_OFFSET
        return dt_arg.strftime("%d/%m  %H:%M (ARG)")
    except Exception:
        return utc_str


def fmt_score(match):
    score = match.get("score", {})
    status = match["status"]
    goals = match.get("goals") or []

    if status in ("SCHEDULED", "TIMED", "POSTPONED", "CANCELLED"):
        return ""

    hid = match["homeTeam"]["id"]
    aid = match["awayTeam"]["id"]
    hg, ag = 0, 0
    for g in goals:
        tid = (g.get("team") or {}).get("id")
        gtype = g.get("type", "REGULAR")
        if gtype == "OWN":
            if tid == hid:
                ag += 1
            else:
                hg += 1
        else:
            if tid == hid:
                hg += 1
            else:
                ag += 1

    pen = score.get("penalties", {})
    if pen and pen.get("home") is not None:
        return f"  {hg}–{ag}  (pen {pen['home']}–{pen['away']})"

    return f"  {hg}–{ag}"


def print_match(match, show_id=False):
    home = match["homeTeam"].get("shortName") or match["homeTeam"]["name"]
    away = match["awayTeam"].get("shortName") or match["awayTeam"]["name"]
    status = match["status"]
    label = STATUS_LABEL.get(status, status)
    score = fmt_score(match)
    time_str = fmt_time(match["utcDate"])
    venue = (match.get("venue") or "")

    id_str = f"  [ID:{match['id']}]" if show_id else ""
    venue_str = f"  📍 {venue}" if venue and status in ("SCHEDULED", "TIMED") else ""

    print(f"  {label:<28} {home} vs {away}{score}")
    if status in ("SCHEDULED", "TIMED", "POSTPONED"):
        print(f"  {'':28} 🕐 {time_str}{venue_str}{id_str}")
    else:
        print(f"  {'':28} 🕐 {time_str}{id_str}")


def main():
    args = sys.argv[1:]
    config = load_config()
    api_key = config.get("api_key", "")

    if not api_key or api_key.startswith("TU_"):
        print("❌ Falta configurar api_key. Ejecuta: python setup.py")
        sys.exit(1)

    try:
        if "--all" in args:
            print("\n🏆  Copa del Mundo 2026 — Todos los partidos\n")
            data = api_get(api_key, f"/competitions/{COMPETITION}/matches")
            matches = data.get("matches", [])
        elif "--next" in args:
            idx = args.index("--next")
            n = int(args[idx + 1]) if idx + 1 < len(args) else 5
            print(f"\n🏆  Copa del Mundo 2026 — Próximos {n} partidos\n")
            data = api_get(api_key, f"/competitions/{COMPETITION}/matches", {"status": "SCHEDULED", "limit": n})
            matches = data.get("matches", [])[:n]
        else:
            today = (datetime.now(timezone.utc) + TZ_OFFSET).strftime("%Y-%m-%d")
            print(f"\n🏆  Copa del Mundo 2026 — Partidos del {today} (Argentina)\n")

            # Live matches first
            live_data = api_get(api_key, f"/competitions/{COMPETITION}/matches", {"status": "LIVE"})
            live_matches = live_data.get("matches", [])

            # Today's matches
            today_data = api_get(api_key, f"/competitions/{COMPETITION}/matches", {"dateFrom": today, "dateTo": today})
            today_matches = today_data.get("matches", [])

            live_ids = {m["id"] for m in live_matches}
            all_today = live_matches + [m for m in today_matches if m["id"] not in live_ids]
            matches = sorted(all_today, key=lambda m: m["utcDate"])

        if not matches:
            print("  No se encontraron partidos.")
        else:
            for m in matches:
                print_match(m)
        print()

    except requests.HTTPError as e:
        if e.response.status_code == 403:
            print("❌ API key inválida o sin acceso a Copa del Mundo.")
            print("   Verifica tu key en: https://www.football-data.org/account")
        else:
            print(f"❌ Error de API: {e}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"❌ Error de conexión: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
