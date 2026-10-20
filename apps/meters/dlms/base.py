from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class DecodedDLMSMessage:
    """
    Результат декодування вхідного повідомлення DLMS Push.
    """
    system_title: str                      # HEX рядок ідентифікатора приладу (8 байт = 16 символів)
    invocation_counter: Optional[int] = None # Лічильник кадрів DLMS (захист від replay attacks)
    event_at: Optional[datetime] = None    # Часова мітка події, передана приладом
    parsed_payload: Dict[str, Any] = field(default_factory=dict) # Структуровані параметри (JSONB)
    is_valid: bool = True                  # Прапорець успішності перевірки та дешифрування
    error_message: Optional[str] = None    # Опис помилки в разі невдачі
    raw_unprotected_hex: Optional[str] = None # Розшифрований APDU в HEX (для діагностики)
    serial_number: Optional[str] = None    # Серійний номер приладу
    model_name: Optional[str] = None       # Модель/серія приладу (наприклад, NIK 2308, NIK 2104 тощо)


class KeyResolver:
    """
    Визначає ключі шифрування та автентифікації для приладу NIK.
    Спочатку перевіряє індивідуальні налаштування приладу за system_title,
    потім використовує глобальні ключі з конфігурації.
    """

    @staticmethod
    def _to_bytes_key(key_val: Any) -> bytes:
        if isinstance(key_val, bytes):
            return key_val
        if isinstance(key_val, str):
            key_str = key_val.strip()
            # Якщо передано hex-рядок довжиною 32 символи (16 байт)
            if len(key_str) == 32:
                try:
                    return bytes.fromhex(key_str)
                except ValueError:
                    pass
            # Інакше кодуємо як ASCII / utf-8
            return key_str.encode("utf-8")
        raise ValueError(f"Неприпустимий тип ключа: {type(key_val)}")

    @classmethod
    def get_keys_for_meter(cls, system_title_hex: str) -> Tuple[bytes, bytes]:
        """
        Повертає кортеж (block_cipher_key, auth_key) для заданого system_title.
        """
        norm_title = system_title_hex.upper().strip()

        # 1. Пошук в індивідуальній мапі приладів
        meter_keys_map = getattr(settings, "DLMS_METER_KEYS_MAP", {})
        if norm_title in meter_keys_map:
            meter_conf = meter_keys_map[norm_title]
            global_key = cls._to_bytes_key(meter_conf.get("global_key"))
            auth_key = cls._to_bytes_key(meter_conf.get("auth_key", meter_conf.get("global_key")))
            return global_key, auth_key

        # 2. Глобальні ключі за замовчуванням
        default_global = getattr(settings, "DLMS_DEFAULT_GLOBAL_KEY", "MYDUMMYGLOBALKEY")
        default_auth = getattr(settings, "DLMS_DEFAULT_AUTH_KEY", "MYDUMMYGLOBALKEY")

        return cls._to_bytes_key(default_global), cls._to_bytes_key(default_auth)


class DLMSDecoderInterface(ABC):
    """
    Базовий інтерфейс для декодерів DLMS Push повідомлень.
    Дозволяє повністю ізолювати протокол DLMS від транспортного рівня та моделей БД.
    """

    @abstractmethod
    def decode(self, raw_data: bytes, source_addr: Optional[Tuple[str, int]] = None) -> DecodedDLMSMessage:
        """
        Приймає «сирі» байти UDP пакета та адресу джерела (IP, port).
        Повертає екземпляр DecodedDLMSMessage.
        """
        pass
