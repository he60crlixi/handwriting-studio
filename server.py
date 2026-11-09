# -*- coding: utf-8 -*-
"""
手写工坊 · 本地版  ——  服务端
纯标准库 + Pillow/numpy，一个进程跑起来就能用，不联网、不收费、不限页数。
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import socketserver
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict

import engine

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
OUT_DIR = os.path.join(ROOT, "output")
os.makedirs(OUT_DIR, exist_ok=True)

JOBS: Dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_UPLOAD = 40 * 1024 * 1024


# ------------------------------------------------------------------ multipart
def parse_multipart(body: bytes, boundary: bytes):
    fields: Dict[str, str] = {}
    files: Dict[str, tuple] = {}
    delim = b"--" + boundary
    for part in body.split(delim):
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        part = part.lstrip(b"\r\n")
        if part.startswith(b"--"):
            break
        head, _, data = part.partition(b"\r\n\r\n")
        if not _:
            continue
        data = data[:-2] if data.endswith(b"\r\n") else data
        hdr = head.decode("utf-8", "replace")
        m = re.search(r'name="([^"]*)"', hdr)
        if not m:
            continue
        name = m.group(1)
        fm = re.search(r'filename="([^"]*)"', hdr)
        if fm:
            fn = fm.group(1)
            if fn:
                files[name] = (fn, data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


# ------------------------------------------------------------------ 任务
def _run_job(job_id: str, text: str, opts: engine.RenderOptions, fmt: str,
             backend: str = "local", rfont: str = "14", rpaper: str = "1"):
    t0 = time.time()
    try:
        if backend == "cloud":
            import remote
            pages = remote.render_text(
                text, font=rfont, paper=rpaper,
                mistake=opts.mistake_rate, messy=opts.messy,
                random_=opts.char_random, upscale=max(1, opts.dpi // 150))
        else:
            pages = engine.render_pages(text, opts)
        # 预览缩略图（长边 ≤ 1000px），供前端逐页展示
        prev_dir = os.path.join(OUT_DIR, job_id)
        os.makedirs(prev_dir, exist_ok=True)
        for i, p in enumerate(pages, 1):
            th = p.copy()
            if max(th.size) > 1000:
                k = 1000.0 / max(th.size)
                th = th.resize((int(th.width * k), int(th.height * k)), engine.Image.LANCZOS)
            th.save(os.path.join(prev_dir, "%03d.jpg" % i), "JPEG", quality=82)

        if fmt == "png":
            data = engine.pages_to_zip(pages, "PNG")
            ext, mime = "zip", "application/zip"
        elif fmt == "jpg":
            data = engine.pages_to_zip(pages, "JPG", quality=95)
            ext, mime = "zip", "application/zip"
        else:
            data = engine.pages_to_pdf(pages, opts.dpi)
            ext, mime = "pdf", "application/pdf"
        path = os.path.join(OUT_DIR, "%s.%s" % (job_id, ext))
        with open(path, "wb") as f:
            f.write(data)
        with JOBS_LOCK:
            JOBS[job_id].update(status="done", path=path, mime=mime, ext=ext,
                                size=len(data), pages=len(pages),
                                w=pages[0].width, h=pages[0].height,
                                preview=prev_dir, backend=backend,
                                elapsed=round(time.time() - t0, 2))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id].update(status="error", error=str(e))


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "HandwritingStudio/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静音
        pass

    # ---------- helpers
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _file(self, path: str, mime: str, download_name: str | None = None):
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            q = urllib.parse.quote(download_name)
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s" % q)
        self.end_headers()
        self.wfile.write(data)

    def _html(self, text: str, code=200):
        b = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    # ---------- GET
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            p = os.path.join(STATIC, "index.html")
            return self._file(p, "text/html; charset=utf-8")
        if path == "/api/options":
            import remote
            return self._json({
                "fonts": [{"key": k, "name": v[0]} for k, v in engine.FONT_MAP.items()],
                "papers": [{"key": k, "name": v[0], "w": v[1], "h": v[2], "style": v[3]}
                           for k, v in engine.PAPER_MAP.items()],
                "site_fonts": [{"key": v, "name": n} for v, n in remote.SITE_FONTS],
                "site_papers": [{"key": v, "name": n} for v, n in remote.SITE_PAPERS],
            })
        if path.startswith("/api/status/"):
            jid = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                j = JOBS.get(jid)
            if not j:
                return self._json({"error": "任务不存在"}, 404)
            return self._json(j)
        if path.startswith("/api/preview/"):
            rest = path[len("/api/preview/"):]
            jid, _, idx = rest.partition("/")
            with JOBS_LOCK:
                j = JOBS.get(jid)
            if not j or j.get("status") != "done":
                return self._json({"error": "未就绪"}, 404)
            fp = os.path.join(j["preview"], "%03d.jpg" % int(idx))
            if not os.path.isfile(fp):
                return self._json({"error": "无此页"}, 404)
            return self._file(fp, "image/jpeg")
        if path.startswith("/api/download/"):
            jid = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                j = JOBS.get(jid)
            if not j or j.get("status") != "done":
                return self._json({"error": "文件未就绪"}, 404)
            name = "手写稿_%s.%s" % (j.get("stamp", jid[:8]), j["ext"])
            return self._file(j["path"], j["mime"], name)
        if path == "/api/health":
            return self._json({"ok": True})

        # 静态资源
        rel = path.lstrip("/")
        if rel and ".." not in rel and "\\" not in rel:
            fp = os.path.join(STATIC, rel)
            if os.path.isfile(fp):
                mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                return self._file(fp, mime)
        return self._json({"error": "not found"}, 404)

    # ---------- POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/render":
            return self._json({"error": "not found"}, 404)

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return self._json({"error": "请求为空或超过 40MB"}, 400)
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        fields, files = {}, {}
        if "multipart/form-data" in ctype:
            m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', ctype)
            if not m:
                return self._json({"error": "缺少 boundary"}, 400)
            fields, files = parse_multipart(body, (m.group(1) or m.group(2)).encode())
        else:
            try:
                fields = json.loads(body.decode("utf-8"))
            except Exception:
                return self._json({"error": "无法解析请求体"}, 400)

        # 文本来源
        text = (fields.get("text") or "").replace("\r\n", "\n")
        if "file" in files and files["file"][1]:
            fname, blob = files["file"]
            tmp = os.path.join(OUT_DIR, "_in_%s_%s" % (uuid.uuid4().hex[:8],
                                                       os.path.basename(fname)))
            with open(tmp, "wb") as f:
                f.write(blob)
            try:
                extracted = engine.extract_text(tmp)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            text = (text + "\n" + extracted).strip() if text.strip() else extracted

        text = (text or "").strip()
        if not text:
            return self._json({"error": "请输入文字或上传 .docx/.txt 文件"}, 400)
        if len(text) > 200000:
            text = text[:200000]

        def num(k, d):
            try:
                return float(fields.get(k, d))
            except (TypeError, ValueError):
                return float(d)

        opts = engine.RenderOptions(
            font=fields.get("font") or "xingkai",
            paper=fields.get("paper") or "a4p",
            dpi=max(72, min(1200, int(num("dpi", 300)))),
            font_size=max(0.0, num("font_size", 0)),
            line_gap=max(1.0, min(3.0, num("line_gap", 1.62))),
            cols=max(0, int(num("cols", 0))),
            mistake_rate=max(0.0, min(10.0, num("mistake", 0))),
            messy=max(0.0, min(10.0, num("messy", 3))),
            char_random=max(0.0, min(10.0, num("random", 3))),
            seed=int(num("seed", 0)) or (int(time.time() * 1000) & 0xFFFF),
            indent=max(0, min(8, int(num("indent", 2)))),
            show_rules=(fields.get("rules", "1") not in ("0", "false", "")),
        )
        fmt = (fields.get("format") or "pdf").lower()
        if fmt not in ("pdf", "png", "jpg"):
            fmt = "pdf"

        backend = (fields.get("backend") or "local").lower()
        if backend not in ("local", "cloud"):
            backend = "local"

        jid = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[jid] = {"id": jid, "status": "running", "pages": len(text),
                         "stamp": time.strftime("%Y%m%d_%H%M%S"), "backend": backend}
        threading.Thread(target=_run_job,
                         args=(jid, text, opts, fmt, backend,
                               fields.get("rfont") or "14",
                               fields.get("rpaper") or "1"),
                         daemon=True).start()
        return self._json({"id": jid, "chars": len(text), "backend": backend})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    srv = Server((a.host, a.port), Handler)
    print("手写工坊·本地版  →  http://%s:%d" % (a.host, a.port))
    print("Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
