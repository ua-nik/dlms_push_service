"""
Реєстр шаблонів об'єктів CompactData (COSEM Клас 62, OBIS 0.0.65.0.0.255).
Дозволяє динамічно визначати структуру полів за template_id без хардкоду в декодері.
"""

import struct
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from .obis_registry import OBISRegistry


@dataclass(frozen=True)
class CaptureField:
    obis: str
    dtype: str = "uint32"  # "dynamic_string", "uint32", "uint16", "int32", "uint64"
    size: Optional[int] = None
    unit: Optional[str] = None
    scaler: int = 0


def resolve_meter_model(serial_or_title: Optional[str], fallback: str = "NIK") -> str:
    """
    Визначає модель/серію лічильника динамічно за серійним номером або system_title.
    Наприклад: '2308213058052025' -> 'NIK 2308'
              '210412345678' -> 'NIK 2104'
              '210800054321' -> 'NIK 2108'
    """
    if not serial_or_title:
        return fallback
    clean = str(serial_or_title).strip()
    # Якщо починається з 4 цифр (наприклад, 2308...)
    if len(clean) >= 4 and clean[:4].isdigit():
        return f"NIK {clean[:4]}"
    if clean.upper().startswith("NIK"):
        parts = clean.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return f"NIK {parts[1]}"
        return clean
    return fallback


@dataclass
class CompactDataTemplate:
    template_id: int
    name: str
    model_name: str = "NIK"
    fields: List[CaptureField] = None

    def decode_buffer(self, buffer: bytes) -> Tuple[List[Dict[str, Any]], Optional[str], str]:
        """
        Універсально декодує сирий буфер CompactData за схемою полів шаблону.
        Повертає (parameters, serial_number, model_name).
        """
        if not buffer or buffer[0] != self.template_id:
            raise ValueError("CompactData template identifier mismatch")
        offset = 1
        parameters = []
        serial_number = None
        formats = {"uint32": (4, ">I", "double-long-unsigned"),
                   "int32": (4, ">i", "long"), "uint16": (2, ">H", "long-unsigned"),
                   "uint64": (8, ">Q", "long64-unsigned")}
        for field in self.fields or []:
            if field.dtype in ("dynamic_string", "visible-string", "visible_string"):
                if offset >= len(buffer):
                    raise ValueError("Truncated CompactData string length")
                length = buffer[offset]
                offset += 1
                if offset + length > len(buffer):
                    raise ValueError("Truncated CompactData string value")
                value = buffer[offset:offset + length].decode("ascii", errors="strict").strip()
                offset += length
                if not serial_number:
                    serial_number = value
                dtype = "visible-string"
            else:
                if field.dtype not in formats:
                    raise ValueError("Unsupported CompactData field type")
                size, fmt, dtype = formats[field.dtype]
                if offset + size > len(buffer):
                    raise ValueError("Truncated CompactData numeric value")
                value = struct.unpack(fmt, buffer[offset:offset + size])[0]
                offset += size
            parameters.append(OBISRegistry.format_parameter(field.obis, value,
                unit=field.unit, scaler=field.scaler, dtype=dtype))
        if offset != len(buffer):
            raise ValueError("Unexpected trailing CompactData bytes")
        if not parameters:
            raise ValueError("Empty CompactData template")
        model = resolve_meter_model(serial_number, fallback=self.model_name)
        return parameters, serial_number, model


# Вбудовані відомі шаблони приладів
_TEMPLATES: Dict[int, CompactDataTemplate] = {
    # Шаблон 11 (0x0B): 3-фазний лічильник НІК, CompactData #0
    11: CompactDataTemplate(
        template_id=11,
        name="NIK 3-Phase Periodic Push",
        model_name="NIK",
        fields=[
            CaptureField(obis="0.0.96.1.4.255", dtype="dynamic_string"),  # Серійний номер
            CaptureField(obis="1.0.1.8.0.255", dtype="uint32", unit="Wh"),  # A+
            CaptureField(obis="1.0.2.8.0.255", dtype="uint32", unit="Wh"),  # A-
            CaptureField(obis="1.0.31.7.0.255", dtype="uint32", unit="A"),  # I1
            CaptureField(obis="1.0.32.7.0.255", dtype="uint32", unit="V"),  # U1
            CaptureField(obis="1.0.51.7.0.255", dtype="uint32", unit="A"),  # I2
            CaptureField(obis="1.0.52.7.0.255", dtype="uint32", unit="V"),  # U2
            CaptureField(obis="1.0.71.7.0.255", dtype="uint32", unit="A"),  # I3
            CaptureField(obis="1.0.72.7.0.255", dtype="uint32", unit="V"),  # U3
            CaptureField(obis="0.0.97.98.0.255", dtype="uint32"),           # Status Word
            CaptureField(obis="0.0.97.98.1.255", dtype="uint32"),           # Diagnostic Word
        ]
    )
}


class CompactDataTemplateRegistry:
    """
    Реєстр шаблонів CompactData. Дозволяє автоматично знаходити опис полів за template_id.
    """

    @classmethod
    def get(cls, template_id: int) -> Optional[CompactDataTemplate]:
        return _TEMPLATES.get(template_id)

    @classmethod
    def register(cls, template: CompactDataTemplate) -> None:
        """Дозволяє динамічно реєструвати нові шаблони (з конфігурації або БД)."""
        _TEMPLATES[template.template_id] = template

    @classmethod
    def all_templates(cls) -> Dict[int, CompactDataTemplate]:
        return dict(_TEMPLATES)
