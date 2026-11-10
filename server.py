#!/usr/bin/env python3
"""Servidor web para la impresora Y50.

   python3 server.py [--addr MAC] [--port N]

API:
  GET  /            -> interfaz
  GET  /api/info    -> modelo / firmware / serie / estado
  POST /api/print   -> {copies, density, widthMm, wDots, hDots, bits(base64)}
  POST /api/pattern -> imprime la etiqueta de calibración 50x30 (sin body)
  POST /api/feed    -> avanza una etiqueta
  POST /api/raw     -> {hex} manda bytes crudos al Bluetooth (avanzado)
"""
import argparse
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.printer import Printer, DEFAULT_MAC, explain_link_error
from lib import ypl
from scripts.print_test import make_label

CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

PRINT_LOCK = threading.Lock()


def load_device():
    config = {}
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}
    return config.get("device", DEFAULT_MAC)


class Api:
    """Unas pocas operaciones sobre el `Printer`, serializadas."""

    def __init__(self):
        self.p = Printer()

    def info(self):
        with PRINT_LOCK:
            try:
                out = self.p.info()
                out["transport"] = self.p.t.name if self.p.t else "?"
                return out
            finally:
                self.p.close()

    def print_bits(self, width_mm, w_dots, h_dots, bits_b64, copies, density, threshold_ok=True):
        if width_mm * ypl.DPI != w_dots:
            return {"error": f"anchura {w_dots} px no coincide con {width_mm} mm"}, 400
        rows = []
        bits = base64.b64decode(bits_b64)
        stride = (w_dots + 7) // 8
        if len(bits) < stride * h_dots:
            return {"error": "bitmap truncado"}, 400
        for y in range(h_dots):
            row = []
            base = y * stride
            for x in range(w_dots):
                b = bits[base + x // 8]
                row.append(1 if b & (0x80 >> (x % 8)) else 0)
            rows.append(row)
        if not rows:
            return {"error": "etiqueta vacía"}, 400
        with PRINT_LOCK:
            try:
                err = self.p.print_rows(rows, width_mm, copies=copies, density=density)
                return {"ok": True} if not err else {"error": str(err)}
            finally:
                self.p.close()

    def feed(self):
        with PRINT_LOCK:
            try:
                self.p.feed()
                return {"ok": True}
            finally:
                self.p.close()

    def pattern(self):
        rows = make_label()
        with PRINT_LOCK:
            try:
                for _g, _c, d, v in self.p.transact([ypl.request(0x05, 0x0B)], 0.8):
                    if (_g, _c) == (0x05, 0x0B) and d == ypl.DIR_REPLY:
                        raw = v[0] if isinstance(v, bytes) and v else v
                        if raw != 0:
                            return {"error": f"impresora no lista: {ypl.describe_status(raw)}"}, 409
                self.p._send_stream(ypl.build_stream(rows, 50, job=0x20))
                return {"ok": True}
            finally:
                self.p.close()

    def raw(self, hexstr):
        data = bytes.fromhex(hexstr)
        from lib.printer import SPPTransport
        with PRINT_LOCK:
            t = SPPTransport(self.p._target or DEFAULT_MAC)
            try:
                t.write(data)
                return {"ok": True, "sent": len(data)}
            finally:
                t.close()


API = Api()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Y50Web/1.0"

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("[api] %s\n" % (fmt % args))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, relpath, ctype):
        path = os.path.normpath(os.path.join(WEB, relpath))
        if not path.startswith(WEB) or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route in ("/", "/index.html"):
            return self._file("index.html", "text/html; charset=utf-8")
        if route == "/style.css":
            return self._file("style.css", "text/css; charset=utf-8")
        if route == "/app.js":
            return self._file("app.js", "text/javascript; charset=utf-8")
        if route.startswith("/vendor/qrcode-generator.js"):
            return self._file("vendor/qrcode-generator.js", "text/javascript; charset=utf-8")
        if route == "/api/info":
            try:
                return self._json(API.info())
            except OSError as e:
                return self._json({"error": explain_link_error(e)}, 502)
            except Exception as e:
                return self._json({"error": repr(e)}, 500)
        if route == "/api/health":
            return self._json({"ok": True})
        self.send_error(404)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, ValueError):
            return self._json({"error": "JSON inválido"}, 400)
        route = self.path.split("?", 1)[0]
        try:
            if route == "/api/print":
                out = API.print_bits(
                    int(payload.get("widthMm", 50)),
                    int(payload["wDots"]),
                    int(payload["hDots"]),
                    payload["bits"],
                    int(payload.get("copies", 1)),
                    int(payload.get("density", 8)),
                )
                return self._json(out)
            if route == "/api/feed":
                return self._json(API.feed())
            if route == "/api/pattern":
                return self._json(API.pattern())
            if route == "/api/raw":
                return self._json(API.raw(payload.get("hex", "")))
        except OSError as e:
            return self._json({"error": explain_link_error(e)}, 502)
        except Exception as e:
            return self._json({"error": repr(e)}, 500)
        self.send_error(404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default=load_device(), help=f"MAC de la impresora (por defecto {DEFAULT_MAC})")
    ap.add_argument("--port", type=int, default=8899)
    args = ap.parse_args()

    global API
    API.p._target = args.addr

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"servidor web en http://localhost:{args.port}")
    print(f"impresora en {args.addr}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("saliendo")


if __name__ == "__main__":
    main()
