"""
LC → CI Converter
- Reads a Letter of Credit PDF or image
- Extracts key fields using GPT-4o Vision
- Generates a Commercial Invoice as a .docx file

Requirements:
    pip install openai python-docx pdf2image pillow
    npm install -g docx   (for the JS generator, optional if using python-docx path)

Usage:
    python lc_to_ci.py --lc path/to/lc.pdf --out outputs/
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

# ── Dependencies check ────────────────────────────────────────────────────────

def require(pkg):
    try:
        __import__(pkg)
    except ImportError:
        print(f"[setup] Installing {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

for pkg in ["openai", "pdf2image", "pillow", "docx"]:
    require(pkg)

import openai
from pdf2image import convert_from_path
from PIL import Image
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ── Config ────────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    sys.exit("[error] Set the OPENAI_API_KEY environment variable before running.")

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# ── Step 1: PDF/Image → base64 ────────────────────────────────────────────────

def file_to_base64_images(path: str) -> list[str]:
    """Convert a PDF or image file to a list of base64-encoded JPEG strings."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        print(f"[ocr] Converting PDF to images...")
        pages = convert_from_path(str(path), dpi=200, fmt="jpeg")
    elif suffix in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        pages = [Image.open(str(path))]
    else:
        sys.exit(f"[error] Unsupported file type: {suffix}")

    encoded = []
    for i, img in enumerate(pages):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            img.save(tmp.name, "JPEG", quality=90)
            with open(tmp.name, "rb") as f:
                encoded.append(base64.b64encode(f.read()).decode("utf-8"))
        os.unlink(tmp.name)
        print(f"[ocr] Page {i+1} encoded.")

    return encoded


# ── Step 2: GPT-4o extraction ─────────────────────────────────────────────────

EXTRACTION_PROMPT = """
You are a trade finance document specialist. Extract the following fields from this Letter of Credit document.

Return ONLY a valid JSON object — no markdown, no commentary — with exactly these keys:

{
  "lc_number": "",
  "lc_date": "",
  "expiry_date": "",
  "applicant_name": "",
  "applicant_address": "",
  "beneficiary_name": "",
  "beneficiary_address": "",
  "advising_bank": "",
  "issuing_bank": "",
  "currency": "",
  "amount": "",
  "incoterms": "",
  "port_of_loading": "",
  "port_of_discharge": "",
  "latest_shipment_date": "",
  "goods_description": "",
  "quantity": "",
  "unit_price": "",
  "partial_shipments": "",
  "transhipment": "",
  "payment_terms": ""
}

If a field is not found, use an empty string. Do not invent values.
"""

def extract_lc_fields(b64_images: list[str]) -> dict:
    print("[gpt4o] Extracting fields from LC...")

    content = []
    for b64 in b64_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}
        })
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content}],
        max_tokens=1500,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[error] GPT-4o returned invalid JSON:\n{raw}")
        sys.exit(str(e))

    print("[gpt4o] Extraction complete.")
    return data


# ── Step 3: Build .docx CI ────────────────────────────────────────────────────

