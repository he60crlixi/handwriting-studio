# -*- coding: utf-8 -*-
"""生成《德国工人党纲领》（哥达纲领）Word 文档"""
import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "哥达纲领.docx")

CN = "宋体"
CN_TITLE = "黑体"
EN = "Times New Roman"


def set_run(run, size=12, bold=False, cn=CN, color=None):
    run.font.name = EN
    run.font.size = Pt(size)
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), cn)
    if color:
        run.font.color.rgb = color


def para(doc, text="", size=12, bold=False, cn=CN, align=None,
         first_indent=None, space_before=0, space_after=6, line=1.5, color=None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    if first_indent is not None:
        pf.first_line_indent = Cm(first_indent)
    if align is not None:
        p.alignment = align
    if text:
        set_run(p.add_run(text), size=size, bold=bold, cn=cn, color=color)
    return p


def heading(doc, text, size=15):
    return para(doc, text, size=size, bold=True, cn=CN_TITLE,
                space_before=16, space_after=8, line=1.4)


def item(doc, num, text):
    """编号条目：编号与正文字号一致，悬挂缩进"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(8)
    pf.line_spacing = 1.6
    pf.left_indent = Cm(0.85)
    pf.first_line_indent = Cm(-0.85)
    set_run(p.add_run(num + "　"), size=12)
    set_run(p.add_run(text), size=12)
    return p


def main():
    doc = Document()

    # 页面：A4，常规页边距
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.54)
    sec.bottom_margin = Cm(2.54)
    sec.left_margin = Cm(3.17)
    sec.right_margin = Cm(3.17)

    # 正文默认样式
    style = doc.styles["Normal"]
    style.font.name = EN
    style.font.size = Pt(12)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CN)

    # ---------------- 标题 ----------------
    para(doc, "德国工人党纲领", size=22, bold=True, cn=CN_TITLE,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=6, line=1.3)
    para(doc, "（哥达纲领）", size=16, bold=True, cn=CN_TITLE,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6, line=1.3)
    para(doc, "一八七五年五月哥达合并代表大会通过", size=11,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=20, line=1.3,
         color=RGBColor(0x55, 0x55, 0x55))

    # ---------------- 引言 ----------------
    para(doc, "德国社会主义工人党于一八七五年五月在哥达召开合并代表大会，"
              "通过了下列纲领。本纲领由全德工人联合会与德国社会民主工党"
              "（爱森纳赫派）两派代表共同议定，作为合并后统一工人党的行动准则。",
         size=12, first_indent=0.85, space_after=10, line=1.6)

    # ---------------- 一、一般原则 ----------------
    heading(doc, "一、一般原则")

    principles = [
        "劳动是一切财富和一切文化的源泉，而因为有益的劳动只有在社会中和通过社会才是可能的，"
        "所以劳动所得应当不折不扣和按照平等的权利属于社会一切成员。",

        "在现代社会中，劳动资料为资本家阶级所垄断。由此造成的工人阶级的依附性"
        "是一切形式的贫困和奴役的原因。",

        "劳动的解放要求把劳动资料提高为社会的公共财产，要求集体调节总劳动"
        "并公平分配劳动所得。",

        "劳动的解放必须是工人阶级的事业。因为其他一切阶级都只是反动的一帮。",

        "工人阶级为了本身的解放，首先是在现代民族国家的范围内进行活动，"
        "同时意识到各民族间的国际的兄弟联合是资产阶级时代的一个特点。",

        "德国工人党从这些原则出发，力求用一切合法手段来争取自由国家和社会主义社会，"
        "通过消灭雇佣劳动制度来粉碎铁的工资规律，消灭一切阶级统治和阶级本身，"
        "消除一切社会的和政治的不平等。",
    ]
    for i, t in enumerate(principles, 1):
        item(doc, "%d." % i, t)

    # ---------------- 二、国家的要求 ----------------
    heading(doc, "二、国家的要求")

    state = [
        "凡年满二十岁的男子，都有普遍的、平等的、直接的、秘密的选举权，"
        "并参加一切国家的和地方的代议机关的选举。选举日期应当定在星期日或节日。",

        "人民有直接立法权。人民自己决定战争与和平的问题。",

        "人民有自由发表意见的权利，出版、结社、集会自由。"
        "废除一切限制言论自由与公共讨论的特别法律。",

        "司法独立。免费诉讼。审判员由人民选举。一切诉讼程序公开，实行口头辩论，"
        "并实行陪审制度。",

        "人民有受教育的权利。国家举办普遍义务的国民教育，一切公共教育机构一律免费。",

        "宣布宗教为私人的事情。国家不干涉宗教团体的事务，也不从国库拨款给宗教团体。",

        "人民有服兵役的义务。和平时期常备军应当缩减到与防御需要相适应的最低限度；"
        "人民代表机关决定宣战与媾和。",

        "国家对居民中的穷困阶级应当给予救助；丧葬费用由社会负担。",

        "废除一切限制工人结社与罢工的法律，承认工会参与劳动条件立法与仲裁的权利。",
    ]
    for i, t in enumerate(state, 1):
        item(doc, "%d." % i, t)

    # ---------------- 三、关于工人组织的自由 ----------------
    heading(doc, "三、关于工人组织的自由")

    union = [
        "工人有结社的自由，有罢工的自由。",

        "工人的组织应当受到国家的保护。",

        "工人有权推派代表参加一切有关劳动条件、工资与工时问题的立法与仲裁机关。",
    ]
    for i, t in enumerate(union, 1):
        item(doc, "%d." % i, t)

    # ---------------- 四、关于劳动保护 ----------------
    heading(doc, "四、关于劳动保护")

    labour = [
        "实行有效的劳动保护。国家监督一切劳动场所，特别是矿山、工厂和手工业作坊，"
        "并由工人自己选举的监察员参加监督。",

        "规定正常工作日，最长不得超过八小时。",

        "禁止童工。十四岁以下的儿童不得做工；十四岁以上的少年做工，"
        "须保证其有受教育的时间。",

        "保护女工。女工在生产前后各六周内免除劳动，并给予补助。",

        "禁止星期日劳动。星期日和一切法定节日应当休息。",
    ]
    for i, t in enumerate(labour, 1):
        item(doc, "%d." % i, t)

    # ---------------- 五、关于文化的要求 ----------------
    heading(doc, "五、关于文化的要求")

    culture = [
        "国家应当举办免费的公共教育，包括初等教育、中等教育和职业教育；"
        "一切儿童都有受教育的权利。",

        "科学与艺术应当自由。国家应当扶助科学与艺术的发展。",
    ]
    for i, t in enumerate(culture, 1):
        item(doc, "%d." % i, t)

    # ---------------- 附记 ----------------
    heading(doc, "附记")
    para(doc, "以上各条，系一八七五年五月德国社会主义工人党在哥达召开的合并代表大会"
              "所通过的纲领全文。马克思于同年四五月间写成《对德国工人党纲领的几点意见》"
              "（即《哥达纲领批判》），逐条批评了这个纲领在国家观、分配观和革命策略上的让步，"
              "并提出了“各尽所能，按需分配”的著名论断。",
         size=11, first_indent=0.85, space_after=10, line=1.6)
    para(doc, "本文件为历史文献的通行中译，供学习与研究之用。",
         size=11, first_indent=0.85, space_after=10, line=1.6,
         color=RGBColor(0x55, 0x55, 0x55))

    doc.save(OUT)
    print("已生成：%s" % OUT)

    # 统计
    d = Document(OUT)
    chars = sum(len(p.text) for p in d.paragraphs)
    print("段落数：%d  总字符：%d" % (len(d.paragraphs), chars))


if __name__ == "__main__":
    main()
