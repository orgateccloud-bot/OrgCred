"""
Logging estruturado com mascaramento de PII (LGPD).

Estruturado via structlog; mascaramento determinístico para CPF/CNPJ.
"""

import re
from typing import Any

import structlog


def mask_pii(text: str) -> str:
    """Mascara CPF e CNPJ em texto."""
    # CPF: XXX.XXX.XXX-XX
    text = re.sub(r"\d{3}\.\d{3}\.\d{3}-\d{2}", "***.***.***-**", text)
    # CNPJ: XX.XXX.XXX/XXXX-XX
    text = re.sub(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", "**.***.***/****-**", text)
    # Números soltos (heurística: 11 ou 14 dígitos sem formatação)
    text = re.sub(r"\b\d{11}\b", r"***\*\***\*\***", text)  # CPF
    text = re.sub(r"\b\d{14}\b", r"**\*\***\*\***\*\***", text)  # CNPJ
    return text


class MaskingProcessor:
    """Processador structlog que mascara PII em valores de log."""

    def __call__(self, logger: Any, name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        # Mascara 'message' e 'exc_info'
        if "event" in event_dict:
            event_dict["event"] = mask_pii(str(event_dict["event"]))

        # Mascara qualquer valor string
        for key in list(event_dict.keys()):
            if isinstance(event_dict[key], str):
                event_dict[key] = mask_pii(event_dict[key])

        return event_dict


def configure_logging() -> None:
    """Configura logging estruturado com structlog."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            MaskingProcessor(),  # type: ignore[list-item]  # PII masking
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Obtém logger estruturado."""
    return structlog.get_logger(name)
