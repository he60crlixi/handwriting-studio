# -*- coding: utf-8 -*-
"""
手写稿渲染引擎 — 纯本地实现
把文本/Word 渲染成"看起来像手写"的纸张图像或 PDF。
无页数限制、无水印、96~1200dpi 任意输出。

依赖：Pillow + numpy
"""
from __future__ import annotations

import io
import os
import random
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

FONT_MAP = {
    "kai":       ("楷体",       ["simkai.ttf", "STKAITI.TTF"]),
    "xingkai":   ("华文行楷",   ["STXINGKA.TTF", "simkai.ttf"]),
    "shuti":     ("方正舒体",   ["FZSTK.TTF", "simkai.ttf"]),
    "yaoti":     ("方正姚体",   ["FZYTK.TTF", "simkai.ttf"]),
    "xinwei":    ("华文新魏",   ["STXINWEI.TTF", "simkai.ttf"]),
    "lishu":     ("隶书",       ["SIMLI.TTF", "STLITI.TTF"]),
    "fangsong":  ("仿宋",       ["simfang.ttf"]),
    "youyuan":   ("幼圆",       ["SIMYOU.TTF", "msyh.ttc"]),
    "hupo":      ("华文琥珀",   ["STHUPO.TTF", "simkai.ttf"]),
    "caiyun":    ("华文彩云",   ["STCAIYUN.TTF", "simkai.ttf"]),
    "zhongsong": ("华文中宋",   ["STZHONGS.TTF", "simsun.ttc"]),
    "song":      ("宋体",       ["simsun.ttc"]),
    "hei":       ("黑体",       ["simhei.ttf", "msyh.ttc"]),
    "en_script": ("英文手写",   ["segoesc.ttf", "Inkfree.ttf"]),
    "en_ink":    ("Ink Free",   ["Inkfree.ttf", "segoesc.ttf"]),
}

# key -> (中文名, 宽, 高, 样式, 线色)  尺寸为 300dpi 基准
PAPER_MAP = {
    "a4p":     ("A4 纵向",      2480, 3508, "ruled", (170, 192, 222)),
    "a4l":     ("A4 横向",      3508, 2480, "ruled", (170, 192, 222)),
    "b5p":     ("B5 纵向",      2079, 2953, "ruled", (170, 192, 222)),
    "b5l":     ("B5 横向",      2953, 2079, "ruled", (170, 192, 222)),
    "a3p":     ("A3 纵向",      3508, 4961, "ruled", (170, 192, 222)),
    "a3l":     ("A3 横向",      4961, 3508, "ruled", (170, 192, 222)),
    "blank":   ("纯白纸",       2480, 3508, "plain", None),
    "ruled":   ("单横线",       2480, 3508, "ruled", (152, 178, 216)),
    "redline": ("单红线信稿纸", 2480, 3508, "redline", (214, 128, 128)),
    "grid400": ("方格稿纸400",  2480, 3508, "grid", (184, 200, 224)),
    "craft":   ("草稿纸实拍",   2240, 2988, "craft", (170, 192, 222)),
}

BASE_DPI = 300.0
_CONFUSABLE = "的地得在了是有和就不人都一上下来去时说要会着没好几看过又还能为以于自之其己巳已未末干千"
_FONT_CACHE: dict = {}


def _font_path(key: str) -> str:
    for c in FONT_MAP.get(key, FONT_MAP["kai"])[1]:
        p = os.path.join(WIN_FONTS, c)
        if os.path.exists(p):
            return p
    for c in ("simkai.ttf", "simsun.ttc", "msyh.ttc", "arial.ttf"):
        p = os.path.join(WIN_FONTS, c)
        if os.path.exists(p):
            return p
    raise RuntimeError("系统未找到可用中文字体")


def _load_font(key: str, size: int) -> ImageFont.FreeTypeFont:
    k = (key, size)
    f = _FONT_CACHE.get(k)
    if f is None:
        f = ImageFont.truetype(_font_path(key), size)
        if len(_FONT_CACHE) > 500:
            _FONT_CACHE.clear()
        _FONT_CACHE[k] = f
    return f


