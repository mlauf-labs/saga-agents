"""Langfuse OTel tracing integration with a no-op fallback.

Call :func:`configure_tracing` once at startup.  It is idempotent — repeated
calls are silently ignored after the first successful configuration.
"""

from __future__ import annotations

import base64
import os

import logfire

from saga_agents.config.models import LangfuseSettings
from saga_agents.core.logging import get_logger

_log = get_logger(__name__)

_configured = False


def configure_tracing(cfg: LangfuseSettings) -> bool:
    """Configure Logfire/OTel to export spans to Langfuse.

    Returns ``True`` when tracing is successfully configured, ``False`` when it
    is skipped (missing keys) or fails (logs a warning, never raises).

    The function is **idempotent**: once it has returned ``True`` it becomes a
    no-op on subsequent calls.

    Args:
        cfg: :class:`LangfuseSettings` carrying the public/secret key pair and
             optional host override.

    Returns:
        ``True`` if tracing was enabled, ``False`` otherwise.
    """
    global _configured

    if not (cfg.public_key and cfg.secret_key):
        return False

    if _configured:
        return True

    try:
        credentials = base64.b64encode(f"{cfg.public_key}:{cfg.secret_key}".encode()).decode()
        endpoint = f"{cfg.host.rstrip('/')}/api/public/otel"
        headers = f"Authorization=Basic {credentials}"

        logfire.configure(send_to_logfire=False, service_name="saga-agents")
        logfire.instrument_pydantic_ai()

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = headers
        _configured = True
        return True

    except Exception as exc:  # noqa: BLE001
        _log.warning("tracing_configure_failed", error=str(exc))
        return False
