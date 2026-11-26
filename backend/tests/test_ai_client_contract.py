import unittest
from unittest.mock import Mock, patch

from app.integrations import ai_client, codex_exec, codex_terminal, responses


class AIClientContractTests(unittest.TestCase):
    def test_analysis_keywords_bind_for_each_transport(self):
        args = ("https://example.invalid", "model", "synthetic-key", "default", "rules", [])
        common = {
            "diagnostics": {},
            "on_progress": Mock(),
            "instruction_messages": [],
            "output_profile": "case_generation",
            "reading_files": [{"path": "task.txt", "text": "fixed"}],
            "reading_guidance": "read index",
        }
        terminal = {"identity": "synthetic-terminal", "execution": "synthetic-execution"}
        # Autospec checks signatures at the transport boundary without starting HTTP or CLI I/O.
        with (
            patch.object(responses, "analyze", autospec=True) as api,
            patch.object(codex_exec, "require_available"),
            patch.object(codex_exec, "_execute", autospec=True) as cli,
            patch.object(codex_terminal, "analyze", autospec=True) as native,
        ):
            ai_client.analyze(*args, call_mode="RESPONSES_API", **common)
            ai_client.analyze(*args, call_mode="CODEX_EXEC", **common)
            ai_client.analyze(*args, call_mode="CODEX_EXEC", terminal_spec=terminal, **common)

        for transport in (api, cli, native):
            transport.assert_called_once()
            self.assertIs(transport.call_args.kwargs["diagnostics"], common["diagnostics"])
            self.assertTrue(callable(transport.call_args.kwargs["on_progress"]))
        self.assertIs(api.call_args.kwargs["instruction_messages"], common["instruction_messages"])
        self.assertEqual(api.call_args.kwargs["output_profile"], "case_generation")
        self.assertNotIn("output_profile", cli.call_args.kwargs)
        self.assertNotIn("output_profile", native.call_args.kwargs)
        for name in ("reading_files", "reading_guidance"):
            self.assertNotIn(name, api.call_args.kwargs)
            self.assertIs(cli.call_args.kwargs[name], common[name])
            self.assertIs(native.call_args.kwargs[name], common[name])
        self.assertIs(native.call_args.kwargs["terminal_spec"], terminal)

    def test_conversation_keywords_bind_for_each_transport(self):
        args = ("https://example.invalid", "model", "synthetic-key", "default", "rules", [])
        diagnostics = {}
        with (
            patch.object(responses, "converse", autospec=True) as api,
            patch.object(codex_exec, "require_available"),
            patch.object(codex_exec, "_execute", autospec=True) as cli,
        ):
            for mode in ("RESPONSES_API", "CODEX_EXEC"):
                progress = Mock()
                ai_client.converse(
                    *args, call_mode=mode, diagnostics=diagnostics, on_progress=progress
                )
                progress.assert_called()
        for transport in (api, cli):
            transport.assert_called_once()
            self.assertIs(transport.call_args.kwargs["diagnostics"], diagnostics)
            self.assertTrue(callable(transport.call_args.kwargs["on_progress"]))