@dataclass
class RenderOptions:
    font: str = "xingkai"
    paper: str = "a4p"
    dpi: int = 300
    font_size: float = 0.0
    line_gap: float = 1.62
    cols: int = 0
    mistake_rate: float = 0.0
    messy: float = 3.0
    char_random: float = 3.0
    ink: Tuple[int, int, int] = (26, 28, 38)
    seed: int = 0
    margin_ratio: float = 0.07
    indent: int = 2
    show_rules: bool = True


# ------------------------------------------------------------ 纸张
def _paper_background(w: int, h: int, style: str, line_rgb, dpi: int,
                      opts: RenderOptions, rs: np.random.RandomState,
                      first_line_y: float, line_h: float, margin_x: float) -> Image.Image:
    scale = dpi / BASE_DPI
    craft = style == "craft"
    base_rgb = np.array([246, 240, 222] if craft else [253, 252, 249], dtype=np.float32)

    def noise(cell: int) -> np.ndarray:
        sw, sh = max(2, w // cell), max(2, h // cell)
        n = rs.randn(sh, sw).astype(np.float32)
        n = (n - n.min()) / (np.ptp(n) + 1e-6)
        return np.asarray(
            Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC),
            dtype=np.float32) / 255.0 - 0.5

    amp = 10.0 if craft else 5.0
    field = (noise(3) * 0.85 + noise(12) * 0.5 + noise(41) * 0.12) * amp
    # 纵向轻微光照不均
    grad = np.linspace(-1, 1, h, dtype=np.float32)[:, None] * amp * 0.35
    arr = np.clip(base_rgb[None, None, :] + field[:, :, None] + grad[:, :, None], 0, 255)
    base = Image.fromarray(arr.astype(np.uint8), "RGB")

    if craft:
        a = np.asarray(base, dtype=np.int16).copy()
        for _ in range(int(220 * scale * scale)):
            x, y = int(rs.randint(0, w)), int(rs.randint(0, h))
            r = int(max(1, rs.uniform(1, 3.0) * scale))
            d = int(rs.randint(-16, -4))
            a[max(0, y):y + r, max(0, x):x + r] = np.clip(a[max(0, y):y + r, max(0, x):x + r] + d, 0, 255)
        base = Image.fromarray(a.astype(np.uint8), "RGB")
        d2 = ImageDraw.Draw(base)
        for _ in range(int(26 * max(1, scale))):
            x0, y0 = int(rs.randint(0, w)), int(rs.randint(0, h))
            d2.line([(x0, y0), (x0 + int(rs.uniform(20, 130) * scale),
                                y0 + int(rs.uniform(-16, 16) * scale))],
                    fill=(226, 218, 196), width=1)
        for f in (0.24, 0.5, 0.76):
            y = int(h * f + rs.uniform(-25, 25) * scale)
            d2.line([(0, y), (w, y)], fill=(222, 214, 192), width=max(1, int(scale * 1.4)))
        shadow = Image.new("L", (w, h), 0)
        ImageDraw.Draw(shadow).rectangle([int(w * 0.02), int(h * 0.02),
                                          int(w * 0.98), int(h * 0.98)],
                                         outline=30, width=int(6 * scale))
        shadow = shadow.filter(ImageFilter.GaussianBlur(int(9 * scale)))
        base = Image.composite(Image.new("RGB", (w, h), (238, 231, 210)), base, shadow)

    draw = ImageDraw.Draw(base)
    lw = max(1, int(round(1.5 * scale)))

    if style in ("ruled", "redline", "craft") and opts.show_rules:
        y = first_line_y
        while y < h - margin_x * 0.4:
            draw.line([(margin_x * 0.42, int(y)), (w - margin_x * 0.42, int(y))],
                      fill=line_rgb, width=lw)
            y += line_h
        draw.line([(int(margin_x * 0.6), int(first_line_y - line_h)),
                   (int(margin_x * 0.6), h - int(margin_x * 0.4))],
                  fill=(212, 216, 226), width=max(1, int(scale)))

    elif style == "grid":
        cols_n, rows_n = 20, 20
        x0, y0 = int(w * 0.075), int(h * 0.065)
        cw = (w - 2 * x0) / cols_n
        ch = (h - 2 * y0) / rows_n
        for i in range(cols_n + 1):
            x = int(round(x0 + i * cw))
            draw.line([(x, y0), (x, int(y0 + rows_n * ch))], fill=line_rgb, width=1)
        for j in range(rows_n + 1):
            y = int(round(y0 + j * ch))
            draw.line([(x0, y), (int(x0 + cols_n * cw), y)], fill=line_rgb, width=1)

    vig = Image.new("L", (max(8, w // 10), max(8, h // 10)), 0)
    ImageDraw.Draw(vig).rectangle([0, 0, vig.size[0] - 1, vig.size[1] - 1], outline=42, width=3)
    vig = vig.resize((w, h), Image.BICUBIC).filter(
        ImageFilter.GaussianBlur(max(2, int(min(w, h) * 0.012))))
    base = Image.composite(Image.new("RGB", (w, h), (241, 239, 232)), base,
                           vig.point(lambda v: int(v * 0.5)))
    return base


# ------------------------------------------------------------ 涂改
def _cross_out(draw: ImageDraw.ImageDraw, x: float, y: float, step: float,
               fsize: float, rnd: random.Random, color):
    w = max(1, int(fsize * 0.05))
    for _ in range(rnd.randint(1, 2)):
        pts = []
        cx = x + step * rnd.uniform(0.2, 0.8)
        cy = y - fsize * rnd.uniform(0.25, 0.7)
        for _i in range(6):
            pts.append((cx + rnd.uniform(-0.42, 0.46) * step,
                        cy + rnd.uniform(-0.34, 0.34) * fsize))
        draw.line(pts, fill=color, width=w, joint="curve")


# ------------------------------------------------------------ 主渲染
_NO_LINE_START = "。，、；：？！）】》」』”’…—·%‰℃"   # 避头（不能放行首）
_NO_LINE_END = "（【《「『“‘"                          # 避尾（不能放行尾）


def _layout(text: str, cols: int, advance: float, half_ratio: float,
            measure) -> List[Tuple[int, List[Tuple[str, float]]]]:
    """两阶段排版的布局阶段：返回 [(行号, [(字符, 宽度)])]

    支持避头尾规则：收尾标点不落行首（悬挂在当前行），起首标点不落行尾（提前换行）。
    """
    lines: List[List[Tuple[str, float]]] = []
    cur: List[Tuple[str, float]] = []
    used = 0.0

    def flush():
        nonlocal cur, used
        lines.append(cur)
        cur = []
        used = 0.0

    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        para = para.rstrip()
        if not para:
            flush()
            continue
        if cur:              # 段前换行
            flush()
        # 段首缩进两格
        cur.append(("", advance * 2))
        used = advance * 2
        for ch in para:
            if ch == "\t":
                w = advance * 2
            elif ch == " ":
                w = advance * half_ratio
            else:
                w = measure(ch)
            if used + w > cols * advance + 1e-6:
                if ch in _NO_LINE_START and cur:
                    cur.append((ch, w))      # 悬挂标点
                    flush()
                    continue
                if cur and cur[-1][0] in _NO_LINE_END:
                    held = cur.pop()
                    flush()
                    cur.append(("", advance * 2))
                    used = advance * 2
                    cur.append(held)
                    used += held[1]
                else:
                    flush()
                    cur.append(("", advance * 2))
                    used = advance * 2
            cur.append((ch, w))
            used += w
    if cur:
        lines.append(cur)
    return list(enumerate(lines))


def render_pages(text: str, opts: RenderOptions | None = None) -> List[Image.Image]:
    o = opts or RenderOptions()
    rnd = random.Random(o.seed or 0xC0FFEE)
    rs = np.random.RandomState((o.seed or 0xC0FFEE) & 0x7FFFFFFF)
    _name, pw, ph, style, line_rgb = PAPER_MAP.get(o.paper, PAPER_MAP["a4p"])
    scale = max(0.1, o.dpi / BASE_DPI)
    w, h = int(pw * scale), int(ph * scale)
    margin_x = int(w * o.margin_ratio)
    margin_y = int(h * o.margin_ratio * 0.95)

    grid = style == "grid"
    if grid:
        cols_n, rows_n = 20, 20
        x0, y0 = int(w * 0.075), int(h * 0.065)
        cell_w = (w - 2 * x0) / cols_n
        cell_h = (h - 2 * y0) / rows_n
        advance, line_h = cell_w, cell_h
        cols, ox = cols_n, x0
        fsize = max(6, int(cell_w * 0.86))
        base_y = y0 + cell_h * 0.8
        rows = rows_n
        half_ratio = 0.5
    else:
        base_w = pw if pw <= ph else ph
        if o.font_size > 0:
            fsize = max(6, int(o.font_size * scale))
        else:
            ncols = o.cols if o.cols > 0 else (32 if pw <= ph else 46)
            usable = base_w - 2 * (base_w * o.margin_ratio)
            fsize = max(6, int(usable / ncols * scale))
        advance = fsize * 1.0
        line_h = fsize * o.line_gap
        cols = o.cols if o.cols > 0 else max(1, int((w - 2 * margin_x) / advance) - 1)
        base_y = margin_y + line_h * 0.86
        rows = max(1, int((h - margin_y * 0.5 - base_y) // line_h) + 1)
        ox = margin_x
        half_ratio = 0.55

    font = _load_font(o.font, fsize)

    def measure(ch: str) -> float:
        if ord(ch) > 0x2E80:
            return advance
        return max(fsize * 0.28, min(advance, font.getlength(ch)))

    ink = o.ink
    messy = max(0.0, min(10.0, o.messy)) / 10.0
    rnd_amt = max(0.0, min(10.0, o.char_random)) / 10.0
    mistake_p = max(0.0, min(10.0, o.mistake_rate)) / 10.0

    lines = _layout(text, cols, advance, half_ratio, measure)
    pages: List[Image.Image] = []
    state = {"page": None, "draw": None}

    def new_page():
        bg = _paper_background(w, h, style, line_rgb, o.dpi, o, rs,
                               base_y, line_h, margin_x)
        state["page"] = bg.convert("RGBA")
        state["draw"] = ImageDraw.Draw(state["page"])

    new_page()
    for li, (_, items) in enumerate(lines):
        line_idx = li % rows
        if li and line_idx == 0:
            pages.append(state["page"].convert("RGB"))
            new_page()
        y = base_y + line_idx * line_h
        x = ox
        # 本行是否抄错一个字
        bad_at = -1
        if mistake_p > 0 and rnd.random() < mistake_p * 0.4:
            cands = [i for i, (c, _w) in enumerate(items) if c]
            if cands:
                bad_at = cands[rnd.randrange(len(cands))]
        for ci, (ch, cw) in enumerate(items):
            if not ch:
                x += cw
                continue
            glyph = ch
            if ci == bad_at:
                glyph = _CONFUSABLE[rnd.randrange(len(_CONFUSABLE))]
            if grid:
                cx = x + cw * 0.5
                cy = y - line_h * 0.42
                put_char(state, o, rnd, font, fsize, advance, line_h, messy, rnd_amt,
                         ink, glyph, cx, cy, center=True)
            else:
                put_char(state, o, rnd, font, fsize, advance, line_h, messy, rnd_amt,
                         ink, glyph, x, y)
            if ci == bad_at:
                _cross_out(state["draw"], x, y, cw, fsize, rnd,
                           (ink[0], ink[1], ink[2], 230))
            x += cw

    pages.append(state["page"].convert("RGB"))
    return pages


def put_char(state, o, rnd, font, fsize, advance, line_h, messy, rnd_amt, ink,
             ch, x, y, center=False):
    """绘制单字（含手写抖动）。center=True 时 x,y 为格子中心。"""
    jx = rnd.uniform(-1, 1) * advance * (0.006 + 0.038 * (rnd_amt * 2.4 + messy))
    jy = rnd.uniform(-1, 1) * line_h * (0.004 + 0.024 * (rnd_amt * 1.8 + messy))
    ang = rnd.uniform(-1, 1) * (0.35 + messy * 4.6 + rnd_amt * 1.8)
    fs = 1.0 + rnd.uniform(-1, 1) * 0.045 * (rnd_amt * 2.2 + messy)
    alpha = rnd.randint(203, 255)
    g = rnd.randint(-9, 11)

    fnt = font if abs(fs - 1.0) < 0.012 else _load_font(o.font, max(6, int(fsize * fs)))
    col = (max(0, min(255, ink[0] + g)), max(0, min(255, ink[1] + g)),
           max(0, min(255, ink[2] + g + rnd.randint(0, 8))), alpha)

    tw = int(advance * 1.9) + 16
    th = int(fsize * 2.0) + 16
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    if center:
        anchor = "mm"
        tx, ty = tw / 2.0, th / 2.0
    else:
        anchor = "ls"
        ty = fsize * 1.34                      # tile 内基线
        tx = tw * 0.16
    td.text((tx, ty), ch, font=fnt, fill=col, anchor=anchor)

    # 手写感：轻微斜切 + 横竖缩放（模拟不同笔顺力度）
    shx = rnd.uniform(-0.05, 0.05) * (0.4 + messy * 2.2 + rnd_amt)
    sw = 1.0 + rnd.uniform(-0.06, 0.06) * (0.3 + rnd_amt * 1.5)
    sh = 1.0 + rnd.uniform(-0.05, 0.05) * (0.3 + rnd_amt * 1.5)
    nw, nh = max(4, int(tw * sw)), max(4, int(th * sh))
    tile = tile.transform((nw, nh), Image.AFFINE,
                          (1.0, shx, -shx * nh * 0.5, 0.0, 1.0, 0.0),
                          resample=Image.BICUBIC)
    # 笔画边缘轻微毛刺（手写墨迹）
    tile = tile.filter(ImageFilter.SMOOTH)
    if abs(ang) > 0.2:
        tile = tile.rotate(ang, resample=Image.BICUBIC, expand=False)
        nw, nh = tile.size
    state["page"].alpha_composite(
        tile, (int(x + jx - nw * (tx / tw)), int(y + jy - nh * (ty / th))))


# ------------------------------------------------------------ 输出
def pages_to_pdf(pages: List[Image.Image], dpi: int, title: str = "") -> bytes:
    if not pages:
        raise RuntimeError("没有可输出的页面")
    buf = io.BytesIO()
    kw = {"title": title} if title else {}
    pages[0].save(buf, format="PDF", resolution=float(dpi), save_all=True,
                  append_images=pages[1:], **kw)
    return buf.getvalue()


def pages_to_zip(pages: List[Image.Image], fmt: str = "PNG", quality: int = 95) -> bytes:
    import zipfile
    fmt = fmt.upper()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, p in enumerate(pages, 1):
            b = io.BytesIO()
            if fmt == "JPG":
                p.convert("RGB").save(b, format="JPEG", quality=quality,
                                      subsampling=0, dpi=(300, 300))
                z.writestr("page_%02d.jpg" % i, b.getvalue())
            else:
                p.save(b, format="PNG", optimize=True)
                z.writestr("page_%02d.png" % i, b.getvalue())
    return buf.getvalue()


def extract_text(path: str) -> str:
    low = path.lower()
    if low.endswith((".txt", ".md", ".csv", ".log")):
        for enc in ("utf-8-sig", "gbk", "gb18030", "utf-16"):
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "ignore")
    if low.endswith(".docx"):
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        d = docx.Document(path)
        out: List[str] = []
        for child in d.element.body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                out.append(Paragraph(child, d).text)
            elif tag == "tbl":
                for row in Table(child, d).rows:
                    out.append("\t".join(c.text.replace("\n", " ") for c in row.cells))
        return "\n".join(out)
    raise RuntimeError("仅支持 .txt / .md / .docx")


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="本地手写稿渲染引擎")
    ap.add_argument("input")
    ap.add_argument("-o", "--out", default="手写稿.pdf")
    ap.add_argument("--font", default="xingkai", choices=list(FONT_MAP))
    ap.add_argument("--paper", default="a4p", choices=list(PAPER_MAP))
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--size", type=float, default=0)
    ap.add_argument("--line-gap", type=float, default=1.62)
    ap.add_argument("--cols", type=int, default=0)
    ap.add_argument("--mistake", type=float, default=0)
    ap.add_argument("--messy", type=float, default=3)
    ap.add_argument("--random", type=float, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    text = extract_text(a.input)
    o = RenderOptions(font=a.font, paper=a.paper, dpi=a.dpi, font_size=a.size,
                      line_gap=a.line_gap, cols=a.cols, mistake_rate=a.mistake,
                      messy=a.messy, char_random=a.random, seed=a.seed)
    pages = render_pages(text, o)
    data = pages_to_zip(pages) if a.png else pages_to_pdf(pages, a.dpi)
    with open(a.out, "wb") as f:
        f.write(data)
    print("输出: %s  页数: %d  尺寸: %dx%d  大小: %.1f KB"
          % (a.out, len(pages), pages[0].width, pages[0].height, len(data) / 1024))


if __name__ == "__main__":
    _cli()
