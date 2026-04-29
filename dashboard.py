#!/usr/bin/env python3
"""
HML Central Dashboard — agrega múltiplos agents.
Porta padrão: 8765

Variáveis de ambiente:
  AGENTS        Lista de agents: nome=http://host:8766,nome2=http://host2:8766
                Se não definido, lê agents.json. Fallback: local agent em :8766.
  DASHBOARD_PORT  Porta de escuta (padrão: 8765)
"""
import http.server
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
PORT = int(os.environ.get("DASHBOARD_PORT", sys.argv[1] if len(sys.argv) > 1 else 8080))
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", 15))
AGENT_TIMEOUT    = int(os.environ.get("AGENT_TIMEOUT", 5))


# ─── agents ───────────────────────────────────────────────────────────────────

def load_agents() -> list[dict]:
    raw = os.environ.get("AGENTS", "").strip()
    if raw:
        agents = []
        for part in raw.split(","):
            part = part.strip()
            if "=" in part:
                name, _, url = part.partition("=")
            else:
                name = part.split(":")[0]
                url  = part
            agents.append({"name": name.strip(), "url": url.strip().rstrip("/")})
        return agents

    agents_file = ROOT / "agents.json"
    if agents_file.exists():
        return json.loads(agents_file.read_text())

    return [{"name": "local", "url": "http://localhost:8766"}]


def fetch_agent(agent: dict) -> dict:
    url = agent["url"] + "/api"
    try:
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=AGENT_TIMEOUT) as r:
            data = json.loads(r.read())
        return {**agent, "status": "online",  "data": data,
                "error": None, "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {**agent, "status": "offline", "data": None,
                "error": str(e), "latency_ms": None}


def fetch_all() -> dict:
    agents = load_agents()
    results = [None] * len(agents)

    def _fetch(i, ag):
        results[i] = fetch_agent(ag)

    threads = [threading.Thread(target=_fetch, args=(i, ag)) for i, ag in enumerate(agents)]
    for t in threads: t.start()
    for t in threads: t.join()

    online  = [r for r in results if r["status"] == "online"]
    total_slots = sum(len(r["data"]["slots"]) for r in online)
    expiring    = sum(
        1 for r in online
        for s in r["data"]["slots"]
        if s.get("alert") in ("critical", "warning", "expired")
    )
    repl_errors = sum(
        1 for r in online
        if r["data"].get("base_repl", {}).get("last_io_error") or
           r["data"].get("base_repl", {}).get("last_sql_error")
    )

    return {
        "servers": results,
        "summary": {
            "total":        len(results),
            "online":       len(online),
            "total_slots":  total_slots,
            "expiring":     expiring,
            "repl_errors":  repl_errors,
        },
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def proxy(agent_url: str, path: str, method="GET", body: bytes = None):
    url = agent_url + path
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 503, json.dumps({"error": str(e)}).encode()


# ─── cache ────────────────────────────────────────────────────────────────────

_cache: dict = {"data": None, "lock": threading.Lock()}


def _background_refresh():
    while True:
        try:
            data = fetch_all()
            with _cache["lock"]:
                _cache["data"] = data
        except Exception:
            pass
        time.sleep(REFRESH_INTERVAL)


def get_cached() -> dict:
    with _cache["lock"]:
        return _cache["data"]


# ─── HTML ─────────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HML Central</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
</style>
<style>
:root{
  --bg:#0d0d0d;--surface:#161616;--surface-2:#1e1e1e;
  --border:#2a2a2a;--border-2:#3a3a3a;
  --text:#f2f2f2;--muted:#888;
  --accent:#4ade80;--accent-dim:rgba(74,222,128,.12);
  --danger:#f87171;--danger-dim:rgba(248,113,113,.1);
  --warning:#fbbf24;--warning-dim:rgba(251,191,36,.1);
  --info:#60a5fa;--info-dim:rgba(96,165,250,.1);
  --radius:10px;--radius-sm:6px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;min-height:100vh}

nav{position:sticky;top:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:52px;background:var(--surface);border-bottom:1px solid var(--border)}
.nav-brand{font-weight:600;font-size:15px;letter-spacing:-.01em}
.nav-right{display:flex;align-items:center;gap:16px}
.ts{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
main{padding:24px;max-width:1600px;margin:0 auto}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;transition:border-color .15s,box-shadow .15s}
.card:hover{border-color:var(--border-2);box-shadow:0 4px 20px rgba(0,0,0,.5)}
.card-label{font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:8px}
.card-value{font-size:1.3rem;font-weight:700;line-height:1}
.card-sub{font-size:12px;color:var(--muted);margin-top:4px}

.server-section{margin-bottom:20px}
.server-header{display:flex;align-items:center;gap:10px;padding:10px 4px;cursor:pointer;user-select:none;border-radius:var(--radius-sm)}
.server-header:hover{background:var(--surface-2)}
.server-name{font-weight:600;font-size:13px}
.server-header::after{content:'';flex:1;height:1px;background:var(--border);margin-left:8px}
.toggle-icon{display:inline-block;transition:transform .2s;font-size:13px;color:var(--muted)}
.server-header.collapsed .toggle-icon{transform:rotate(-90deg)}
.server-body{padding:0 4px 8px}
.server-body.hidden{display:none}

.repl-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:14px}
.repl-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px}
.repl-card-label{font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:6px}
.repl-card-value{font-size:1.1rem;font-weight:700}

