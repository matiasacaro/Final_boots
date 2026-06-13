#!/usr/bin/env python3
"""
Copa del Mundo 2026 — Alertas en tiempo real via Telegram.
Detecta goles, inicio, entretiempo, expulsiones y final.
"""

import json
import logging
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / ".state.json"

FOOTBALL_API = "https://api.football-data.org/v4"
COMPETITION = "WC"

# Status codes from football-data.org
IN_PLAY = "IN_PLAY"
PAUSED = "PAUSED"
FINISHED = "FINISHED"
EXTRA_TIME = "EXTRA_TIME"
PENALTY_SHOOTOUT = "PENALTY_SHOOTOUT"
LIVE_STATUSES = {IN_PLAY, PAUSED, EXTRA_TIME, PENALTY_SHOOTOUT}
ENDED_STATUSES = {FINISHED}
NOT_STARTED = {"SCHEDULED", "TIMED", "POSTPONED", "CANCELLED", "SUSPENDED"}


# ── Config & State ────────────────────────────────────────────────────────────

def load_config():
    if not CONFIG_FILE.exists():
        log.error("config.json no encontrado. Ejecuta primero: python setup.py")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Telegram ──────────────────────────────────────────────────────────────────

def tg_send(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            log.error("Telegram error %s: %s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        log.error("Telegram fallo: %s", e)


# ── Football API ───────────────────────────────────────────────────────────────

def api_get(api_key, path, params=None):
    headers = {"X-Auth-Token": api_key}
    try:
        r = requests.get(
            f"{FOOTBALL_API}{path}",
            headers=headers,
            params=params,
            timeout=15,
        )
        if r.status_code == 429:
            log.warning("Rate limit alcanzado, esperando 60s...")
            time.sleep(60)
            return None
        if r.status_code == 403:
            log.error("API key invalida o sin permiso para Copa del Mundo. Verifica tu key en config.json")
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.error("API error: %s", e)
        return None


def get_live_matches(api_key):
    data = api_get(api_key, "/matches", {"competitions": COMPETITION, "status": "LIVE"})
    if data:
        return data.get("matches", [])
    return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_followed(match, followed_teams):
    if not followed_teams:
        return True
    home = match["homeTeam"]["name"].lower()
    away = match["awayTeam"]["name"].lower()
    return any(t.lower() in home or t.lower() in away for t in followed_teams)


def current_score(match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    goals = match.get("goals") or []
    hid = match["homeTeam"]["id"]
    aid = match["awayTeam"]["id"]

    hg, ag = 0, 0
    for g in goals:
        tid = (g.get("team") or {}).get("id")
        gtype = g.get("type", "REGULAR")
        if gtype == "OWN":
            if tid == hid:
                ag += 1
            elif tid == aid:
                hg += 1
        else:
            if tid == hid:
                hg += 1
            elif tid == aid:
                ag += 1

    return f"{home} {hg} – {ag} {away}", hg, ag


def goal_key(idx, goal):
    minute = goal.get("minute", 0)
    gtype = goal.get("type", "REGULAR")
    team_id = (goal.get("team") or {}).get("id", "x")
    scorer_ref = (goal.get("scorer") or {}).get("id") or (goal.get("scorer") or {}).get("name", "?")
    return f"{idx}_{minute}_{gtype}_{team_id}_{scorer_ref}"


def booking_key(idx, booking):
    minute = booking.get("minute", 0)
    card = booking.get("card", "?")
    team_id = (booking.get("team") or {}).get("id", "x")
    player_ref = (booking.get("player") or {}).get("id") or (booking.get("player") or {}).get("name", "?")
    return f"{idx}_{minute}_{card}_{team_id}_{player_ref}"


# ── Event processing ───────────────────────────────────────────────────────────

def process_match(match, state, token, chat_id):
    fid = str(match["id"])
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    status = match["status"]
    duration = match.get("score", {}).get("duration", "REGULAR")
    goals = match.get("goals") or []
    bookings = match.get("bookings") or []

    prev = state.get(fid, {})
    prev_status = prev.get("status", "")
    seen_goals = set(prev.get("seen_goals", []))
    seen_bookings = set(prev.get("seen_bookings", []))
    prev_paused_count = prev.get("paused_count", 0)

    score_str, hg, ag = current_score(match)

    def notify(text):
        log.info("→ %s", text.replace("\n", " | ")[:100])
        tg_send(token, chat_id, text)

    # ── Inicio del partido ─────────────────────────────────────────────────
    if status == IN_PLAY and prev_status in NOT_STARTED | {""}:
        notify(
            f"⚽ <b>¡INICIO DEL PARTIDO!</b>\n"
            f"🏆 Copa del Mundo 2026\n"
            f"🆚 {home} vs {away}\n"
            f"¡El partido ha comenzado!"
        )

    # ── Entretiempo / pausa ────────────────────────────────────────────────
    paused_count = prev_paused_count
    if status == PAUSED and prev_status == IN_PLAY:
        paused_count = prev_paused_count + 1
        if paused_count == 1:
            label = "⏸️ <b>ENTRETIEMPO</b>\nFin del primer tiempo"
        elif duration == "EXTRA_TIME" or paused_count == 2:
            label = "⏸️ <b>DESCANSO — PRÓRROGA</b>\nFin del primer tiempo extra"
        else:
            label = "⏸️ <b>PAUSA</b>"
        notify(
            f"{label}\n"
            f"🏆 Copa del Mundo 2026\n"
            f"📊 {score_str}"
        )

    # ── Segundo tiempo / reanudación ───────────────────────────────────────
    if status == IN_PLAY and prev_status == PAUSED:
        paused_count_prev = prev.get("paused_count", 0)
        if paused_count_prev == 1:
            label = "▶️ <b>¡SEGUNDO TIEMPO!</b>"
        elif duration == "EXTRA_TIME":
            label = "▶️ <b>¡SEGUNDO TIEMPO EXTRA!</b>"
        else:
            label = "▶️ <b>¡REANUDA EL JUEGO!</b>"
        notify(
            f"{label}\n"
            f"🏆 Copa del Mundo 2026\n"
            f"📊 {score_str}"
        )

    # ── Prórroga (tiempo extra) ────────────────────────────────────────────
    if duration == "EXTRA_TIME" and prev.get("duration") == "REGULAR" and status == IN_PLAY:
        notify(
            f"⏳ <b>¡TIEMPO EXTRA!</b>\n"
            f"🏆 Copa del Mundo 2026\n"
            f"📊 {score_str}\n"
            f"¡30 minutos más para decidir el partido!"
        )

    # ── Penales ────────────────────────────────────────────────────────────
    if status == PENALTY_SHOOTOUT and prev_status != PENALTY_SHOOTOUT:
        notify(
            f"🎯 <b>¡DEFINICIÓN POR PENALES!</b>\n"
            f"🏆 Copa del Mundo 2026\n"
            f"📊 {score_str}\n"
            f"¡Empieza la tanda de penaltis!"
        )

    # ── Goles ──────────────────────────────────────────────────────────────
    for idx, goal in enumerate(goals):
        gk = goal_key(idx, goal)
        if gk in seen_goals:
            continue
        seen_goals.add(gk)

        minute = goal.get("minute", "?")
        gtype = goal.get("type", "REGULAR")
        team_name = (goal.get("team") or {}).get("name", "?")
        scorer_name = (goal.get("scorer") or {}).get("name", "Desconocido")
        assist_data = goal.get("assist")
        assist_name = (assist_data or {}).get("name") if assist_data else None

        score_str_now, _, _ = current_score(match)

        if gtype == "OWN":
            notify(
                f"🤚 <b>AUTOGOL</b>\n"
                f"🏆 Copa del Mundo 2026\n"
                f"👤 {scorer_name} ({team_name})\n"
                f"📊 {score_str_now}\n"
                f"⏱️ Min {minute}'"
            )
        elif gtype == "PENALTY":
            notify(
                f"⚽ <b>¡GOOOOL! (Penal)</b>\n"
                f"🏆 Copa del Mundo 2026\n"
                f"👤 {scorer_name} ({team_name})\n"
                f"📊 {score_str_now}\n"
                f"⏱️ Min {minute}'"
            )
        else:
            assist_line = f"\n👟 Asistencia: {assist_name}" if assist_name else ""
            notify(
                f"🥅 <b>¡GOOOOL!</b> ⚽\n"
                f"🏆 Copa del Mundo 2026\n"
                f"👤 {scorer_name} ({team_name}){assist_line}\n"
                f"📊 {score_str_now}\n"
                f"⏱️ Min {minute}'"
            )

        time.sleep(1)

    # ── Expulsiones / Tarjetas rojas ───────────────────────────────────────
    for idx, booking in enumerate(bookings):
        card = booking.get("card", "")
        if card not in ("RED_CARD", "YELLOW_RED_CARD"):
            continue
        bk = booking_key(idx, booking)
        if bk in seen_bookings:
            continue
        seen_bookings.add(bk)

        minute = booking.get("minute", "?")
        player_name = (booking.get("player") or {}).get("name", "Desconocido")
        team_name = (booking.get("team") or {}).get("name", "?")
        card_label = "🟥 TARJETA ROJA" if card == "RED_CARD" else "🟨🟥 DOBLE AMARILLA"

        notify(
            f"{card_label} — <b>EXPULSIÓN</b>\n"
            f"🏆 Copa del Mundo 2026\n"
            f"👤 {player_name} ({team_name})\n"
            f"📊 {score_str}\n"
            f"⏱️ Min {minute}'"
        )
        time.sleep(1)

    # ── Final del partido ──────────────────────────────────────────────────
    if status == FINISHED and prev_status not in ENDED_STATUSES:
        dur_labels = {
            "REGULAR": "FINAL DEL PARTIDO",
            "EXTRA_TIME": "FINAL — Prórroga",
            "PENALTY_SHOOTOUT": "FINAL — Penales",
        }
        label = dur_labels.get(duration, "FINAL")
        notify(
            f"🏁 <b>{label}</b>\n"
            f"🏆 Copa del Mundo 2026\n"
            f"📊 {score_str}\n"
            f"¡Partido terminado!"
        )

    # ── Actualizar estado ──────────────────────────────────────────────────
    state[fid] = {
        "status": status,
        "duration": duration,
        "paused_count": paused_count,
        "home": home,
        "away": away,
        "hg": hg,
        "ag": ag,
        "seen_goals": list(seen_goals),
        "seen_bookings": list(seen_bookings),
    }


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    config = load_config()
    api_key = config.get("api_key", "")
    token = config["telegram"]["bot_token"]

    if not api_key or api_key.startswith("TU_"):
        log.error("Falta configurar api_key en config.json. Ejecuta primero: python setup.py")
        sys.exit(1)
    if not token or token.startswith("123456"):
        log.error("Falta configurar telegram.bot_token en config.json.")
        sys.exit(1)

    log.info("🚀 Alertas Copa del Mundo 2026 iniciadas")
    state = load_state()

    while True:
        # Recargar config en cada ciclo para reflejar cambios hechos desde la web
        try:
            config = load_config()
        except Exception:
            pass

        api_key = config.get("api_key", "")
        token = config["telegram"]["bot_token"]
        chat_id = config["telegram"]["chat_id"]
        followed_teams = config.get("followed_teams", [])
        interval_live = config.get("poll_interval_seconds", 30)
        interval_idle = config.get("poll_interval_idle_seconds", 300)
        try:
            matches = get_live_matches(api_key)
            followed = [m for m in matches if is_followed(m, followed_teams)]

            if followed:
                log.info("Partidos en vivo seguidos: %d", len(followed))
                for match in followed:
                    process_match(match, state, token, chat_id)
                save_state(state)
                time.sleep(interval_live)
            else:
                if matches:
                    log.info(
                        "Hay %d partido(s) en vivo pero ninguno de los equipos seguidos. Revisando en %ds",
                        len(matches),
                        interval_idle,
                    )
                else:
                    log.info("Sin partidos en vivo ahora. Revisando en %ds", interval_idle)
                time.sleep(interval_idle)

        except KeyboardInterrupt:
            log.info("Detenido por el usuario.")
            save_state(state)
            sys.exit(0)
        except Exception as e:
            log.error("Error inesperado: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    run()
