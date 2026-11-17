#!/usr/bin/env python3
"""Servidor del experimento QR (benigno). Solo biblioteca estándar.

Guarda por visitante: token aleatorio (generado en el navegador), id del póster y hora.
NO guarda IP, user-agent ni cookies. Uso: python3 server.py  (puerto 8000 por defecto)
"""
import json, os, re, sqlite3, time, threading
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
DB = os.environ.get("QR_DB", str(BASE / "visitas.db"))
PORT = int(os.environ.get("PORT", "8000"))
STATS_KEY = os.environ.get("STATS_KEY", "")          # define una clave para ver /api/stats
BOT_WORDS = ("bot", "crawler", "spider", "preview", "facebookexternalhit", "slackbot",
             "whatsapp", "telegram", "curl", "python-requests", "headless")
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
POSTER_RE = re.compile(r"^[a-z0-9-]{1,12}$")

lock = threading.Lock()
hits = defaultdict(lambda: deque(maxlen=30))          # límite de tasa por IP, solo en memoria

DATABASE_URL = os.environ.get("DATABASE_URL", "")
TRUST_PROXY = os.environ.get("TRUST_PROXY", "") == "1"   # ponlo en 1 detrás de Render/Cloudflare

class Conn:
    """Envoltura mínima: mismo código para SQLite (local) y Postgres (Render)."""
    def __init__(self):
        if DATABASE_URL:
            import psycopg2
            self.c, self.pg = psycopg2.connect(DATABASE_URL), True
        else:
            self.c, self.pg = sqlite3.connect(DB), False
    def run(self, sql, args=()):
        cur = self.c.cursor()
        cur.execute(sql.replace("?", "%s") if self.pg else sql, args)
        return cur
    def __enter__(self): return self
    def __exit__(self, et, ev, tb):
        self.c.commit() if et is None else self.c.rollback()
        self.c.close()

def db():
    c = Conn()
    pk = "SERIAL PRIMARY KEY" if c.pg else "INTEGER PRIMARY KEY"
    c.run(f"CREATE TABLE IF NOT EXISTS visitas (n {pk}, token TEXT UNIQUE, poster TEXT, ts BIGINT)")
    return c

def rate_ok(ip):
    now = time.time(); q = hits[ip]
    while q and now - q[0] > 60: q.popleft()
    if len(q) >= 60: return False
    q.append(now); return True

class H(BaseHTTPRequestHandler):
    server_version = "qr-exp"
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-src https://www.youtube-nocookie.com; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            return self._send(200, (BASE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/health":
            return self._send(200, "ok", "text/plain")
        if path == "/api/stats":
            if not STATS_KEY or f"k={STATS_KEY}" not in query:
                return self._send(403, '{"error":"forbidden"}')
            with lock, db() as c:
                total = c.run("SELECT COUNT(*) FROM visitas").fetchone()[0]
                rows = c.run("SELECT poster, COUNT(*) FROM visitas GROUP BY poster").fetchall()
            return self._send(200, json.dumps({"total": total, "por_poster": dict(rows)}))
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/api/hit": return self._send(404, '{"error":"not found"}')
        ip = self.client_address[0]
        if TRUST_PROXY:
            ip = self.headers.get("X-Forwarded-For", ip).split(",")[-1].strip()
        if not rate_ok(ip): return self._send(429, '{"error":"rate"}')
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 512: raise ValueError
            d = json.loads(self.rfile.read(n))
            token, poster = str(d.get("t", "")), str(d.get("p", "x"))
        except Exception:
            return self._send(400, '{"error":"bad request"}')
        if not TOKEN_RE.match(token) or not POSTER_RE.match(poster):
            return self._send(400, '{"error":"bad request"}')
        ua = self.headers.get("User-Agent", "").lower()
        with lock, db() as c:
            if any(w in ua for w in BOT_WORDS):                    # los bots no inflan el contador
                total = c.run("SELECT COUNT(*) FROM visitas").fetchone()[0]
                return self._send(200, json.dumps({"n": None, "total": total}))
            c.run("INSERT INTO visitas(token, poster, ts) VALUES (?,?,?) ON CONFLICT(token) DO NOTHING",
                  (token, poster, int(time.time())))
            # número = posición del visitante (robusto aunque queden huecos en la secuencia)
            n_ = c.run("SELECT COUNT(*) FROM visitas WHERE n <= (SELECT n FROM visitas WHERE token=?)",
                       (token,)).fetchone()[0]
            total = c.run("SELECT COUNT(*) FROM visitas").fetchone()[0]
        self._send(200, json.dumps({"n": n_, "total": total}))

    def log_message(self, *a): pass                                 # sin logs con IP

if __name__ == "__main__":
    with db(): pass
    print(f"Escuchando en http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
