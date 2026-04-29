#!/usr/bin/env python3
"""
HML Agent — API JSON por servidor.
Roda em cada servidor e expõe dados locais ao Dashboard central.
Porta padrão: 8766

Variáveis de ambiente:
  SERVER_NAME   Nome exibido no dashboard central  (padrão: hostname)
  AGENT_PORT    Porta de escuta                     (padrão: 8766)
  PROJECT_ROOT  Raiz do projeto mysql-hml-slots     (padrão: dir do script)
"""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).parent))
PORT = int(os.environ.get("AGENT_PORT", sys.argv[1] if len(sys.argv) > 1 else 8766))
SERVER_NAME = os.environ.get("SERVER_NAME", socket.gethostname())
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", 10))

# ─── jobs ─────────────────────────────────────────────────────────────────────

_jobs: dict = {}
_jobs_lock = threading.Lock()


def start_job(label: str, cmd: list, cwd=None) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {"label": label, "status": "running", "output": "",
                         "started": datetime.now().strftime("%H:%M:%S")}

    def _run():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(cwd or ROOT),
            )
            out = []
            for line in proc.stdout:
                out.append(line)
                with _jobs_lock:
                    _jobs[job_id]["output"] = "".join(out)
            proc.wait()
            st = "done" if proc.returncode == 0 else "error"
        except Exception as e:
            st = "error"
            with _jobs_lock:
                _jobs[job_id]["output"] += f"\nException: {e}"
        with _jobs_lock:
            _jobs[job_id]["status"] = st

    threading.Thread(target=_run, daemon=True).start()
    return job_id


# ─── helpers ──────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {}
    for f in [ROOT / ".env"]:
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    return env


def _run(cmd: list, timeout=8) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                       timeout=timeout).decode().strip()
    except Exception:
        return ""


def docker_status(name: str) -> str:
    out = _run(["docker", "inspect", "--format", "{{.State.Status}}", name])
    return out or "not found"


def docker_stats(name: str) -> dict | None:
    out = _run(["docker", "stats", "--no-stream", "--format",
                "{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}", name], timeout=12)
    if not out:
        return None
    parts = out.split("\t")
    if len(parts) < 3:
        return None
    return {"cpu": parts[0], "mem": parts[1], "mem_pct": parts[2]}


def mysql_query(container: str, password: str, sql: str) -> str:
    return _run(["docker", "exec", container,
                 "mysql", "-uroot", f"-p{password}", "-sN", "-e", sql])


def mysql_metrics(container: str, password: str) -> dict | None:
    out = mysql_query(container, password,
                      "SHOW GLOBAL STATUS WHERE Variable_name IN "
                      "('Uptime','Threads_connected','Questions','Queries')")
    if not out:
        return None
    m = {}
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            m[parts[0]] = parts[1]
    return m or None


def replica_status(container: str, password: str) -> dict | None:
    # Sem -sN: o formato \G requer saída verbosa para ser parseado corretamente
    out = _run(["docker", "exec", container,
                "mysql", "-uroot", f"-p{password}",
                "-e", "SHOW REPLICA STATUS\\G"])
    if not out:
        return None
    fields = {}
    for line in out.splitlines():
        line = line.strip()
        if ": " in line:
            k, _, v = line.partition(": ")
            fields[k.strip()] = v.strip()
    if not fields:
        return None

    def f(*keys):
        for k in keys:
            if k in fields:
                return fields[k]
        return ""

    lag_raw = f("Seconds_Behind_Source", "Seconds_Behind_Master")
    return {
        "configured": True,
        "io_running":      f("Replica_IO_Running", "Slave_IO_Running"),
        "sql_running":     f("Replica_SQL_Running", "Slave_SQL_Running"),
        "lag":             lag_raw,
        "lag_int":         int(lag_raw) if lag_raw and lag_raw.isdigit() else None,
        "source_host":     f("Source_Host", "Master_Host"),
        "source_port":     f("Source_Port", "Master_Port"),
        "last_io_error":   f("Last_IO_Error"),
        "last_sql_error":  f("Last_SQL_Error"),
        "gtid_received":   f("Retrieved_Gtid_Set"),
        "gtid_executed":   f("Executed_Gtid_Set"),
    }


def snapshot_info() -> dict | None:
    latest = ROOT / "snapshots" / "latest.sql.gz"
    if not latest.exists():
        return None
    st = latest.stat()
    return {
        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size_mb":  round(st.st_size / (1024 * 1024), 2),
    }


def container_logs(name: str, lines: int = 100) -> str:
    try:
        return subprocess.check_output(
            ["docker", "logs", "--tail", str(lines), name],
            stderr=subprocess.STDOUT, timeout=10,
        ).decode(errors="replace")
    except Exception as e:
        return f"Erro ao obter logs: {e}"


# ─── dados ────────────────────────────────────────────────────────────────────

