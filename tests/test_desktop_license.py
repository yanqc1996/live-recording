import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_license import LicenseManager, make_license_code


class LicenseManagerStabilityTest(unittest.TestCase):
    def manager(self, path: Path) -> LicenseManager:
        with (
            patch("desktop_license.stable_machine_material", return_value="mac:STABLE-HARDWARE-UUID"),
            patch("desktop_license.legacy_machine_material", return_value="Darwin|arm64|old-name|123|UUID"),
        ):
            return LicenseManager(path)

    def test_license_record_survives_new_manager_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "license.json"
            first = self.manager(path)
            first.activate(make_license_code(first.device_id, customer="测试用户"))

            second = self.manager(path)

            self.assertTrue(second.status()["active"])
            self.assertEqual(first.device_id, second.device_id)

    def test_existing_v1_device_code_remains_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory) / "license.json")
            legacy_code = make_license_code(manager.legacy_device_id, customer="老用户")

            status = manager.activate(legacy_code)

            self.assertTrue(status["active"])
            self.assertEqual(2, status["device_id_version"])

    def test_unrelated_device_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(Path(directory) / "license.json")
            code = make_license_code("AAAA-BBBB-CCCC-DDDD")

            with self.assertRaisesRegex(ValueError, "设备不匹配"):
                manager.activate(code)


if __name__ == "__main__":
    unittest.main()
