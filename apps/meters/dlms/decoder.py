import struct
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

from django.conf import settings
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .base import DLMSDecoderInterface, DecodedDLMSMessage, KeyResolver
from .obis_registry import OBISRegistry
from .template_registry import CompactDataTemplateRegistry, resolve_meter_model

logger = logging.getLogger(__name__)

WRAPPER_HEADER_LEN = 8
TAG_GENERAL_GLOBAL_CIPHER = 0xDB
TAG_DATA_NOTIFICATION = 0x0F
GCM_TAG_LENGTH = 12


class RealDLMSDecoder(DLMSDecoderInterface):
    """
    Реальний DLMS/COSEM декодер для лічильників NIK.
    
    Підтримує:
    - Розбір транспортного обрамлення HDLC (IEC 62056-46) та DLMS Wrapper (IEC 62056-47 UDP/IP)
    - Дешифрування GeneralGlobalCipher (Security Suite 0, AES-GCM-128)
    - Перевірку цілісності та автентичності (Auth Tag 12 байт, AAD)
    - Динамічне вилучення System Title та лічильника кадрів (Invocation Counter)
    - Динамічний розбір CompactData (COSEM Class 62) за Template ID
    - Автоматичне визначення моделі/серії лічильника за серійним номером
    """

    def decode(self, raw_data: bytes, source_addr: Optional[Tuple[str, int]] = None) -> DecodedDLMSMessage:
        if not raw_data:
            return DecodedDLMSMessage(
                system_title="UNKNOWN",
                is_valid=False,
                error_message="Порожній UDP пакет"
            )

        # 1. Зняття транспортного обрамлення: HDLC (7E ... 7E), DLMS Wrapper (8 байтів) або прямий APDU
        apdu_bytes = None

        if len(raw_data) >= 8 and raw_data[0] == 0x7E and raw_data[-1] == 0x7E:
            # HDLC кадр (IEC 62056-46): шукаємо LLC заголовок (E6 E7 00 або E6 E6 00)
            llc_idx = raw_data.find(b"\xe6\xe7\x00")
            if llc_idx == -1:
                llc_idx = raw_data.find(b"\xe6\xe6\x00")

            if llc_idx != -1 and len(raw_data) > llc_idx + 3 + 2:
                # Відокремлюємо APDU (між LLC заголовком та FCS CRC + кінцевим 0x7E)
                apdu_bytes = raw_data[llc_idx + 3 : -3]
            else:
                # Якщо LLC відсутній, шукаємо тег APDU (0x0F або 0xDB) всередині
                for idx in range(1, len(raw_data) - 3):
                    if raw_data[idx] in (TAG_DATA_NOTIFICATION, TAG_GENERAL_GLOBAL_CIPHER):
                        apdu_bytes = raw_data[idx:-3]
                        break

        elif len(raw_data) >= WRAPPER_HEADER_LEN and raw_data[:2] == b"\x00\x01":
            # Заголовок DLMS Wrapper (IEC 62056-47 UDP, 8 байтів)
            version, src_wport, dst_wport, payload_len = struct.unpack(">HHHH", raw_data[:WRAPPER_HEADER_LEN])
            apdu_bytes = raw_data[WRAPPER_HEADER_LEN:]
            if len(apdu_bytes) != payload_len:
                logger.warning(
                    "Невідповідність довжини Wrapper payload: заявлено %d, отримано %d",
                    payload_len, len(apdu_bytes)
                )
                return DecodedDLMSMessage(system_title="UNKNOWN", is_valid=False, error_message="Wrapper payload length mismatch")

        elif len(raw_data) >= 1 and raw_data[0] in (TAG_DATA_NOTIFICATION, TAG_GENERAL_GLOBAL_CIPHER):
            # Чистий APDU без обрамлення
            apdu_bytes = raw_data

        else:
            return DecodedDLMSMessage(
                system_title="UNKNOWN",
                is_valid=False,
                error_message="Unsupported transport framing"
            )

        if not apdu_bytes:
            return DecodedDLMSMessage(
                system_title="UNKNOWN",
                is_valid=False,
                error_message="Не вдалося вилучити APDU з вхідного пакета"
            )

        apdu_tag = apdu_bytes[0]

        # Варіант А: Зашифроване повідомлення general-glo-ciphering (0xDB)
        if apdu_tag == TAG_GENERAL_GLOBAL_CIPHER:
            return self._decode_general_global_cipher(apdu_bytes, source_addr)

        # Варіант Б: Відкрите повідомлення DataNotification (0x0F)
        elif apdu_tag == TAG_DATA_NOTIFICATION:
            if not getattr(settings, "DLMS_ALLOW_UNENCRYPTED", False):
                return DecodedDLMSMessage(system_title="UNENCRYPTED", is_valid=False, error_message="Unencrypted DLMS notifications are disabled")
            return self._decode_plain_data_notification(apdu_bytes, system_title="UNENCRYPTED")

        else:
            return DecodedDLMSMessage(
                system_title="UNKNOWN",
                is_valid=False,
                error_message=f"Непідтримуваний тег APDU: 0x{apdu_tag:02X}"
            )

    def _decode_general_global_cipher(
        self, apdu_bytes: bytes, source_addr: Optional[Tuple[str, int]]
    ) -> DecodedDLMSMessage:
        """
        Розбирає та розшифровує APDU типу GeneralGlobalCipher (0xDB).
        """
        if len(apdu_bytes) < 2:
            return DecodedDLMSMessage(
                system_title="UNKNOWN",
                is_valid=False,
                error_message="Недостатньо байтів для читання довжини System Title"
            )

        sys_title_len = apdu_bytes[1]
        offset = 2

        if len(apdu_bytes) < offset + sys_title_len:
            return DecodedDLMSMessage(
                system_title="UNKNOWN",
                is_valid=False,
                error_message="Недостатньо байтів для читання System Title"
            )

        system_title = apdu_bytes[offset:offset + sys_title_len]
        system_title_hex = system_title.hex().upper()
        offset += sys_title_len

        # Довжина зашифрованих даних або поле Security Control
        if offset >= len(apdu_bytes):
            return DecodedDLMSMessage(
                system_title=system_title_hex,
                is_valid=False,
                error_message="Відсутні дані шифрування після System Title"
            )

        # Якщо наступний байт - довжина A-XDR (наприклад 0x3B = 59 байтів), а за ним Security Control (0x30):
        first_byte = apdu_bytes[offset]
        if first_byte in (0x10, 0x20, 0x30, 0x40, 0x50):
            # Одразу Security Control
            sec_control_byte = first_byte
            offset += 1
        else:
            # Довжина в A-XDR, за нею Security Control
            if offset + 1 >= len(apdu_bytes):
                return DecodedDLMSMessage(system_title=system_title_hex, is_valid=False, error_message="Truncated cipher header")
            sec_control_byte = apdu_bytes[offset + 1]
            offset += 2

        # Читання Invocation Counter (4 байти, big-endian)
        if len(apdu_bytes) < offset + 4:
            return DecodedDLMSMessage(
                system_title=system_title_hex,
                is_valid=False,
                error_message="Недостатньо байтів для читання Invocation Counter"
            )

        invocation_counter = struct.unpack(">I", apdu_bytes[offset:offset + 4])[0]
        offset += 4

        # Решта байтів: ciphertext + 12 байтів authentication tag
        cipher_and_tag = apdu_bytes[offset:]
        if len(cipher_and_tag) < GCM_TAG_LENGTH:
            return DecodedDLMSMessage(
                system_title=system_title_hex,
                invocation_counter=invocation_counter,
                is_valid=False,
                error_message="Довжина зашифрованих даних менша за розмір Auth Tag (12 байтів)"
            )

        # Отримуємо ключі шифрування та автентифікації з конфігурації
        try:
            enc_key, auth_key = KeyResolver.get_keys_for_meter(system_title_hex)
        except Exception as e:
            return DecodedDLMSMessage(
                system_title=system_title_hex,
                invocation_counter=invocation_counter,
                is_valid=False,
                error_message=f"Помилка визначення ключів: {e}"
            )

        # Виконуємо розшифрування AES-GCM-128
        iv = system_title + invocation_counter.to_bytes(4, "big")
        tag = cipher_and_tag[-GCM_TAG_LENGTH:]
        ciphertext = cipher_and_tag[:-GCM_TAG_LENGTH]
        associated_data = bytes([sec_control_byte]) + auth_key

        try:
            decryptor = Cipher(
                algorithms.AES(enc_key),
                modes.GCM(iv, tag, min_tag_length=GCM_TAG_LENGTH)
            ).decryptor()
            decryptor.authenticate_additional_data(associated_data)
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        except InvalidTag:
            logger.warning(
                "DLMS Decryption: InvalidTag (system_title=%s, invoc=%d)",
                system_title_hex, invocation_counter
            )
            return DecodedDLMSMessage(
                system_title=system_title_hex,
                invocation_counter=invocation_counter,
                is_valid=False,
                error_message="Помилка автентифікації / невірний ключ шифрування (InvalidTag)"
            )
        except Exception as e:
            logger.warning(
                "DLMS Decryption failed: %s (system_title=%s)",
                e, system_title_hex
            )
            return DecodedDLMSMessage(
                system_title=system_title_hex,
                invocation_counter=invocation_counter,
                is_valid=False,
                error_message=f"Збій розшифрування: {str(e)}"
            )

        # Розбір розшифрованого повідомлення (DataNotification)
        return self._decode_plain_data_notification(
            plaintext,
            system_title=system_title_hex,
            invocation_counter=invocation_counter,
            sec_control=sec_control_byte
        )

    def _decode_plain_data_notification(
        self,
        plain_apdu: bytes,
        system_title: str,
        invocation_counter: Optional[int] = None,
        sec_control: Optional[int] = None
    ) -> DecodedDLMSMessage:
        """
        Розбирає розшифрований DataNotification APDU (0x0F).
        """
        if not plain_apdu or plain_apdu[0] != TAG_DATA_NOTIFICATION:
            return DecodedDLMSMessage(
                system_title=system_title,
                invocation_counter=invocation_counter,
                is_valid=False,
                error_message=f"Розшифрований APDU не є DataNotification (тег 0x{plain_apdu[0]:02X})" if plain_apdu else "Порожній розшифрований APDU",
                raw_unprotected_hex=plain_apdu.hex().upper() if plain_apdu else None
            )

        offset = 1
        # long-invoke-id-and-priority (4 байти)
        if len(plain_apdu) < offset + 4:
            return DecodedDLMSMessage(
                system_title=system_title,
                invocation_counter=invocation_counter,
                is_valid=False,
                error_message="Недостатньо байтів для LongInvokeIdAndPriority"
            )
        invoke_id = struct.unpack(">I", plain_apdu[offset:offset + 4])[0]
        offset += 4

        # date-time optional:
        event_at = None
        if offset < len(plain_apdu):
            first_byte = plain_apdu[offset]
            if first_byte == 0x0C and len(plain_apdu) >= offset + 13:
                # Безпосередня довжина 12 байтів (0x0C)
                dt_bytes = plain_apdu[offset + 1 : offset + 13]
                offset += 13
                event_at = self._parse_dlms_datetime(dt_bytes)
            elif first_byte == 0x01 and offset + 1 < len(plain_apdu) and plain_apdu[offset + 1] == 0x0C and len(plain_apdu) >= offset + 14:
                # Прапорець наявності 0x01 + довжина 0x0C + 12 байтів
                dt_bytes = plain_apdu[offset + 2 : offset + 14]
                offset += 14
                event_at = self._parse_dlms_datetime(dt_bytes)
            elif first_byte == 0x00:
                # Прапорець відсутності дати-часу
                offset += 1

        # notification-body
        body_bytes = plain_apdu[offset:]

        # Розбір параметрів у notification-body
        try:
            if not body_bytes:
                raise ValueError("Empty notification body")
            parsed_payload, body_event_at, extracted_title, extracted_model = self._parse_notification_body(body_bytes)
            if not parsed_payload.get("parameters"):
                raise ValueError("Empty notification parameters")
        except ValueError as error:
            return DecodedDLMSMessage(system_title=system_title, invocation_counter=invocation_counter,
                is_valid=False, error_message=str(error), raw_unprotected_hex=plain_apdu.hex().upper())
        if event_at is None and body_event_at is not None:
            event_at = body_event_at

        final_title = extracted_title or system_title
        meta_info = {
            "invoke_id": invoke_id,
            "security_control": sec_control,
            "authenticated": sec_control is not None,
            "system_title": final_title,
        }
        parsed_payload["meta"] = meta_info

        return DecodedDLMSMessage(
            system_title=final_title,
            invocation_counter=invocation_counter,
            event_at=event_at,
            parsed_payload=parsed_payload,
            is_valid=True,
            raw_unprotected_hex=plain_apdu.hex().upper(),
            serial_number=extracted_title,
            model_name=extracted_model or resolve_meter_model(final_title, fallback="NIK")
        )

    def _parse_dlms_datetime(self, dt_bytes: bytes) -> Optional[datetime]:
        """
        Розбирає стандартну 12-байтову дату-час DLMS (IEC 62056-6-2).
        year (2B), month (1B), day_of_month (1B), day_of_week (1B),
        hour (1B), minute (1B), second (1B), hundredths (1B),
        deviation (2B), status (1B)
        """
        try:
            year, month, day, _, hour, minute, second = struct.unpack(">HBBBBBB", dt_bytes[:8])
            if year < 2000 or month < 1 or month > 12 or day < 1 or day > 31:
                return None
            return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except Exception:
            return None

    def _parse_notification_body(
        self, body_bytes: bytes
    ) -> Tuple[Dict[str, Any], Optional[datetime], Optional[str], Optional[str]]:
        """
        Універсальний та надійний розбір тіла сповіщення NIK.
        Підтримує:
        - Шаблони CompactData (визначаються динамічно за template_id)
        - Компактні блоки 34 байти (1-фазні лічильники NIK)
        - Довільні структури DLMS A-XDR
        Повертає: (parsed_payload, event_at, serial_number, model_name)
        """
        result: Dict[str, Any] = {
            "parameters": [],
            "raw_body_hex": body_bytes.hex().upper(),
            "body_length": len(body_bytes),
        }
        event_dt = None
        serial_no = None
        model_name = None

        if not body_bytes:
            return result, None, None, None

        payload = body_bytes
        if payload[0] == 0x02:
            if len(payload) < 2 or payload[1] != 1:
                raise ValueError("Unsupported notification structure")
            payload = payload[2:]
        if not payload:
            raise ValueError("Empty notification payload")
        if payload[0] == 0x09:
            if len(payload) < 2:
                raise ValueError("Truncated OctetString length")
            size = payload[1]
            offset = 2
            if size & 0x80:
                count = size & 0x7F
                if count == 0 or count > 4 or len(payload) < offset + count:
                    raise ValueError("Invalid OctetString length")
                size = int.from_bytes(payload[offset:offset + count], "big")
                offset += count
            if len(payload) != offset + size:
                raise ValueError("OctetString payload length mismatch")
            payload = payload[offset:]
        if not payload:
            raise ValueError("Empty notification payload")

        raw_payload = payload

        # Варіант 1: Автоматичне визначення шаблону CompactData за template_id (байт 0):
        if len(payload) > 1:
            template_id = payload[0]
            template = CompactDataTemplateRegistry.get(template_id)
            if template:
                try:
                    result["template_id"] = template_id
                    params, extracted_sn, model_name = template.decode_buffer(payload)
                    result["parameters"] = params
                    serial_no = extracted_sn
                    return result, event_dt, serial_no, model_name
                except (ValueError, struct.error, UnicodeError) as error:
                    raise ValueError("Invalid CompactData template %s: %s" % (template_id, error)) from error

        # Варіант 2: Характерний 34-байтний формат 1-фазних лічильників NIK:
        if len(raw_payload) == 34 and raw_payload[0] == 0x12:
            try:
                model_name = "NIK"
                ts1 = struct.unpack(">I", raw_payload[1:5])[0]
                if 1262304000 < ts1 < 2524608000:  # між 2010 і 2050 роком
                    event_dt = datetime.fromtimestamp(ts1, timezone.utc)

                energy_raw = struct.unpack("<I", raw_payload[9:13])[0]
                param1 = struct.unpack("<I", raw_payload[13:17])[0]

                ts2 = struct.unpack(">I", raw_payload[18:22])[0]
                billing_dt = None
                if 1262304000 < ts2 < 2524608000:
                    billing_dt = datetime.fromtimestamp(ts2, timezone.utc).isoformat()

                net_status = struct.unpack(">H", raw_payload[22:24])[0]
                param2 = struct.unpack(">I", raw_payload[24:28])[0]
                param3 = struct.unpack(">I", raw_payload[28:32])[0]
                flags = struct.unpack(">H", raw_payload[32:34])[0]

                result["parameters"] = [
                    {
                        "name": "Event Timestamp",
                        "name_en": "Event Timestamp",
                        "name_ua": "Часова мітка події",
                        "obis": "0.0.1.0.0.255",
                        "class_id": 8,
                        "attribute_id": 2,
                        "type": "datetime",
                        "value": event_dt.isoformat() if event_dt else None,
                        "raw_hex": raw_payload[1:5].hex().upper(),
                    },
                    OBISRegistry.format_parameter("1.0.1.8.0.255", energy_raw, unit="Wh", dtype="long64-unsigned"),
                    OBISRegistry.format_parameter("1.0.31.7.0.255", param1, unit="A", dtype="double-long-unsigned"),
                    {
                        "name": "Billing Period Timestamp",
                        "name_en": "Billing Period Timestamp",
                        "name_ua": "Розрахунковий період",
                        "obis": "0.0.0.1.2.255",
                        "class_id": 8,
                        "attribute_id": 2,
                        "type": "datetime",
                        "value": billing_dt,
                        "raw_hex": raw_payload[18:22].hex().upper(),
                    },
                    OBISRegistry.format_parameter("0.0.96.10.1.255", net_status, dtype="long-unsigned"),
                    OBISRegistry.format_parameter("1.0.51.7.0.255", param2, unit="A", dtype="double-long-unsigned"),
                    OBISRegistry.format_parameter("1.0.71.7.0.255", param3, unit="A", dtype="double-long-unsigned"),
                    OBISRegistry.format_parameter("0.0.96.5.0.255", flags, dtype="long-unsigned"),
                ]
                return result, event_dt, serial_no, model_name
            except Exception as e:
                logger.debug("Не вдалося розібрати 34-байтний формат NIK: %s", e)

        # Варіант 3: Загальний розбір для довільного формату / структури DLMS
        raise ValueError("Unsupported notification format")
