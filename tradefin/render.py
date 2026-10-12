"""Invoice calculations and Word template rendering."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .errors import TemplateError
from .models import InvoiceData


def _amount(value: str) -> Decimal | None:
    cleaned = re.sub(r"[^0-9.]", "", value.replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def complete_calculations(data: InvoiceData) -> InvoiceData:
    """Fill calculated fields only when source values are present."""
    fields = data.model_dump()
    base = _amount(data.base_unit_price_numeric)
    gcv = _amount(data.actual_gcv_arb_result)
    quantity = _amount(data.total_quantity_shipped)
    if base is not None and gcv is not None and not data.adjusted_base_price:
        fields["adjusted_base_price"] = str(
            (base * gcv / Decimal("3400")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    adjusted = _amount(fields["adjusted_base_price"])
    if adjusted is not None and quantity is not None and not data.total_shipment_value:
        fields["total_shipment_value"] = str(
            (adjusted * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    if not fields["actual_gcv"]:
        fields["actual_gcv"] = data.actual_gcv_arb_result
    if adjusted is not None and not data.adjusted_price:
        fields["adjusted_price"] = f"USD {adjusted:.2f}"
    if fields["total_shipment_value"] and not data.total_shipment_value_words:
        try:
            from num2words import num2words

            total = _amount(fields["total_shipment_value"])
            if total is not None:
                dollars = int(total)
                cents = int((total - dollars) * 100)
                words = num2words(dollars).upper().replace("-", " ")
                suffix = f" AND {cents:02d}/100" if cents else ""
                fields["total_shipment_value_words"] = f"USD {words}{suffix} ONLY"
        except ImportError:
            pass
    return InvoiceData.model_validate(fields)


def render_invoice(data: InvoiceData, template_path: Path, output_path: Path) -> None:
    """Render validated fields into the configured docxtpl template."""
    if not template_path.is_file():
        raise TemplateError(f"Invoice template not found: {template_path}")
    try:
        from docxtpl import DocxTemplate

        output_path.parent.mkdir(parents=True, exist_ok=True)
        document = DocxTemplate(str(template_path))
        document.render(data.model_dump())
        document.save(str(output_path))
    except Exception as exc:
        raise TemplateError(f"Could not render invoice: {exc}") from exc