def get_data() -> dict:
    env = load_env()
    password = env.get("BASE_MYSQL_ROOT_PASSWORD", "")

    registry_file = ROOT / "registry" / "slots.json"
    slots_raw = json.loads(registry_file.read_text()) if registry_file.exists() else []

    now = datetime.now().astimezone()

    def enrich(s):
        name = s["slot_name"]
        st = docker_status(name)
        expires = datetime.fromisoformat(s["expires_at"])
        delta = expires - now
        secs = delta.total_seconds()
        if secs < 0:
            remaining, expired, alert = "EXPIRADO", True, "expired"
        elif secs < 3600:
            h, m = int(secs // 3600), int((secs % 3600) // 60)
            remaining, expired, alert = f"{h}h {m}m", False, "critical"
        elif secs < 7200:
            h, m = int(secs // 3600), int((secs % 3600) // 60)
            remaining, expired, alert = f"{h}h {m}m", False, "warning"
        else:
            h, m = int(secs // 3600), int((secs % 3600) // 60)
            remaining, expired, alert = f"{h}h {m}m", False, "ok"

        running = st == "running"
        return {
            **s,
            "container_status": st,
            "remaining": remaining,
            "expired": expired,
            "alert": alert,
            "stats":   docker_stats(name)   if running else None,
            "metrics": mysql_metrics(name, password) if running else None,
            "replica": replica_status(name, password) if running else None,
        }

    results = [None] * len(slots_raw)
    threads = []
    for i, s in enumerate(slots_raw):
        def _e(idx, slot):
            results[idx] = enrich(slot)
        t = threading.Thread(target=_e, args=(i, s))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    base_st = docker_status("mysql-hml-base")
    prd_st  = docker_status("mysql-hml-prd")
    base_repl_raw = replica_status("mysql-hml-base", password) if base_st == "running" else None
    base_repl = base_repl_raw if base_repl_raw else {"configured": False}

    return {
        "server":      SERVER_NAME,
        "slots":       results,
        "base":        base_st,
        "prd":         prd_st,
        "base_stats":  docker_stats("mysql-hml-base") if base_st == "running" else None,
        "prd_stats":   docker_stats("mysql-hml-prd")  if prd_st  == "running" else None,
        "base_repl":   base_repl,
        "snapshot":    snapshot_info(),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── cache ────────────────────────────────────────────────────────────────────

_cache: dict = {"data": None, "lock": threading.Lock()}


def _background_refresh():
    while True:
        try:
            data = get_data()
            with _cache["lock"]:
                _cache["data"] = data
        except Exception:
            pass
        threading.Event().wait(REFRESH_INTERVAL)


def get_cached() -> dict:
    with _cache["lock"]:
        return _cache["data"]


# ─── HTTP handler ─────────────────────────────────────────────────────────────

def parse_qs(q: str) -> dict:
    out = {}
    for p in q.split("&"):
        if "=" in p:
            k, _, v = p.partition("=")
            out[k] = v
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code: int, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        qs   = parse_qs(self.path.split("?")[1]) if "?" in self.path else {}

        if path == "/health":
            self.send_json(200, {"status": "ok", "server": SERVER_NAME,
                                 "timestamp": datetime.now().isoformat()})

        elif path == "/api":
            data = get_cached()
            if data is None:
                data = get_data()
                with _cache["lock"]:
                    _cache["data"] = data
            self.send_json(200, data)

        elif path == "/action/status":
            with _jobs_lock:
                job = _jobs.get(qs.get("job_id", ""), {"status": "not found", "output": ""})
            self.send_json(200, job)

        elif path == "/logs":
            slot = qs.get("slot", "")
            logs = container_logs(slot) if slot else "slot não informado"
            self.send_json(200, {"logs": logs})

        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path   = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        if path == "/action/refresh":
            env = load_env()
            password = env.get("BASE_MYSQL_ROOT_PASSWORD", "")
            job_id = start_job("refresh base", [
                "docker", "exec", "mysql-hml-base",
                "mysql", "-uroot", f"-p{password}", "-e",
                "STOP REPLICA; START REPLICA; SHOW REPLICA STATUS\\G",
            ])
            self.send_json(200, {"job_id": job_id})

        elif path == "/action/restart":
            slot = body.get("slot", "")
            try:
                subprocess.run(["docker", "restart", slot],
                               capture_output=True, timeout=30)
                self.send_json(200, {"ok": True})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})

        elif path == "/action/set-owner":
            import fcntl
            slot      = body.get("slot", "").strip()
            new_owner = body.get("owner", "").strip()
            if not slot or not new_owner:
                self.send_json(400, {"error": "slot e owner são obrigatórios"})
                return
            registry_file = ROOT / "registry" / "slots.json"
            lock_file     = ROOT / "registry" / "slots.lock"
            try:
                with open(lock_file, "w") as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    slots = json.loads(registry_file.read_text())
                    updated = next((s for s in slots if s["slot_name"] == slot), None)
                    if not updated:
                        fcntl.flock(lf, fcntl.LOCK_UN)
                        self.send_json(404, {"error": f"slot '{slot}' não encontrado"})
                        return
                    updated["owner"] = new_owner
                    registry_file.write_text(
                        json.dumps(slots, indent=2, ensure_ascii=False) + "\n"
                    )
                    fcntl.flock(lf, fcntl.LOCK_UN)
                self.send_json(200, {"ok": True})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})

        else:
            self.send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


if __name__ == "__main__":
    threading.Thread(target=_background_refresh, daemon=True, name="cache-refresh").start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"HML Agent [{SERVER_NAME}] em http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
