"""LLM extraction and validation against the invoice schema."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from openai import OpenAI

from .errors import ExtractionError
from .model_catalog import DEFAULT_MODEL, REASONING_MODELS
from .models import InvoiceData
from .ocr import DocumentContent


def _prompt() -> str:
    schema = {field: "" for field in InvoiceData.field_names() if field != "actual_gcv"}
    return f"""You extract commercial invoice fields from Letters of Credit and supporting documents.
Return one JSON object with exactly these keys and string values:
{json.dumps(schema, indent=2)}

Rules:
- Use an empty string when a value is absent. Never guess or infer a document fact.
- If invoice_date is absent, use today's date: {date.today():%d %B %Y}.
- Extract documentary_credit_number and documentary_credit_date from the Letter of Credit itself
  (LC number/reference and date of issue). Do not substitute the invoice date, expiry date,
  latest shipment date, or a date from a supporting document.
- Extract contract_number when labeled Contract No., Contract Number, Sales Contract, or
  Purchase Contract; keep it distinct from the LC number and invoice number.
- Extract port_of_discharge from the LC's port/place of discharge field (for example field 44F).
  Do not confuse it with port_of_loading (for example field 44E); preserve the stated location.
- Read vessel name, B/L number, B/L date, and IMO from the Bill of Lading when provided.
- Read actual analysis results from the Certificate of Analysis when provided.
- Preserve units and wording shown in source documents. Copy the price, disclaimer, and cargo clauses exactly.
- Extract typical and rejection limits separately for each coal specification.
- Calculate adjusted_base_price = base_unit_price_numeric * actual_gcv_arb_result / 3400,
  and total_shipment_value = adjusted_base_price * total_quantity_shipped, rounded to 2 decimals.
- Express total_shipment_value_words in uppercase USD words ending in ONLY.
"""


class LLMExtractor:
    """Extract and validate fields from page images or OCR text."""

    def __init__(self, client: OpenAI, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self._model = model

    def extract(self, documents: list[DocumentContent]) -> InvoiceData:
        if not documents:
            raise ExtractionError("No document content was provided.")
        content: list[dict[str, Any]] = []
        image_mode = any(document.images for document in documents)
        if image_mode:
            for document in documents:
                content.append({"type": "text", "text": f"Source document: {document.path.name}"})
                for image in document.images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "high"},
                    })
        else:
            text = "\n\n".join(
                f"--- SOURCE: {document.path.name} ---\n{document.text}"
                for document in documents
            )
            content.append({"type": "text", "text": f"{_prompt()}\n\n{text}"})
        if image_mode:
            content.append({"type": "text", "text": _prompt()})

        try:
            request: dict[str, Any] = {
                "model": self._model,
                "messages": [{"role": "user", "content": content}],
                "max_completion_tokens": 3000,
            }
            if self._model in REASONING_MODELS:
                request["reasoning_effort"] = "low"
            else:
                request["temperature"] = 0
            response = self._client.chat.completions.create(**request)
            raw = response.choices[0].message.content or ""
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("The model response must be a JSON object.")
            return InvoiceData.model_validate(payload)
        except Exception as exc:
            raise ExtractionError(f"Field extraction failed: {exc}") from exc
