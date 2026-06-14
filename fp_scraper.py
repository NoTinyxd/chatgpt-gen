#!/usr/bin/env python3
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from console import log


HOST = "127.0.0.1"
PORT = 8765
FP_DIR = Path("fp")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>OpenAI Sentinel FP scraper</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: ui-monospace, "JetBrains Mono", Menlo, monospace;
         background:#0b0b0e; color:#e7e7ea; padding:2rem;
         max-width:60rem; margin:0 auto; }
  h1 { font-size:1.2rem; color:#94d2ff; margin:0 0 1rem; }
  .row { display:flex; gap:1rem; align-items:center; margin:1rem 0; }
  button { background:#4ade80; color:#0b0b0e; border:0;
           padding:.7rem 1.4rem; font-size:1rem; font-weight:700;
           border-radius:.3rem; cursor:pointer; font-family:inherit; }
  button:hover { background:#22c55e; }
  #count { font-size:2.4rem; font-weight:800; color:#4ade80; }
  pre { background:#15151a; padding:1rem; border-radius:.3rem;
        overflow:auto; max-height:30rem; font-size:.8rem; line-height:1.4;
        border:1px solid #222; }
  .ok { color:#4ade80; } .err { color:#f87171; } .dim { color:#7a7a82; }
  code { color:#fbbf24; }
</style></head>
<body>
<h1>OpenAI Sentinel fingerprint scraper</h1>
<p class="dim">Click capture to snapshot this browser's fingerprint into <code>fp/</code>. Open this page from each browser / profile / window you want to use as a source.</p>
<div class="row"><span class="dim">captured:</span><span id="count">…</span></div>
<div class="row"><button id="btn">Capture fingerprint</button><span id="status" class="dim"></span></div>
<pre id="last"></pre>
<script>
async function refreshCount() {
  const r = await fetch('/count');
  document.getElementById('count').textContent = (await r.json()).count;
}
function pickKey(obj) {
  const k = Object.keys(obj);
  return k.length ? k[Math.floor(Math.random()*k.length)] : "";
}
function navProtoSample() {
  const keys = [];
  for (const k in Navigator.prototype) keys.push(k);
  if (!keys.length) return "platform−" + navigator.platform;
  const k = keys[Math.floor(Math.random()*keys.length)];
  try { return k + "−" + navigator[k]; }
  catch (_) { return "platform−" + navigator.platform; }
}
function secChUa() {
  if (!navigator.userAgentData || !navigator.userAgentData.brands) return null;
  return navigator.userAgentData.brands
    .map(b => `"${b.brand}";v="${b.version}"`).join(", ");
}
async function capture() {
  const status = document.getElementById('status');
  status.className = 'dim'; status.textContent = 'capturing…';
  const fp = {
    screen_sum: screen.width + screen.height,
    date_string: "" + new Date(),
    heap_size_limit: (performance.memory && performance.memory.jsHeapSizeLimit) || null,
    user_agent: navigator.userAgent,
    script_src: "https://sentinel.openai.com/backend-api/sentinel/sdk.js",
    data_build: null,
    language: navigator.language,
    languages: (navigator.languages || []).join(","),
    nav_proto_sample: navProtoSample(),
    doc_key_sample: pickKey(document),
    window_key_sample: pickKey(window),
    url_param_keys: Array.from(new URLSearchParams(location.search).keys()).join(","),
    hardware_concurrency: navigator.hardwareConcurrency,
    in_ai:             +("ai" in window),
    in_install_trigger:+("InstallTrigger" in window),
    in_cache:          +("cache" in window),
    in_data:           +("data" in window),
    in_solana:         +("solana" in window),
    in_force_sync:     +("forceSync" in window),
    in_memory:         +("memory" in window),
  };
  const uad = navigator.userAgentData;
  const headers = {
    "User-Agent": navigator.userAgent,
    "Accept-Language": (navigator.language || "en-US") + ",en;q=0.9",
    "Sec-Ch-Ua": secChUa(),
    "Sec-Ch-Ua-Platform": uad ? `"${uad.platform}"` : null,
    "Sec-Ch-Ua-Mobile": uad ? (uad.mobile ? "?1" : "?0") : null,
    "Oai-Language": "en-US"
  };
  const payload = { fp, headers, captured_at: new Date().toISOString() };
  const r = await fetch('/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (r.ok) {
    const d = await r.json();
    status.className = 'ok';
    status.textContent = 'saved → ' + d.file;
    document.getElementById('last').textContent = JSON.stringify(payload, null, 2);
    refreshCount();
  } else {
    status.className = 'err';
    status.textContent = 'failed: HTTP ' + r.status;
  }
}
document.getElementById('btn').addEventListener('click', capture);
refreshCount();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, code: int, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            data = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/count":
            n = len(list(FP_DIR.glob("*.json"))) if FP_DIR.is_dir() else 0
            self._send_json(200, {"count": n})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"invalid json: {exc}"})
            return
        if not isinstance(data, dict) or "fp" not in data or "headers" not in data:
            self._send_json(400, {"error": "expected {fp, headers, captured_at}"})
            return
        FP_DIR.mkdir(exist_ok=True)
        name = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f") + ".json"
        path = FP_DIR / name
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        log("SUCCESS", f"fingerprint saved → {path}")
        self._send_json(200, {"file": str(path)})


def main():
    FP_DIR.mkdir(exist_ok=True)
    srv = HTTPServer((HOST, PORT), Handler)
    log("INFO", f"FP scraper running at http://{HOST}:{PORT}/")
    log("INFO", "open that URL in any browser/profile and click Capture")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("WAITING", "shutting down")
        srv.server_close()


if __name__ == "__main__":
    main()
