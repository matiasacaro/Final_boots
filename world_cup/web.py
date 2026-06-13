#!/usr/bin/env python3
"""
Copa del Mundo 2026 — Dashboard Web.
Accesible desde el dominio configurado en Cloudflare Tunnel.
"""

import json
import logging
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template_string, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
FOOTBALL_API = "https://api.football-data.org/v4"
COMPETITION = "WC"
TZ_ARG = timezone(timedelta(hours=-3))

app = Flask(__name__)

_cache = {"matches": None, "ts": 0}
CACHE_TTL = 30  # segundos


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def bot_is_running():
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "wc2026"],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return None  # No se puede determinar


def fetch_matches():
    now = time.time()
    if _cache["matches"] is not None and now - _cache["ts"] < CACHE_TTL:
        return _cache["matches"]

    try:
        config = load_config()
        api_key = config.get("api_key", "")
        headers = {"X-Auth-Token": api_key}
        today = datetime.now(TZ_ARG).strftime("%Y-%m-%d")

        r = requests.get(
            f"{FOOTBALL_API}/competitions/{COMPETITION}/matches",
            headers=headers,
            params={"dateFrom": today, "dateTo": today},
            timeout=10,
        )
        if r.ok:
            _cache["matches"] = r.json().get("matches", [])
            _cache["ts"] = now
        else:
            log.warning("API %s: %s", r.status_code, r.text[:100])

    except Exception as e:
        log.error("fetch_matches: %s", e)

    return _cache["matches"] or []


def compute_score(match):
    home_id = match["homeTeam"]["id"]
    goals = match.get("goals") or []
    hg, ag = 0, 0
    for g in goals:
        tid = (g.get("team") or {}).get("id")
        gtype = g.get("type", "REGULAR")
        if gtype == "OWN":
            if tid == home_id:
                ag += 1
            else:
                hg += 1
        else:
            if tid == home_id:
                hg += 1
            else:
                ag += 1
    return hg, ag


