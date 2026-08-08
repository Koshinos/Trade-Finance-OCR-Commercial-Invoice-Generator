import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from datetime import date
import numpy as np

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
require("paddleocr")
# You may also need paddlepaddle: pip install paddlepaddle

import openai
from pdf2image import convert_from_path
from PIL import Image
from docxtpl import DocxTemplate
from paddleocr import PaddleOCR

# ── Config ────────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    sys.exit("[error] Set OPENAI_API_KEY in your .env file or environment.")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
TEMPLATE_PATH = "inputs/template.docx.docx"

# Initialize PaddleOCR (downloads models on first run)
print("[setup] Initializing PaddleOCR...")
ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

# ── Step 1: Local OCR using PaddleOCR ─────────────────────────────────────────


def extract_text_with_paddleocr(path: str) -> str:
    path = Path(path)
    suffix = path.suffix.lower()

    if not path.exists():
        sys.exit(f"[error] File not found: {path}")

    if suffix == ".pdf":
        print(f"[ocr] Converting PDF {path.name} to images...")
        pages = convert_from_path(str(path), dpi=200, fmt="jpeg")
    elif suffix in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        pages = [Image.open(str(path))]
    else:
        sys.exit(f"[error] Unsupported file type: {suffix}")

    extracted_text = []

    for i, img in enumerate(pages):
        print(f"[ocr] Processing {path.name} - Page {i+1}...")

        # Convert PIL Image to OpenCV format (numpy array) for PaddleOCR
        img_array = np.array(img.convert("RGB"))
        # PaddleOCR expects BGR format
        img_array = img_array[:, :, ::-1].copy()

        result = ocr.ocr(img_array, cls=True)

        page_text = []
        if result and result[0]:
            for line in result[0]:
                # line[1][0] contains the recognized text
                text = line[1][0]
                page_text.append(text)

        extracted_text.append("\n".join(page_text))
        print(f"[ocr] Page {i+1} text extracted.")

    return "\n\n--- PAGE BREAK ---\n\n".join(extracted_text)


# ── Step 2: GPT-4o Text Extraction ────────────────────────────────────────────

EXTRACTION_PROMPT = (
    """
You are a trade finance specialist. Extract the following fields from the provided OCR text of a Letter of Credit and related documents.

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
- For adjusted_base_price: calculate as (base_price * actual_gcv_arb) / 3400, rounded to 2 decimal places.
- For total_shipment_value: calculate as adjusted_base_price * total_quantity_shipped, rounded to 2 decimal places.
- Do not invent values not present in the document text.
- For coal specifications, extract both the TYPICAL value and REJECTION limit for each parameter.
- For price_adjustment_clause: find the paragraph describing the price adjustment formula for GCV (ARB). Extract it exactly word for word.
- For specifications_disclaimer: find the paragraph starting with "THE SPECIFICATIONS LISTED ABOVE ARE TYPICAL SPECIFICATIONS AS CONTRACTUALLY AGREED..." and extract it exactly word for word.
- For cargo_value_clause: find the paragraph starting with "THE CARGO VALUE OF 100PCT..." specifying quantity and quality determined at loading port. Extract exactly word for word.
- For vessel details, extract from the Bill of Lading text (if provided).
- For total_shipment_value_words: convert total_shipment_value to English words in USD format, e.g. "USD TWO MILLION SEVEN THOUSAND NINETY-FIVE ONLY".
- For actual results, extract from the Certificate of Sampling and Analysis text. Return each as the numeric value with its unit exactly as shown in the document.

Here is the extracted OCR Text to analyze:
"""
)


def extract_lc_fields_from_text(ocr_text: str) -> dict:
    print("[gpt] Sending OCR text to LLM for JSON extraction...")

    response = client.chat.completions.create(
        model="gpt-4o",  # You can now use gpt-4o, gpt-4-turbo, or even gpt-3.5-turbo
        messages=[
            {"role": "system", "content": "You are a specialized data extraction API."},
            {"role": "user", "content": EXTRACTION_PROMPT + "\n\n" + ocr_text},
        ],
        max_tokens=2500,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[error] LLM returned invalid JSON:\n{raw}")
        sys.exit(str(e))

    print("[gpt] Extraction complete.")
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

    # 1. Extract text via PaddleOCR
    full_text_payload = ""

    print("[info] Extracting Letter of Credit text...")
    full_text_payload += extract_text_with_paddleocr(args.lc) + "\n\n"

    if args.bl:
        for bl_file in args.bl:
            print(f"[info] Extracting Bill of Lading: {bl_file}")
            full_text_payload += extract_text_with_paddleocr(bl_file) + "\n\n"

    if args.coa:
        for coa_file in args.coa:
            print(f"[info] Extracting Certificate of Analysis: {coa_file}")
            full_text_payload += extract_text_with_paddleocr(coa_file) + "\n\n"

    # 2. Extract fields using text-based LLM
    data = extract_lc_fields_from_text(full_text_payload)

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
