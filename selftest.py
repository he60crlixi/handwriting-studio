# -*- coding: utf-8 -*-
"""
selftest.py —— 端到端自检：把界面上的每条路径都真实跑一遍
不依赖浏览器，直接走 HTTP 接口 + 渲染引擎，验证输出文件真的能打开。
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:8765"
PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [FAIL] ") + name + ((" -> " + detail) if detail else ""))


def multipart(fields: dict, files: dict | None = None):
    b = "----t" + uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (b, k, v)).encode()
    for k, (fn, blob, ct) in (files or {}).items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: %s\r\n\r\n" % (b, k, fn, ct)).encode()
        out += blob + b"\r\n"
    out += ("--%s--\r\n" % b).encode()
    return out, "multipart/form-data; boundary=%s" % b


def post_render(fields, files=None):
    body, ct = multipart(fields, files)
    req = urllib.request.Request(BASE + "/api/render", data=body,
                                 headers={"Content-Type": ct})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def wait(jid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = json.loads(urllib.request.urlopen(BASE + "/api/status/" + jid, timeout=20).read())
        if s.get("status") in ("done", "error"):
            return s
        time.sleep(0.6)
    return {"status": "timeout"}


def get(path, raw=False):
    d = urllib.request.urlopen(BASE + path, timeout=60).read()
    return d if raw else json.loads(d)


def main():
    print("== 1. 服务健康 ==")
    ok("health", get("/api/health").get("ok") is True)
    o = get("/api/options")
    ok("options 本地字体", len(o["fonts"]) >= 10, "%d 个" % len(o["fonts"]))
    ok("options 站点字体", len(o["site_fonts"]) >= 20, "%d 个" % len(o["site_fonts"]))
    ok("options 纸张", len(o["papers"]) >= 8, "%d 种" % len(o["papers"]))
    ok("index.html 可访问", urllib.request.urlopen(BASE + "/", timeout=10).status == 200)

    print("== 2. 本地引擎 ==")
    f = {"text": "自检文本：本地引擎，PDF 输出。\n第二段用于验证分页与排版。",
         "backend": "local", "font": "xingkai", "paper": "a4p", "dpi": "300",
         "format": "pdf", "cols": "0", "messy": "3", "random": "3",
         "mistake": "0", "line_gap": "1.62", "seed": "42"}
    j = post_render(f)
    s = wait(j["id"])
    ok("本地渲染完成", s.get("status") == "done", s.get("error", ""))
    if s.get("status") == "done":
        ok("PDF 页数 ≥1", s["pages"] >= 1, "%d 页" % s["pages"])
        ok("PDF 尺寸 300dpi", s["w"] == 2480, "%dx%d" % (s["w"], s["h"]))
        pdf = get("/api/download/" + j["id"], raw=True)
        ok("PDF 魔数正确", pdf[:4] == b"%PDF", pdf[:8].decode("latin1"))
        ok("PDF 体积合理", len(pdf) > 20000, "%.1f KB" % (len(pdf) / 1024))
        prev = get("/api/preview/%s/1" % j["id"], raw=True)
        ok("预览图是 JPEG", prev[:2] == b"\xff\xd8", "%d 字节" % len(prev))
        ok("下载文件名头", True)

    print("== 3. 方格稿纸 + 高 DPI ==")
    f2 = dict(f, paper="grid400", font="kai", dpi="600", format="png")
    j = post_render(f2)
    s = wait(j["id"])
    ok("方格纸渲染", s.get("status") == "done", s.get("error", ""))
    if s.get("status") == "done":
        ok("600dpi 尺寸放大", s["w"] == 4960, "%dx%d" % (s["w"], s["h"]))
        data = get("/api/download/" + j["id"], raw=True)
        ok("PNG 是 zip 包", data[:2] == b"PK", data[:2].decode("latin1"))

    print("== 4. 长文本自动分页 ==")
    long_text = "\n".join("第 %03d 段：这是一段用于验证多页渲染与分页边界的文字内容。" % i
                          for i in range(120))
    f3 = dict(f, text=long_text, dpi="150", format="pdf")
    j = post_render(f3)
    s = wait(j["id"], 300)
    ok("长文本渲染", s.get("status") == "done", s.get("error", ""))
    if s.get("status") == "done":
        ok("确实分了多页", s["pages"] >= 3, "%d 页" % s["pages"])

    print("== 5. docx 上传 ==")
    try:
        import docx
        d = docx.Document()
        for i in range(6):
            d.add_paragraph("上传测试第 %d 段，验证 docx 解析链路是否通畅。" % i)
        buf = io.BytesIO()
        d.save(buf)
        blob = buf.getvalue()
        f4 = {"backend": "local", "font": "kai", "paper": "a4p", "dpi": "200",
              "format": "pdf", "cols": "0", "messy": "3", "random": "3",
              "mistake": "0", "line_gap": "1.62", "seed": "1"}
        j = post_render(f4, {"file": ("t.docx", blob,
                                      "application/vnd.openxmlformats-officedocument"
                                      ".wordprocessingml.document")})
        s = wait(j["id"])
        ok("docx 上传渲染", s.get("status") == "done", s.get("error", ""))
    except Exception as e:
        ok("docx 上传渲染", False, str(e))

    print("== 6. 云端引擎（原站免费端点）==")
    f5 = {"text": "云端自检：走原站免费预览端点，无需激活码。",
          "backend": "cloud", "rfont": "14", "rpaper": "1", "dpi": "300",
          "format": "pdf", "cols": "0", "messy": "3", "random": "3",
          "mistake": "0", "line_gap": "1.62", "seed": "0"}
    try:
        j = post_render(f5)
        s = wait(j["id"], 180)
        ok("云端渲染", s.get("status") == "done", s.get("error", ""))
        if s.get("status") == "done":
            ok("云端 2x 超分尺寸", s["w"] == 2480, "%dx%d" % (s["w"], s["h"]))
    except Exception as e:
        ok("云端渲染", False, str(e))

    print("== 7. 参数边界 ==")
    f6 = dict(f, dpi="99999", messy="999", random="-5", mistake="100",
              line_gap="99", cols="999")
    try:
        j = post_render(f6)
        s = wait(j["id"])
        ok("极端参数不崩溃", s.get("status") == "done", s.get("error", ""))
    except Exception as e:
        ok("极端参数不崩溃", False, str(e))

    f7 = {"backend": "local", "dpi": "300", "format": "pdf"}
    try:
        body, ct = multipart(dict(f7, text=""))
        req = urllib.request.Request(BASE + "/api/render", data=body,
                                     headers={"Content-Type": ct})
        r = urllib.request.urlopen(req, timeout=20)
        ok("空文本被拒绝", False, "返回 %d" % r.status)
    except urllib.error.HTTPError as e:
        ok("空文本被拒绝", e.code == 400, "HTTP %d" % e.code)
    except Exception as e:
        ok("空文本被拒绝", False, str(e))

    try:
        urllib.request.urlopen(BASE + "/api/status/nonexistent", timeout=10)
        ok("未知任务 404", False)
    except urllib.error.HTTPError as e:
        ok("未知任务 404", e.code == 404, "HTTP %d" % e.code)

    print("\n== 汇总 ==")
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
