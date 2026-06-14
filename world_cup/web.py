#!/usr/bin/env python3
"""
Copa del Mundo 2026 — Dashboard Web.
Diseño estilo promiedos.com: fila compacta con status, equipos, marcador y goleadores.
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
HEARTBEAT_FILE = BASE / ".heartbeat"
FOOTBALL_API = "https://api.football-data.org/v4"
COMPETITION = "WC"
TZ_ARG = timezone(timedelta(hours=-3))

app = Flask(__name__)

_cache = {"matches": None, "ts": 0}
CACHE_TTL = 30

# Banderas por TLA (código de 3 letras de football-data.org)
TLA_FLAG = {
    "ARG": "🇦🇷", "BRA": "🇧🇷", "FRA": "🇫🇷", "GER": "🇩🇪", "ESP": "🇪🇸",
    "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "POR": "🇵🇹", "NED": "🇳🇱", "URU": "🇺🇾", "MEX": "🇲🇽",
    "USA": "🇺🇸", "CAN": "🇨🇦", "JPN": "🇯🇵", "KOR": "🇰🇷", "MAR": "🇲🇦",
    "SEN": "🇸🇳", "NGA": "🇳🇬", "GHA": "🇬🇭", "CMR": "🇨🇲", "ECU": "🇪🇨",
    "COL": "🇨🇴", "CHI": "🇨🇱", "PER": "🇵🇪", "VEN": "🇻🇪", "BOL": "🇧🇴",
    "PAR": "🇵🇾", "PAN": "🇵🇦", "CRC": "🇨🇷", "HON": "🇭🇳", "JAM": "🇯🇲",
    "KSA": "🇸🇦", "IRN": "🇮🇷", "IRQ": "🇮🇶", "AUS": "🇦🇺", "NZL": "🇳🇿",
    "SUI": "🇨🇭", "BEL": "🇧🇪", "CRO": "🇭🇷", "DEN": "🇩🇰", "POL": "🇵🇱",
    "SRB": "🇷🇸", "UKR": "🇺🇦", "AUT": "🇦🇹", "TUR": "🇹🇷", "CZE": "🇨🇿",
    "SVK": "🇸🇰", "HUN": "🇭🇺", "ROU": "🇷🇴", "SCO": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "WAL": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "ALB": "🇦🇱", "SVN": "🇸🇮", "QAT": "🇶🇦", "CIV": "🇨🇮", "EGY": "🇪🇬",
    "TUN": "🇹🇳", "ALG": "🇩🇿", "HAI": "🇭🇹", "IDN": "🇮🇩", "UZB": "🇺🇿",
    "CHN": "🇨🇳", "MLI": "🇲🇱", "CPV": "🇨🇻", "COD": "🇨🇩", "SLV": "🇸🇻",
    "GUA": "🇬🇹", "TRI": "🇹🇹", "NOR": "🇳🇴", "ITA": "🇮🇹", "SWE": "🇸🇪",
    "GRE": "🇬🇷", "ZAF": "🇿🇦", "TAN": "🇹🇿", "ANG": "🇦🇴", "NOR": "🇳🇴",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def bot_is_running():
    # Método 1 (Docker): el bot escribe un heartbeat en cada ciclo.
    # Lo consideramos vivo si el latido es más reciente que el intervalo idle + margen.
    try:
        if HEARTBEAT_FILE.exists():
            last = int(HEARTBEAT_FILE.read_text().strip())
            config = load_config()
            idle = config.get("poll_interval_idle_seconds", 300)
            return (time.time() - last) < (idle + 120)
    except Exception:
        pass

    # Método 2 (Raspberry/systemd): consultar el servicio.
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "wc2026"],
            capture_output=True, text=True, timeout=3,
        )
        if r.stdout.strip() in ("active", "inactive", "failed"):
            return r.stdout.strip() == "active"
    except Exception:
        pass

    return None


def fetch_matches():
    now = time.time()
    if _cache["matches"] is not None and now - _cache["ts"] < CACHE_TTL:
        return _cache["matches"]
    try:
        config = load_config()
        headers = {"X-Auth-Token": config.get("api_key", "")}
        now_arg = datetime.now(TZ_ARG)
        date_from = (now_arg - timedelta(days=2)).strftime("%Y-%m-%d")
        date_to = (now_arg + timedelta(days=4)).strftime("%Y-%m-%d")
        r = requests.get(
            f"{FOOTBALL_API}/competitions/{COMPETITION}/matches",
            headers=headers,
            params={"dateFrom": date_from, "dateTo": date_to},
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
    # Para partidos terminados, score.fullTime es la fuente más confiable.
    # Para partidos en vivo, fullTime es null → contamos desde el array goals.
    ft = (match.get("score") or {}).get("fullTime") or {}
    if ft.get("home") is not None and ft.get("away") is not None:
        return ft["home"], ft["away"]

    home_id = match["homeTeam"]["id"]
    hg, ag = 0, 0
    for g in (match.get("goals") or []):
        tid = (g.get("team") or {}).get("id")
        gtype = g.get("type", "REGULAR")
        if gtype == "OWN":
            if tid == home_id: ag += 1
            else: hg += 1
        else:
            if tid == home_id: hg += 1
            else: ag += 1
    return hg, ag


def fmt_kickoff(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(TZ_ARG).strftime("%H:%M")
    except Exception:
        return "?"


def match_date(utc_str):
    """Fecha del partido en horario argentino, formato YYYY-MM-DD."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(TZ_ARG).strftime("%Y-%m-%d")
    except Exception:
        return ""


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
        is_home = (tid == home_id and gtype != "OWN") or (tid != home_id and gtype == "OWN")
        (scorers_home if is_home else scorers_away).append(entry)

    home_tla = m["homeTeam"].get("tla", "")
    away_tla = m["awayTeam"].get("tla", "")

    return {
        "id": m["id"],
        "home": m["homeTeam"].get("shortName") or m["homeTeam"]["name"],
        "away": m["awayTeam"].get("shortName") or m["awayTeam"]["name"],
        "home_flag": TLA_FLAG.get(home_tla, ""),
        "away_flag": TLA_FLAG.get(away_tla, ""),
        "hg": hg,
        "ag": ag,
        "status": m["status"],
        "kickoff": fmt_kickoff(m["utcDate"]),
        "scorers_home": scorers_home,
        "scorers_away": scorers_away,
        "group": m.get("group") or "",
        "date": match_date(m["utcDate"]),
        "home_crest": m["homeTeam"].get("crest", ""),
        "away_crest": m["awayTeam"].get("crest", ""),
    }


