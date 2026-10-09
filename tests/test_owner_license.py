import tempfile
import unittest
from pathlib import Path

from desktop_license import LicenseManager
from scripts.prepare_owner_license import prepare_owner_license


class OwnerLicenseBuildTest(unittest.TestCase):
    def test_generated_owner_record_is_active_on_build_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "license.json"

            generated, device_id = prepare_owner_license(target)
            status = LicenseManager(generated).status()

            self.assertEqual(target, generated)
            self.assertEqual(device_id, status["device_id"])
            self.assertTrue(status["active"])
            self.assertEqual("Owner Build", status["customer"])


if __name__ == "__main__":
    unittest.main()
