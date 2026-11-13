import unittest

from app.security.source_content import contains_private_key


class SourceContentTests(unittest.TestCase):
    def test_literal_header_removal_is_source_code_and_other_key_markers_stay_blocked(self):
        for kind in ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "):
            header = f"-----BEGIN {kind}PRIVATE KEY-----"
            for cleanup in (
                f'privateKey.replace("{header}", "")',
                f'privateKey.replaceAll(\n "{header}" , ""\n)',
                f"private_key.replace('{header}', '')",
            ):
                self.assertFalse(contains_private_key(cleanup))
                key = header + "\n" + "A" * 64 + "\n-----END PRIVATE KEY-----"
                self.assertTrue(contains_private_key(cleanup + "\n" + key))
            self.assertTrue(contains_private_key(header))
            self.assertTrue(contains_private_key(f'key.replace("{header}", "hidden")'))
            self.assertTrue(contains_private_key(f'key.replace("{header}\\nAAAA", "")'))
        self.assertFalse(contains_private_key('key.replace("-----BEGIN PUBLIC KEY-----", "")'))
