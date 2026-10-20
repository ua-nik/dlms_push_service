"""
Пакет DLMS протоколу: декодери, реєстр OBIS-кодів та шаблонів CompactData.
"""

from .base import DLMSDecoderInterface, DecodedDLMSMessage, KeyResolver
from .decoder import RealDLMSDecoder
from .obis_registry import OBISRegistry, OBISInfo
from .template_registry import (
    CompactDataTemplateRegistry,
    CompactDataTemplate,
    CaptureField,
    resolve_meter_model,
)

__all__ = [
    "DLMSDecoderInterface",
    "DecodedDLMSMessage",
    "KeyResolver",
    "RealDLMSDecoder",
    "OBISRegistry",
    "OBISInfo",
    "CompactDataTemplateRegistry",
    "CompactDataTemplate",
    "CaptureField",
    "resolve_meter_model",
]
