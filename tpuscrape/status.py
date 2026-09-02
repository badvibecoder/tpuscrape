"""Local status dashboard (FastAPI) for monitoring and human-in-the-loop control."""
from __future__ import annotations

import threading

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .frontier import Queue
from .runtime import RuntimeState
from .store import Store

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tpuscrape — Status</title>
<style>
  :root { --bg:#0f172a; --card:#1e293b; --text:#e2e8f0; --muted:#94a3b8;
          --green:#22c55e; --amber:#f59e0b; --red:#ef4444; --blue:#3b82f6; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif; padding:2rem; }
  h1 { margin-top:0; font-size:1.5rem; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:1rem; margin:1rem 0; }
  .card { background:var(--card); border-radius:10px; padding:1rem; }
  .card .k { color:var(--muted); font-size:.85rem; text-transform:uppercase; letter-spacing:.05em; }
  .card .v { font-size:1.6rem; font-weight:700; }
  .banner { border-radius:10px; padding:1rem 1.25rem; margin:1rem 0; font-weight:600; }
  .banner.blocked { background:#7f1d1d; border:1px solid #b91c1c; }
  .banner.paused { background:#78350f; border:1px solid #b45309; }
  .banner.ok { background:#14532d; border:1px solid #16a34a; }
  button { background:var(--blue); color:#fff; border:0; border-radius:8px; padding:.55rem 1rem; font-size:1rem; cursor:pointer; margin-right:.5rem; }
  button.secondary { background:#334155; }
  textarea { width:100%; min-height:90px; background:#0b1220; color:var(--text); border:1px solid #334155; border-radius:8px; padding:.6rem; font-family:monospace; }
  pre { background:#0b1220; border:1px solid #334155; border-radius:8px; padding:.75rem; max-height:420px; overflow:auto; font-size:.85rem; }
  table { border-collapse:collapse; width:100%; }
  td,th { text-align:left; padding:.35rem .6rem; border-bottom:1px solid #334155; }
  .badge { display:inline-block; padding:.1rem .5rem; border-radius:999px; font-size:.75rem; font-weight:700; }
  .done { background:#14532d; color:#86efac; } .queued { background:#1e3a8a; color:#bfdbfe; }
  .in_progress { background:#78350f; color:#fcd34d; } .blocked { background:#7f1d1d; color:#fca5a5; }
  .failed { background:#450a0a; color:#fca5a5; }
</style>
</head>
<body>
<h1>🖥️ tpuscrape</h1>
<div id="banner"></div>
<div class="grid">
  <div class="card"><div class="k">Done</div><div class="v" id="s-done">–</div></div>
  <div class="card"><div class="k">Queued</div><div class="v" id="s-queued">–</div></div>
  <div class="card"><div class="k">In progress</div><div class="v" id="s-in_progress">–</div></div>
  <div class="card"><div class="k">Blocked</div><div class="v" id="s-blocked">–</div></div>
  <div class="card"><div class="k">Failed</div><div class="v" id="s-failed">–</div></div>
  <div class="card"><div class="k">Uptime</div><div class="v" id="s-uptime">–</div></div>
</div>

<div class="card">
  <div class="k">Controls</div>
  <p><button onclick="ctl('pause')">⏸ Pause</button>
     <button onclick="ctl('resume')">▶ Resume</button>
     <button class="secondary" onclick="ctl('retry-blocked')">🔁 Retry blocked</button></p>
  <div class="k">Add URLs (one per line)</div>
  <textarea id="urls" placeholder="one /gpu-specs/<slug>.c#### URL per line"></textarea>
  <p><button onclick="addUrls()">➕ Add URLs to feed</button></p>
</div>

<div class="card">
  <div class="k">Current / latest activity</div>
  <pre id="events">loading…</pre>
</div>

<script>
async function refresh(){
  try {
    const r = await fetch('/api/state'); const s = await r.json();
    for (const k of ['done','queued','in_progress','blocked','failed'])
      document.getElementById('s-'+k).textContent = s.counts[k] ?? 0;
    document.getElementById('s-uptime').textContent = fmt(s.uptime_s);
    const b = document.getElementById('banner');
    if (s.blocked) {
      b.className = 'banner blocked';
      b.innerHTML = '⚠️ <b>Challenge detected</b> — solve it in the Chrome window, or press “Retry blocked”.<br>URL: ' + esc(s.blocked_url);
    } else if (s.paused) {
      b.className = 'banner paused';
      b.innerHTML = '⏸ <b>Paused</b> — press Resume to continue.';
    } else {
      b.className = 'banner ok';
      b.innerHTML = '✅ Running — scraping ' + (s.current ? esc(s.current.name||s.current.id||'') : '…');
    }
    document.getElementById('events').textContent = (s.events||[]).join('\\n') || 'no events yet';
  } catch(e){ /* server not up yet */ }
}
function fmt(sec){ const m=Math.floor(sec/60), s=sec%60; return (m?m+'m ':'')+s+'s'; }
function esc(x){ return (x||'').replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
async function ctl(a){ await fetch('/api/'+a, {method:'POST'}); refresh(); }
async function addUrls(){
  await fetch('/api/add-urls', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({urls: document.getElementById('urls').value})});
  document.getElementById('urls').value=''; refresh();
}
refresh(); setInterval(refresh, 2000);
</script>
</body>
</html>"""


def create_app(store: Store, runtime: RuntimeState, queue: Queue) -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/state")
    def state():
        snap = runtime.snapshot()
        snap["counts"] = store.count_by_status()
        return snap

    @app.post("/api/pause")
    def pause():
        runtime.set_paused(True)
        runtime.log("paused by user")
        return {"ok": True}

    @app.post("/api/resume")
    def resume():
        runtime.set_paused(False)
        runtime.log("resumed by user")
        return {"ok": True}

    @app.post("/api/retry-blocked")
    def retry_blocked():
        n = 0
        for g in store.list_by_status("blocked"):
            store.set_status(g["id"], "queued")
            n += 1
        runtime.clear_blocked()
        runtime.log(f"retried {n} blocked GPU(s)")
        return {"ok": True, "requeued": n}

    @app.post("/api/add-urls")
    async def add_urls(request: Request):
        body = await request.json()
        raw = body.get("urls", "")
        added = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "gpu-specs/" not in line:
                continue
            from .frontier import extract_id

            gpu_id = extract_id(line)
            before = store.has(gpu_id) if gpu_id else False
            queue.add_url(line, source="feed")
            if gpu_id and not before and store.has(gpu_id):
                added += 1
        runtime.log(f"added {added} URL(s) from status page")
        return {"ok": True, "added": added}

    return app


def start_server(app: FastAPI, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _run():
        server.run()

    threading.Thread(target=_run, daemon=True).start()
    return server
