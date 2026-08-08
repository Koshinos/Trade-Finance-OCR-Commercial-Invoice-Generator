"""
LC → CI Converter
- Reads a Letter of Credit PDF or image
- Extracts key fields using GPT-4o Vision
- Fills your CI Word template (ci_template_docx.docx) using docxtpl

Requirements:
    pip install openai pdf2image pillow python-dotenv docxtpl

Usage:
    python main.py --lc inputs/saiilc.pdf --out outputs/
"""

import argparse
import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from datetime import date

from dotenv import load_dotenv

load_dotenv()

# ── Dependencies check ────────────────────────────────────────────────────────


def require(pkg, install_name=None):
    try:
        __import__(pkg)
    except ImportError:
        name = install_name or pkg
        print(f"[setup] Installing {name}...")
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", name, "-q"])


require("openai")
require("pdf2image")
require("PIL", "pillow")
require("docxtpl")

import openai
from pdf2image import convert_from_path
from PIL import Image
from docxtpl import DocxTemplate


# ── Config ────────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    sys.exit("[error] Set OPENAI_API_KEY in your .env file or environment.")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

TEMPLATE_PATH = "inputs/template.docx.docx"


# ── Step 1: PDF/Image → base64 ────────────────────────────────────────────────


def file_to_base64_images(path: str) -> list:
    path = Path(path)
    suffix = path.suffix.lower()

    if not path.exists():
        sys.exit(f"[error] File not found: {path}")

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
# Fields match the {{placeholders}} in ci_template_docx.docx exactly.

EXTRACTION_PROMPT = (
    """
You are a trade finance specialist. Extract the following fields from this Letter of Credit document.

Return ONLY a valid JSON object with exactly these keys (no markdown, no commentary):

{
  "beneficiary_name_and_address": "",
  "applicant_name_and_address": "",
  "invoice_number": "",
  "invoice_date": "",
  "vessel_name": "",
  "bill_of_lading_number": "",
  "bill_of_lading_date": "",
  "vessel_imo": "",
  "contract_number": "",
  "documentary_credit_number": "",
  "country_of_origin": "",
  "lc_issuing_bank": "",
  "exact_description_of_goods_for_invoice": "",
  "port_of_loading": "",
  "base_unit_price_numeric": "",
  "total_quantity_shipped": "",
  "adjusted_base_price": "",
  "total_shipment_value": "",
  "actual_tm_result": "",
  "actual_ash_result": "",
  "actual_inherent_moisture": "",
  "actual_volatile_matter": "",
  "actual_sulphur_result": "",
  "actual_gcv_arb_result": "",
  "actual_fixed_carbon": "",
  "actual_hard_grove_index": "",
  "actual_size_crushed": "",
  "tm_typical": "",
  "tm_rejection": "",
  "ash_typical": "",
  "ash_rejection": "",
  "inherent_moisture_typical": "",
  "inherent_moisture_rejection": "",
  "sulphur_typical": "",
  "sulphur_rejection": "",
  "gcv_typical": "",
  "gcv_rejection": "",
  "fixed_carbon_typical": "",
  "fixed_carbon_rejection": "",
  "hgi_typical": "",
  "hgi_rejection": "",
  "size_typical": "",
  "size_rejection": "",
  "volatile_matter_typical": "",
  "volatile_matter_rejection": "",
  "adjusted_price": "",
  "total_quantity_shipped": "",
  "adjusted_base_price": "",
  "specifications_disclaimer": "",
  "cargo_value_clause": "",
  "total_shipment_value_words": "",
  "price_adjustment_clause": ""
}

Rules:
- If a field is not found, use an empty string.
- For invoice_date, use today's date if not specified: """
    + date.today().strftime("%d %B %Y")
    + """
- For adjusted_base_price: calculate as (base_price * actual_gcv_arb) / 3400, rounded to 2 decimal places. If values are missing, leave empty.
- For total_shipment_value: calculate as adjusted_base_price * total_quantity_shipped, rounded to 2 decimal places. If values are missing, leave empty.
- Do not invent values not present in the document.
- For coal specifications, extract both the TYPICAL value and REJECTION limit for each parameter.
- These are usually in a table with columns: PARAMETER | TYPICAL | REJECTION | RESULTS.
- Extract from whichever document contains them (LC or COA).
- For price_adjustment_clause: find the paragraph describing the price adjustment formula for GCV (ARB). Extract it exactly word for word, including the formula and the actual numbers (base price, GCV value, calculated result). Keep the full text as one string.
- For specifications_disclaimer: find the paragraph starting with "THE SPECIFICATIONS LISTED ABOVE 
- ARE TYPICAL SPECIFICATIONS AS CONTRACTUALLY AGREED..." and extract it exactly word for word. If not found in the document, return an empty string.
- For cargo_value_clause: find the paragraph starting with "THE CARGO VALUE OF 100PCT..." 
- specifying quantity and quality determined at loading port. Extract exactly word for word. If not found, return an empty string.
- For vessel details, extract from the Bill of Lading document (if provided):
- vessel_name: the name of the vessel
- bill_of_lading_number: the Bill of Lading number
- bill_of_lading_date: the date on the Bill of Lading
- vessel_imo: the IMO number of the vessel
- If the Bill of Lading is not provided, return empty strings for all four fields.
- For total_shipment_value_words: convert total_shipment_value to English words in USD format, e.g. "USD TWO MILLION SEVEN THOUSAND NINETY-FIVE ONLY". If total_shipment_value is not found, return empty string.- For actual results, extract from the Certificate of Sampling and Analysis document 
- actual_tm_result: Total Moisture (ARB) result
- actual_ash_result: Ash (ADB) result
- actual_inherent_moisture: Inherent Moisture (ADB) result
- actual_volatile_matter: Volatile Matter (ADB) result
- actual_sulphur_result: Sulphur (ADB) result
- actual_gcv_arb_result: Gross Calorific Value (ARB) result
- actual_fixed_carbon: Fixed Carbon (ADB) result
- actual_hard_grove_index: Hard Grove Index (HGI) result
- actual_size_crushed: Size (0-200mm) Crushed result
- Return each as the numeric value with its unit exactly as shown in the document (e.g. "16.48 PCT", "3,412 KCAL/KG").
- If the COA is not provided, return empty strings for all actual results.
"""
)


