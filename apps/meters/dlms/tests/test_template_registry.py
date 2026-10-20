import unittest
from apps.meters.dlms import (
    CompactDataTemplateRegistry,
    CompactDataTemplate,
    CaptureField,
    resolve_meter_model,
)


class TemplateRegistryTestCase(unittest.TestCase):
    def test_default_template_11(self):
        """Перевірка наявності дефолтного Шаблону 11."""
        template = CompactDataTemplateRegistry.get(11)
        self.assertIsNotNone(template)
        self.assertEqual(template.template_id, 11)
        self.assertEqual(template.model_name, "NIK")
        self.assertGreater(len(template.fields), 5)

    def test_decode_buffer_template_11(self):
        """Перевірка динамічного декодування буфера за Шаблоном 11 та визначення моделі."""
        # 0x0B (id=11), 0x10 (len=16), '2308213058052025', 10 x uint32
        import struct
        sn_bytes = b"2308213058052025"
        buf = bytes([11, len(sn_bytes)]) + sn_bytes + struct.pack(">10I", 100, 200, 10, 220, 20, 221, 30, 222, 1, 2)
        template = CompactDataTemplateRegistry.get(11)
        params, sn, model = template.decode_buffer(buf)
        self.assertEqual(sn, "2308213058052025")
        self.assertEqual(model, "NIK 2308")
        self.assertEqual(len(params), 11)
        # Перевірка першого числового параметра (A+)
        self.assertEqual(params[1]["obis"], "1.0.1.8.0.255")
        self.assertEqual(params[1]["value"], "100")

    def test_custom_template_registration(self):
        """Перевірка динамічної реєстрації нового довільного шаблону."""
        custom_id = 99
        custom_tmpl = CompactDataTemplate(
            template_id=custom_id,
            name="Custom Meter Template",
            model_name="NIK Custom",
            fields=[
                CaptureField(obis="1.0.1.8.0.255", dtype="uint32", unit="Wh"),
                CaptureField(obis="1.0.32.7.0.255", dtype="uint32", unit="V"),
            ]
        )
        CompactDataTemplateRegistry.register(custom_tmpl)
        self.assertIsNotNone(CompactDataTemplateRegistry.get(custom_id))

        import struct
        buf = bytes([custom_id]) + struct.pack(">2I", 555, 230)
        params, sn, model = custom_tmpl.decode_buffer(buf)
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0]["value"], "555")
        self.assertEqual(params[1]["value"], "230")
        self.assertEqual(model, "NIK Custom")

    def test_resolve_meter_model(self):
        """Перевірка автоматичного визначення моделі за серійним номером."""
        self.assertEqual(resolve_meter_model("2308213058052025"), "NIK 2308")
        self.assertEqual(resolve_meter_model("210400123456"), "NIK 2104")
        self.assertEqual(resolve_meter_model("210812345678"), "NIK 2108")
        self.assertEqual(resolve_meter_model(""), "NIK")
        self.assertEqual(resolve_meter_model(None), "NIK")
