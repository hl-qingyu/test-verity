"""Claim a synthetic worker item using the production queue and a simulated reservation."""

from unittest.mock import patch
from uuid import uuid4

from app import chat_worker
from app.modules.ai import scheduling


def claim(db, model):
    options = next(
        options for registered, _, options in chat_worker._registry() if registered is model
    )
    with (
        patch.object(
            scheduling,
            "analysis_configuration",
            return_value=({"base_url": "https://example.invalid"}, "synthetic"),
        ),
        patch.object(scheduling.reservations, "lock_budget"),
        patch.object(scheduling.reservations, "reserve", return_value=str(uuid4())),
    ):
        item = scheduling.claim(db, model, str(uuid4()), **options)
    return item[0] if item else None