# ── Template ──────────────────────────────────────────────────────────────────

PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mundial 2026</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#deeaf6;color:#111}

header{background:#4a8fc7;padding:12px 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:3px solid #FFD700}
.logo{color:#fff;font-size:1rem;font-weight:900;text-transform:uppercase;letter-spacing:.5px}
.logo em{color:#FFD700;font-style:normal}
.hdr-right{display:flex;align-items:center;gap:12px}
#upd{font-size:.67rem;color:rgba(255,255,255,.7)}
.cfg-link{color:rgba(255,255,255,.9);text-decoration:none;font-size:.88rem}

.date-bar{background:#4a8fc7;display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-bottom:2px solid #FFD700}
.date-lbl{font-size:.9rem;font-weight:800;color:#fff;text-transform:uppercase;letter-spacing:.5px;text-align:center;flex:1}
.date-nav{background:rgba(255,255,255,.15);color:#fff;border:none;width:36px;height:36px;border-radius:8px;font-size:1.4rem;font-weight:700;cursor:pointer;line-height:1;flex-shrink:0;transition:background .15s}
.date-nav:hover{background:rgba(255,255,255,.3)}
.date-nav:disabled{opacity:.3;cursor:default}

.tabs{background:#fff;display:flex;padding:0 12px;border-bottom:2px solid #cde0f5}
.tab{padding:9px 14px;font-size:.8rem;font-weight:700;color:#999;border-bottom:3px solid transparent;margin-bottom:-2px;cursor:pointer;user-select:none}
.tab.on{color:#2d6ea8;border-bottom-color:#FFD700}
.tab .cnt{background:#c00;color:#fff;border-radius:20px;padding:0 5px;font-size:.65rem;margin-left:3px;vertical-align:middle}
.tabs-spacer{flex:1}

main{padding:10px 0 50px}

/* Bloque de competencia */
.bloque{background:#fff;margin:10px 10px;border-radius:9px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.11)}
.bloque-hdr{background:#4a8fc7;color:#fff;padding:9px 14px;font-size:.82rem;font-weight:700;display:flex;align-items:center;gap:7px;border-left:4px solid #FFD700}

/* Fila de partido */
.partido{border-bottom:1px solid #f0f0f0}
.partido:last-child{border-bottom:none}
.fila{display:flex;align-items:center;padding:9px 10px;gap:6px}

/* Status */
.st{width:46px;flex-shrink:0;text-align:center;font-size:.7rem;font-weight:700;line-height:1.3;color:#888}
.st.live{color:#c00}
.st.ft{color:#555}
.live-pulse{display:inline-block;width:6px;height:6px;background:#c00;border-radius:50%;animation:p 1.2s infinite;vertical-align:middle;margin-right:2px}
@keyframes p{0%,100%{opacity:1}50%{opacity:.2}}

/* Equipos */
.local{flex:1;display:flex;align-items:center;justify-content:flex-end;gap:6px;overflow:hidden}
.visita{flex:1;display:flex;align-items:center;gap:6px;overflow:hidden}
.tnombre{font-size:.82rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.escudo{width:26px;height:26px;border-radius:50%;object-fit:contain;flex-shrink:0;background:#f0f4f8;border:1px solid #dde8f0;padding:2px}

/* Marcador */
.marcador{width:60px;flex-shrink:0;text-align:center}
.score{font-size:1rem;font-weight:800;color:#2d6ea8;letter-spacing:1px;white-space:nowrap}
.hora{font-size:.95rem;font-weight:700;color:#2d6ea8}
.guion{color:#bbb;font-weight:400}

/* Goleadores */
.goles{display:flex;padding:0 10px 7px}
.goles-gap{width:46px;flex-shrink:0}
.goles-l{flex:1;text-align:right;font-size:.65rem;color:#777;line-height:1.6;padding-right:3px}
.goles-m{width:60px;flex-shrink:0}
.goles-r{flex:1;font-size:.65rem;color:#777;line-height:1.6;padding-left:3px}
.gol-min{color:#bbb}

.empty-msg{text-align:center;color:#888;padding:35px 20px;font-size:.88rem}

/* Config */
.cfg-wrap{padding:10px 10px 0}
.cfg-card{background:#fff;border-radius:9px;padding:18px;box-shadow:0 1px 4px rgba(0,0,0,.1);margin-bottom:12px}
.cfg-card h3{font-size:.88rem;color:#2d6ea8;font-weight:800;margin-bottom:14px;padding-bottom:9px;border-bottom:2px solid #FFD700;text-transform:uppercase;letter-spacing:.5px}
.field{margin-bottom:12px}
.field label{display:block;font-size:.73rem;font-weight:700;color:#555;margin-bottom:4px}
.field input{width:100%;padding:8px 10px;border:1px solid #cde0f5;border-radius:6px;font-size:.87rem;outline:none}
.field input:focus{border-color:#4a8fc7}
.hint{font-size:.67rem;color:#999;margin-top:3px}
.btn{background:#4a8fc7;color:#fff;border:none;padding:11px;border-radius:7px;font-size:.87rem;font-weight:700;cursor:pointer;width:100%}
.btn:hover{background:#2d6ea8}
.toast{background:#d4edda;color:#155724;border-radius:7px;padding:10px 14px;font-size:.82rem;margin-bottom:12px;border:1px solid #c3e6cb}
.bdg{display:inline-block;padding:2px 9px;border-radius:20px;font-size:.7rem;font-weight:700}
.bdg.on{background:#d4edda;color:#155724}
.bdg.off{background:#f8d7da;color:#721c24}
.bdg.unk{background:#fff3cd;color:#856404}
code{background:#f5f5f5;padding:2px 6px;border-radius:4px;font-size:.72rem}

footer{text-align:center;font-size:.67rem;color:#7aaed4;padding:16px;background:#fff;border-top:1px solid #cde0f5}

@media(max-width:380px){
  .tnombre{font-size:.75rem}
  .st{width:40px;font-size:.65rem}
  .marcador{width:52px}
  .score{font-size:.9rem}
  .goles-gap{width:40px}
  .goles-m{width:52px}
}
</style>
</head>
<body>

<header>
  <div class="logo">⚽ MUNDIAL <em>2026</em></div>
  <div class="hdr-right">
    <span id="upd"></span>
    {% if page == 'home' %}
      <a class="cfg-link" href="/config">⚙️</a>
    {% else %}
      <a class="cfg-link" href="/">← Partidos</a>
    {% endif %}
  </div>
</header>

{% if page == 'home' %}
<div class="date-bar">
  <button class="date-nav" id="nav-prev" onclick="cambiarDia(-1)">‹</button>
  <span class="date-lbl" id="date-lbl">HOY</span>
  <button class="date-nav" id="nav-next" onclick="cambiarDia(1)">›</button>
</div>
<div class="tabs">
  <div class="tab on" id="tab-todos" onclick="setTab('todos',this)">TODOS</div>
  <div class="tab" id="tab-live" onclick="setTab('live',this)">VIVO</div>
  <div class="tabs-spacer"></div>
</div>
{% endif %}

<main>
{% if page == 'home' %}
  <div id="content"><div class="empty-msg">Cargando...</div></div>

{% elif page == 'config' %}
<div class="cfg-wrap">
  {% if saved %}
  <div class="toast">✅ Guardado. El bot lo aplica en el próximo ciclo.</div>
  {% endif %}

  <div class="cfg-card">
    <h3>Estado del Bot</h3>
    <div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:.82rem">
      {% if bot_status == True %}
        <span class="bdg on">● ACTIVO</span> Enviando alertas a Telegram.
      {% elif bot_status == False %}
        <span class="bdg off">● INACTIVO</span>
        No hay latido reciente. Revisá los logs: <code>docker compose logs alertas</code>
      {% else %}
        <span class="bdg unk">● DESCONOCIDO</span>
        Esperando el primer latido del bot. Si tarda, verificá que el contenedor <code>alertas</code> esté corriendo.
      {% endif %}
    </div>
    <button type="button" class="btn btn-test" onclick="probarTelegram(this)" style="margin-top:14px">
      📲 Enviar mensaje de prueba a Telegram
    </button>
    <div id="test-result" style="font-size:.8rem;margin-top:9px"></div>
  </div>

  <div class="cfg-card">
    <h3>⚙️ Configuración de Alertas</h3>
    <form method="POST" action="/config">
      <div class="field">
        <label>Equipos a seguir</label>
        <input type="text" name="followed_teams" value="{{ config.get('followed_teams',[])|join(',') }}" placeholder="Argentina,Brasil,Francia">
        <p class="hint">Separados por coma. Vacío = TODOS los partidos del Mundial.</p>
      </div>
      <div class="field">
        <label>Intervalo en vivo (segundos, mín 30)</label>
        <input type="number" name="poll_live" value="{{ config.get('poll_interval_seconds',30) }}" min="30">
      </div>
      <div class="field">
        <label>Intervalo sin partidos (segundos, mín 60)</label>
        <input type="number" name="poll_idle" value="{{ config.get('poll_interval_idle_seconds',300) }}" min="60">
      </div>
      <button type="submit" class="btn">Guardar cambios</button>
    </form>
  </div>
</div>
{% endif %}
</main>

<footer>Copa del Mundo 2026 · Horarios en Argentina (UTC-3)</footer>

<script>
var LIVE_ST = ['IN_PLAY','PAUSED','EXTRA_TIME','PENALTY_SHOOTOUT'];
var mode = 'todos';
var lastData = [];
var selectedDate = null;  // 'YYYY-MM-DD' del día que se está viendo

var ST = {
  IN_PLAY: 'EN<br>VIVO', PAUSED: 'ENTRE<br>TIEMPO', EXTRA_TIME: 'PRÓRR.',
  PENALTY_SHOOTOUT: 'PENAL.', FINISHED: 'Final'
};

function setTab(t, el) {
  mode = t;
  document.querySelectorAll('.tab').forEach(function(x){ x.classList.remove('on'); });
  el.classList.add('on');
  renderContent(lastData);
}

function renderPartido(m) {
  var isLive = LIVE_ST.includes(m.status);
  var isFt   = m.status === 'FINISHED';
  var isSch  = m.status === 'SCHEDULED' || m.status === 'TIMED';

  // Status cell
  var stTxt, stCls = '';
  if (isLive) {
    stTxt = '<span class="live-pulse"></span>' + (ST[m.status] || 'VIVO');
    stCls = 'live';
  } else if (isFt) {
    stTxt = 'Final'; stCls = 'ft';
  } else {
    stTxt = m.kickoff;
  }

  // Score / hora cell
  var marcador;
  if (isSch) {
    marcador = '<span class="hora">'+m.kickoff+'</span>';
  } else {
    marcador = '<span class="score">'+m.hg+'<span class="guion"> - </span>'+m.ag+'</span>';
  }

  var hCrest = m.home_crest ? '<img class="escudo" src="'+m.home_crest+'" onerror="this.style.display=\'none\'">' : '';
  var aCrest = m.away_crest ? '<img class="escudo" src="'+m.away_crest+'" onerror="this.style.display=\'none\'">' : '';

  // Goleadores: formato "minuto' nombre"
  var gh = (m.scorers_home||[]).map(function(s){
    return '<span class="gol-min">'+s.minute+"'</span> "+s.name;
  }).join('<br>');
  var ga = (m.scorers_away||[]).map(function(s){
    return '<span class="gol-min">'+s.minute+"'</span> "+s.name;
  }).join('<br>');
  var golesHtml = (gh||ga)
    ? '<div class="goles"><div class="goles-gap"></div><div class="goles-l">'+gh+'</div><div class="goles-m"></div><div class="goles-r">'+ga+'</div></div>'
    : '';

  return '<div class="partido">'
    + '<div class="fila">'
    +   '<div class="st '+stCls+'">'+stTxt+'</div>'
    +   '<div class="local"><span class="tnombre">'+m.home+'</span>'+hCrest+'</div>'
    +   '<div class="marcador">'+marcador+'</div>'
    +   '<div class="visita">'+aCrest+'<span class="tnombre">'+m.away+'</span></div>'
    + '</div>'
    + golesHtml
    + '</div>';
}

function todayISO() {
  // Fecha de hoy en horario argentino (UTC-3)
  var n = new Date();
  var arg = new Date(n.getTime() + (n.getTimezoneOffset()*60000) - (3*3600000));
  return arg.getFullYear()+'-'+String(arg.getMonth()+1).padStart(2,'0')+'-'+String(arg.getDate()).padStart(2,'0');
}

function addDays(iso, n) {
  var p = iso.split('-');
  var d = new Date(p[0], p[1]-1, p[2]);
  d.setDate(d.getDate()+n);
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}

function dateLabel(iso) {
  var p = iso.split('-');
  var d = new Date(p[0], p[1]-1, p[2]);
  var diff = Math.round((d - new Date(todayISO().split('-')[0], todayISO().split('-')[1]-1, todayISO().split('-')[2])) / 86400000);
  var dias = ['DOMINGO','LUNES','MARTES','MIÉRCOLES','JUEVES','VIERNES','SÁBADO'];
  var meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  var fecha = d.getDate()+' '+meses[d.getMonth()];
  var pre;
  if (diff === 0) pre = 'PARTIDOS DE HOY';
  else if (diff === -1) pre = 'AYER';
  else if (diff === 1) pre = 'MAÑANA';
  else pre = dias[d.getDay()];
  return (diff===0) ? pre : pre + ' · ' + fecha;
}

function dateBounds() {
  // Rango navegable: -2 / +4 días desde hoy (igual al fetch del backend)
  return { min: addDays(todayISO(), -2), max: addDays(todayISO(), 4) };
}

function cambiarDia(delta) {
  var b = dateBounds();
  var nuevo = addDays(selectedDate, delta);
  if (nuevo < b.min || nuevo > b.max) return;
  selectedDate = nuevo;
  renderContent(lastData);
}

function renderContent(matches) {
  var live = matches.filter(function(m){ return LIVE_ST.includes(m.status); });

  // Badge de la pestaña VIVO
  var tl = document.getElementById('tab-live');
  if (tl) tl.innerHTML = live.length
    ? 'VIVO <span class="cnt">'+live.length+'</span>'
    : 'VIVO';

  // Etiqueta de fecha + estado de las flechas
  var b = dateBounds();
  var dl = document.getElementById('date-lbl');
  if (dl) dl.textContent = (mode === 'live') ? 'EN VIVO' : dateLabel(selectedDate);
  var np = document.getElementById('nav-prev'), nn = document.getElementById('nav-next');
  var navOff = (mode === 'live');
  if (np) np.disabled = navOff || (selectedDate <= b.min);
  if (nn) nn.disabled = navOff || (selectedDate >= b.max);

  // Partidos a mostrar: en modo live todos los en curso, si no los del día elegido
  var vis = (mode === 'live')
    ? live
    : matches.filter(function(m){ return m.date === selectedDate; });

  var c = document.getElementById('content');
  if (!c) return;

  if (!vis.length) {
    c.innerHTML = '<div class="empty-msg">'
      + (mode==='live' ? 'No hay partidos en vivo ahora.' : 'No hay partidos este día.')
      + '</div>';
    return;
  }

  c.innerHTML = '<div class="bloque">'
    + '<div class="bloque-hdr">🏆 COPA DEL MUNDO 2026</div>'
    + vis.map(renderPartido).join('')
    + '</div>';
}

function refresh() {
  fetch('/api/matches')
    .then(function(r){ return r.json(); })
    .then(function(data){
      lastData = data.matches;
      if (!selectedDate) selectedDate = todayISO();
      renderContent(lastData);
      var t = new Date().toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'});
      var u = document.getElementById('upd');
      if (u) u.textContent = t;
      var live = lastData.filter(function(m){ return LIVE_ST.includes(m.status); });
      document.title = (live.length ? '('+live.length+') ' : '') + 'Mundial 2026';
    })
    .catch(function(e){ console.error(e); });
}

function probarTelegram(btn) {
  var res = document.getElementById('test-result');
  btn.disabled = true;
  res.textContent = 'Enviando...';
  res.style.color = '#888';
  fetch('/test-telegram', {method:'POST'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.ok) {
        res.textContent = '✅ ¡Enviado! Revisá tu Telegram.';
        res.style.color = '#155724';
      } else {
        res.textContent = '❌ ' + (d.error || 'Error desconocido');
        res.style.color = '#721c24';
      }
    })
    .catch(function(e){
      res.textContent = '❌ No se pudo conectar: ' + e;
      res.style.color = '#721c24';
    })
    .finally(function(){ btn.disabled = false; });
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


@app.route("/api/debug")
def api_debug():
    """Diagnóstico: devuelve la respuesta cruda de football-data.org."""
    config = load_config()
    api_key = config.get("api_key", "")
    headers = {"X-Auth-Token": api_key}
    today = datetime.now(TZ_ARG).strftime("%Y-%m-%d")
    out = {
        "api_key_configurada": bool(api_key and not api_key.startswith("TU_")),
        "fecha_consultada": today,
    }
    try:
        r = requests.get(
            f"{FOOTBALL_API}/competitions/{COMPETITION}/matches",
            headers=headers,
            params={"dateFrom": today, "dateTo": today},
            timeout=10,
        )
        out["http_status"] = r.status_code
        data = r.json()
        out["resultSet"] = data.get("resultSet")
        out["competition"] = (data.get("competition") or {}).get("name")
        # Primer partido completo, sin filtrar, para ver la estructura real
        ms = data.get("matches", [])
        out["cantidad_partidos"] = len(ms)
        out["primer_partido_crudo"] = ms[0] if ms else None
    except Exception as e:
        out["error"] = str(e)
    return jsonify(out)


@app.route("/test-telegram", methods=["POST"])
def test_telegram():
    """Envía un mensaje de prueba al chat de Telegram configurado."""
    config = load_config()
    tg = config.get("telegram", {})
    token = tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "")
    if not token or token.startswith("123456") or not chat_id:
        return jsonify({"ok": False, "error": "Telegram no está configurado (bot_token / chat_id)."})
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": str(chat_id),
                "text": (
                    "✅ <b>Mensaje de prueba</b>\n"
                    "🏆 Copa del Mundo 2026\n"
                    "El bot de alertas está conectado correctamente."
                ),
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if r.ok:
            return jsonify({"ok": True})
        data = r.json()
        return jsonify({"ok": False, "error": data.get("description", r.text[:200])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


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
        PAGE, page="config", config=config, saved=saved, bot_status=bot_is_running()
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
