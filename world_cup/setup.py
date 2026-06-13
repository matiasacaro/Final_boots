#!/usr/bin/env python3
"""
Asistente de configuración para alertas Copa del Mundo 2026.
Ejecutar una sola vez para generar config.json.
"""

import json
import sys
from pathlib import Path

import requests

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
EXAMPLE_FILE = BASE / "config.example.json"

FOOTBALL_API = "https://api.football-data.org/v4"
COMPETITION = "WC"


def p(msg):
    print(msg)


def prompt(label, default=None, secret=False):
    hint = f" [{default}]" if default and not secret else ""
    try:
        val = input(f"  {label}{hint}: ").strip()
    except (KeyboardInterrupt, EOFError):
        p("\nCancelado.")
        sys.exit(0)
    return val if val else (default or "")


def separator():
    p("─" * 55)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_telegram_send(token, chat_id, msg):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": str(chat_id), "text": msg, "parse_mode": "HTML"},
        timeout=10,
    )
    return r.ok, r.json() if r.ok else r.text


def get_chat_id_from_updates(token):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, timeout=10)
        if r.ok:
            results = r.json().get("result", [])
            for update in reversed(results):
                msg = update.get("message") or update.get("channel_post")
                if msg:
                    return msg["chat"]["id"]
    except requests.RequestException:
        pass
    return None


def test_football_api(api_key):
    headers = {"X-Auth-Token": api_key}
    try:
        r = requests.get(
            f"{FOOTBALL_API}/competitions/{COMPETITION}",
            headers=headers,
            timeout=10,
        )
        return r.ok, r.status_code
    except requests.RequestException as e:
        return False, str(e)


# ── Wizard ──────────────────────────────────────────────────────────────────────

