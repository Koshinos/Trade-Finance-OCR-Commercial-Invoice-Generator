import argparse
import os
import os
import re
import sys
from pathlib import Path
from datetime import date
import numpy as np

# ── Dependencies check ────────────────────────────────────────────────────────


def require(pkg, install_name=None):
    try:
        __import__(pkg)
    except ImportError:
        name = install_name or pkg
        print(f"[setup] Installing {name}...")
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", name, "-q"])


require("pdf2image")
require("PIL", "pillow")
require("docxtpl")
require("paddleocr")
require("num2words")
# You may also need paddlepaddle: pip install paddlepaddle

from pdf2image import convert_from_path
from PIL import Image
from docxtpl import DocxTemplate
from paddleocr import PaddleOCR
from num2words import num2words

# ── Config ────────────────────────────────────────────────────────────────────

TEMPLATE_PATH = "inputs/template.docx.docx"

print("[setup] Initializing PaddleOCR...")
# show_log=False keeps the console clean from Paddle's debug text
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
                text = line[1][0]
                page_text.append(text)

        extracted_text.append("\n".join(page_text))

    return "\n\n--- PAGE BREAK ---\n\n".join(extracted_text)


# ── Step 2: Rule-Based Extraction (RegEx) ─────────────────────────────────────


def extract_lc_fields_with_regex(ocr_text: str) -> dict:
    print("[regex] Parsing text for required fields...")

    # Helper to safely search and return group 1
    def extract(pattern, text, default="", flags=re.IGNORECASE):
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else default

    # Initialize data dictionary
    data = {
        "invoice_date": date.today().strftime("%d %B %Y"),  # Default to today
        "beneficiary_name_and_address": "",
        "applicant_name_and_address": "",
        "invoice_number": "",
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
        "price_adjustment_clause": "",
    }

    # ── Standard Field RegEx Patterns ──
    # Note: You will need to adjust these patterns based on your exact document formatting.

    data["invoice_number"] = extract(
        r"Invoice\s*(?:No|Number)[\s:]*([A-Z0-9\-\/]+)", ocr_text
    )
    data["vessel_name"] = extract(
        r"(?:MV|M/V|Vessel)[\s:]*([A-Za-z\s]+)(?:Voyage|IMO|\n)", ocr_text
    )
    data["vessel_imo"] = extract(r"IMO\s*(?:No|Number)?[\s:]*(\d{7})", ocr_text)
    data["bill_of_lading_number"] = extract(
        r"B/L\s*(?:No|Number)[\s:]*([A-Z0-9\-\/]+)", ocr_text
    )
    data["contract_number"] = extract(
        r"Contract\s*(?:No|Number)[\s:]*([A-Z0-9\-\/]+)", ocr_text
    )
    data["documentary_credit_number"] = extract(
        r"(?:Documentary Credit|L/C|LC)\s*(?:No|Number)[\s:]*([A-Z0-9\-\/]+)", ocr_text
    )
    data["country_of_origin"] = extract(r"Origin[\s:]*([A-Za-z\s]+)(?:\n|$)", ocr_text)
    data["port_of_loading"] = extract(
        r"Port of Loading[\s:]*([A-Za-z\s,]+)(?:\n|$)", ocr_text
    )

    # Financials / Quantities
    data["base_unit_price_numeric"] = extract(
        r"(?:Price|Unit Price)[\s:]*(?:USD|\$)?\s*([\d,]+\.?\d*)", ocr_text
    )
    data["total_quantity_shipped"] = extract(
        r"(?:Quantity|Weight)[\s:]*([\d,]+\.?\d*)\s*(?:MT|Metric Tons)", ocr_text
    )

    # Actual COA Results (Extracting number + unit, e.g., "16.48 PCT" or "3,412 KCAL/KG")
    data["actual_tm_result"] = extract(
        r"Total Moisture\s*\(ARB\)[\s:]*([\d,]+\.?\d*\s*(?:PCT|%))", ocr_text
    )
    data["actual_ash_result"] = extract(
        r"Ash\s*\(ADB\)[\s:]*([\d,]+\.?\d*\s*(?:PCT|%))", ocr_text
    )
    data["actual_gcv_arb_result"] = extract(
        r"Gross Calorific Value\s*\(ARB\)[\s:]*([\d,]+\.?\d*\s*(?:KCAL/KG))", ocr_text
    )
    data["actual_sulphur_result"] = extract(
        r"Total Sulphur\s*\(ADB\)[\s:]*([\d,]+\.?\d*\s*(?:PCT|%))", ocr_text
    )

    # Specifications (Looking for Typical / Rejection patterns in text blocks)
    # This requires looking for rows like "Total Moisture | 15% | > 18%"
    data["tm_typical"] = extract(
        r"Total Moisture.*?([\d,]+\.?\d*\s*(?:PCT|%)).*?(?:>|<|Max|Min)", ocr_text
    )
    data["tm_rejection"] = extract(
        r"Total Moisture.*?(?:>|<|Max|Min)\s*([\d,]+\.?\d*\s*(?:PCT|%))", ocr_text
    )
    data["gcv_typical"] = extract(
        r"Gross Calorific Value.*?([\d,]+\.?\d*\s*(?:KCAL/KG)).*?(?:>|<|Max|Min)",
        ocr_text,
    )
    data["gcv_rejection"] = extract(
        r"Gross Calorific Value.*?(?:>|<|Max|Min)\s*([\d,]+\.?\d*\s*(?:KCAL/KG))",
        ocr_text,
    )

    # Multi-line Clauses (Using re.DOTALL to capture paragraphs)
    data["specifications_disclaimer"] = extract(
        r"(THE SPECIFICATIONS LISTED ABOVE ARE TYPICAL SPECIFICATIONS AS CONTRACTUALLY AGREED.*?)(?:\n\n|\Z)",
        ocr_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    data["cargo_value_clause"] = extract(
        r"(THE CARGO VALUE OF 100PCT.*?)(?:\n\n|\Z)",
        ocr_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    data["price_adjustment_clause"] = extract(
        r"(Price Adjustment:.*?)(?:\n\n|\Z)", ocr_text, flags=re.IGNORECASE | re.DOTALL
    )

    print("[regex] Extraction complete.")
    return data


# ── Step 3: Calculation & Fill CI template ────────────────────────────────────


def build_ci_docx(data: dict, output_path: str):
    print("[docx] Calculating adjustments and filling CI template...")

    if not os.path.exists(TEMPLATE_PATH):
        sys.exit(f"[error] Template not found at: {TEMPLATE_PATH}")

    # Clean numbers from regex strings to perform math
    def clean_num(val, default=0.0):
        try:
            # Strip out commas and units to convert to float
            cleaned = re.sub(r"[^\d.]", "", str(val))
            return float(cleaned) if cleaned else default
        except (ValueError, TypeError):
            return default

    base_price = clean_num(data.get("base_unit_price_numeric"))
    actual_gcv = clean_num(data.get("actual_gcv_arb_result"))
    qty = clean_num(data.get("total_quantity_shipped"))

    # Calculate Adjusted Base Price
    if base_price and actual_gcv and not data.get("adjusted_base_price"):
        data["adjusted_base_price"] = str(round((base_price * actual_gcv) / 3400, 2))

    adj_price = clean_num(data.get("adjusted_base_price"))

    # Calculate Total Shipment Value
    if adj_price and qty and not data.get("total_shipment_value"):
        total_val = round(adj_price * qty, 2)
        data["total_shipment_value"] = str(total_val)

        # Convert total value to English Words (e.g., USD TWO MILLION...)
        cents = int(round(total_val * 100)) % 100
        dollars = int(total_val)
        words = num2words(dollars).upper().replace("-", " ")
        cents_words = f" AND {cents}/100" if cents > 0 else ""
        data["total_shipment_value_words"] = f"USD {words}{cents_words} ONLY"

    # Formatting string outputs
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
        "--coa", required=False, nargs="+", help="Certificate of Analysis PDFs"
    )
    parser.add_argument("--bl", required=False, nargs="+", help="Bill of Lading PDFs")

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

    # 2. Extract fields using Local Regex
    data = extract_lc_fields_with_regex(full_text_payload)

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
