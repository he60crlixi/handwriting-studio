# -*- coding: utf-8 -*-
"""
remote.py —— 复用 autohanding 的免费渲染端点，绕开付费墙

原理（实测结论，2026-11 抓包确认）：
  * 真正的付费门槛只挂在 handwrite-download/* 与 cp/order/deducted 上，
    必须携带合法激活码(cp)才放行；
  * handwrite-preview/* 完全免费、无需登录、返回的 PNG 没有任何水印，
    画质与付费版同源（同一套渲染服务），只是：
        - 单次请求页数上限 12 页
        - 输出尺寸固定约 150dpi（dpi 参数被服务端忽略）
  * 因此不必碰激活码：直接打 preview 端点即可拿到成品，
    再靠「文本分块 + 多次请求 + 本地合并 + 超分放大」突破 12 页与分辨率限制。
"""
from __future__ import annotations

import io
import re
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from typing import List, Tuple

from PIL import Image, ImageFilter

BASE = "https://www.autohanding.com"
PREVIEW_TEXT = BASE + "/api/v1/handwrite-preview/convert-text"
PREVIEW_FILE = BASE + "/api/v1/handwrite-preview/convert"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 站点字体（value -> 名称），从 app 包里的 <option> 还原
SITE_FONTS = [
    ("1", "栗壳坚坚体"), ("2", "喜脉喜欢体"), ("3", "pigtruman手写体"), ("4", "新叶念体"),
    ("6", "手写体1"), ("7", "平方洒脱体"), ("8", "王强手写体"), ("9", "日文-TekitouPoem"),
    ("10", "韩文-KimjungchulScript"), ("12", "硬笔楷书"), ("13", "繁体-辰宇落雁体"),
    ("14", "真实-手写体2"), ("15", "真实-手写体3"), ("16", "真实-手写体4"),
    ("17", "真实-手写体5"), ("18", "真实-手写体6"), ("19", "真实-手写体7"),
    ("20", "真实-手写体8"), ("21", "真实-手写体9"), ("22", "真实-手写体10"),
    ("23", "真实-手写体11"), ("24", "真实-手写体12"),
    ("1015", "真实-手写体3-加粗"), ("1016", "真实-手写体4-加粗"),
    ("1017", "真实-手写体5-加粗"), ("1018", "真实-手写体6-加粗"),
    ("1019", "真实-手写体7-加粗"), ("1020", "真实-手写体8-加粗"),
    ("1021", "真实-手写体9-加粗"), ("1022", "真实-手写体10-加粗"),
    ("1023", "真实-手写体11-加粗"), ("1024", "真实-手写体12-加粗"),
]

# 站点纸张（value -> 名称）
SITE_PAPERS = [
    ("0", "草稿纸-高清实拍"),
    ("1", "可打印-A4纵向-600dpi(4960x7015)"),
    ("2", "可打印-A4横向-600dpi(7015x4960)"),
    ("20", "实拍-单红线信稿纸"),
    ("30", "可打印-单红线A4信稿纸"),
    ("41", "实拍-红格子稿纸400字"),
    ("42", "可打印-黑格子稿纸400字"),
    ("43", "可打印-红格子稿纸400字"),
]

CHUNK_CHARS = 1600      # 单请求字符块（远低于站点 3500 上限，同时控制页数 ≤ 12）
RETRY = 3


class RemoteError(RuntimeError):
    pass


def _multipart(fields: dict, files: dict | None = None) -> Tuple[bytes, str]:
    b = "----WebKitFormBoundary" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n"
                   % (b, k)).encode())
        out.write(str(v).encode("utf-8") + b"\r\n")
    for k, (fn, blob, ct) in (files or {}).items():
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                   "Content-Type: %s\r\n\r\n" % (b, k, fn, ct)).encode())
        out.write(blob + b"\r\n")
    out.write(("--%s--\r\n" % b).encode())
    return out.getvalue(), "multipart/form-data; boundary=%s" % b


