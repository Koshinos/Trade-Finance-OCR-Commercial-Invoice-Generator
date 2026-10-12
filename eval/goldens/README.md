# Gold labels

Add one manually verified JSON object per source document. Keep each filename stable so the evaluator can match it to a prediction with the same filename. Use the filename stem as the MCP `sample_id` when extracting. Include every field being scored; an empty string means the field is absent from the source.

Do not create labels from the model's own output. Review each value against the source document and record ambiguous or unreadable fields as blank with a note outside the JSON.
