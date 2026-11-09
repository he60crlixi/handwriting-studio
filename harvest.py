# -*- coding: utf-8 -*-
"""
harvest.py —— 批量取成品（走原站免费预览端点，不碰付费墙）

用法：
    python harvest.py 文稿.docx                     -> 手写稿.docx.pdf
    python harvest.py 文稿.txt --font 16 --paper 20
    python harvest.py 文稿.txt --upscale 3 --png

免费端点的两个硬限制与对策：
    1) 单次最多 12 页     -> 文本按 1600 字分块，多次请求后本地合并
    2) 输出约 150dpi      -> --upscale 2/3 做 LANCZOS 超分 + 锐化，等效 300/450dpi
"""
from __future__ import annotations

import argparse
import os
import sys

import engine
import remote


def main():
    ap = argparse.ArgumentParser(description="凹凸工坊免费端点批量取稿")
    ap.add_argument("input", help=".txt / .md / .docx")
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--font", default="14", help="站点字体 value，默认 14（真实-手写体2）")
    ap.add_argument("--paper", default="1", help="站点纸张 value，默认 1（A4纵向）")
    ap.add_argument("--mistake", type=float, default=0, help="抄错字 0-10")
    ap.add_argument("--messy", type=float, default=3, help="凌乱度 0-10")
    ap.add_argument("--random", type=float, default=3, help="单字随机 0-10")
    ap.add_argument("--upscale", type=int, default=2, help="超分倍数 1-4")
    ap.add_argument("--png", action="store_true", help="输出 PNG 压缩包")
    ap.add_argument("--list", action="store_true", help="列出站点可选字体/纸张")
    a = ap.parse_args()

    if a.list:
        print("== 字体 ==")
        for v, n in remote.SITE_FONTS:
            print("  %-5s %s" % (v, n))
        print("== 纸张 ==")
        for v, n in remote.SITE_PAPERS:
            print("  %-5s %s" % (v, n))
        return

    if not os.path.isfile(a.input):
        print("找不到文件：%s" % a.input)
        sys.exit(1)

    ext = os.path.splitext(a.input)[1].lower()
    print("读取：%s" % a.input)

    def prog(i, n, pages):
        print("  第 %d/%d 批完成，累计 %d 页" % (i, n, pages))

    if ext == ".docx":
        blob = open(a.input, "rb").read()
        pages = remote.render_docx(blob, os.path.basename(a.input), font=a.font,
                                   paper=a.paper, mistake=a.mistake, messy=a.messy,
                                   random_=a.random, upscale=a.upscale, progress=prog)
    else:
        text = engine.extract_text(a.input)
        print("  字符数：%d" % len(text))
        pages = remote.render_text(text, font=a.font, paper=a.paper,
                                   mistake=a.mistake, messy=a.messy,
                                   random_=a.random, upscale=a.upscale, progress=prog)

    out = a.out or (os.path.splitext(a.input)[0] + ("_手写稿.zip" if a.png else "_手写稿.pdf"))
    if a.png:
        data = engine.pages_to_zip(pages, "PNG")
    else:
        data = engine.pages_to_pdf(pages, 300)
    with open(out, "wb") as f:
        f.write(data)
    print("完成：%s  %d 页  %dx%d  %.1f MB"
          % (out, len(pages), pages[0].width, pages[0].height, len(data) / 1048576))


if __name__ == "__main__":
    main()