.slot-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:4px}
.slot-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px;display:flex;flex-direction:column;gap:10px;transition:border-color .15s,box-shadow .15s}
.slot-card:hover{border-color:var(--border-2);box-shadow:0 4px 20px rgba(0,0,0,.4)}
.slot-card.alert-critical{border-color:rgba(248,113,113,.4)}
.slot-card.alert-warning{border-color:rgba(251,191,36,.35)}
.slot-card.alert-expired{opacity:.5}
.slot-card-header{display:flex;align-items:center;gap:8px}
.slot-card-name{font-weight:700;font-size:14px;flex:1}
.slot-card-body{display:flex;flex-direction:column;gap:6px}
.slot-card-row{display:flex;align-items:center;justify-content:space-between;font-size:12px}
.slot-card-row-label{color:var(--muted);font-weight:500}
.slot-card-ttl{font-size:13px;font-weight:700;text-align:right}
.slot-card-actions{display:flex;gap:5px;flex-wrap:wrap;padding-top:4px;border-top:1px solid var(--border)}
.slot-empty{color:var(--muted);font-size:13px;padding:16px 4px;font-style:italic}

.badge{display:inline-block;padding:2px 8px;border-radius:var(--radius-sm);font-size:11px;font-weight:600;white-space:nowrap}
.b-green{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(74,222,128,.2)}
.b-red{background:var(--danger-dim);color:var(--danger);border:1px solid rgba(248,113,113,.2)}
.b-yellow{background:var(--warning-dim);color:var(--warning);border:1px solid rgba(251,191,36,.2)}
.b-gray{background:var(--surface-2);color:var(--muted);border:1px solid var(--border)}
.b-blue{background:var(--info-dim);color:var(--info);border:1px solid rgba(96,165,250,.2)}

.alert-expired td{opacity:.45}
.alert-critical td:nth-child(6){color:var(--danger);font-weight:700}
.alert-warning  td:nth-child(6){color:var(--warning);font-weight:600}

.metrics{font-size:12px;color:var(--muted);line-height:1.8}
.metrics b{color:var(--text)}
.repl-ok{color:var(--accent)}
.repl-err{color:var(--danger)}
.none{color:var(--border-2);font-style:italic;font-size:12px}

