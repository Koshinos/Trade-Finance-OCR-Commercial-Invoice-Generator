"""Exceptions raised by the Tradefin pipeline."""


class TradefinError(Exception):
    """Base class for expected application errors."""


class DocumentError(TradefinError):
    """A source document could not be read or converted."""


class ExtractionError(TradefinError):
    """Structured data could not be extracted from the source documents."""


class TemplateError(TradefinError):
    """The invoice template could not be rendered."""