def _post(url: str, fields: dict, files: dict | None = None,
          timeout: int = 240) -> bytes:
    body, ctype = _multipart(fields, files)
    last = None
    for attempt in range(RETRY):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": ctype,
            "User-Agent": UA,
            "Origin": BASE,
            "Referer": BASE + "/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            last = RemoteError("HTTP %s: %s" % (e.code, detail))
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 + attempt * 3)
                continue
            raise last
        except Exception as e:  # 网络抖动
            last = RemoteError(str(e))
            time.sleep(2 + attempt * 3)
    raise last or RemoteError("请求失败")


def _zip_pages(blob: bytes) -> List[Image.Image]:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        head = blob[:200].decode("utf-8", "replace")
        raise RemoteError("返回不是压缩包，服务端可能限流：%s" % head)
    pages = []
    for name in sorted(n for n in z.namelist() if n.lower().endswith((".png", ".jpg", ".jpeg"))):
        im = Image.open(io.BytesIO(z.read(name)))
        pages.append(im.convert("RGB"))
    if not pages:
        raise RemoteError("返回包内没有图片")
    return pages


def _split_text(text: str, size: int = CHUNK_CHARS) -> List[str]:
    """按段落/句号切块，尽量不切断句子"""
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= size:
        return [text]
    chunks, buf = [], ""
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:
            cut = para.rfind("。", 0, size)
            cut = cut + 1 if cut > size * 0.4 else size
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:cut])
            para = para[cut:]
        if len(buf) + len(para) + 1 > size:
            chunks.append(buf)
            buf = para
        else:
            buf = (buf + "\n" + para).strip() if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def render_text(text: str, font: str = "14", paper: str = "1", mistake: float = 0,
                messy: float = 3, random_: float = 3, upscale: int = 2,
                progress=None) -> List[Image.Image]:
    chunks = _split_text(text)
    pages: List[Image.Image] = []
    for i, chunk in enumerate(chunks):
        fields = {
            "fullText": chunk,
            "fontType": str(font),
            "paperBgType": str(paper),
            "mistakeRate": str(int(max(0, min(10, mistake)))),
            "messyRatio": str(int(max(0, min(10, messy)))),
            "charRandom": str(int(max(0, min(10, random_)))),
            "clientId": "lc-" + uuid.uuid4().hex,
        }
        blob = _post(PREVIEW_TEXT, fields)
        pages.extend(_zip_pages(blob))
        if progress:
            progress(i + 1, len(chunks), len(pages))
    return _upscale(pages, upscale)


def render_docx(blob: bytes, filename: str = "input.docx", font: str = "14",
                paper: str = "1", mistake: float = 0, messy: float = 3,
                random_: float = 3, upscale: int = 2, progress=None) -> List[Image.Image]:
    ct = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          if filename.lower().endswith(".docx") else "application/octet-stream")
    fields = {
        "fontType": str(font),
        "paperBgType": str(paper),
        "mistakeRate": str(int(max(0, min(10, mistake)))),
        "messyRatio": str(int(max(0, min(10, messy)))),
        "charRandom": str(int(max(0, min(10, random_)))),
        "clientId": "lc-" + uuid.uuid4().hex,
    }
    data = _post(PREVIEW_FILE, fields, {"file": (filename, blob, ct)}, timeout=600)
    pages = _zip_pages(data)
    if progress:
        progress(1, 1, len(pages))
    return _upscale(pages, upscale)


def _upscale(pages: List[Image.Image], factor: int) -> List[Image.Image]:
    factor = max(1, min(4, int(factor or 1)))
    if factor == 1:
        return pages
    out = []
    for p in pages:
        big = p.resize((p.width * factor, p.height * factor), Image.LANCZOS)
        big = big.filter(ImageFilter.UnsharpMask(radius=1.6, percent=62, threshold=2))
        out.append(big)
    return out


def extract_docx_text(blob: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(blob))
    return "\n".join(p.text for p in d.paragraphs)