def fmt_kickoff(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(TZ_ARG).strftime("%H:%M")
    except Exception:
        return "?"


def match_to_dict(m):
    hg, ag = compute_score(m)
    home_id = m["homeTeam"]["id"]
    scorers_home, scorers_away = [], []
    for g in (m.get("goals") or []):
        name = (g.get("scorer") or {}).get("name", "")
        if not name:
            continue
        minute = g.get("minute", "?")
        gtype = g.get("type", "REGULAR")
        tid = (g.get("team") or {}).get("id")
        suffix = " (AG)" if gtype == "OWN" else (" (P)" if gtype == "PENALTY" else "")
        entry = {"name": f"{name}{suffix}", "minute": minute}
        # Own goal: beneficia al equipo contrario
        is_for_home = (tid == home_id and gtype != "OWN") or (tid != home_id and gtype == "OWN")
        (scorers_home if is_for_home else scorers_away).append(entry)

    return {
        "id": m["id"],
        "home": m["homeTeam"].get("shortName") or m["homeTeam"]["name"],
        "away": m["awayTeam"].get("shortName") or m["awayTeam"]["name"],
        "hg": hg,
        "ag": ag,
        "status": m["status"],
        "kickoff": fmt_kickoff(m["utcDate"]),
        "scorers_home": scorers_home,
        "scorers_away": scorers_away,
        "stage": m.get("stage", ""),
        "group": m.get("group", ""),
    }


# ── Template ──────────────────────────────────────────────────────────────────

PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Copa del Mundo 2026</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#eef0f3;color:#1a1a2e;min-height:100vh}

header{background:#002f6c;color:#fff;padding:12px 20px;display:flex;align-items:center;justify-content:space-between}
header h1{font-size:1.05rem;font-weight:700;letter-spacing:.3px}
header .sub{font-size:.72rem;opacity:.65;margin-top:2px}
.header-right{text-align:right}
#update-badge{font-size:.68rem;background:rgba(255,255,255,.15);padding:3px 8px;border-radius:20px}

nav{background:#00235a;display:flex;padding:0 16px}
nav a{color:#99b8e0;text-decoration:none;padding:10px 14px;font-size:.82rem;border-bottom:3px solid transparent;display:inline-block}
nav a.active,nav a:hover{color:#fff;border-bottom-color:#FFD600}

main{max-width:700px;margin:18px auto;padding:0 12px 40px}

.section-label{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;color:#556;padding:14px 0 7px;display:flex;align-items:center;gap:6px}
.dot{width:8px;height:8px;background:#c00;border-radius:50%;animation:pulse 1.2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}

.card{background:#fff;border-radius:9px;margin-bottom:7px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.09)}
.card.live{border-left:4px solid #c00}
.card.finished{opacity:.8}

.card-body{padding:13px 16px}
.match-row{display:flex;align-items:center;gap:8px}
.team{flex:1;font-size:.92rem;font-weight:600;line-height:1.2}
.team.right{text-align:right}
.score-box{text-align:center;min-width:76px}
.score{font-size:1.45rem;font-weight:800;letter-spacing:3px;color:#002f6c}
.status-lbl{font-size:.65rem;font-weight:700;margin-top:1px;text-transform:uppercase;letter-spacing:.5px}
.status-lbl.live{color:#c00}
.status-lbl.ft{color:#2d7a2d}
.status-lbl.sched{color:#555;font-size:.78rem;font-weight:700}

.scorers{display:flex;justify-content:space-between;margin-top:9px;padding-top:8px;border-top:1px solid #f0f0f0}
.sc-col{flex:1;font-size:.7rem;color:#555;line-height:1.7}
.sc-col.right{text-align:right}
.sc-min{color:#aaa;font-size:.64rem}

.empty{text-align:center;color:#888;padding:40px 20px;font-size:.88rem}

/* Config page */
.cfg-card{background:#fff;border-radius:9px;padding:22px;box-shadow:0 1px 4px rgba(0,0,0,.09)}
.cfg-card h3{color:#002f6c;font-size:.95rem;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #eee}
.field{margin-bottom:14px}
.field label{display:block;font-size:.75rem;font-weight:600;color:#445;margin-bottom:4px}
.field input{width:100%;padding:8px 10px;border:1px solid #dde;border-radius:6px;font-size:.88rem;outline:none}
.field input:focus{border-color:#002f6c}
.field .hint{font-size:.68rem;color:#888;margin-top:3px}
.btn-save{background:#002f6c;color:#fff;border:none;padding:9px 22px;border-radius:6px;font-size:.88rem;cursor:pointer;font-weight:600}
.btn-save:hover{background:#001a40}
.toast{padding:9px 14px;border-radius:6px;font-size:.82rem;margin-bottom:14px;background:#d4edda;color:#155724;border:1px solid #c3e6cb}

.bot-status{display:flex;align-items:center;gap:8px;margin-bottom:16px;font-size:.82rem}
.badge{padding:3px 10px;border-radius:20px;font-size:.72rem;font-weight:700}
.badge.on{background:#d4edda;color:#155724}
.badge.off{background:#f8d7da;color:#721c24}
.badge.unknown{background:#fff3cd;color:#856404}

footer{text-align:center;font-size:.68rem;color:#aaa;padding:20px}
</style>
</head>
<body>

<header>
  <div>
    <h1>🏆 Copa del Mundo 2026</h1>
    <div class="sub">Marcadores en tiempo real</div>
  </div>
  <div class="header-right">
    <span id="update-badge">Actualizando...</span>
  </div>
</header>

<nav>
  <a href="/" class="{{ 'active' if page=='home' else '' }}">Partidos</a>
  <a href="/config" class="{{ 'active' if page=='config' else '' }}">⚙️ Bot</a>
</nav>

<main>

{% if page == 'home' %}
  <div id="content">
    <div class="empty">Cargando partidos...</div>
  </div>

{% elif page == 'config' %}
  {% if saved %}
  <div class="toast">✅ Configuración guardada. Los cambios se aplican en el próximo ciclo del bot.</div>
  {% endif %}

  <div class="cfg-card">
    <h3>Estado del Bot de Alertas</h3>
    <div class="bot-status">
      {% if bot_status == True %}
        <span class="badge on">● ACTIVO</span> El bot está enviando alertas a Telegram.
      {% elif bot_status == False %}
        <span class="badge off">● INACTIVO</span> El bot no está corriendo.
        <code style="font-size:.72rem;color:#555">sudo systemctl start wc2026</code>
      {% else %}
        <span class="badge unknown">● DESCONOCIDO</span> Estado del servicio no determinado.
      {% endif %}
    </div>
  </div>

  <br>

  <div class="cfg-card">
    <h3>⚙️ Configuración de Alertas</h3>
    <form method="POST" action="/config">
      <div class="field">
        <label>Equipos a seguir</label>
        <input type="text" name="followed_teams" value="{{ config.get('followed_teams', [])|join(',') }}" placeholder="Argentina,Brasil,Francia,España">
        <p class="hint">Separados por coma. Dejá vacío para recibir alertas de TODOS los partidos.</p>
      </div>
      <div class="field">
        <label>Intervalo en vivo (segundos)</label>
        <input type="number" name="poll_live" value="{{ config.get('poll_interval_seconds', 30) }}" min="30">
        <p class="hint">Mínimo 30 segundos. Con el plan gratuito de football-data.org se recomienda 30-60s.</p>
      </div>
      <div class="field">
        <label>Intervalo sin partidos (segundos)</label>
        <input type="number" name="poll_idle" value="{{ config.get('poll_interval_idle_seconds', 300) }}" min="60">
      </div>
      <button type="submit" class="btn-save">Guardar cambios</button>
    </form>
  </div>
{% endif %}

</main>

<footer>Copa del Mundo 2026 · Zona horaria Argentina (UTC-3)</footer>

<script>
var LIVE = ['IN_PLAY','PAUSED','EXTRA_TIME','PENALTY_SHOOTOUT'];
var STATUS_LBL = {
  'IN_PLAY':'EN VIVO','PAUSED':'ENTRETIEMPO','EXTRA_TIME':'PRÓRROGA',
  'PENALTY_SHOOTOUT':'PENALES','FINISHED':'FINAL','SCHEDULED':'','TIMED':''
};

function renderCard(m) {
  var isLive = LIVE.includes(m.status);
  var isFt   = m.status === 'FINISHED';
  var isSch  = m.status === 'SCHEDULED' || m.status === 'TIMED';

  var cls = 'card' + (isLive?' live':'') + (isFt?' finished':'');

  var scoreEl = isSch
    ? '<span class="score" style="font-size:1.1rem;letter-spacing:1px">'+m.kickoff+'</span><div class="status-lbl sched">ARG</div>'
    : '<span class="score">'+m.hg+'&thinsp;&ndash;&thinsp;'+m.ag+'</span><div class="status-lbl '+(isLive?'live':isFt?'ft':'')+'">'+STATUS_LBL[m.status]+'</div>';

  var scHome = (m.scorers_home||[]).map(function(s){
    return '<span>⚽ '+s.name+' <span class="sc-min">'+s.minute+"'</span></span>";
  }).join('');
  var scAway = (m.scorers_away||[]).map(function(s){
    return '<span>⚽ '+s.name+' <span class="sc-min">'+s.minute+"'</span></span>";
  }).join('');
  var scorersHtml = (scHome||scAway)
    ? '<div class="scorers"><div class="sc-col">'+scHome+'</div><div class="sc-col right">'+scAway+'</div></div>'
    : '';

  return '<div class="'+cls+'"><div class="card-body">'
    +'<div class="match-row">'
    +'<div class="team">'+m.home+'</div>'
    +'<div class="score-box">'+scoreEl+'</div>'
    +'<div class="team right">'+m.away+'</div>'
    +'</div>'+scorersHtml
    +'</div></div>';
}

function renderAll(matches) {
  var live  = matches.filter(function(m){ return LIVE.includes(m.status); });
  var rest  = matches.filter(function(m){ return !LIVE.includes(m.status); });
  var html  = '';

  if (live.length) {
    html += '<div class="section-label"><span class="dot"></span> EN VIVO</div>';
    html += live.map(renderCard).join('');
  }
  if (rest.length) {
    var d = new Date();
    var label = d.getDate()+'/'+(d.getMonth()+1);
    html += '<div class="section-label">📅 HOY — '+label+'</div>';
    html += rest.map(renderCard).join('');
  }
  if (!matches.length) html = '<div class="empty">No hay partidos programados para hoy.</div>';
  return html;
}

function refresh() {
  fetch('/api/matches')
    .then(function(r){ return r.json(); })
    .then(function(data){
      document.getElementById('content').innerHTML = renderAll(data.matches);
      var t = new Date().toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'});
      document.getElementById('update-badge').textContent = 'Actualizado '+t;
    })
    .catch(function(e){ console.error(e); });
}

{% if page == 'home' %}
refresh();
setInterval(refresh, 30000);
{% endif %}
</script>
</body>
</html>"""


# ── Rutas ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(PAGE, page="home")


@app.route("/api/matches")
def api_matches():
    matches = fetch_matches()
    return jsonify({"matches": [match_to_dict(m) for m in matches]})


@app.route("/config", methods=["GET", "POST"])
def config_page():
    saved = False
    config = load_config()

    if request.method == "POST":
        raw = request.form.get("followed_teams", "")
        config["followed_teams"] = [t.strip() for t in raw.split(",") if t.strip()]
        config["poll_interval_seconds"] = max(30, int(request.form.get("poll_live", 30)))
        config["poll_interval_idle_seconds"] = max(60, int(request.form.get("poll_idle", 300)))
        save_config(config)
        saved = True

    return render_template_string(
        PAGE,
        page="config",
        config=config,
        saved=saved,
        bot_status=bot_is_running(),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