.btn{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-family:inherit;font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,border-color .15s}
.btn:hover:not(:disabled){background:#2a2a2a;border-color:var(--border-2)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-accent{background:var(--accent);border-color:var(--accent);color:#0d0d0d;font-weight:600}
.btn-accent:hover:not(:disabled){background:#22c55e;border-color:#22c55e;color:#0d0d0d}
.btn-warning{background:var(--warning-dim);border-color:rgba(251,191,36,.25);color:var(--warning)}
.btn-warning:hover:not(:disabled){background:rgba(251,191,36,.18)}
.btn-sm{padding:4px 9px;font-size:12px}
.actions{display:flex;gap:5px;flex-wrap:wrap}

.offline-banner{display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:var(--radius-sm);background:var(--danger-dim);border:1px solid rgba(248,113,113,.2);color:var(--danger);font-size:13px}

#job-toast{position:fixed;bottom:24px;right:24px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;max-width:420px;width:100%;z-index:100;display:none;box-shadow:0 8px 32px rgba(0,0,0,.6)}
#job-toast .job-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:13px;font-weight:600}
#job-toast pre{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px;font-size:12px;max-height:200px;overflow-y:auto;color:var(--muted);white-space:pre-wrap;word-break:break-all}
#job-close{background:none;border:none;color:var(--muted);cursor:pointer;font-size:1rem}
#job-close:hover{color:var(--text)}

#log-modal{position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:200;display:none;align-items:flex-end;justify-content:center}
#log-modal.open{display:flex}
#log-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius) var(--radius) 0 0;width:100%;max-width:960px;max-height:70vh;display:flex;flex-direction:column}
#log-header{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--border);font-size:13px;font-weight:600}
#log-body{overflow-y:auto;padding:16px 20px;flex:1}
#log-body pre{font-size:12px;color:var(--muted);white-space:pre-wrap;word-break:break-all;line-height:1.7}
#log-close{background:none;border:none;color:var(--muted);cursor:pointer;font-size:1.1rem}
#log-close:hover{color:var(--text)}

.spinner{display:inline-block;width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* topology */
.topo{display:flex;align-items:center;gap:0;margin-bottom:14px;overflow-x:auto;padding:2px 0}
.topo-node{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;min-width:140px;flex-shrink:0}
.topo-node-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:4px}
.topo-node-name{font-size:13px;font-weight:600;margin-bottom:3px}
.topo-node-port{font-size:11px;color:var(--muted)}
.topo-arrow{display:flex;flex-direction:column;align-items:center;padding:0 8px;flex-shrink:0;gap:2px}
.topo-arrow-line{display:flex;align-items:center;gap:0;width:100%}
.topo-arrow svg{flex-shrink:0}
.topo-arrow-label{font-size:10px;color:var(--muted);text-align:center;white-space:nowrap}
.topo-arrow-meta{font-size:11px;font-weight:600;text-align:center;white-space:nowrap}
.topo-slots{display:flex;flex-direction:column;gap:6px;flex-shrink:0}
.topo-slot-node{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 12px;display:flex;align-items:center;gap:10px;min-width:200px}
.topo-slot-name{font-size:12px;font-weight:600;flex:1}
.topo-slot-meta{font-size:11px;color:var(--muted)}

.owner-cell{cursor:pointer;white-space:nowrap}
.owner-cell:hover{color:var(--info)}
.owner-edit{display:inline-flex;align-items:center;gap:6px}
.owner-input{background:var(--surface-2);border:1px solid var(--info);border-radius:var(--radius-sm);color:var(--text);font-family:inherit;font-size:13px;padding:2px 7px;width:110px;outline:none}
.owner-input:focus{box-shadow:0 0 0 2px rgba(96,165,250,.2)}

#slot-modal{position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:200;display:none;align-items:center;justify-content:center}
#slot-modal.open{display:flex}
#slot-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);width:100%;max-width:420px;padding:24px}
#slot-panel h3{font-size:15px;font-weight:600;margin-bottom:20px}
.form-row{margin-bottom:14px}
.form-row label{display:block;font-size:12px;font-weight:500;color:var(--muted);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em}
.form-input{width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-family:inherit;font-size:13px;padding:7px 10px;outline:none}
.form-input:focus{border-color:var(--info);box-shadow:0 0 0 2px rgba(96,165,250,.15)}
.form-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:20px}
.btn-danger{background:var(--danger-dim);border-color:rgba(248,113,113,.25);color:var(--danger)}
.btn-danger:hover:not(:disabled){background:rgba(248,113,113,.18)}
</style>
</head>
<body>

<nav>
  <span class="nav-brand">HML Central</span>
  <div class="nav-right">
    <span class="ts" id="clock"></span>
    <span class="ts" id="ts"></span>
  </div>
</nav>

<main>
  <div class="cards">
    <div class="card"><div class="card-label">Servidores</div><div class="card-value" id="g-servers">—</div><div class="card-sub" id="g-servers-sub"></div></div>
    <div class="card"><div class="card-label">Slots ativos</div><div class="card-value" id="g-slots">—</div></div>
    <div class="card"><div class="card-label">Expirando</div><div class="card-value" id="g-expiring">—</div></div>
    <div class="card"><div class="card-label">Erros replicação</div><div class="card-value" id="g-repl-err">—</div></div>
  </div>

  <div id="servers-container"></div>
</main>

<div id="job-toast">
  <div class="job-header">
    <span id="job-label">—</span>
    <button id="job-close" onclick="closeToast()">✕</button>
  </div>
  <pre id="job-output"></pre>
  <div style="margin-top:10px;display:flex;align-items:center;gap:8px">
    <span id="job-status-badge"></span>
    <span id="job-spinner" class="spinner" style="display:none"></span>
  </div>
</div>

<div id="log-modal" onclick="closeLog(event)">
  <div id="log-panel">
    <div id="log-header">
      <span id="log-title">Logs</span>
      <button id="log-close" onclick="closeLog()">✕</button>
    </div>
    <div id="log-body"><pre id="log-pre"></pre></div>
  </div>
</div>

<div id="slot-modal" onclick="if(event.target===this)closeSlotModal()">
  <div id="slot-panel">
    <h3>Criar Slot</h3>
    <div class="form-row">
      <label>Nome</label>
      <input class="form-input" id="slot-name" placeholder="hml-03" maxlength="30"
             onkeydown="if(event.key==='Enter')document.getElementById('slot-owner').focus()">
    </div>
    <div class="form-row">
      <label>Owner</label>
      <input class="form-input" id="slot-owner" placeholder="bruno" maxlength="40"
             onkeydown="if(event.key==='Enter')document.getElementById('slot-ttl').focus()">
    </div>
    <div class="form-row">
      <label>TTL (horas)</label>
      <input class="form-input" id="slot-ttl" type="number" value="24" min="1" max="720"
             onkeydown="if(event.key==='Enter')submitCreateSlot()">
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeSlotModal()">Cancelar</button>
      <button class="btn btn-accent" id="slot-submit" onclick="submitCreateSlot()">Criar</button>
    </div>
  </div>
</div>

<script>
const badge = (st) => {
  const map = {running:'b-green',exited:'b-red','not found':'b-gray',paused:'b-yellow',online:'b-green',offline:'b-red'};
  return `<span class="badge ${map[st]||'b-gray'}">${st}</span>`;
};

const statsHtml = (s, m) => {
  if (!s) return '<span class="none">—</span>';
  const conn = m?.Threads_connected ?? null;
  const connHtml = conn !== null
    ? ` &nbsp;<span style="color:var(--muted)">${conn} conn</span>`
    : '';
  return `<span style="font-size:12px"><b>${s.cpu}</b> &nbsp;${s.mem}${connHtml}</span>`;
};

const metricsHtml = (m) => {
  if (!m) return '<span class="none">—</span>';
  const up = m.Uptime ? Math.round(m.Uptime/60)+'m' : '—';
  return `<div class="metrics">up <b>${up}</b><br>conn <b>${m.Threads_connected||'—'}</b><br>q <b>${m.Questions||m.Queries||'—'}</b></div>`;
};

const replCellHtml = (r) => {
  if (!r) return '<span class="none">—</span>';
  const io = r.Slave_IO_Running || r.io_running || '?';
  const sql = r.Slave_SQL_Running || r.sql_running || '?';
  const lag = r.Seconds_Behind_Master || r.lag;
  const err = r.Last_IO_Error || r.last_io_error || r.Last_SQL_Error || r.last_sql_error || '';
  return `<span style="font-size:12px">IO <span class="${io==='Yes'?'repl-ok':'repl-err'}">${io}</span> SQL <span class="${sql==='Yes'?'repl-ok':'repl-err'}">${sql}</span>${lag!==undefined?` Lag <b>${lag}s</b>`:''}${err?`<br><span class="repl-err" style="font-size:11px">${err.slice(0,50)}</span>`:''}</span>`;
};

function renderRepl(r) {
  if (!r || !r.configured) {
    return `
      <div class="repl-cards">
        <div class="repl-card"><div class="repl-card-label">IO Thread</div><div><span class="badge b-gray">não configurado</span></div></div>
        <div class="repl-card"><div class="repl-card-label">SQL Thread</div><div><span class="badge b-gray">não configurado</span></div></div>
        <div class="repl-card"><div class="repl-card-label">Lag</div><div class="repl-card-value none">—</div></div>
        <div class="repl-card"><div class="repl-card-label">Fonte</div><div style="font-size:11px;color:var(--muted)">execute make setup-replication</div></div>
      </div>`;
  }
  const ioOk  = r.io_running  === 'Yes';
  const sqlOk = r.sql_running === 'Yes';
  const lag   = r.lag_int;
  const lagColor = lag === null ? 'var(--muted)' : lag > 60 ? 'var(--danger)' : lag > 10 ? 'var(--warning)' : 'var(--accent)';
  const err   = r.last_io_error || r.last_sql_error || '';
  return `
    <div class="repl-cards">
      <div class="repl-card"><div class="repl-card-label">IO Thread</div><div>${badge(ioOk?'running':'stopped')}</div></div>
      <div class="repl-card"><div class="repl-card-label">SQL Thread</div><div>${badge(sqlOk?'running':'stopped')}</div></div>
      <div class="repl-card"><div class="repl-card-label">Lag</div><div class="repl-card-value" style="color:${lagColor}">${lag!==null?lag+'s':'—'}</div></div>
      <div class="repl-card"><div class="repl-card-label">Fonte</div><div style="font-size:12px;color:var(--muted)">${r.source_host||'—'}${r.source_port?':'+r.source_port:''}</div></div>
      ${err ? `<div class="repl-card" style="grid-column:1/-1"><div class="repl-card-label">Erro</div><div style="font-size:12px;color:var(--danger)">${err}</div></div>` : ''}
    </div>`;
}

function topoArrow(label, meta, metaColor) {
  return `
    <div class="topo-arrow">
      <div class="topo-arrow-label">${label}</div>
      <div class="topo-arrow-line">
        <svg width="48" height="2"><line x1="0" y1="1" x2="40" y2="1" stroke="var(--border-2)" stroke-width="1.5"/><polygon points="40,0 48,1 40,2" fill="var(--border-2)"/></svg>
      </div>
      ${meta !== null ? `<div class="topo-arrow-meta" style="color:${metaColor}">${meta}</div>` : ''}
    </div>`;
}

function renderTopology(d) {
  const repl   = d.base_repl || {};
  const slots  = d.slots     || [];
  const lag    = repl.lag_int;
  const ioOk   = repl.io_running  === 'Yes';
  const sqlOk  = repl.sql_running === 'Yes';
  const replOk = repl.configured && ioOk && sqlOk;
  const lagColor = lag === null ? 'var(--muted)'
                 : lag > 60    ? 'var(--danger)'
                 : lag > 10    ? 'var(--warning)'
                 : 'var(--accent)';
  const replLabel = repl.configured
    ? (replOk ? 'GTID replication' : '<span style="color:var(--danger)">replication error</span>')
    : '<span style="color:var(--muted)">não configurado</span>';
  const lagMeta = repl.configured
    ? (lag !== null ? `lag ${lag}s` : '—')
    : null;

  const prdBorderColor  = d.prd  === 'running' ? 'var(--accent)' : 'var(--danger)';
  const baseBorderColor = d.base === 'running' ? (replOk ? 'var(--accent)' : 'var(--warning)') : 'var(--danger)';

  const slotNodes = slots.length
    ? slots.map(s => {
        const ok = s.container_status === 'running';
        const bc = ok ? 'var(--accent)' : 'var(--danger)';
        return `<div class="topo-slot-node" style="border-color:${bc}">
          <span class="topo-slot-name">${s.slot_name}</span>
          <span class="badge b-blue" style="font-size:10px">${s.port}</span>
          <span class="topo-slot-meta">${s.owner}</span>
          ${badge(s.container_status)}
        </div>`;
      }).join('')
    : `<div class="topo-slot-node" style="color:var(--muted);font-size:12px;border-style:dashed">nenhum slot ativo</div>`;

  return `<div class="topo">
    <div class="topo-node" style="border-color:${prdBorderColor}">
      <div class="topo-node-label">PRD</div>
      <div class="topo-node-name">${repl.source_host || 'mysql-hml-prd'}</div>
      <div class="topo-node-port">:${repl.source_port || 3306}</div>
      <div style="margin-top:6px">${badge(d.prd)}</div>
    </div>
    ${topoArrow(replLabel, lagMeta, lagColor)}
    <div class="topo-node" style="border-color:${baseBorderColor}">
      <div class="topo-node-label">Base (réplica)</div>
      <div class="topo-node-name">mysql-hml-base</div>
      <div class="topo-node-port">:3306</div>
      <div style="margin-top:6px">${badge(d.base)}</div>
    </div>
    ${topoArrow('Clone Plugin', null, '')}
    <div class="topo-slots">${slotNodes}</div>
  </div>`;
}

function renderServer(srv) {
  const d = srv.data;
  const sid = 'srv-' + srv.name.replace(/[^a-z0-9]/gi, '-');

  if (srv.status === 'offline') {
    return `
      <div class="server-section">
        <div class="server-header" onclick="toggleServer('${sid}')">
          <span class="toggle-icon" id="${sid}-icon">▾</span>
          <span class="server-name">${srv.name}</span>
          ${badge('offline')}
          <span style="font-size:12px;color:var(--muted)">${srv.error||''}</span>
        </div>
      </div>`;
  }

  const slots = d.slots || [];
  const snap  = d.snapshot;

  const cards = slots.length ? slots.map(s => {
    const remColor = s.alert==='expired'||s.alert==='critical' ? 'var(--danger)' : s.alert==='warning' ? 'var(--warning)' : 'var(--accent)';
    const ownerSafe = s.owner.replace(/'/g,"\\'");
    const conn = s.metrics?.Threads_connected ?? null;
    return `
      <div class="slot-card alert-${s.alert}">
        <div class="slot-card-header">
          <span class="slot-card-name">${s.slot_name}</span>
          <span class="badge b-blue">${s.port}</span>
          ${badge(s.container_status)}
        </div>
        <div class="slot-card-body">
          <div class="slot-card-row">
            <span class="slot-card-row-label">Owner</span>
            <span class="owner-cell" onclick="editOwner(this,'${srv.url}','${s.slot_name}','${ownerSafe}')">${s.owner} <span style="opacity:.35;font-size:10px">✎</span></span>
          </div>
          ${s.stats ? `<div class="slot-card-row">
            <span class="slot-card-row-label">CPU / Mem</span>
            <span>${s.stats.cpu} &nbsp; ${s.stats.mem.split('/')[0].trim()}${conn!==null?' &nbsp; '+conn+' conn':''}</span>
          </div>` : ''}
          <div class="slot-card-row">
            <span class="slot-card-row-label">Replicação</span>
            <span>${replCellHtml(s.replica)}</span>
          </div>
          <div class="slot-card-row">
            <span class="slot-card-row-label">Expira</span>
            <span style="font-size:11px;color:var(--muted)">${s.expires_at.slice(0,16).replace('T',' ')}</span>
          </div>
          <div class="slot-card-ttl" style="color:${remColor}">${s.remaining}</div>
        </div>
        <div class="slot-card-actions">
          <button class="btn btn-sm" onclick="doLogs('${srv.url}','${s.slot_name}')">⬛ Logs</button>
          <button class="btn btn-warning btn-sm" onclick="doRestart('${srv.url}','${s.slot_name}',this)">↻ Restart</button>
          <button class="btn btn-danger btn-sm" onclick="doDestroy('${srv.url}','${s.slot_name}')">✕ Destruir</button>
        </div>
      </div>`;
  }).join('') : `<div class="slot-empty">Nenhum slot ativo</div>`;

  return `
    <div class="server-section">
      <div class="server-header" onclick="toggleServer('${sid}')">
        <span class="toggle-icon" id="${sid}-icon">▾</span>
        <span class="server-name">${srv.name}</span>
        ${badge('online')}
        <span class="badge b-gray">${slots.length} slot${slots.length!==1?'s':''}</span>
        <span style="font-size:12px;color:var(--muted)">base ${badge(d.base)} &nbsp; prd ${badge(d.prd)}</span>
        <span style="font-size:12px;color:var(--muted)">${snap?'snapshot '+snap.modified+' · '+snap.size_mb+'MB':''}</span>
        <span style="font-size:12px;color:var(--muted)">${srv.latency_ms!==null?srv.latency_ms+'ms':''}</span>
        <button class="btn btn-accent btn-sm" style="margin-left:8px" onclick="event.stopPropagation();doRefresh('${srv.url}','${srv.name}')">↻ Voltar Base</button>
        <button class="btn btn-sm" style="margin-left:4px" onclick="event.stopPropagation();openSlotModal('${srv.url}')">+ Criar Slot</button>
      </div>
      <div class="server-body" id="${sid}-body">
        ${renderTopology(d)}
        ${renderRepl(d.base_repl)}
        <div class="slot-grid">${cards}</div>
      </div>
    </div>`;
}

function render(data) {
  const s = data.summary;
  document.getElementById('ts').textContent  = '· ' + data.generated_at.slice(11);
  document.getElementById('g-servers').innerHTML = `<span>${s.online}</span><span style="color:var(--muted);font-size:.9rem"> / ${s.total}</span>`;
  document.getElementById('g-servers-sub').textContent = s.online < s.total ? `${s.total-s.online} offline` : 'todos online';
  document.getElementById('g-slots').textContent    = s.total_slots;
  document.getElementById('g-expiring').innerHTML   = s.expiring  ? `<span style="color:var(--warning)">${s.expiring}</span>`  : '0';
  document.getElementById('g-repl-err').innerHTML   = s.repl_errors ? `<span style="color:var(--danger)">${s.repl_errors}</span>` : '0';

  const container = document.getElementById('servers-container');
  // preserve collapsed state
  const collapsed = new Set(
    [...container.querySelectorAll('.server-header.collapsed')]
      .map(h => h.closest('.server-section')?.querySelector('.toggle-icon')?.id)
  );
  container.innerHTML = data.servers.map(renderServer).join('');
  collapsed.forEach(iconId => {
    const icon = document.getElementById(iconId);
    if (icon) {
      icon.closest('.server-header').classList.add('collapsed');
      const bodyId = iconId.replace('-icon', '-body');
      const body = document.getElementById(bodyId);
      if (body) body.classList.add('hidden');
    }
  });
}

function toggleServer(sid) {
  const icon = document.getElementById(sid + '-icon');
  const body = document.getElementById(sid + '-body');
  if (!icon || !body) return;
  icon.closest('.server-header').classList.toggle('collapsed');
  body.classList.toggle('hidden');
}

async function load() {
  try {
    const r = await fetch('/api');
    render(await r.json());
  } catch(e) { console.error(e); }
}

setInterval(load, 30000);
load();

function updateClock() {
  const now = new Date(), pad = n => String(n).padStart(2,'0');
  const el = document.getElementById('clock');
  if (el) el.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
updateClock(); setInterval(updateClock, 1000);

// ── actions ──────────────────────────────────────────────────────────────────

let _pollTimer = null;

function showToast(label) {
  document.getElementById('job-label').textContent = label;
  document.getElementById('job-output').textContent = '';
  document.getElementById('job-status-badge').innerHTML = '';
  document.getElementById('job-spinner').style.display = 'inline-block';
  document.getElementById('job-toast').style.display = 'block';
}

function closeToast() {
  document.getElementById('job-toast').style.display = 'none';
  if (_pollTimer) clearInterval(_pollTimer);
}

function pollJob(agentUrl, jobId) {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    const r = await fetch(`/action/status?agent=${encodeURIComponent(agentUrl)}&job_id=${jobId}`);
    const d = await r.json();
    const pre = document.getElementById('job-output');
    pre.textContent = d.output || '';
    pre.scrollTop   = pre.scrollHeight;
    if (d.status !== 'running') {
      clearInterval(_pollTimer);
      document.getElementById('job-spinner').style.display = 'none';
      const ok = d.status === 'done';
      document.getElementById('job-status-badge').innerHTML =
        `<span class="badge ${ok?'b-green':'b-red'}">${ok?'Concluído':'Erro'}</span>`;
      if (ok) load();
    }
  }, 1000);
}

async function doRefresh(agentUrl, serverName) {
  showToast(`↺ Voltar Base — ${serverName}`);
  const r = await fetch(`/action/refresh?agent=${encodeURIComponent(agentUrl)}`, {method:'POST'});
  const d = await r.json();
  pollJob(agentUrl, d.job_id);
}

async function doRestart(agentUrl, slot, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    await fetch(`/action/restart?agent=${encodeURIComponent(agentUrl)}`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({slot}),
    });
  } finally {
    btn.disabled = false;
    btn.innerHTML = '↻ Restart';
    load();
  }
}

