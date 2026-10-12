# Tradefin

Tradefin extracts commercial invoice fields from a Letter of Credit and optional Bills of Lading and Certificates of Analysis, then fills the Word template at `inputs/template.docx.docx`.

## Run

Set `OPENAI_API_KEY` in `.env`, then run the vision pipeline:

```powershell
python -m tradefin --lc inputs/saiilc.pdf --bl inputs/bl.pdf --coa inputs/coa.pdf --out outputs
```

To use the desktop interface instead of the command line:

```powershell
python -m tradefin.gui
```

Choose the LC, optional supporting documents, template, output folder, and OCR backend in the window. The extracted fields and saved invoice path appear when processing finishes.

To run local PaddleOCR before the same LLM extraction step:

```powershell
uv sync --extra paddle
python -m tradefin --ocr-backend paddle --lc inputs/saiilc.pdf --bl inputs/bl.pdf --coa inputs/coa.pdf
```

## Use Tradefin from Codex with MCP

Tradefin includes a local stdio MCP server with three bounded tools: `get_evaluation_status`, `extract_invoice`, and `score_extraction_predictions`. Codex can edit this checkout through its normal workspace access; these MCP tools give it direct access to Tradefin's extraction and scoring workflows.

Install the MCP extra and register the server from PowerShell in the repository root:

```powershell
uv sync --extra mcp
tools\register_codex_mcp.ps1
codex mcp list
```

Restart the Codex session after registration. To evaluate a code change, ask Codex to check the eval status, re-extract every labeled example using a `sample_id` matching its golden JSON filename, and then call the scorer. Each extraction uses the selected OpenAI API model, so a full set requires one model call per example. The scorer uses only manually verified files in `eval/goldens/` and same-named JSON files in `eval/predictions/`. Add verified labels before relying on an accuracy score; model outputs must never be copied into the gold set as truth. Extraction accepts paths inside this repository, writes a timestamped invoice under `outputs/`, and saves the JSON prediction under `eval/predictions/` for scoring. Repeating a sample ID refreshes that sample's prediction. Generated eval predictions are ignored by Git.

Each generated invoice filename includes the LC number and a local timestamp. If two runs start in the same second, a numbered suffix keeps both files.

The desktop app and CLI offer GPT-6.1 Sol (default), GPT-6 Astra/Sol/Luna, GPT-5.6 Sol/Terra/Luna, and GPT-4o (legacy). For example, select a model in the GUI or pass its API ID on the command line:

```powershell
python -m tradefin --model gpt-6-luna --lc inputs/saiilc.pdf
python -m tradefin --model gpt-5.6-sol --lc inputs/saiilc.pdf
```

GPT-5.6 and GPT-6 models receive reasoning-compatible request settings automatically. API access to individual models depends on the OpenAI project tied to `OPENAI_API_KEY`.

The vision backend needs `pdf2image`'s Poppler executable available on PATH for PDF input. PaddleOCR also downloads its OCR models on first use. `main.py`, `paddlemain.py`, `hybridmain.py`, and `ma.py` remain as small compatibility launchers; `paddlemain.py` now uses the shared LLM extraction path instead of its former regex-only extraction. New commands should use `python -m tradefin`.

## Structure

- `tradefin/ocr.py` — vision and local PaddleOCR readers
- `tradefin/extraction.py` — shared extraction prompt and OpenAI response validation
- `tradefin/models.py` — typed Pydantic invoice schema
- `tradefin/render.py` — calculated fields and Word template rendering
- `tradefin/pipeline.py` — common end-to-end workflow
- `tradefin/evaluation.py` — field-level exact-match scoring
- `tradefin/mcp_server.py` — local Codex tools for extraction and evaluation

## Accuracy report

**Field-level accuracy: not measured (0 gold-labeled documents).** The repository contains source documents and generated invoices, but no independently verified field labels or documented pairing between them. Treating the generated invoices as gold would measure agreement with prior outputs, not extraction accuracy. There are 16 PDFs under `inputs/` (19 total including the root-level PDF and separate `Amma ocr/` archive); their presence alone does not make them a labeled evaluation set.

Add at least 20 manually checked JSON labels under `eval/goldens/`, one per source document, with the same filenames used for predictions. Include the fields being scored and use `""` when a field is absent. Then run each document through Tradefin with `--json-out` and score the matching outputs:

```powershell
python -m tradefin --lc inputs/saiilc.pdf --json-out eval/predictions/saiilc.json
python -m tradefin.evaluation --gold eval/goldens --predictions eval/predictions
```

The evaluator reports accuracy per field and overall. It compares normalized exact strings (case-insensitive, whitespace-collapsed), includes blank labels in the denominator, and counts a missing prediction as incorrect unless the gold value is blank. The report is only representative of the selected documents and labeled fields.

## Dependencies

Install the project dependencies with `uv sync`. For local OCR, install the optional PaddleOCR dependencies with `uv sync --extra paddle`. The PaddleOCR engine may require platform-specific setup and model downloads.
