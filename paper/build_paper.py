#!/usr/bin/env python3
# ruff: noqa: E501
"""Build the SAHVS BACSE202 research paper from measured project artifacts."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "paper"
ASSET_DIR = PAPER_DIR / "assets"
OUT_PATH = PAPER_DIR / "SAHVS_Research_Paper.docx"
BENCHMARK_JSON = ROOT / "results" / "benchmark-20261010T102604Z.json"
BENCHMARK_CSV = ROOT / "results" / "benchmark-20261010T102604Z.csv"
ABLATION_JSON = ROOT / "results" / "ablation-20261010T102859Z.json"

NAVY = "17365D"
MID_BLUE = "4472C4"
PALE_BLUE = "EAF2F8"
PALE_GRAY = "F4F6F7"
GRID = "D9D9D9"
TEXT = "111111"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = GRID, size: str = "4") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top=75, start=85, bottom=75, end=85) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_columns(section, count: int, spacing_twips: int = 420) -> None:
    sect_pr = section._sectPr
    cols = sect_pr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect_pr.append(cols)
    cols.set(qn("w:num"), str(count))
    cols.set(qn("w:space"), str(spacing_twips))
    cols.set(qn("w:equalWidth"), "1")


def set_continuous(section) -> None:
    sect_pr = section._sectPr
    type_el = sect_pr.find(qn("w:type"))
    if type_el is None:
        type_el = OxmlElement("w:type")
        sect_pr.insert(0, type_el)
    type_el.set(qn("w:val"), "continuous")


def set_font(run, name="Aptos", size=10, bold=False, italic=False, color=TEXT) -> None:
    run.font.name = name
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor.from_string(color)


def add_field(paragraph, instruction: str, fallback: str = "1") -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = fallback
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, text, end])
    set_font(run, size=8.5, color="555555")


def keep_with_next(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    keep = p_pr.find(qn("w:keepNext"))
    if keep is None:
        p_pr.append(OxmlElement("w:keepNext"))


def add_paragraph(doc, text: str, *, first_line=True, space_after=3.2, align=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    if first_line:
        p.paragraph_format.first_line_indent = Inches(0.18)
    if align is not None:
        p.alignment = align
    parts = re.split(r"(\[[0-9]+(?:,\s*[0-9]+)*\])", text)
    for part in parts:
        run = p.add_run(part)
        set_font(run, size=10)
        if re.fullmatch(r"\[[0-9]+(?:,\s*[0-9]+)*\]", part):
            run.font.color.rgb = RGBColor.from_string(NAVY)
    return p


def add_heading(doc, text: str, level: int = 1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(8 if level == 1 else 5)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(text)
    set_font(r, size=11.5 if level == 1 else 10.5, bold=True, color="000000")
    return p


def add_caption(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text)
    set_font(r, size=8.5, italic=True, color="333333")
    keep_with_next(p)
    return p


def add_picture(doc, path: Path, width: float, alt_text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(1)
    shape = p.add_run().add_picture(str(path), width=Inches(width))
    doc_pr = shape._inline.docPr
    doc_pr.set("descr", alt_text)
    return p


def add_table(doc, headers, rows, widths=None, font_size=8.2):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = 0
    table.autofit = False
    if widths:
        total_twips = round(sum(widths) * 1440)
        tbl_pr = table._tbl.tblPr
        tbl_w = tbl_pr.find(qn("w:tblW"))
        if tbl_w is None:
            tbl_w = OxmlElement("w:tblW")
            tbl_pr.append(tbl_w)
        tbl_w.set(qn("w:w"), str(total_twips))
        tbl_w.set(qn("w:type"), "dxa")
        grid_cols = table._tbl.tblGrid.findall(qn("w:gridCol"))
        for grid_col, width in zip(grid_cols, widths, strict=True):
            grid_col.set(qn("w:w"), str(round(width * 1440)))
    header_tr_pr = table.rows[0]._tr.get_or_add_trPr()
    header_tr_pr.append(OxmlElement("w:cantSplit"))
    header_tr_pr.append(OxmlElement("w:tblHeader"))
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_shading(cell, NAVY)
        set_cell_border(cell)
        set_cell_margins(cell)
        if widths:
            cell.width = Inches(widths[i])
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(header))
        set_font(r, size=font_size, bold=True, color="FFFFFF")
    for row_index, row in enumerate(rows):
        cells = table.add_row().cells
        tr_pr = table.rows[-1]._tr.get_or_add_trPr()
        tr_pr.append(OxmlElement("w:cantSplit"))
        for i, value in enumerate(row):
            cell = cells[i]
            cell.text = ""
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_border(cell)
            set_cell_margins(cell)
            set_cell_shading(cell, "FFFFFF" if row_index % 2 == 0 else PALE_BLUE)
            if widths:
                cell.width = Inches(widths[i])
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(value))
            set_font(r, size=font_size, color="111111")
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_ITALIC = "/System/Library/Fonts/Supplemental/Arial Italic.ttf"


def pil_font(size: int, bold: bool = False, italic: bool = False):
    path = FONT_BOLD if bold else FONT_ITALIC if italic else FONT_REGULAR
    return ImageFont.truetype(path, size=size)


def center_text(draw, xy, text, font, fill="#111111", spacing=4):
    box = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=spacing)
    width = box[2] - box[0]
    height = box[3] - box[1]
    draw.multiline_text(
        (xy[0] - width / 2, xy[1] - height / 2),
        text,
        font=font,
        fill=fill,
        align="center",
        spacing=spacing,
    )


def create_architecture_figure() -> Path:
    path = ASSET_DIR / "architecture.png"
    image = Image.new("RGB", (1100, 1440), "white")
    draw = ImageDraw.Draw(image)
    bold = pil_font(25, bold=True)
    small = pil_font(22, bold=True)

    def box(x, y, w, h, text, fill, font=bold):
        draw.rounded_rectangle(
            (x, y, x + w, y + h), radius=18, fill=f"#{fill}", outline=f"#{NAVY}", width=3
        )
        center_text(draw, (x + w / 2, y + h / 2), text, font)

    def arrow(x1, y1, x2, y2, label=None):
        draw.line((x1, y1, x2, y2), fill="#52616B", width=4)
        angle = __import__("math").atan2(y2 - y1, x2 - x1)
        length = 16
        for delta in (2.55, -2.55):
            draw.line(
                (
                    x2,
                    y2,
                    x2 + length * __import__("math").cos(angle + delta),
                    y2 + length * __import__("math").sin(angle + delta),
                ),
                fill="#52616B",
                width=4,
            )
        if label:
            draw.text(((x1 + x2) / 2 + 8, (y1 + y2) / 2), label, font=pil_font(20), fill="#37474F")

    box(230, 40, 640, 115, "Search request\ntext query   metadata filters   top k", PALE_BLUE)
    box(40, 245, 430, 115, "Feature hash encoder\n384 dimensional query vector", "F4F6F7", small)
    box(630, 245, 430, 115, "PostgreSQL EXPLAIN\nestimated matching rows", "F4F6F7", small)
    box(
        220,
        455,
        660,
        145,
        "SAHVS adaptive planner\nselectivity features   five nearest observations\nrecall adjusted measured cost",
        "DCE6F1",
        small,
    )
    box(15, 735, 330, 135, "Exact filtered scan\nperfect recall baseline", "EDF2F7", small)
    box(385, 735, 330, 135, "HNSW post filter\nbounded candidates", "EDF2F7", small)
    box(755, 735, 330, 135, "Iterative HNSW\nstrict ordered scan", "EDF2F7", small)
    box(135, 990, 830, 110, "Ranked products and execution measurements", PALE_BLUE)
    box(
        30,
        1260,
        450,
        125,
        "Recall guard\nexact fallback if results are incomplete",
        "F4F6F7",
        small,
    )
    box(
        620,
        1260,
        450,
        125,
        "query observations table\nlatency   recall   result count   context",
        "F4F6F7",
        small,
    )
    arrow(550, 155, 260, 245)
    arrow(550, 155, 845, 245)
    arrow(260, 360, 410, 455)
    arrow(845, 360, 690, 455)
    arrow(475, 600, 180, 735)
    arrow(550, 600, 550, 735)
    arrow(625, 600, 920, 735)
    arrow(180, 870, 350, 990)
    arrow(550, 870, 550, 990)
    arrow(920, 870, 750, 990)
    arrow(410, 1100, 255, 1260)
    arrow(690, 1100, 845, 1260)
    arrow(845, 1260, 865, 600, "feedback")
    image.save(path, optimize=True)
    return path


def create_baseline_figure(benchmark: dict) -> Path:
    path = ASSET_DIR / "baseline_performance.png"
    order = ["exact_prefilter", "ann_postfilter", "ann_iterative"]
    labels = ["Exact\nfiltered", "ANN\npost-filter", "Iterative\nHNSW"]
    means = [benchmark["summary"][key]["mean_latency_ms"] for key in order]
    p95s = [benchmark["summary"][key]["p95_latency_ms"] for key in order]
    recalls = [benchmark["summary"][key]["mean_recall_at_k"] for key in order]
    image = Image.new("RGB", (1180, 760), "white")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 120, 65, 1060, 625
    max_y = 34.0
    for tick in range(0, 35, 5):
        y = bottom - (tick / max_y) * (bottom - top)
        draw.line((left, y, right, y), fill="#D9D9D9", width=2)
        draw.text((55, y - 12), str(tick), font=pil_font(20), fill="#333333")
    draw.line((left, top, left, bottom), fill="#333333", width=3)
    draw.line((left, bottom, right, bottom), fill="#333333", width=3)
    centers = [285, 590, 895]
    colors = ["#17365D", "#6FA8DC", "#4472C4"]
    for i, (cx, mean, p95, recall, label) in enumerate(
        zip(centers, means, p95s, recalls, labels, strict=True)
    ):
        y = bottom - (mean / max_y) * (bottom - top)
        draw.rectangle((cx - 70, y, cx + 70, bottom), fill=colors[i])
        center_text(draw, (cx, y - 25), f"{mean:.2f}", pil_font(20, bold=True))
        p95_y = bottom - (p95 / max_y) * (bottom - top)
        draw.line((cx - 45, p95_y, cx + 45, p95_y), fill="#111111", width=7)
        rec_y = bottom - recall * (bottom - top)
        if i:
            prev_y = bottom - recalls[i - 1] * (bottom - top)
            draw.line((centers[i - 1], prev_y, cx, rec_y), fill="#B85450", width=5)
        draw.ellipse((cx - 9, rec_y - 9, cx + 9, rec_y + 9), fill="#B85450")
        center_text(draw, (cx, bottom + 55), label, pil_font(21), spacing=2)
        draw.text((cx + 12, rec_y - 29), f"{recall:.2f}", font=pil_font(19), fill="#8B3A3A")
    draw.text((10, 20), "Latency in milliseconds", font=pil_font(23, bold=True), fill="#17365D")
    draw.line((735, 25, 780, 25), fill="#111111", width=7)
    draw.text((790, 12), "p95 latency", font=pil_font(19), fill="#333333")
    draw.line((735, 53, 780, 53), fill="#B85450", width=5)
    draw.text((790, 40), "mean recall at 10", font=pil_font(19), fill="#8B3A3A")
    image.save(path, optimize=True)
    return path


def create_ablation_figure(ablation: dict) -> Path:
    path = ASSET_DIR / "ablation.png"
    order = ["full", "no_feedback", "no_selectivity", "fixed_candidate_budget", "no_recall_guard"]
    labels = ["Full", "No\nfeedback", "No\nselectivity", "Fixed\nbudget", "No\nguard"]
    latency = [ablation["summary"][key]["mean_latency_ms"] for key in order]
    recall = [ablation["summary"][key]["mean_recall_at_k"] for key in order]
    fallback = [ablation["summary"][key]["fallback_rate"] for key in order]
    colors = ["#17365D", "#6FA8DC", "#4472C4", "#9FBAD0", "#BCCCDC"]
    image = Image.new("RGB", (1180, 1080), "white")
    draw = ImageDraw.Draw(image)
    centers = [170, 380, 590, 800, 1010]
    left, right = 90, 1110
    # Upper latency panel.
    top1, bottom1 = 65, 465
    for tick in (0, 2, 4, 6, 8):
        y = bottom1 - tick / 8 * (bottom1 - top1)
        draw.line((left, y, right, y), fill="#D9D9D9", width=2)
        draw.text((35, y - 11), str(tick), font=pil_font(19), fill="#333333")
    draw.text(
        (35, 20), "Mean latency in milliseconds", font=pil_font(23, bold=True), fill="#17365D"
    )
    for cx, value, color in zip(centers, latency, colors, strict=True):
        y = bottom1 - value / 8 * (bottom1 - top1)
        draw.rectangle((cx - 55, y, cx + 55, bottom1), fill=color)
        center_text(draw, (cx, y - 20), f"{value:.2f}", pil_font(18, bold=True))
    # Lower recall/fallback panel.
    top2, bottom2 = 590, 955
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        y = bottom2 - tick * (bottom2 - top2)
        draw.line((left, y, right, y), fill="#D9D9D9", width=2)
        draw.text((23, y - 11), f"{tick:.2f}", font=pil_font(18), fill="#333333")
    draw.text((35, 540), "Recall and fallback rate", font=pil_font(23, bold=True), fill="#17365D")
    for cx, rec, fall, label in zip(centers, recall, fallback, labels, strict=True):
        rec_y = bottom2 - rec * (bottom2 - top2)
        fall_y = bottom2 - fall * (bottom2 - top2)
        draw.rectangle((cx - 55, rec_y, cx - 5, bottom2), fill="#4472C4")
        draw.rectangle((cx + 5, fall_y, cx + 55, bottom2), fill="#B85450")
        center_text(draw, (cx, bottom2 + 48), label, pil_font(18), spacing=2)
    draw.rectangle((730, 545, 760, 570), fill="#4472C4")
    draw.text((770, 545), "recall at 10", font=pil_font(18), fill="#333333")
    draw.rectangle((920, 545, 950, 570), fill="#B85450")
    draw.text((960, 545), "fallback", font=pil_font(18), fill="#333333")
    image.save(path, optimize=True)
    return path


def create_equation_figure() -> Path:
    path = ASSET_DIR / "planner_equations.png"
    image = Image.new("RGBA", (1300, 410), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    lines = [
        "s = m̂ / N",
        "b = min(N, max(10k, ceil(1.25k / max(s, 1/N))))",
        "Cᵢ = Lᵢ + 1000 I[nᵢ < k] + 100 max(0, 0.95 - rᵢ)",
    ]
    for text, y, size in zip(lines, (70, 200, 330), (46, 39, 39), strict=True):
        center_text(draw, (650, y), text, pil_font(size, italic=True))
    image.save(path, optimize=True)
    return path


def load_data():
    benchmark = json.loads(BENCHMARK_JSON.read_text())
    ablation = json.loads(ABLATION_JSON.read_text())
    per_query = defaultdict(lambda: defaultdict(list))
    with BENCHMARK_CSV.open() as handle:
        for row in csv.DictReader(handle):
            per_query[int(row["query_number"])][row["strategy"]].append(row)
    return benchmark, ablation, per_query


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.58)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)

    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string(TEXT)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    normal.paragraph_format.space_after = Pt(3.2)

    for style_name in ("Title", "Heading 1", "Heading 2"):
        style = doc.styles[style_name]
        style.font.name = "Aptos Display" if style_name == "Title" else "Aptos"
        style._element.rPr.rFonts.set(qn("w:ascii"), style.font.name)
        style._element.rPr.rFonts.set(qn("w:hAnsi"), style.font.name)
        style.font.color.rgb = RGBColor(0, 0, 0)
        p_pr = style._element.get_or_add_pPr()
        p_bdr = p_pr.find(qn("w:pBdr"))
        if p_bdr is not None:
            p_pr.remove(p_bdr)

    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    r = p.add_run("BACSE202 Digital Assignment 3   |   SAHVS   |   ")
    set_font(r, size=8.5, color="555555")
    add_field(p, "PAGE", "1")


def build_document() -> Path:
    benchmark, ablation, per_query = load_data()
    architecture = create_architecture_figure()
    baseline_plot = create_baseline_figure(benchmark)
    ablation_plot = create_ablation_figure(ablation)
    equations = create_equation_figure()

    doc = Document()
    configure_document(doc)
    props = doc.core_properties
    props.title = (
        "SAHVS A Selectivity Aware Adaptive Query Planner for Hybrid Vector and Metadata Search"
    )
    props.subject = "BACSE202 Digital Assignment 3 DBMS Research Project"
    props.author = "BACSE202 Project Group"
    props.keywords = (
        "DBMS, PostgreSQL, pgvector, HNSW, filtered vector search, adaptive query planning"
    )

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(5)
    r = title.add_run(
        "SAHVS A Selectivity Aware Adaptive Query Planner for Hybrid Vector and Metadata Search"
    )
    set_font(r, name="Aptos Display", size=18, bold=True, color="000000")
    title_pr = title._p.get_or_add_pPr()
    title_border = title_pr.find(qn("w:pBdr"))
    if title_border is not None:
        title_pr.remove(title_border)

    byline = doc.add_paragraph()
    byline.alignment = WD_ALIGN_PARAGRAPH.CENTER
    byline.paragraph_format.space_after = Pt(5)
    r = byline.add_run(
        "Project Group   BACSE202 Database Management Systems   Digital Assignment 3"
    )
    set_font(r, size=9.5, color="333333")

    abstract_heading = doc.add_paragraph()
    abstract_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    abstract_heading.paragraph_format.space_before = Pt(2)
    abstract_heading.paragraph_format.space_after = Pt(2)
    r = abstract_heading.add_run("Abstract")
    set_font(r, size=10.5, bold=True, color="000000")
    abstract_text = (
        "Hybrid database searches must satisfy two different requirements at once: rank rows by vector "
        "similarity and enforce exact predicates on ordinary columns. A single physical strategy performs "
        "poorly across all filter selectivities. Exact filtered scans preserve recall but become costly as the "
        "eligible set grows, while bounded approximate search is fast but may discard relevant or even enough "
        "rows after metadata filtering. We present SAHVS, a Selectivity Aware Hybrid Vector Search planner for "
        "PostgreSQL and pgvector. SAHVS estimates predicate selectivity with PostgreSQL EXPLAIN, derives a compact "
        "query context, and selects among exact filtered search, HNSW candidate post-filtering, and iterative "
        "filtered HNSW. The planner starts with transparent rules and then predicts recall-adjusted cost from the "
        "five closest recorded executions. A dynamic candidate budget and exact fallback protect result completeness. "
        "We implemented the method as a FastAPI service over 50,000 products with 384-dimensional vectors, B-tree "
        "metadata indexes, an HNSW index, and an observation table. Across ten mixed-selectivity queries and five "
        "repetitions, exact search averaged 18.21 ms at recall@10 of 1.00. Raw HNSW post-filtering averaged 0.63 ms "
        "but recall fell to 0.56; iterative HNSW reached 0.81 recall at 0.87 ms. The complete adaptive planner "
        "averaged 6.42 ms with recall 1.00, a 2.83 times speedup over exact search. Removing workload feedback "
        "reduced recall to 0.81, and removing selectivity reduced recall to 0.89. These results show that measured "
        "feedback and relational selectivity are necessary for the observed latency-recall balance on this workload."
    )
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.35)
    p.paragraph_format.right_indent = Inches(0.35)
    p.paragraph_format.space_after = Pt(4)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(abstract_text)
    set_font(r, size=9.2)
    keywords = doc.add_paragraph()
    keywords.alignment = WD_ALIGN_PARAGRAPH.CENTER
    keywords.paragraph_format.space_after = Pt(5)
    r = keywords.add_run(
        "Keywords  filtered vector search  query optimization  PostgreSQL  pgvector  HNSW  adaptive planning"
    )
    set_font(r, size=8.7, italic=True, color="333333")

    section = doc.add_section(WD_SECTION.CONTINUOUS)
    set_continuous(section)
    set_columns(section, 2, 360)
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.58)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)

    add_heading(doc, "1 Introduction")
    intro = [
        "A product search such as lightweight modern laptop under 70000 is one database query with two distinct notions of relevance. The price and category conditions are Boolean: a row either qualifies or it does not. The words lightweight and modern are softer. They describe similarity between a query representation and a stored product representation. Relational database management systems are mature at the first task, while vector indexes were developed for the second. Modern applications increasingly ask the DBMS to perform both in one request [1].",
        "The straightforward implementation is an exact filtered scan. The DBMS applies the metadata predicates, computes a distance for every qualifying vector, sorts the distances, and returns the nearest k rows. This is accurate and surprisingly competitive when only a small number of rows survive the filter. It is wasteful for a broad predicate, because the database evaluates thousands of high-dimensional distances only to keep ten results. Approximate nearest-neighbor indexes reduce this work by traversing a small part of the vector space. HNSW is widely used because its layered proximity graph offers a useful speed-recall trade-off [2].",
        "Filtering changes that trade-off. A post-filter plan first asks HNSW for a bounded candidate set and then removes candidates that violate category, price, rating, brand, or stock conditions. If only a small fraction of all rows qualifies, most of the nearest global candidates can be rejected. The query may return fewer than k rows, and the surviving rows may omit nearer valid products. pgvector addresses part of this problem with iterative index scans, which continue graph traversal when filtering removes too many candidates [3]. Iteration improves completeness, but it still has tuning costs and it does not make exact search obsolete for highly selective predicates.",
        "This project studies the DBMS decision hidden inside that user-facing search: which physical retrieval strategy should execute a particular filtered vector query? The decision depends on the estimated fraction of qualifying rows, requested result count, number of predicates, collection size, candidate budget, and the behavior observed on previous requests. Static thresholds can provide a safe cold start, but they cannot capture machine-specific costs or interactions between the query and the vector index. A heavy reinforcement-learning optimizer would be excessive for three alternatives and a small course-scale workload. We therefore designed a local, interpretable planner whose predictions come directly from nearby measured executions.",
        "SAHVS makes three contributions. First, it exposes three concrete PostgreSQL plans behind one API and represents each request with relational and vector-search features. Second, it combines a transparent cold-start rule with a five-nearest-observation cost model that penalizes incomplete results and recall below 0.95. Third, it provides a reproducible evaluation workflow with raw strategy baselines, tie-aware recall, online observations, and component ablations. The implementation is deliberately modest: it adds no custom PostgreSQL access method and does not retrain an embedding model. Its novelty for this project lies in the integration of selectivity estimation, runtime feedback, recall-aware plan selection, and safety checks within an ordinary relational system.",
        "The measured result is a useful middle ground. On 50,000 products, the complete planner preserved the exact baseline's mean recall@10 of 1.00 while reducing mean latency from 18.21 ms to 6.42 ms. The fastest fixed strategy was much quicker, but its recall loss was too large to be a valid replacement. The ablation study explains why the adaptive result was possible: historical feedback prevented the planner from relying only on broad rules, and selectivity separated contexts in which the same ANN choice behaved differently.",
    ]
    for text in intro:
        add_paragraph(doc, text)

    add_heading(doc, "2 Literature Study")
    literature = [
        "Vector database systems extend data management beyond symbolic values by storing high-dimensional representations and supporting similarity operators. Pan, Wang, and Li describe a vector DBMS as more than a stand-alone nearest-neighbor library: it must combine indexing with query processing, transactions, scalability, and the other services expected from a database [1]. That systems view motivates our use of PostgreSQL. Product attributes and embeddings remain in the same row, metadata predicates use ordinary SQL, and the planner can draw on the optimizer's row estimates instead of maintaining a separate filtering service.",
        "Malkov and Yashunin's HNSW index organizes vectors in a hierarchy of navigable small-world graphs [2]. Sparse upper layers support long jumps; denser lower layers refine the search near the query. Two parameters matter for this project. The construction parameter M controls graph connectivity, while the search breadth controls how many candidates the traversal explores. Increasing the breadth generally improves recall at additional latency. Our database uses an HNSW index with M equal to 16 and ef_construction equal to 64. SAHVS does not change the graph. It changes when the graph is used and sets the query-time search breadth from the candidate budget.",
        "pgvector brings exact and approximate vector operators into PostgreSQL. Its documentation makes the filtering problem explicit: with an approximate index, PostgreSQL can scan the vector index and then apply the WHERE clause, so a restrictive filter may leave fewer rows than the LIMIT requests. Since version 0.8.0, iterative scans can continue until enough results are found or a scan limit is reached [3]. The same documentation recommends ordinary filter indexes for suitable exact searches, partial indexes for a small number of stable categories, and partitioning when many rows can be separated. These options are valuable, but they require a database administrator to anticipate the workload. SAHVS instead treats exact, bounded approximate, and iterative approximate execution as alternatives for each request.",
        "PostgreSQL's native optimizer already bases physical decisions on estimated cardinalities. EXPLAIN reports a plan tree with estimated row counts and costs, and ANALYZE maintains sampled statistics for these estimates [4, 5]. Selectivity is the estimated fraction of table rows that satisfy a condition. It is central to filtered vector search because it predicts the rate at which global ANN candidates will survive a metadata predicate. We reuse PostgreSQL's estimate rather than constructing an application-side histogram. This retains the DBMS as the source of truth and automatically supports combinations of category, brand, price, rating, and Boolean stock predicates.",
        "Research on filtered ANN often modifies the index itself. Filtered-DiskANN introduced graph construction and traversal methods that incorporate labels, reporting high recall across selective filters and strong throughput relative to several public baselines [6]. ACORN extended HNSW with predicate subgraph traversal and a predicate-agnostic construction method, supporting more general predicate sets; its evaluation reported between 2 and 1000 times higher throughput than prior methods at a fixed recall on the tested datasets [7]. These methods demonstrate what specialized index engineering can achieve. They also require a modified graph implementation and do not directly answer which existing SQL execution path a PostgreSQL application should select.",
        "Recent system studies show why plan selection remains important even with strong indexes. Amanbayev and colleagues compared filtering strategies in FAISS, Milvus, and pgvector and found that engine-level adaptations can dominate raw index behavior. Their experiments reported cases where pgvector selected an approximate scan even though an exact scan offered perfect recall at comparable latency [8]. Shi, Cai, and Zheng likewise organize filtered ANN methods as filter-then-search, search-then-filter, and hybrid search, and argue that evaluation must account for selectivity, recall targets, and dataset-dependent tuning [9]. Our three physical plans correspond closely to those categories, but our goal is per-query selection inside one reproducible PostgreSQL application.",
        "Aslam and colleagues proposed an adaptive query-aware HNSW method that reuses similar historical queries to choose better entry points for graph traversal [10]. Their approach is the nearest conceptual neighbor to SAHVS because both learn from prior requests and include selectivity in the context. The mechanisms differ. Their method changes how a single graph search starts and organizes prior queries in attribute-specific structures. SAHVS leaves pgvector unchanged and chooses among full exact evaluation, bounded HNSW post-filtering, and iterative HNSW. This makes the idea implementable through SQL and session settings on an unmodified PostgreSQL installation.",
        "A second relevant literature concerns learned query optimization. The Join Order Benchmark showed that cardinality errors can compound and cause large plan-quality differences in conventional optimizers [11]. Neo uses a neural value model and continues learning from incoming query performance [12], while Balsa combines simulated experience with safe learning from real executions and reported workload improvements over expert optimizers [13]. Those systems search large join-order and operator spaces. SAHVS borrows the feedback principle but uses a much smaller model appropriate to three choices. Nearest-neighbor regression keeps the decision auditable: for any selected plan, the system can point to similar observed contexts and their measured latency, completeness, and recall.",
        "The literature therefore provides strong algorithms for filtered ANN, practical support in pgvector, and evidence that learned optimizers can adapt to workload behavior. It leaves room for a small application-level meta-planner that uses PostgreSQL selectivity estimates and measured recall to arbitrate among the physical paths already available in an open relational stack. That is the scope of the research gap addressed here.",
    ]
    for text in literature:
        add_paragraph(doc, text)

    add_heading(doc, "3 Research Gap")
    gap = [
        "Most filtered ANN work optimizes one search algorithm. ACORN, Filtered-DiskANN, and related graph methods improve traversal or construction, but adopting them may require a specialized engine or a custom index. At the other extreme, PostgreSQL exposes exact search and configurable HNSW behavior but leaves much of the choice to its general cost model and administrator settings. The application developer still needs to decide whether a request should use an exact filtered scan, a bounded ANN candidate set, or iterative ANN.",
        "A fixed answer is inadequate because filter selectivity spans several orders of magnitude. In our workload, PostgreSQL estimated that between 4.916 percent and 100 percent of products matched. For the most selective contexts, exact evaluation restricts distance calculations to a manageable set and guarantees correct ranking. For broad contexts, exact evaluation is the dominant cost. Post-filtering reverses those properties: it is exceptionally fast when candidates survive, but can return an incomplete or low-recall answer after a selective predicate. Iterative HNSW reduces incompleteness but may spend more work than either alternative.",
        "The missing mechanism is a low-overhead plan selector that combines two kinds of evidence. The first is static context available before execution, especially the DBMS's own cardinality estimate. The second is empirical evidence collected after execution, including latency, result count, and recall measured during controlled benchmark runs. Existing learned optimizers establish the value of feedback, but their neural or reinforcement-learning machinery is difficult to justify for a three-plan decision and complicates explanation in a classroom implementation.",
        "We formulate the research question as follows: can an interpretable, selectivity-aware planner use prior executions to preserve exact-search recall while reducing latency for hybrid vector and metadata queries? Two testable subquestions follow. Does runtime feedback contribute beyond a cold-start threshold policy? Does relational selectivity contribute beyond latency observations and query-shape features? The ablation study removes each component separately, allowing the results to answer these questions rather than treating the planner as an indivisible black box.",
    ]
    for text in gap:
        add_paragraph(doc, text)

    add_heading(doc, "4 Proposed Novel Methodology")
    methodology = [
        "SAHVS is implemented as a query-planning layer between a search API and PostgreSQL. A request contains free text, zero or more metadata predicates, and k. The text becomes a 384-dimensional vector. The validated experiment uses deterministic feature hashing over normalized unigrams and bigrams, plus a small product-domain synonym map. This choice makes the benchmark repeatable without a model download. It is not presented as a learned language embedding; the experiment isolates database planning rather than natural-language model quality.",
        "The products table stores the vector beside relational columns for category, brand, price, rating, stock status, title, and description. B-tree indexes exist for each filterable scalar column. The vector column uses pgvector's cosine HNSW operator class. Separate query_observations and experiment_runs tables make the adaptive state first-class database data. An observation records a query fingerprint, chosen strategy, estimated selectivity, requested k, predicate count, candidate budget, latency, result count, optional recall, and timestamp.",
        "Figure 1 shows the request path. The encoder and PostgreSQL EXPLAIN run before plan choice. Their outputs form a query context for the adaptive planner. Exactly one of three strategies executes, unless the recall guard detects an incomplete approximate result and invokes exact search. The ranked output returns to the API, while its measurements become evidence for later decisions. This feedback loop changes plan selection without altering the HNSW index or PostgreSQL source code.",
    ]
    for text in methodology:
        add_paragraph(doc, text)
    add_picture(
        doc,
        architecture,
        3.15,
        "Architecture of the SAHVS planner, execution paths, recall guard, and observation feedback loop",
    )
    add_caption(doc, "Figure 1  SAHVS system architecture and feedback loop")

    add_heading(doc, "4.1 Physical Search Strategies", level=2)
    physical = [
        "Exact filtered scan computes cosine distance for every qualifying row, orders by distance, and returns k rows. During the benchmark, index and bitmap scans are disabled locally for this strategy so PostgreSQL cannot silently choose HNSW; it therefore supplies deterministic ground truth. The method has recall 1.00 by definition for the indexed data and distance function. Its cost rises with the eligible set and, in this implementation, includes a sequential pass over the 50,000-row table.",
        "ANN post-filter first retrieves b globally nearest HNSW candidates inside a materialized common table expression. The outer SQL query applies all metadata predicates, sorts the surviving candidates, and keeps k. Materialization makes the candidate boundary explicit. This plan has predictable bounded vector work and low latency, but a selective filter can reject most of the b rows. Increasing b improves the chance of complete results at additional work.",
        "Iterative HNSW places metadata predicates in the indexed query, enables strict-order iterative scanning, and sets hnsw.ef_search from the candidate budget with a lower bound of 40 and an upper bound of 1000. pgvector may continue traversal when filtered rows are insufficient. Strict ordering ensures the returned rows remain ordered by distance. This strategy is designed for the middle region where a bounded global candidate set is risky but exact evaluation would touch too many qualifying vectors.",
    ]
    for text in physical:
        add_paragraph(doc, text)

    add_heading(doc, "4.2 Query Features and Candidate Budget", level=2)
    features_text = [
        "For a table with N rows and an EXPLAIN estimate of m matching rows, SAHVS defines selectivity s as m divided by N. PostgreSQL supplies m from the Plan Rows field, and the application clamps s to the interval from 1/N to 1. The candidate budget estimates how many global neighbors must be visited to obtain k survivors if matches were uniformly distributed. A factor of 1.25 provides slack, while a floor of 10k prevents very small searches and a cap of N prevents an impossible budget.",
        "The feature vector contains an intercept; normalized log table size; s and its square root; normalized k; normalized predicate count; and the candidate budget capped at 10,000. Including both s and its square root preserves resolution near zero, where small selectivity changes strongly affect post-filter survival. The implementation currently uses a single 50,000-row table, but table size remains in the representation so recorded contexts can be compared after future growth.",
    ]
    for text in features_text:
        add_paragraph(doc, text)
    add_picture(
        doc,
        equations,
        3.1,
        "Equations defining selectivity, candidate budget, and recall-adjusted observation cost",
    )
    add_caption(doc, "Figure 2  Selectivity candidate budget and observation cost equations")
    add_paragraph(
        doc,
        "In Figure 2, L is measured latency, n is the number of returned rows, and r is recall@k. The indicator penalty of 1000 ms makes an incomplete plan unattractive even if it is fast. The recall term adds 100 times the shortfall below the 0.95 target. These constants intentionally separate invalid fast answers from acceptable plans on a millisecond-scale workload.",
    )

    add_heading(doc, "4.3 Cold Start and Feedback Model", level=2)
    feedback = [
        "The planner begins with rules because no empirical model is trustworthy before all strategies have been observed. If the estimated match count is at most the larger of 200 and 8k, SAHVS selects exact search. Otherwise, selectivity below 0.20 selects iterative HNSW, and broader filters select ANN post-filtering. The thresholds are easy to inspect and provide deterministic behavior during deployment and tests.",
        "Once every strategy has at least eight observations, SAHVS compares the current feature vector with the stored vectors for each strategy. It retains the five nearest observations under Euclidean distance and averages their recall-adjusted costs. The strategy with the lowest predicted cost wins. This is local regression rather than a global neural model: behavior in a 5 percent selectivity neighborhood need not be averaged with behavior for an unfiltered query.",
        "The online service uses a 10 percent exploration probability so that a once-slow strategy can be reconsidered when data or hardware changes. Exploration is disabled in the ablation experiment to make variants deterministic. The final safeguard checks approximate result completeness against the expected number of results. If an approximate strategy returns fewer than min(k, exact available rows), the service runs exact search and returns the safe answer. The recorded fallback frequency is itself an evaluation measure.",
        "Tie-aware recall is necessary for this synthetic catalog because multiple product descriptions can produce equal hashed vectors and equal cosine distances. A strict set intersection with one arbitrary exact top-k set would incorrectly punish another valid ordering of tied rows. We therefore take the largest distance in the exact top-k answer as a boundary. An approximate result is relevant if its distance is no greater than that boundary plus 10 to the power of minus 7, and the count is divided by the number of exact results. This preserves recall semantics without allowing a farther row to pass.",
    ]
    for text in feedback:
        add_paragraph(doc, text)

    add_heading(doc, "5 Quantitative Experimental Validation")
    experiment = [
        "The experiment ran locally on an Apple M4 MacBook Air with ten CPU cores and 24 GB of unified memory, using macOS 15.6.1, PostgreSQL 17.11, and pgvector 0.8.7. The application and database communicated over localhost. Each reported latency surrounds the complete repository operation, including acquiring a pooled connection, starting a transaction, applying local session settings, executing SQL, and fetching rows. The values therefore represent application-observed database latency rather than isolated CPU distance time.",
        "A deterministic generator created 50,000 products with seed 42. Five categories contain laptops, phones, audio products, wearables, and home devices. Each row has a brand, price drawn from a category-specific range, rating, stock flag, templated title and description, and a normalized 384-dimensional feature-hash vector. This construction provides controlled metadata distributions and repeatable vectors. Its limitation is reduced linguistic diversity, so the experiment evaluates plan selection rather than general semantic retrieval quality.",
        "The workload contains ten queries ranging from two-predicate category-and-price searches to an unfiltered reliable product query. PostgreSQL's estimated selectivity ranges from 0.04916 to 1.00, corresponding to 2,458 through 50,000 eligible rows. Requested k is 10. Each raw strategy executes five times for each query, producing 150 measured searches, in addition to exact ground-truth executions. The same workload then runs five times under each of five planner variants, producing 250 ablation measurements.",
        "We report mean, median, and 95th-percentile latency; tie-aware recall@10 against exact search; full-result rate, defined as the fraction of executions returning all requested rows; and fallback rate for planner variants. No benchmark number is embedded in the application. The scripts write timestamped CSV and JSON artifacts and load strategy observations into PostgreSQL before the adaptive study.",
    ]
    for text in experiment:
        add_paragraph(doc, text)

    table_break = doc.add_paragraph()
    table_break.add_run().add_break(WD_BREAK.COLUMN)
    add_caption(doc, "Table 1  Experimental configuration")
    add_table(
        doc,
        ["Component", "Setting"],
        [
            ("Database", "PostgreSQL 17.11 with pgvector 0.8.7"),
            ("Hardware", "Apple M4 10 cores 24 GB memory"),
            ("Dataset", "50000 products seed 42"),
            ("Vectors", "384 dimensions cosine distance feature hash"),
            ("Indexes", "Five B-tree metadata indexes and HNSW M 16"),
            ("Workload", "10 queries k 10 five repetitions"),
            ("Metrics", "Latency recall full results fallback rate"),
        ],
        widths=[0.95, 2.15],
        font_size=7.8,
    )

    results = benchmark["summary"]
    add_heading(doc, "5.1 Baseline Results", level=2)
    baseline_text = [
        "Table 2 and Figure 3 expose the central trade-off. Exact filtered search averaged 18.21 ms and achieved recall 1.00 with complete results for every run. ANN post-filtering reduced mean latency to 0.63 ms, approximately 29 times faster, but mean recall fell to 0.56 and only 70 percent of executions returned all ten rows. Iterative HNSW cost 0.87 ms, retained a complete result count in every execution, and improved recall to 0.81. A full count is therefore not evidence of correct nearest neighbors: iteration found ten qualifying rows, yet some exact top-k rows were still missed.",
        "Tail latency follows the same pattern. Exact search had a p95 of 30.28 ms, compared with 1.08 ms for post-filtering and 1.72 ms for iterative HNSW. These differences confirm that ANN is valuable for broad filters. They also show why choosing the globally fastest average would be wrong. The 0.63 ms post-filter plan would save time by returning a materially different answer set on this workload.",
        "Performance also varies by query context. The first laptop query had estimated selectivity 0.06742 and a dynamic budget of 186; post-filter recall was 0.90 and iterative recall was 1.00. The second phone query had similar selectivity, 0.06576, yet post-filtering returned only five rows with recall 0.50 and iterative recall was 0.80. Selectivity alone is therefore informative but not sufficient. Historical behavior for nearby contexts supplies evidence about how vector neighborhoods and metadata predicates interact.",
    ]
    for text in baseline_text:
        add_paragraph(doc, text)
    add_caption(doc, "Table 2  Raw physical strategy results")
    add_table(
        doc,
        ["Strategy", "Mean ms", "Median ms", "p95 ms", "Recall", "Full"],
        [
            (
                "Exact filtered",
                f"{results['exact_prefilter']['mean_latency_ms']:.2f}",
                f"{results['exact_prefilter']['median_latency_ms']:.2f}",
                f"{results['exact_prefilter']['p95_latency_ms']:.2f}",
                "1.00",
                "1.00",
            ),
            (
                "ANN post-filter",
                f"{results['ann_postfilter']['mean_latency_ms']:.2f}",
                f"{results['ann_postfilter']['median_latency_ms']:.2f}",
                f"{results['ann_postfilter']['p95_latency_ms']:.2f}",
                "0.56",
                "0.70",
            ),
            (
                "Iterative HNSW",
                f"{results['ann_iterative']['mean_latency_ms']:.2f}",
                f"{results['ann_iterative']['median_latency_ms']:.2f}",
                f"{results['ann_iterative']['p95_latency_ms']:.2f}",
                "0.81",
                "1.00",
            ),
        ],
        widths=[0.9, 0.45, 0.48, 0.43, 0.42, 0.42],
        font_size=7.2,
    )
    add_picture(
        doc,
        baseline_plot,
        3.15,
        "Bar chart of mean and p95 latency with a recall line for exact, post-filter, and iterative HNSW baselines",
    )
    add_caption(doc, "Figure 3  Baseline latency and recall trade-off")

    add_heading(doc, "5.2 Adaptive Planner Result", level=2)
    adaptive = [
        "The complete SAHVS planner averaged 6.42 ms with recall@10 of 1.00 and a full-result rate of 1.00. Dividing the exact baseline's 18.21 ms by 6.42 ms gives a 2.83 times speedup at equal mean recall. The planner selected exact search for 15 of 50 repeated requests, iterative HNSW for 20, and post-filtering for 15. This mixture explains why its latency is higher than either raw ANN average: it deliberately spends more time on contexts where the observed ANN answer is not reliable.",
        "No fallback occurred for the full variant in the stable evaluation workload. This does not make the guard useless; it means the learned choice avoided strategies that returned fewer than k in those contexts. The correct interpretation is that plan selection delivered the quality result, while the guard remained a protection against an incomplete unseen request. A shifted workload is needed to quantify the guard's independent benefit.",
        "The experiment supports the main hypothesis within its stated scale. Feedback does not make approximate search exact in a mathematical sense. It learns when the measured approximate plans meet the recall target and chooses exact search elsewhere. The result is therefore a workload-conditioned latency-recall improvement, not a universal guarantee over arbitrary data.",
    ]
    for text in adaptive:
        add_paragraph(doc, text)

    add_heading(doc, "5.3 Threats to Validity", level=2)
    threats = [
        "The dataset is synthetic and contains templated language. Equal hashed features create more distance ties than a natural embedding corpus, although the tie-aware metric prevents those ties from biasing recall downward. A future study should repeat the experiment with a learned sentence encoder and a public product or document dataset. The current results should not be generalized to linguistic relevance.",
        "All measurements come from one laptop, one PostgreSQL configuration, one dataset size, and ten query templates. Local execution reduces network noise but does not model concurrent clients, buffer-cache churn, updates, or remote database latency. Five repetitions characterize the stable demonstration workload but are too few for a production service-level claim. Multiple dataset sizes and cold-cache trials would strengthen external validity.",
        "Finally, the exact ground-truth plan disables index and bitmap scans to prevent accidental ANN use. That creates a clean reference but can be slower than the best hand-tuned exact plan with partial indexes or partitions. The reported 2.83 times speedup is relative to this defined exact baseline. It should not be read as a comparison against every possible PostgreSQL schema design.",
    ]
    for text in threats:
        add_paragraph(doc, text)

    add_heading(doc, "6 Ablation Study")
    abl = ablation["summary"]
    ablation_text = [
        "The ablation study holds the dataset, workload, k, and repetitions constant while removing one planner component. The full variant uses selectivity features, stored observations, dynamic candidate sizing, and the exact fallback. No feedback invokes only the cold-start rules. No selectivity replaces selectivity with 1.0 and also supplies a minimal candidate context to the planner. Fixed budget uses 10k candidates instead of the selectivity-derived budget. No recall guard suppresses the exact fallback.",
        "Removing feedback produced the lowest latency, 2.27 ms, but recall fell from 1.00 to 0.81. The cold-start policy selected only ANN strategies: iterative HNSW for 30 executions and post-filtering for 20. Its speed therefore came from accepting errors. The 19 percentage-point recall decrease demonstrates that measured execution history is necessary for the full system's quality on this workload.",
        "Removing selectivity increased mean latency from 6.42 to 7.02 ms and lowered recall to 0.89. The altered context led the planner to choose post-filtering for 45 of 50 executions and exact search for five; 30 percent of executions required fallback. This is the clearest evidence that relational selectivity is not a cosmetic feature. Without it, nearby-neighbor lookup groups physically different requests together, chooses an unsafe approximate path more often, and then pays for exact recovery in some cases.",
        "The fixed-budget variant averaged 6.41 ms with recall 1.00, while the no-guard variant averaged 6.37 ms with recall 1.00. Both selected the same 15 exact, 20 iterative, and 15 post-filter executions as the full planner. Consequently, this stable workload does not prove that dynamic budgeting or the guard is individually necessary. We retain them as engineering safeguards and do not include them in the paper's core causal claim. Their value should be tested with rare predicates, distribution shift, smaller exploration history, and queries whose estimated and actual cardinalities disagree.",
        "Figure 4 makes the quality-latency interpretation visible. A lower bar is not automatically better if the corresponding recall bar also falls. The full system occupies the desired region: exact mean recall with substantially lower latency than the exact baseline. The two successful ablations identify the core contribution more narrowly as selectivity-aware use of measured workload feedback.",
    ]
    for text in ablation_text:
        add_paragraph(doc, text)
    add_caption(doc, "Table 3  Component ablation results")
    add_table(
        doc,
        ["Variant", "Mean ms", "Recall", "Full", "Fallback"],
        [
            ("Full", f"{abl['full']['mean_latency_ms']:.2f}", "1.00", "1.00", "0.00"),
            ("No feedback", f"{abl['no_feedback']['mean_latency_ms']:.2f}", "0.81", "1.00", "0.10"),
            (
                "No selectivity",
                f"{abl['no_selectivity']['mean_latency_ms']:.2f}",
                "0.89",
                "1.00",
                "0.30",
            ),
            (
                "Fixed budget",
                f"{abl['fixed_candidate_budget']['mean_latency_ms']:.2f}",
                "1.00",
                "1.00",
                "0.00",
            ),
            (
                "No guard",
                f"{abl['no_recall_guard']['mean_latency_ms']:.2f}",
                "1.00",
                "1.00",
                "0.00",
            ),
        ],
        widths=[1.0, 0.55, 0.5, 0.48, 0.57],
        font_size=7.3,
    )
    add_picture(
        doc,
        ablation_plot,
        3.15,
        "Two-panel ablation chart showing latency, recall, and fallback rate for five planner variants",
    )
    add_caption(doc, "Figure 4  Ablation latency recall and fallback behavior")

    add_heading(doc, "7 Conclusion")
    conclusion = [
        "SAHVS demonstrates that hybrid vector and metadata search is a query-planning problem as much as an indexing problem. Exact scanning, bounded post-filtering, and iterative HNSW each dominate under different conditions. A general instruction to always use the vector index loses recall, while always using exact search wastes time on broad filters.",
        "The proposed method combines PostgreSQL's estimated selectivity with measured executions in a small local cost model. On the 50,000-row workload, it matched exact search at mean recall@10 of 1.00 and reduced mean latency from 18.21 ms to 6.42 ms. The ablation results locate the benefit in two components: removing feedback reduced recall to 0.81, and removing selectivity reduced recall to 0.89 while increasing latency and fallback use. Dynamic candidate sizing and the guard did not change this stable run, so their necessity remains a future test rather than a claimed result.",
        "The next evaluation should use a public corpus with learned embeddings, increase the table through several scale factors, introduce concurrent clients and data updates, and create deliberate distribution shifts between training and test queries. It should also compare SAHVS with PostgreSQL's chosen plan, partial indexes, partitioned tables, and specialized filtered ANN systems. Within the present scope, the project provides a working DBMS artifact, a reproducible experiment, and evidence that an interpretable adaptive layer can improve the latency-recall balance without modifying the database engine.",
    ]
    for text in conclusion:
        add_paragraph(doc, text)

    add_heading(doc, "References")
    references = [
        "[1] J. J. Pan, J. Wang, and G. Li, Survey of vector database management systems, The VLDB Journal, vol. 33, pp. 1591-1615, 2024. doi 10.1007/s00778-024-00864-x.",
        "[2] Y. A. Malkov and D. A. Yashunin, Efficient and robust approximate nearest neighbor search using hierarchical navigable small world graphs, IEEE Transactions on Pattern Analysis and Machine Intelligence, vol. 42, no. 4, pp. 824-836, 2020. doi 10.1109/TPAMI.2018.2889473.",
        "[3] pgvector contributors, pgvector open source vector similarity search for Postgres, project documentation, version 0.8 series, 2024-2026. https://github.com/pgvector/pgvector.",
        "[4] PostgreSQL Global Development Group, Using EXPLAIN, PostgreSQL 18 Documentation, 2026. https://www.postgresql.org/docs/current/using-explain.html.",
        "[5] PostgreSQL Global Development Group, Statistics Used by the Planner, PostgreSQL 18 Documentation, 2026. https://www.postgresql.org/docs/current/planner-stats.html.",
        "[6] S. Gollapudi et al., Filtered-DiskANN Graph Algorithms for Approximate Nearest Neighbor Search with Filters, Proceedings of The Web Conference, pp. 3745-3756, 2023. doi 10.1145/3543507.3583552.",
        "[7] L. Patel, P. Kraft, C. Guestrin, and M. Zaharia, ACORN Performant and Predicate Agnostic Search Over Vector Embeddings and Structured Data, Proceedings of the ACM on Management of Data, vol. 2, no. 3, pp. 1-27, 2024. arXiv 2403.04871.",
        "[8] A. Amanbayev, B. Tsan, T. Dang, and F. Rusu, Filtered Approximate Nearest Neighbor Search in Vector Databases System Design and Performance Analysis, arXiv 2602.11443, 2026.",
        "[9] J. Shi, Y. Cai, and W. Zheng, Filtered Approximate Nearest Neighbor Search A Unified Benchmark and Systematic Experimental Study, arXiv 2509.07789, 2025.",
        "[10] A. Aslam, R. Khan, G. Simonini, and G. Konstantinidis, Adaptive Query Aware Hybrid Search in Vector Databases, EDBT 2026, pp. 530-536, 2026. doi 10.48786/edbt.2026.42.",
        "[11] V. Leis, A. Gubichev, A. Mirchev, P. Boncz, A. Kemper, and T. Neumann, How Good Are Query Optimizers Really, Proceedings of the VLDB Endowment, vol. 9, no. 3, pp. 204-215, 2015. doi 10.14778/2850583.2850594.",
        "[12] R. Marcus et al., Neo A Learned Query Optimizer, Proceedings of the VLDB Endowment, vol. 12, no. 11, pp. 1705-1718, 2019. doi 10.14778/3342263.3342644.",
        "[13] Z. Yang, W. Chiang, S. Luan, G. Mittal, M. Luo, and I. Stoica, Balsa Learning a Query Optimizer Without Expert Demonstrations, Proceedings of the 2022 International Conference on Management of Data, pp. 931-944, 2022. doi 10.1145/3514221.3517885.",
    ]
    for ref in references:
        if ref.startswith("[9]"):
            breaker = doc.add_paragraph()
            breaker.add_run().add_break(WD_BREAK.COLUMN)
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.16)
        p.paragraph_format.first_line_indent = Inches(-0.16)
        p.paragraph_format.space_after = Pt(2.2)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        r = p.add_run(ref)
        set_font(r, size=8.3)

    # Repeat footer in all sections and keep headings with their next paragraph.
    for sec in doc.sections[1:]:
        sec.footer.is_linked_to_previous = True
    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith("Heading"):
            keep_with_next(paragraph)

    doc.settings.element.append(OxmlElement("w:updateFields"))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_PATH)
    return OUT_PATH


if __name__ == "__main__":
    output = build_document()
    print(output)