def main():
    p("\n" + "=" * 55)
    p("  🏆  Alertas Copa del Mundo 2026 — Configuración")
    p("=" * 55)

    existing = {}
    if CONFIG_FILE.exists():
        p("\n⚠️  Ya existe un config.json. Se editará el actual.")
        p("   (Presiona Enter para mantener el valor actual)\n")
        with open(CONFIG_FILE) as f:
            existing = json.load(f)

    # ── PASO 1: Football API ──────────────────────────────────────────────────
    p("")
    separator()
    p("PASO 1 — API de fútbol (gratuita)")
    separator()
    p("  1. Andá a: https://www.football-data.org/client/register")
    p("  2. Registrate con tu email (es gratis)")
    p("  3. Verificá tu email y copiá tu API Key del dashboard\n")

    default_key = existing.get("api_key", "")
    api_key = prompt("API Key de football-data.org", default_key)

    p("")
    p("  Verificando API key...")
    ok, status = test_football_api(api_key)
    if ok:
        p("  ✅ API Key válida — Copa del Mundo 2026 accesible!")
    elif status == 403:
        p("  ❌ API Key inválida o sin acceso a Copa del Mundo.")
        p("     Verificá la key en https://www.football-data.org/account")
        if prompt("¿Continuar de todas formas? (s/n)", "n").lower() != "s":
            sys.exit(1)
    else:
        p(f"  ⚠️  No se pudo verificar (error {status}). Continuando...")

    # ── PASO 2: Telegram ──────────────────────────────────────────────────────
    p("")
    separator()
    p("PASO 2 — Bot de Telegram")
    separator()
    p("  1. Abrí Telegram y buscá @BotFather")
    p("  2. Enviá el comando: /newbot")
    p("  3. Seguí las instrucciones (elegí nombre y username)")
    p("  4. Copiá el token que te da (formato: 123456:ABCdef...)\n")

    default_token = existing.get("telegram", {}).get("bot_token", "")
    bot_token = prompt("Bot Token de Telegram", default_token)

    p("")
    p("  Para obtener tu Chat ID:")
    p("  1. Buscá tu bot en Telegram y enviá cualquier mensaje")
    p("  2. El sistema intentará detectar tu Chat ID automáticamente\n")

    detected_id = get_chat_id_from_updates(bot_token)
    default_chat = existing.get("telegram", {}).get("chat_id", "")

    if detected_id:
        p(f"  ✅ Chat ID detectado automáticamente: {detected_id}")
        use_detected = prompt("¿Usar este Chat ID? (s/n)", "s").lower()
        chat_id = str(detected_id) if use_detected == "s" else prompt("Chat ID manual", str(default_chat))
    else:
        p("  ⚠️  No se detectó Chat ID. Asegurate de haber enviado un mensaje al bot primero.")
        p("  También podés obtenerlo en: https://api.telegram.org/bot<TOKEN>/getUpdates")
        chat_id = prompt("Chat ID de Telegram", str(default_chat))

    # Test Telegram
    p("")
    p("  Enviando mensaje de prueba a Telegram...")
    ok, resp = test_telegram_send(
        bot_token,
        chat_id,
        "✅ <b>¡Configuración exitosa!</b>\n\n"
        "🏆 Copa del Mundo 2026\n"
        "Vas a recibir alertas aquí de:\n"
        "• ⚽ Goles con nombres de goleadores\n"
        "• 🔔 Inicio, entretiempo y final\n"
        "• 🟥 Expulsiones\n"
        "• ⏳ Prórroga y penales"
    )
    if ok:
        p("  ✅ ¡Mensaje enviado! Revisá tu Telegram.")
    else:
        p(f"  ❌ Error al enviar: {resp}")
        if prompt("¿Continuar de todas formas? (s/n)", "n").lower() != "s":
            sys.exit(1)

    # ── PASO 3: Equipos ───────────────────────────────────────────────────────
    p("")
    separator()
    p("PASO 3 — Equipos a seguir")
    separator()
    p("  Ingresá los equipos separados por coma.")
    p("  Ejemplos: Argentina,Brasil,Francia,España")
    p("  Dejá vacío para recibir alertas de TODOS los partidos.\n")

    default_teams = ",".join(existing.get("followed_teams", []))
    teams_input = prompt("Equipos", default_teams or "(todos)")

    if teams_input and teams_input.strip() != "(todos)":
        followed_teams = [t.strip() for t in teams_input.split(",") if t.strip()]
        p(f"  👁️  Siguiendo: {', '.join(followed_teams)}")
    else:
        followed_teams = []
        p("  👁️  Siguiendo todos los partidos del torneo")

    # ── PASO 4: Intervalos ────────────────────────────────────────────────────
    p("")
    separator()
    p("PASO 4 — Frecuencia de actualización")
    separator()
    p("  ℹ️  El plan gratuito de football-data.org permite 10 req/min.")
    p("     Con 30 segundos de intervalo usás ~2 req/min (muy seguro).\n")

    default_live = existing.get("poll_interval_seconds", 30)
    default_idle = existing.get("poll_interval_idle_seconds", 300)
    interval_live = int(prompt("Segundos entre consultas (partido en vivo)", str(default_live)))
    interval_idle = int(prompt("Segundos entre consultas (sin partido en vivo)", str(default_idle)))

    if interval_live < 30:
        p("  ⚠️  Mínimo recomendado: 30 segundos. Ajustado a 30.")
        interval_live = 30

    # ── Guardar config ─────────────────────────────────────────────────────────
    config = {
        "api_key": api_key,
        "telegram": {
            "bot_token": bot_token,
            "chat_id": chat_id,
        },
        "followed_teams": followed_teams,
        "poll_interval_seconds": interval_live,
        "poll_interval_idle_seconds": interval_idle,
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    p("")
    separator()
    p(f"  ✅ config.json guardado en {CONFIG_FILE}")
    separator()
    p("")
    p("  🚀 Para iniciar las alertas:")
    p("     python alerts.py")
    p("")
    p("  📅 Para ver los partidos de hoy:")
    p("     python schedule.py")
    p("")
    p("  📅 Para ver los próximos 5 partidos:")
    p("     python schedule.py --next 5")
    p("")


if __name__ == "__main__":
    main()
