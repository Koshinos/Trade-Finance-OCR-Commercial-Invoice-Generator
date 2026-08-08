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

python main.py --lc inputs/saiilc.pdf --bl inputs/bl.pdf --coa inputs/coa.pdf




python paddlemain.py --lc sample_docs/lc_document.pdf --out custom_outputs/

python paddlemain.py --lc inputs/saiilc.pdf --bl inputs/bl.pdf --coa inputs/coa.pdf

python hybridmain.py --lc inputs/saiilc.pdf --bl inputs/bl.pdf --coa inputs/coa.pdf