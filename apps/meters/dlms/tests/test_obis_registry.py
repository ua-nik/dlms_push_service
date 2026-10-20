import unittest
from apps.meters.dlms import OBISRegistry, OBISInfo


class OBISRegistryTestCase(unittest.TestCase):
    def test_obis_lookup_total_energy(self):
        """Перевірка пошуку стандартних кодів енергії."""
        info = OBISRegistry.get("1.0.1.8.0.255")
        self.assertIsNotNone(info)
        self.assertEqual(info.unit, "Wh")
        self.assertEqual(info.class_id, 3)
        self.assertIn("Active Energy", info.name_en)
        self.assertIn("Активна енергія", info.name_ua)

    def test_obis_lookup_voltages(self):
        """Перевірка пошуку параметрів напруги фаз."""
        for obis in ["1.0.32.7.0.255", "1.0.52.7.0.255", "1.0.72.7.0.255"]:
            info = OBISRegistry.get(obis)
            self.assertIsNotNone(info)
            self.assertEqual(info.unit, "V")
            self.assertEqual(info.class_id, 3)

    def test_format_parameter(self):
        """Перевірка форматування параметрів для збереження в БД та виводу."""
        param = OBISRegistry.format_parameter(
            "1.0.1.8.0.255",
            value=1571,
            unit="Wh"
        )
        self.assertEqual(param["obis"], "1.0.1.8.0.255")
        self.assertEqual(param["value"], "1571")
        self.assertEqual(param["unit"], "Wh")
        self.assertIn("Active Energy", param["name_en"])
        self.assertIn("Активна енергія", param["name_ua"])

    def test_unknown_obis_fallback(self):
        """Перевірка коректної обробки невідомого OBIS коду."""
        unknown_code = "9.9.99.99.99.255"
        self.assertIsNone(OBISRegistry.get(unknown_code))
        self.assertEqual(OBISRegistry.get_name(unknown_code), unknown_code)
        
        param = OBISRegistry.format_parameter(unknown_code, 42)
        self.assertEqual(param["name"], unknown_code)
        self.assertEqual(param["value"], "42")
