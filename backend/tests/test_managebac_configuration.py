import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import load_backend_environment  # noqa: E402
from services.managebac_security import (  # noqa: E402
    log_managebac_credential_readiness,
    managebac_credential_readiness,
)


class ManageBacConfigurationTests(unittest.TestCase):
    def test_backend_local_environment_overrides_inherited_blank_value(self):
        key = Fernet.generate_key().decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory)
            (config_dir / ".env").write_text(
                "INTEGRATION_CREDENTIAL_KEY=wrong\n",
                encoding="utf-8",
            )
            (config_dir / ".env.local").write_text(
                f"INTEGRATION_CREDENTIAL_KEY={key}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"INTEGRATION_CREDENTIAL_KEY": ""}):
                load_backend_environment(config_dir)
                self.assertEqual(key, os.environ["INTEGRATION_CREDENTIAL_KEY"])

    def test_readiness_distinguishes_missing_invalid_and_valid_keys(self):
        missing = managebac_credential_readiness(key="")
        invalid = managebac_credential_readiness(key="not-a-fernet-key")
        valid = managebac_credential_readiness(
            key=Fernet.generate_key().decode("ascii")
        )
        self.assertFalse(missing.configured)
        self.assertEqual("credential_key_missing", missing.code)
        self.assertFalse(invalid.configured)
        self.assertEqual("credential_key_invalid", invalid.code)
        self.assertTrue(valid.configured)
        self.assertIsNone(valid.code)

    def test_startup_log_is_actionable_and_does_not_expose_key(self):
        key = Fernet.generate_key().decode("ascii")
        with patch("services.managebac_security.settings.INTEGRATION_CREDENTIAL_KEY", key):
            with self.assertLogs(
                "services.managebac_security", level=logging.INFO
            ) as captured:
                self.assertTrue(log_managebac_credential_readiness("test-api"))
        output = "\n".join(captured.output)
        self.assertIn("ready component=test-api", output)
        self.assertNotIn(key, output)

        with patch("services.managebac_security.settings.INTEGRATION_CREDENTIAL_KEY", ""):
            with self.assertLogs(
                "services.managebac_security", level=logging.ERROR
            ) as captured:
                self.assertFalse(log_managebac_credential_readiness("test-worker"))
        output = "\n".join(captured.output)
        self.assertIn("backend/.env.local", output)
        self.assertIn("restart", output)


if __name__ == "__main__":
    unittest.main()