def extract_lc_fields(b64_images: list) -> dict:
    print("[gpt4o] Sending LC to GPT-4o Vision for extraction...")

    content = []
    for b64 in b64_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
            }
        )
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content}],
        max_tokens=2000,
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


# ── Step 3: Fill CI template ──────────────────────────────────────────────────


def build_ci_docx(data: dict, output_path: str):
    print("[docx] Filling CI template...")

    if not os.path.exists(TEMPLATE_PATH):
        sys.exit(f"[error] Template not found at: {TEMPLATE_PATH}")

    # Safety net: recalculate if GPT missed them
    def clean_num(val, default=0.0):
        try:
            return float("".join(c for c in str(val) if c.isdigit() or c == "."))
        except (ValueError, TypeError):
            return default

    base_price = clean_num(data.get("base_unit_price_numeric"))
    actual_gcv = clean_num(data.get("actual_gcv_arb_result"))
    qty = clean_num(data.get("total_quantity_shipped"))

    if base_price and actual_gcv and not data.get("adjusted_base_price"):
        data["adjusted_base_price"] = str(round((base_price * actual_gcv) / 3400, 2))

    adj_price = clean_num(data.get("adjusted_base_price"))
    if adj_price and qty and not data.get("total_shipment_value"):
        data["total_shipment_value"] = str(round(adj_price * qty, 2))

    if actual_gcv and not data.get("actual_gcv"):
        data["actual_gcv"] = data.get("actual_gcv_arb_result", "")

    if adj_price and not data.get("adjusted_price"):
        data["adjusted_price"] = f"USD {adj_price:.2f}"

    doc = DocxTemplate(TEMPLATE_PATH)
    doc.render(data)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc.save(output_path)
    print(f"[docx] Saved → {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    print("Script started")

    parser = argparse.ArgumentParser(
        description="Convert a Letter of Credit to a Commercial Invoice (.docx)"
    )
    parser.add_argument(
        "--lc", required=True, help="Path to the LC file (PDF or image)"
    )
    parser.add_argument(
        "--out", default="outputs", help="Output directory (default: outputs/)"
    )
    parser.add_argument(
        "--coa",
        required=False,
        nargs="+",
        help="Certificate of Analysis PDFs (optional, multiple allowed)",
    )
    parser.add_argument(
        "--bl",
        required=False,
        nargs="+",
        help="Bill of Lading PDFs (optional, multiple allowed)",
    )

    args = parser.parse_args()

    # 1. Encode LC to images
    # Encode all provided documents
    images = file_to_base64_images(args.lc)
    if args.bl:
        for bl_file in args.bl:
            print(f"[info] Adding Bill of Lading: {bl_file}")
            images += file_to_base64_images(bl_file)
    if args.coa:
        for coa_file in args.coa:
            print(f"[info] Adding Certificate of Analysis: {coa_file}")
            images += file_to_base64_images(coa_file)

    # 2. Extract fields with GPT-4o
    data = extract_lc_fields(images)

    # Print extracted fields
    print("\n── Extracted Fields ──────────────────────────────")
    for k, v in data.items():
        print(f"  {k:<40} {v or '(not found)'}")
    print("──────────────────────────────────────────────────\n")

    # 3. Fill template and save
    lc_num = re.sub(r"[^\w]", "_", data.get("documentary_credit_number", "unknown"))
    out_file = os.path.join(args.out, f"CI_{lc_num}.docx")
    build_ci_docx(data, out_file)

    print(f"\nDone! Commercial Invoice saved to: {out_file}")


if __name__ == "__main__":
    main()
