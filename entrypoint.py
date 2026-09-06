"""Production edge entrypoint: Shopify webhook ingress + existing API proxy."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from shopify_webhook import handle_shopify_webhook

PUBLIC_PORT = int(os.getenv("PORT", "8080"))
UPSTREAM_PORT = int(os.getenv("OPSORA_UPSTREAM_PORT", "8081"))
UPSTREAM = f"http://127.0.0.1:{UPSTREAM_PORT}"


class EdgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _shopify(self, body):
        code, payload = handle_shopify_webhook(self, body)
        self._json(code, payload)

    def _proxy(self, body=b""):
        url = UPSTREAM + self.path
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length"}}
        req = Request(url, data=body or None, method=self.command, headers=headers)
        try:
            with urlopen(req, timeout=190) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
        except HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        except (URLError, TimeoutError) as exc:
            self._json(503, {"error": "Upstream unavailable", "detail": str(exc)[:200]})

    def do_OPTIONS(self):
        if self.path.startswith("/v1/webhooks/shopify") or self.path.startswith("/api/v1/webhooks/shopify"):
            self._json(200, {"status": "ok"})
            return
        self._proxy()

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        body = self._body()
        if self.path in {"/v1/webhooks/shopify", "/api/v1/webhooks/shopify"}:
            self._shopify(body)
            return
        self._proxy(body)

    def log_message(self, fmt, *args):
        print("[edge]", fmt % args, flush=True)


def main():
    env = os.environ.copy()
    env["PORT"] = str(UPSTREAM_PORT)
    upstream = subprocess.Popen(["python", "opsora_server.py"], env=env)
    server = ThreadingHTTPServer(("0.0.0.0", PUBLIC_PORT), EdgeHandler)
    print(f"Opsora edge listening on :{PUBLIC_PORT}; API upstream :{UPSTREAM_PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.shutdown()
        upstream.terminate()
        upstream.wait(timeout=15)


if __name__ == "__main__":
    main()
