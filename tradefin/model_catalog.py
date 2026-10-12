"""OpenAI model choices available in the desktop and command-line interfaces."""

MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("GPT-6.1 Sol (recommended)", "gpt-6.1-sol"),
    ("GPT-6 Astra", "gpt-6-astra"),
    ("GPT-6 Sol", "gpt-6-sol"),
    ("GPT-6 Luna", "gpt-6-luna"),
    ("GPT-5.6 Sol", "gpt-5.6-sol"),
    ("GPT-5.6 Terra", "gpt-5.6-terra"),
    ("GPT-5.6 Luna", "gpt-5.6-luna"),
    ("GPT-4o (legacy)", "gpt-4o"),
)

DEFAULT_MODEL = "gpt-6.1-sol"
MODEL_ID_BY_LABEL = {label: model_id for label, model_id in MODEL_OPTIONS}
MODEL_LABEL_BY_ID = {model_id: label for label, model_id in MODEL_OPTIONS}
SUPPORTED_MODELS = tuple(MODEL_LABEL_BY_ID)
REASONING_MODELS = frozenset(model_id for _, model_id in MODEL_OPTIONS if model_id != "gpt-4o")
