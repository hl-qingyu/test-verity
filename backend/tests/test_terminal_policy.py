"""Native terminal authorization is enforced on RPC actions, not edited user text."""

import copy
import tempfile
import unittest
from pathlib import Path

from app.integrations.terminal_policy import PolicyDenied, TerminalPolicy


class TerminalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.policy = TerminalPolicy(
            self.work,
            {
                "features.shell_tool": False,
                "features.apply_patch_freeform": False,
                "default_permissions": "verity",
                "permissions.verity.filesystem": {
                    ":root": "deny",
                    ":minimal": "read",
                    str(self.work): "read",
                },
                "permissions.verity.network.enabled": False,
                "mcp_servers": {"filesystem": {"command": "fixed-node"}},
            },
        )

    def test_dialogue_text_is_preserved_including_bang_multiline_and_control_lookalikes(self):
        text = "正常标点 ! != !echo is data\n\x1b[33u补充说明"
        request = {
            "id": 7,
            "method": "turn/start",
            "params": {"threadId": "own", "input": [{"type": "text", "text": text}]},
        }
        before = copy.deepcopy(request)
        result = self.policy.request(request)
        self.assertEqual(result["params"]["input"], before["params"]["input"])
        self.assertEqual(request, before)
        self.assertEqual(result["params"]["permissions"], "verity")
        self.assertEqual(result["params"]["cwd"], str(self.work))
        self.assertEqual(result["params"]["approvalPolicy"], "never")

    def test_all_execution_filesystem_and_configuration_bypasses_fail_closed(self):
        for method in (
            "thread/shellCommand",
            "command/exec",
            "command/exec/write",
            "process/spawn",
            "process/writeStdin",
            "fs/writeFile",
            "fs/readFile",
            "fs/remove",
            "fs/copy",
            "fs/createDirectory",
            "plugin/install",
            "marketplace/add",
            "config/value/write",
            "config/batchWrite",
            "config/mcpServer/reload",
            "mcpServer/tool/call",
            "externalAgentConfig/import",
            "thread/approveGuardianDeniedAction",
            "unknown/new-method",
        ):
            with self.subTest(method=method), self.assertRaises(PolicyDenied):
                self.policy.request({"id": 1, "method": method, "params": {"command": "anything"}})

    def test_permissions_cannot_be_expanded_in_start_resume_or_later_turns(self):
        for method in ("thread/start", "thread/resume", "turn/start", "thread/settings/update"):
            for payload in (
                {"cwd": str(self.work.parent)},
                {"permissions": "danger-full-access"},
                {"sandbox": "workspace-write"},
                {"sandboxPolicy": {"type": "dangerFullAccess"}},
                {"approvalPolicy": "on-request"},
                {"runtimeWorkspaceRoots": [str(self.work.parent)]},
                {"config": {"features": {"shell_tool": True}}},
                {"config": {"features": {"apply_patch_freeform": True}}},
                {"config": {"mcp_servers": {"untrusted": {"command": "powershell"}}}},
                {"environments": [{"id": "other"}]},
                {"path": "outside-session.jsonl"},
                {"history": []},
                {"modelProvider": "other"},
            ):
                with self.subTest(method=method, payload=payload), self.assertRaises(PolicyDenied):
                    self.policy.request({"id": 1, "method": method, "params": payload})

    def test_legacy_readonly_bootstrap_is_narrowed_and_dynamic_tools_are_removed(self):
        result = self.policy.request(
            {
                "id": 1,
                "method": "thread/start",
                "params": {
                    "sandbox": "read-only",
                    "config": {"features": {"shell_tool": False}},
                    "dynamicTools": [{"name": "untrusted"}],
                },
            }
        )
        self.assertNotIn("sandbox", result["params"])
        self.assertEqual(result["params"]["dynamicTools"], [])
        self.assertEqual(
            result["params"]["config"]["permissions"]["verity"]["network"], {"enabled": False}
        )
        self.assertEqual(result["params"]["runtimeWorkspaceRoots"], [str(self.work)])

    def test_status_and_current_task_history_methods_remain_available(self):
        for method in (
            "initialize",
            "initialized",
            "thread/list",
            "thread/read",
            "thread/turns/list",
            "turn/interrupt",
            "model/list",
            "config/read",
        ):
            message = {"id": 1, "method": method, "params": {}}
            self.assertEqual(self.policy.request(message), message)

    def test_external_metadata_scans_and_attachments_cannot_read_other_directories(self):
        for payload in ({"cwds": [str(self.work.parent)]}, {"forceRefetch": True}):
            with self.assertRaises(PolicyDenied):
                self.policy.request({"id": 1, "method": "skills/list", "params": payload})
        for part in (
            {"type": "localImage", "path": str(self.work.parent / "private.png")},
            {"type": "skill", "path": str(self.work.parent / "SKILL.md"), "name": "external"},
        ):
            with self.assertRaises(PolicyDenied):
                self.policy.request({"id": 1, "method": "turn/start", "params": {"input": [part]}})

    def test_only_preselected_images_are_allowed_even_inside_the_task_directory(self):
        selected = self.work / "image-1.png"
        url = "data:image/png;base64,SELECTED"
        policy = TerminalPolicy(self.work, self.policy.overrides, [selected], [url])
        for part in (
            {"type": "localImage", "path": str(selected)},
            {"type": "image", "url": url},
        ):
            request = {"id": 1, "method": "turn/start", "params": {"input": [part]}}
            self.assertEqual(policy.request(request)["params"]["input"], [part])
        for part in (
            {"type": "localImage", "path": str(self.work / "input.json")},
            {"type": "localImage", "path": str(self.work / "other.png")},
            {"type": "image", "url": "https://example.com/private.png"},
            {"type": "image", "url": "data:image/png;base64,UNSELECTED"},
        ):
            with self.assertRaises(PolicyDenied):
                policy.request({"id": 1, "method": "turn/start", "params": {"input": [part]}})

    def test_native_resume_default_template_does_not_block_text_or_override_server_rules(self):
        request = {
            "id": 1,
            "method": "turn/start",
            "params": {
                "input": [{"type": "text", "text": "继续分析"}],
                "collaborationMode": {
                    "mode": "default",
                    "settings": {"developer_instructions": "Untrusted client template"},
                },
            },
        }
        result = self.policy.request(request)
        self.assertEqual(result["params"]["input"], request["params"]["input"])
        self.assertIsNone(result["params"]["collaborationMode"])
        self.assertEqual(result["params"]["permissions"], "verity")
        self.assertEqual(result["params"]["approvalPolicy"], "never")
        request["params"]["baseInstructions"] = "Override server rules"
        with self.assertRaises(PolicyDenied):
            self.policy.request(request)
