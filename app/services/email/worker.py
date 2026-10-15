"""Periodic retries for unsent inspector credential emails."""

import asyncio
import logging

from app.services.email.delivery import process_unsent_verified_inspector_emails

logger = logging.getLogger(__name__)
EMAIL_RETRY_INTERVAL_SECONDS = 15 * 60


async def run_email_delivery_worker() -> None:
    """Process unsent emails at startup, then retry every 15 minutes."""
    while True:
        try:
            await asyncio.to_thread(process_unsent_verified_inspector_emails)
        except Exception:
            logger.exception("Inspector credential email retry pass failed.")
        await asyncio.sleep(EMAIL_RETRY_INTERVAL_SECONDS)