async function doLogs(agentUrl, slot) {
  document.getElementById('log-title').textContent = `Logs — ${slot}`;
  document.getElementById('log-pre').textContent   = 'Carregando...';
  document.getElementById('log-modal').classList.add('open');
  const r = await fetch(`/logs?agent=${encodeURIComponent(agentUrl)}&slot=${slot}`);
  const d = await r.json();
  document.getElementById('log-pre').textContent = d.logs || '(sem logs)';
  document.getElementById('log-body').scrollTop = document.getElementById('log-body').scrollHeight;
}

function closeLog(e) {
  if (!e || e.target===document.getElementById('log-modal') || e.currentTarget===document.getElementById('log-close'))
    document.getElementById('log-modal').classList.remove('open');
}

// ── create / destroy slot ─────────────────────────────────────────────────────

let _createAgentUrl = null;

function openSlotModal(agentUrl) {
  _createAgentUrl = agentUrl;
  document.getElementById('slot-name').value  = '';
  document.getElementById('slot-owner').value = '';
  document.getElementById('slot-ttl').value   = '24';
  document.getElementById('slot-submit').disabled = false;
  document.getElementById('slot-modal').classList.add('open');
  setTimeout(() => document.getElementById('slot-name').focus(), 50);
}

function closeSlotModal() {
  document.getElementById('slot-modal').classList.remove('open');
}

