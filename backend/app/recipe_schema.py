"""Provider-neutral JSON Schema for generated recipe drafts."""

RECIPE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "preparation_time_minutes": {"type": ["integer", "null"]},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "string"},
                },
                "required": ["name", "quantity"],
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "duration_minutes": {"type": ["integer", "null"]},
                },
                "required": ["instruction", "duration_minutes"],
            },
        },
        "missing_products": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "preparation_time_minutes", "ingredients", "steps", "missing_products"],
}
