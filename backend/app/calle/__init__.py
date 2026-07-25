"""THE CALL-E INTEGRATION SEAM.

Every byte of CALL-E traffic in this codebase goes through this package:
client.py for REST calls via the calle-ai SDK, webhook.py for terminal
webhook verification. Nothing elsewhere talks to CALL-E.
"""

from app.calle.client import CalleService
from app.calle.webhook import WebhookVerificationError, verify_and_parse_webhook

__all__ = ["CalleService", "WebhookVerificationError", "verify_and_parse_webhook"]
