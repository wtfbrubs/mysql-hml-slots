#!/usr/bin/env python3
"""
HML Slots Dashboard
Uso: python3 dashboard.py [porta]   (padrão: 8765)
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# ─── background jobs ─────────────────────────────────────────────────────────

_jobs: dict = {}
_jobs_lock = threading.Lock()


def start_job(label: str, cmd: list, cwd=ROOT) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {"label": label, "status": "running", "output": "", "started": datetime.now().strftime("%H:%M:%S")}

    def _run():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=cwd,
            )
            out = []
            for line in proc.stdout:
                out.append(line)
                with _jobs_lock:
                    _jobs[job_id]["output"] = "".join(out)
            proc.wait()
            status = "done" if proc.returncode == 0 else "error"
        except Exception as e:
            status = "error"
            with _jobs_lock:
                _jobs[job_id]["output"] += f"\nException: {e}"
        with _jobs_lock:
            _jobs[job_id]["status"] = status

    threading.Thread(target=_run, daemon=True).start()
    return job_id


# ─── helpers ─────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def docker_status(name: str) -> str:
    try:
        return subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.Status}}", name],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        return "not found"


def docker_stats(name: str) -> dict | None:
    try:
        out = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format",
             "{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}", name],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode().strip()
        cpu, mem, mem_pct = out.split("\t")
        return {"cpu": cpu, "mem": mem, "mem_pct": mem_pct}
    except Exception:
        return None


def mysql_metrics(container: str, password: str) -> dict | None:
    try:
        out = subprocess.check_output(
            ["docker", "exec", container,
             "mysql", "-uroot", f"-p{password}", "-sN", "-e",
             "SHOW GLOBAL STATUS WHERE Variable_name IN "
             "('Uptime','Threads_connected','Questions','Queries')"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        metrics = {}
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                metrics[parts[0]] = parts[1]
        return metrics
    except Exception:
        return None


def base_replica_status(password: str) -> dict | None:
    """Consulta SHOW REPLICA STATUS no base e retorna dict estruturado."""
    try:
        out = subprocess.check_output(
            ["docker", "exec", "mysql-hml-base",
             "mysql", "-uroot", f"-p{password}", "-sN",
             "-e", "SHOW REPLICA STATUS\\G"],
            stderr=subprocess.DEVNULL, timeout=8,
        ).decode().strip()
        if not out:
            return {"configured": False}
        fields = {}
        for line in out.splitlines():
            line = line.strip()
            if ": " in line:
                k, _, v = line.partition(": ")
                fields[k.strip()] = v.strip()
        lag_raw = fields.get("Seconds_Behind_Source") or fields.get("Seconds_Behind_Master")
        return {
            "configured": True,
            "io_running": fields.get("Replica_IO_Running") or fields.get("Slave_IO_Running", "?"),
            "sql_running": fields.get("Replica_SQL_Running") or fields.get("Slave_SQL_Running", "?"),
            "lag": lag_raw,
            "lag_int": int(lag_raw) if lag_raw and lag_raw.isdigit() else None,
            "source_host": fields.get("Source_Host") or fields.get("Master_Host", ""),
            "source_port": fields.get("Source_Port") or fields.get("Master_Port", ""),
            "last_io_error": fields.get("Last_IO_Error", ""),
            "last_sql_error": fields.get("Last_SQL_Error", ""),
            "gtid_received": fields.get("Retrieved_Gtid_Set", ""),
            "gtid_executed": fields.get("Executed_Gtid_Set", ""),
            "channel": fields.get("Channel_Name", ""),
        }
    except Exception:
        return None


def replica_status(container: str, password: str) -> dict | None:
    try:
        out = subprocess.check_output(
            ["docker", "exec", container,
             "mysql", "-uroot", f"-p{password}", "-sN",
             "-e", "SHOW REPLICA STATUS"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        if not out:
            return None
        fields = [
            "Slave_IO_State", "Master_Host", "Master_User", "Master_Port",
            "Connect_Retry", "Master_Log_File", "Read_Master_Log_Pos",
            "Relay_Log_File", "Relay_Log_Pos", "Relay_Master_Log_File",
            "Slave_IO_Running", "Slave_SQL_Running", "Replicate_Do_DB",
            "Replicate_Ignore_DB", "Replicate_Do_Table", "Replicate_Ignore_Table",
            "Replicate_Wild_Do_Table", "Replicate_Wild_Ignore_Table",
            "Last_Errno", "Last_Error", "Skip_Counter", "Exec_Master_Log_Pos",
            "Relay_Log_Space", "Until_Condition", "Until_Log_File", "Until_Log_Pos",
            "Master_SSL_Allowed", "Master_SSL_CA_File", "Master_SSL_CA_Path",
            "Master_SSL_Cert", "Master_SSL_Cipher", "Master_SSL_Key",
            "Seconds_Behind_Master", "Master_SSL_Verify_Server_Cert",
            "Last_IO_Errno", "Last_IO_Error", "Last_SQL_Errno", "Last_SQL_Error",
            "Replicate_Ignore_Server_Ids", "Master_Server_Id", "Master_UUID",
            "Master_Info_File", "SQL_Delay", "SQL_Remaining_Delay",
            "Slave_SQL_Running_State", "Master_Retry_Count", "Master_Bind",
            "Last_IO_Error_Timestamp", "Last_SQL_Error_Timestamp",
            "Master_SSL_Crl", "Master_SSL_Crlpath",
            "Retrieved_Gtid_Set", "Executed_Gtid_Set", "Auto_Position",
            "Replicate_Rewrite_DB", "Channel_Name", "Master_TLS_Version",
            "Master_public_key_path", "Get_master_public_key", "Network_Namespace",
        ]
        return dict(zip(fields, out.split("\t")))
    except Exception:
        return None


def snapshot_info() -> dict | None:
    latest = ROOT / "snapshots" / "latest.sql.gz"
    if not latest.exists():
        return None
    stat = latest.stat()
    return {
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
    }


def container_logs(name: str, lines: int = 100) -> str:
    try:
        return subprocess.check_output(
            ["docker", "logs", "--tail", str(lines), name],
            stderr=subprocess.STDOUT, timeout=10,
        ).decode(errors="replace")
    except Exception as e:
        return f"Erro ao obter logs: {e}"


# ─── data ────────────────────────────────────────────────────────────────────

def get_data() -> dict:
    env = load_env()
    password = env.get("BASE_MYSQL_ROOT_PASSWORD", "")

    registry_file = ROOT / "registry" / "slots.json"
    slots_raw = json.loads(registry_file.read_text()) if registry_file.exists() else []

    now = datetime.now().astimezone()

    def enrich_slot(s):
        name = s["slot_name"]
        st = docker_status(name)
        expires = datetime.fromisoformat(s["expires_at"])
        delta = expires - now
        if delta.total_seconds() < 0:
            remaining = "EXPIRADO"
            expired = True
            alert = "expired"
        elif delta.total_seconds() < 3600:
            h = int(delta.total_seconds() // 3600)
            m = int((delta.total_seconds() % 3600) // 60)
            remaining = f"{h}h {m}m"
            expired = False
            alert = "critical"
        elif delta.total_seconds() < 7200:
            h = int(delta.total_seconds() // 3600)
            m = int((delta.total_seconds() % 3600) // 60)
            remaining = f"{h}h {m}m"
            expired = False
            alert = "warning"
        else:
            h = int(delta.total_seconds() // 3600)
            m = int((delta.total_seconds() % 3600) // 60)
            remaining = f"{h}h {m}m"
            expired = False
            alert = "ok"

        stats = docker_stats(name) if st == "running" else None
        metrics = mysql_metrics(name, password) if st == "running" else None
        repl = replica_status(name, password) if st == "running" else None

        return {
            **s,
            "container_status": st,
            "remaining": remaining,
            "expired": expired,
            "alert": alert,
            "stats": stats,
            "metrics": metrics,
            "replica": repl,
        }

    # enrich slots in parallel
    results = [None] * len(slots_raw)
    threads = []
    for i, s in enumerate(slots_raw):
        def _enrich(idx, slot):
            results[idx] = enrich_slot(slot)
        t = threading.Thread(target=_enrich, args=(i, s))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    base_st = docker_status("mysql-hml-base")
    prd_st = docker_status("mysql-hml-prd")

    base_repl = base_replica_status(password) if base_st == "running" else None

    return {
        "slots": results,
        "base": base_st,
        "prd": prd_st,
        "base_stats": docker_stats("mysql-hml-base") if base_st == "running" else None,
        "prd_stats": docker_stats("mysql-hml-prd") if prd_st == "running" else None,
        "base_repl": base_repl,
        "snapshot": snapshot_info(),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── HTML ────────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HML Slots</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/@phosphor-icons/web@2.1.2"></script>
<style>
:root{
  --bg:#0d0d0d;
  --surface:#161616;
  --surface-2:#1e1e1e;
  --border:#2a2a2a;
  --border-2:#3a3a3a;
  --text:#f2f2f2;
  --muted:#888;
  --accent:#4ade80;
  --accent-dim:rgba(74,222,128,.12);
  --danger:#f87171;
  --danger-dim:rgba(248,113,113,.1);
  --warning:#fbbf24;
  --warning-dim:rgba(251,191,36,.1);
  --info:#60a5fa;
  --info-dim:rgba(96,165,250,.1);
  --radius:10px;
  --radius-sm:6px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;min-height:100vh}
a{color:inherit}

/* nav */
nav{position:sticky;top:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:52px;background:var(--surface);border-bottom:1px solid var(--border)}
.nav-brand{font-weight:600;font-size:15px;letter-spacing:-.01em}
.nav-right{display:flex;align-items:center;gap:16px}
.ts{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
main{padding:24px;max-width:1400px;margin:0 auto}

/* cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:28px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;transition:border-color .15s,box-shadow .15s}
.card:hover{border-color:var(--border-2);box-shadow:0 4px 20px rgba(0,0,0,.5)}
.card-label{font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:8px}
.card-value{font-size:1.25rem;font-weight:700;line-height:1}
.card-sub{font-size:12px;color:var(--muted);margin-top:5px}
.card-stats{font-size:12px;color:var(--muted);margin-top:6px;display:flex;gap:10px}

/* section */
section{margin-bottom:28px}
section h2{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:10px;display:flex;align-items:center;gap:10px}
section h2::after{content:'';flex:1;height:1px;background:var(--border)}

/* table */
.table-wrap{overflow-x:auto;border-radius:var(--radius);border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;background:var(--surface);min-width:900px}
th{text-align:left;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:10px 14px;border-bottom:1px solid var(--border);background:var(--bg);white-space:nowrap}
td{padding:12px 14px;border-bottom:1px solid var(--border);font-size:13px;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--surface-2)}

/* badges */
.badge{display:inline-block;padding:2px 8px;border-radius:var(--radius-sm);font-size:11px;font-weight:600;white-space:nowrap}
.b-green{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(74,222,128,.2)}
.b-red{background:var(--danger-dim);color:var(--danger);border:1px solid rgba(248,113,113,.2)}
.b-yellow{background:var(--warning-dim);color:var(--warning);border:1px solid rgba(251,191,36,.2)}
.b-gray{background:var(--surface-2);color:var(--muted);border:1px solid var(--border)}
.b-blue{background:var(--info-dim);color:var(--info);border:1px solid rgba(96,165,250,.2)}

/* alerts */
.alert-expired td{opacity:.45}
.alert-critical td:nth-child(7){color:var(--danger);font-weight:700}
.alert-warning td:nth-child(7){color:var(--warning);font-weight:600}

/* metrics */
.metrics{font-size:12px;color:var(--muted);line-height:1.8}
.metrics b{color:var(--text)}
.repl-ok{color:var(--accent)}
.repl-err{color:var(--danger)}
.none{color:var(--border-2);font-style:italic;font-size:12px}

/* buttons */
.btn{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-family:inherit;font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,border-color .15s}
.btn:hover:not(:disabled){background:#2a2a2a;border-color:var(--border-2)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-accent{background:var(--accent);border-color:var(--accent);color:#0d0d0d;font-weight:600}
.btn-accent:hover:not(:disabled){background:#22c55e;border-color:#22c55e;color:#0d0d0d}
.btn-danger{background:var(--danger-dim);border-color:rgba(248,113,113,.25);color:var(--danger)}
.btn-danger:hover:not(:disabled){background:rgba(248,113,113,.18);border-color:rgba(248,113,113,.4)}
.btn-warning{background:var(--warning-dim);border-color:rgba(251,191,36,.25);color:var(--warning)}
.btn-warning:hover:not(:disabled){background:rgba(251,191,36,.18);border-color:rgba(251,191,36,.4)}
.actions{display:flex;gap:6px;flex-wrap:wrap}

/* job toast */
#job-toast{position:fixed;bottom:24px;right:24px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;max-width:420px;width:100%;z-index:100;display:none;box-shadow:0 8px 32px rgba(0,0,0,.6)}
#job-toast .job-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:13px;font-weight:600}
#job-toast pre{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px;font-size:12px;max-height:200px;overflow-y:auto;color:var(--muted);white-space:pre-wrap;word-break:break-all}
#job-close{background:none;border:none;color:var(--muted);cursor:pointer;font-size:1rem;padding:0 4px}
#job-close:hover{color:var(--text)}

/* log modal */
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
</style>
</head>
<body>

<nav>
  <span class="nav-brand">HML Slots</span>
  <div class="nav-right">
    <span class="ts" id="clock"></span>
    <span class="ts" id="ts"></span>
    <button class="btn btn-accent" onclick="doRefresh()"><i class="ph ph-arrows-clockwise"></i> Voltar Base</button>
  </div>
</nav>

<main>
  <div class="cards" id="cards">
    <div class="card"><div class="card-label">Slots ativos</div><div class="card-value" id="c-slots">—</div></div>
    <div class="card"><div class="card-label">mysql-hml-base</div><div class="card-value" id="c-base">—</div><div class="card-stats" id="c-base-stats"></div></div>
    <div class="card"><div class="card-label">mysql-hml-prd</div><div class="card-value" id="c-prd">—</div><div class="card-stats" id="c-prd-stats"></div></div>
    <div class="card"><div class="card-label">Último snapshot</div><div class="card-value" id="c-snap" style="font-size:.95rem">—</div><div class="card-sub" id="c-snap-size"></div></div>
  </div>

  <section>
    <h2>Replicação PRD → Base</h2>
    <div id="repl-panel" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:4px">
      <div class="card"><div class="card-label">IO Thread</div><div class="card-value" id="r-io">—</div></div>
      <div class="card"><div class="card-label">SQL Thread</div><div class="card-value" id="r-sql">—</div></div>
      <div class="card"><div class="card-label">Lag</div><div class="card-value" id="r-lag">—</div><div class="card-sub" id="r-lag-sub"></div></div>
      <div class="card"><div class="card-label">Fonte</div><div class="card-value" id="r-source" style="font-size:.85rem;word-break:break-all">—</div></div>
      <div class="card" id="r-error-card" style="display:none"><div class="card-label">Erro</div><div class="card-sub" id="r-error" style="color:var(--danger);font-size:.75rem"></div></div>
    </div>
  </section>

  <section>
    <h2>Slots</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Slot</th>
            <th>Owner</th>
            <th>Porta</th>
            <th>Container</th>
            <th>CPU / Mem</th>
            <th>MySQL</th>
            <th>Expira / Restante</th>
            <th>Replicação</th>
            <th>Ações</th>
          </tr>
        </thead>
        <tbody id="slots-body">
          <tr><td colspan="9" style="text-align:center;color:#334155;padding:32px">Carregando...</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</main>

<!-- job toast -->
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

<!-- log modal -->
<div id="log-modal" onclick="closeLog(event)">
  <div id="log-panel">
    <div id="log-header">
      <span id="log-title">Logs</span>
      <button id="log-close" onclick="closeLog()">✕</button>
    </div>
    <div id="log-body"><pre id="log-pre"></pre></div>
  </div>
</div>

<script>
const badge = (st) => {
  const map = {running:'b-green',exited:'b-red','not found':'b-gray',paused:'b-yellow'};
  return `<span class="badge ${map[st]||'b-gray'}">${st}</span>`;
};

const repl = (r) => {
  if (!r) return '<span class="none">—</span>';
  const io = r.Slave_IO_Running || '?';
  const sql = r.Slave_SQL_Running || '?';
  const lag = r.Seconds_Behind_Master;
  const err = r.Last_IO_Error || r.Last_SQL_Error || '';
  return `<span style="font-size:.73rem">
    IO <span class="${io==='Yes'?'repl-ok':'repl-err'}">${io}</span>
    SQL <span class="${sql==='Yes'?'repl-ok':'repl-err'}">${sql}</span>
    ${lag !== undefined ? `Lag <b>${lag}s</b>` : ''}
    ${err ? `<br><span class="repl-err" style="font-size:.68rem">${err.slice(0,60)}</span>` : ''}
  </span>`;
};

const statsHtml = (s) => {
  if (!s) return '<span class="none">—</span>';
  return `<span style="font-size:.73rem"><b>${s.cpu}</b> &nbsp; ${s.mem}</span>`;
};

const metricsHtml = (m) => {
  if (!m) return '<span class="none">—</span>';
  const uptime = m.Uptime ? `${Math.round(m.Uptime/60)}m` : '—';
  const conns = m.Threads_connected || '—';
  const qps = m.Questions || m.Queries || '—';
  return `<div class="metrics">uptime <b>${uptime}</b><br>conns <b>${conns}</b><br>queries <b>${qps}</b></div>`;
};

function renderRepl(r) {
  if (!r) {
    ['r-io','r-sql','r-lag','r-source'].forEach(id => {
      document.getElementById(id).innerHTML = '<span class="none">base offline</span>';
    });
    return;
  }
  if (!r.configured) {
    ['r-io','r-sql'].forEach(id => {
      document.getElementById(id).innerHTML = '<span class="badge b-gray">não configurado</span>';
    });
    document.getElementById('r-lag').innerHTML = '<span class="none">—</span>';
    document.getElementById('r-source').innerHTML = '<span class="none">execute make setup-replication</span>';
    return;
  }

  const ioOk = r.io_running === 'Yes';
  const sqlOk = r.sql_running === 'Yes';
  document.getElementById('r-io').innerHTML =
    `<span class="badge ${ioOk ? 'b-green' : 'b-red'}">${r.io_running}</span>`;
  document.getElementById('r-sql').innerHTML =
    `<span class="badge ${sqlOk ? 'b-green' : 'b-red'}">${r.sql_running}</span>`;

  const lag = r.lag_int;
  let lagColor = 'var(--accent)';
  let lagSub = 'sincronizado';
  if (lag === null) { lagColor = 'var(--muted)'; lagSub = ''; }
  else if (lag > 60)  { lagColor = 'var(--danger)';  lagSub = 'lag crítico'; }
  else if (lag > 10)  { lagColor = 'var(--warning)'; lagSub = 'lag moderado'; }
  document.getElementById('r-lag').innerHTML =
    `<span style="color:${lagColor};font-weight:700">${lag !== null ? lag + 's' : '—'}</span>`;
  document.getElementById('r-lag-sub').textContent = lagSub;

  document.getElementById('r-source').textContent =
    r.source_host ? `${r.source_host}:${r.source_port}` : '—';

  const err = r.last_io_error || r.last_sql_error || '';
  const errCard = document.getElementById('r-error-card');
  errCard.style.display = err ? '' : 'none';
  if (err) document.getElementById('r-error').textContent = err;
}

function render(data) {
  document.getElementById('ts').textContent = '· refresh ' + data.generated_at.slice(11);
  renderRepl(data.base_repl);
  document.getElementById('c-slots').textContent = data.slots.length;
  document.getElementById('c-base').innerHTML = badge(data.base);
  document.getElementById('c-prd').innerHTML = badge(data.prd);

  const bs = data.base_stats;
  document.getElementById('c-base-stats').innerHTML = bs
    ? `<span>CPU ${bs.cpu}</span><span>${bs.mem}</span>` : '';

  const ps = data.prd_stats;
  document.getElementById('c-prd-stats').innerHTML = ps
    ? `<span>CPU ${ps.cpu}</span><span>${ps.mem}</span>` : '';

  const snap = data.snapshot;
  document.getElementById('c-snap').textContent = snap ? snap.modified : '—';
  document.getElementById('c-snap-size').textContent = snap ? snap.size_mb + ' MB' : '';

  const tbody = document.getElementById('slots-body');
  if (!data.slots.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:32px">Nenhum slot ativo</td></tr>';
    return;
  }

  tbody.innerHTML = data.slots.map(s => {
    const expStr = s.expires_at.slice(0,19).replace('T',' ');
    const remColor = s.alert === 'expired' ? '#f87171' : s.alert === 'critical' ? '#f87171' : s.alert === 'warning' ? '#fbbf24' : '#4ade80';
    return `<tr class="alert-${s.alert}">
      <td><strong>${s.slot_name}</strong></td>
      <td>${s.owner}</td>
      <td><span class="badge b-blue">${s.port}</span></td>
      <td>${badge(s.container_status)}</td>
      <td>${statsHtml(s.stats)}</td>
      <td>${metricsHtml(s.metrics)}</td>
      <td><span style="font-size:.73rem;color:#64748b">${expStr}</span><br><span style="color:${remColor};font-weight:700;font-size:.8rem">${s.remaining}</span></td>
      <td>${repl(s.replica)}</td>
      <td>
        <div class="actions">
          <button class="btn" onclick="doLogs('${s.slot_name}')"><i class="ph ph-terminal"></i> Logs</button>
          <button class="btn btn-warning" onclick="doRestart('${s.slot_name}', this)"><i class="ph ph-arrows-clockwise"></i> Reiniciar</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

async function load() {
  try {
    const r = await fetch('/api');
    const data = await r.json();
    render(data);
  } catch(e) {
    console.error('load error', e);
  }
}

// relógio ao vivo
function updateClock() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  const el = document.getElementById('clock');
  if (el) el.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
updateClock();
setInterval(updateClock, 1000);

// auto-refresh
setInterval(load, 30000);
load();

// ── actions ────────────────────────────────────────────────────────────────

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

function pollJob(job_id) {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    const r = await fetch('/action/status?job_id=' + job_id);
    const d = await r.json();
    document.getElementById('job-output').textContent = d.output || '';
    const pre = document.getElementById('job-output');
    pre.scrollTop = pre.scrollHeight;
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

async function doRefresh() {
  showToast('↺ Voltar Base (make refresh)');
  const r = await fetch('/action/refresh', {method:'POST'});
  const d = await r.json();
  pollJob(d.job_id);
}

async function doRestart(slot, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    await fetch('/action/restart', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({slot}),
    });
  } finally {
    btn.disabled = false;
    btn.innerHTML = '↺ Reiniciar';
    load();
  }
}

async function doLogs(slot) {
  document.getElementById('log-title').textContent = 'Logs — ' + slot;
  document.getElementById('log-pre').textContent = 'Carregando...';
  document.getElementById('log-modal').classList.add('open');
  const r = await fetch('/logs?slot=' + slot);
  const d = await r.json();
  document.getElementById('log-pre').textContent = d.logs || '(sem logs)';
  const body = document.getElementById('log-body');
  body.scrollTop = body.scrollHeight;
}

function closeLog(e) {
  if (!e || e.target === document.getElementById('log-modal') || e.currentTarget === document.getElementById('log-close')) {
    document.getElementById('log-modal').classList.remove('open');
  }
}
</script>
</body>
</html>"""


# ─── HTTP handler ─────────────────────────────────────────────────────────────

def parse_qs(query: str) -> dict:
    params = {}
    for part in query.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            params[k] = v
    return params


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
        qs = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}

        if path == "/api":
            self.send_json(200, get_data())

        elif path == "/action/status":
            job_id = qs.get("job_id", "")
            with _jobs_lock:
                job = _jobs.get(job_id, {"status": "not found", "output": ""})
            self.send_json(200, job)

        elif path == "/logs":
            slot = qs.get("slot", "")
            logs = container_logs(slot) if slot else "slot não informado"
            self.send_json(200, {"logs": logs})

        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/action/refresh":
            job_id = start_job("make refresh", ["make", "refresh"])
            self.send_json(200, {"job_id": job_id})

        elif path == "/action/restart":
            slot = body.get("slot", "")
            try:
                subprocess.run(["docker", "restart", slot],
                               capture_output=True, timeout=30)
                self.send_json(200, {"ok": True})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})

        else:
            self.send_json(404, {"error": "not found"})


class ThreadedServer(http.server.ThreadingHTTPServer):
    pass


if __name__ == "__main__":
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"Dashboard em http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
