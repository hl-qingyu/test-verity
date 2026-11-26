import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from app.integrations import codex_config


class CodexConfigTests(unittest.TestCase):
    def test_profiles_preserve_sandbox_tools_retries_and_effort(self):
        work = Path("W:/Original Workspace")
        fake_mcp = {"command": "node.exe", "args": ["server", str(work)], "required": True}
        for profile in ("exec", "probe", "terminal"):
            with (
                self.subTest(profile=profile),
                patch.object(codex_config.codex_filesystem, "configuration", return_value=fake_mcp),
            ):
                args = codex_config.build(
                    profile, work, "https://example.invalid", "high", work / "rules.txt"
                )
                self.assertEqual(args[::2], ["-c"] * (len(args) // 2))
                config = tomllib.loads("\n".join(args[1::2]))
                self.assertEqual(
                    config["features"],
                    dict.fromkeys(
                        (
                            "shell_tool",
                            "multi_agent",
                            "apply_patch_freeform",
                            "view_image",
                            "plugins",
                            "apps",
                            "hooks",
                            "shell_snapshot",
                        ),
                        False,
                    ),
                )
                self.assertEqual(config["model_reasoning_effort"], "high")
                self.assertEqual(config["approval_policy"], "never")
                self.assertEqual(config["web_search"], "disabled")
                self.assertEqual(config["model_providers"]["verity"]["env_key"], "VERITY_CODEX_KEY")
                if profile == "probe":
                    self.assertNotIn("permissions", config)
                    self.assertEqual(config["mcp_servers"], {})
                    self.assertEqual(config["model_providers"]["verity"]["request_max_retries"], 0)
                    self.assertEqual(config["model_providers"]["verity"]["stream_max_retries"], 0)
                else:
                    policy = config["permissions"]["verity"]
                    self.assertEqual(
                        policy["filesystem"],
                        {":root": "deny", ":minimal": "read", str(work): "read"},
                    )
                    self.assertFalse(policy["network"]["enabled"])
                    self.assertNotIn("request_max_retries", config["model_providers"]["verity"])
                    self.assertEqual(
                        config["mcp_servers"],
                        {"filesystem": fake_mcp} if profile == "terminal" else {},
                    )