async function submitCreateSlot() {
  const name  = document.getElementById('slot-name').value.trim();
  const owner = document.getElementById('slot-owner').value.trim() || 'bruno';
  const ttl   = parseInt(document.getElementById('slot-ttl').value) || 24;
  if (!name) { document.getElementById('slot-name').focus(); return; }
  document.getElementById('slot-submit').disabled = true;
  closeSlotModal();
  showToast(`+ Criando slot ${name}`);
  const r = await fetch(`/action/create-slot?agent=${encodeURIComponent(_createAgentUrl)}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, owner, ttl}),
  });
  const d = await r.json();
  pollJob(_createAgentUrl, d.job_id);
}

async function doDestroy(agentUrl, slot) {
  if (!confirm(`Destruir o slot "${slot}"?\n\nEssa ação é irreversível.`)) return;
  showToast(`✕ Destruindo slot ${slot}`);
  const r = await fetch(`/action/destroy-slot?agent=${encodeURIComponent(agentUrl)}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: slot}),
  });
  const d = await r.json();
  pollJob(agentUrl, d.job_id);
}

// ── owner inline edit ─────────────────────────────────────────────────────────

function editOwner(span, agentUrl, slot, currentOwner) {
  span.outerHTML = `
    <span class="owner-edit" id="owner-edit-${slot}">
      <input class="owner-input" id="owner-input-${slot}" value="${currentOwner}" maxlength="40"
             onkeydown="ownerKey(event,'${agentUrl}','${slot}')"
             onfocus="this.select()">
      <button class="btn btn-sm" style="padding:2px 7px" onclick="saveOwner('${agentUrl}','${slot}')">✓</button>
      <button class="btn btn-sm" style="padding:2px 7px" onclick="load()">✕</button>
    </span>`;
  const input = document.getElementById('owner-input-' + slot);
  if (input) { input.focus(); input.select(); }
}