def set_cell_bg(cell, hex_color: str):
    """Set table cell background color."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def add_paragraph(doc, text="", bold=False, size=11, alignment=WD_ALIGN_PARAGRAPH.LEFT, color=None, space_after=6):
    p = doc.add_paragraph()
    p.alignment = alignment
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor(*bytes.fromhex(color))
    return p


def add_kv_row(table, label, value, label_bg="EBF3FB"):
    row = table.add_row()
    lbl_cell, val_cell = row.cells[0], row.cells[1]

    set_cell_bg(lbl_cell, label_bg)
    lbl_p = lbl_cell.paragraphs[0]
    lbl_p.paragraph_format.space_after = Pt(2)
    lbl_run = lbl_p.add_run(label)
    lbl_run.bold = True
    lbl_run.font.size = Pt(9)
    lbl_run.font.color.rgb = RGBColor(0x1A, 0x56, 0x8C)

    val_p = val_cell.paragraphs[0]
    val_p.paragraph_format.space_after = Pt(2)
    val_run = val_p.add_run(str(value) if value else "—")
    val_run.font.size = Pt(10)

    return row


def build_ci_docx(data: dict, output_path: str):
    print("[docx] Building Commercial Invoice...")
    doc = Document()

    # Page margins (1 inch all around)
    section = doc.sections[0]
    section.top_margin    = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin   = Inches(1)
    section.right_margin  = Inches(1)

    # ── Header ────────────────────────────────────────────────────────────────
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_after = Pt(4)
    title_run = title_p.add_run("COMMERCIAL INVOICE")
    title_run.bold = True
    title_run.font.size = Pt(18)
    title_run.font.color.rgb = RGBColor(0x1A, 0x56, 0x8C)

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_p.paragraph_format.space_after = Pt(16)
    sub_run = sub_p.add_run(f"Date: {date.today().strftime('%d %B %Y')}")
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # ── Section helper ────────────────────────────────────────────────────────
    def section_heading(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after  = Pt(4)
        run = p.add_run(text.upper())
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        # Fake colored background via paragraph shading
        pPr = p._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "1A568C")
        pPr.append(shd)
        p.paragraph_format.left_indent = Inches(0.1)

    def kv_table():
        tbl = doc.add_table(rows=0, cols=2)
        tbl.style = "Table Grid"
        tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
        tbl.columns[0].width = Inches(2.2)
        tbl.columns[1].width = Inches(5.1)
        return tbl

    # ── LC Reference ──────────────────────────────────────────────────────────
    section_heading("Letter of Credit Details")
    tbl = kv_table()
    add_kv_row(tbl, "LC Number",               data.get("lc_number"))
    add_kv_row(tbl, "LC Date",                 data.get("lc_date"))
    add_kv_row(tbl, "Expiry Date",             data.get("expiry_date"))
    add_kv_row(tbl, "Issuing Bank",            data.get("issuing_bank"))
    add_kv_row(tbl, "Advising Bank",           data.get("advising_bank"))
    add_kv_row(tbl, "Payment Terms",           data.get("payment_terms"))

    # ── Parties ───────────────────────────────────────────────────────────────
    section_heading("Seller (Beneficiary)")
    tbl2 = kv_table()
    add_kv_row(tbl2, "Name",    data.get("beneficiary_name"))
    add_kv_row(tbl2, "Address", data.get("beneficiary_address"))

    section_heading("Buyer (Applicant)")
    tbl3 = kv_table()
    add_kv_row(tbl3, "Name",    data.get("applicant_name"))
    add_kv_row(tbl3, "Address", data.get("applicant_address"))

    # ── Shipment ──────────────────────────────────────────────────────────────
    section_heading("Shipment Details")
    tbl4 = kv_table()
    add_kv_row(tbl4, "Incoterms",              data.get("incoterms"))
    add_kv_row(tbl4, "Port of Loading",        data.get("port_of_loading"))
    add_kv_row(tbl4, "Port of Discharge",      data.get("port_of_discharge"))
    add_kv_row(tbl4, "Latest Shipment Date",   data.get("latest_shipment_date"))
    add_kv_row(tbl4, "Partial Shipments",      data.get("partial_shipments"))
    add_kv_row(tbl4, "Transhipment",           data.get("transhipment"))

    # ── Goods & Value ─────────────────────────────────────────────────────────
    section_heading("Goods & Invoice Value")
    tbl5 = doc.add_table(rows=1, cols=4)
    tbl5.style = "Table Grid"
    tbl5.alignment = WD_TABLE_ALIGNMENT.LEFT

    headers = ["Description", "Quantity", "Unit Price", "Total Amount"]
    col_widths = [Inches(3.0), Inches(1.2), Inches(1.5), Inches(1.6)]
    for i, (hdr, w) in enumerate(zip(headers, col_widths)):
        cell = tbl5.rows[0].cells[i]
        cell.width = w
        set_cell_bg(cell, "1A568C")
        p = cell.paragraphs[0]
        run = p.add_run(hdr)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Goods row
    def clean_num(val):
        try:
            return float("".join(c for c in str(val) if c.isdigit() or c == "."))
        except (ValueError, TypeError):
            return 0.0

    qty        = clean_num(data.get("quantity", 0))
    unit_price = clean_num(data.get("unit_price", 0))
    total      = qty * unit_price if qty and unit_price else 0
    currency   = data.get("currency", "USD")

    goods_row = tbl5.add_row()
    values = [
        data.get("goods_description", "—"),
        f"{qty:,.2f}" if qty else data.get("quantity", "—"),
        f"{currency} {unit_price:,.2f}" if unit_price else data.get("unit_price", "—"),
        f"{currency} {total:,.2f}" if total else data.get("amount", "—"),
    ]
    for i, val in enumerate(values):
        cell = goods_row.cells[i]
        cell.width = col_widths[i]
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(val)
        run.font.size = Pt(10)

    # Total row
    total_row = tbl5.add_row()
    set_cell_bg(total_row.cells[2], "EBF3FB")
    set_cell_bg(total_row.cells[3], "EBF3FB")
    lbl_run = total_row.cells[2].paragraphs[0].add_run("TOTAL")
    lbl_run.bold = True
    lbl_run.font.size = Pt(10)
    lbl_run.font.color.rgb = RGBColor(0x1A, 0x56, 0x8C)
    val_run = total_row.cells[3].paragraphs[0].add_run(
        f"{currency} {total:,.2f}" if total else data.get("amount", "—")
    )
    val_run.bold = True
    val_run.font.size = Pt(10)

    # ── Footer note ───────────────────────────────────────────────────────────
    doc.add_paragraph()
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(16)
    note_run = note.add_run(
        "This Commercial Invoice is prepared in accordance with the terms and conditions "
        "of the above-referenced Letter of Credit."
    )
    note_run.font.size = Pt(9)
    note_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc.save(output_path)
    print(f"[docx] Saved → {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert a Letter of Credit to a Commercial Invoice (.docx)")
    parser.add_argument("--lc",  required=True, help="Path to the LC file (PDF or image)")
    parser.add_argument("--out", default="outputs", help="Output directory (default: outputs/)")
    args = parser.parse_args()

    if not os.path.exists(args.lc):
        sys.exit(f"[error] File not found: {args.lc}")

    # 1. Encode
    images = file_to_base64_images(args.lc)

    # 2. Extract
    data = extract_lc_fields(images)

    # Pretty-print extracted fields
    print("\n── Extracted Fields ──────────────────────────────")
    for k, v in data.items():
        print(f"  {k:<30} {v or '(not found)'}")
    print("──────────────────────────────────────────────────\n")

    # 3. Generate CI
    lc_num = re.sub(r"[^\w]", "_", data.get("lc_number", "unknown"))
    out_file = os.path.join(args.out, f"CI_{lc_num}.docx")
    build_ci_docx(data, out_file)

    print(f"\nDone! Commercial Invoice saved to: {out_file}")


if __name__ == "__main__":
    main()