function ownerKey(e, agentUrl, slot) {
  if (e.key === 'Enter')  saveOwner(agentUrl, slot);
  if (e.key === 'Escape') load();
}

async function saveOwner(agentUrl, slot) {
  const input = document.getElementById('owner-input-' + slot);
  const newOwner = input ? input.value.trim() : '';
  if (!newOwner) return;
  input.disabled = true;
  try {
    const r = await fetch(`/action/set-owner?agent=${encodeURIComponent(agentUrl)}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slot, owner: newOwner}),
    });
    if (!r.ok) console.error('set-owner error', await r.text());
  } finally {
    load();
  }
}
</script>
</body>
</html>"""


# ─── HTTP handler ─────────────────────────────────────────────────────────────

def parse_qs(q: str) -> dict:
    out = {}
    for p in q.split("&"):
        if "=" in p:
            k, _, v = p.partition("=")
            from urllib.parse import unquote
            out[k] = unquote(v)
    return out


def agent_url_for(qs: dict) -> str | None:
    agent = qs.get("agent", "")
    if agent:
        return agent
    agents = load_agents()
    return agents[0]["url"] if agents else None


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code: int, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        qs   = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}

        if path == "/api":
            data = get_cached()
            if data is None:
                data = fetch_all()
                with _cache["lock"]:
                    _cache["data"] = data
            self.send_json(200, data)

        elif path == "/action/status":
            url = agent_url_for(qs)
            if not url:
                self.send_json(404, {"error": "agent not found"})
                return
            code, body = proxy(url, f"/action/status?job_id={qs.get('job_id','')}")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/logs":
            url = agent_url_for(qs)
            if not url:
                self.send_json(404, {"error": "agent not found"})
                return
            code, body = proxy(url, f"/logs?slot={qs.get('slot','')}")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        path   = self.path.split("?")[0]
        qs     = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b""

        url = agent_url_for(qs)
        if not url:
            self.send_json(404, {"error": "agent not found"})
            return

        if path == "/action/refresh":
            code, resp = proxy(url, "/action/refresh", "POST", body or b"{}")
        elif path == "/action/restart":
            code, resp = proxy(url, "/action/restart", "POST", body)
        elif path == "/action/set-owner":
            code, resp = proxy(url, "/action/set-owner", "POST", body)
        elif path == "/action/create-slot":
            code, resp = proxy(url, "/action/create-slot", "POST", body)
        elif path == "/action/destroy-slot":
            code, resp = proxy(url, "/action/destroy-slot", "POST", body)
        else:
            self.send_json(404, {"error": "not found"})
            return

        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(resp))
        self.end_headers()
        self.wfile.write(resp)


if __name__ == "__main__":
    agents = load_agents()
    print(f"HML Central Dashboard em http://localhost:{PORT}")
    print(f"Agents configurados ({len(agents)}):")
    for a in agents:
        print(f"  {a['name']} → {a['url']}")
    threading.Thread(target=_background_refresh, daemon=True, name="cache-refresh").start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
