"""Private RPC gateway auth and privilege refusal against a synthetic stdio server."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from app.integrations.terminal_gateway import TerminalGateway
from app.integrations.terminal_policy import TerminalPolicy
from app.integrations.windows_job import WindowsJob


@unittest.skipUnless(os.name == "nt", "Windows owned process integration")
class TerminalGatewayTests(unittest.TestCase):
    def test_auth_and_command_denial_before_stdio_while_text_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "synthetic_server.py"
            script.write_text(
                """import json,sys
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
pending=None
for line in sys.stdin:
    m=json.loads(line)
    if m.get('method') in ('thread/shellCommand','command/exec','process/spawn','fs/writeFile'):
        Path('MUST_NOT_EXIST').write_text('unsafe request reached execution')
    if m.get('method')=='turn/start':
        pending=m['id']
        print(json.dumps({'id':'permission-1','method':'item/permissions/requestApproval','params':{}}),flush=True)
    elif m.get('id')=='permission-1':
        print(json.dumps({'id':pending,'result':{'grant_denied':'error' in m}}),flush=True)
    else:
        print(json.dumps({'id':m.get('id'),'result':{'params':m.get('params')}}),flush=True)
""",
                encoding="utf-8",
            )
            job = WindowsJob()
            gateway = TerminalGateway(
                [sys.executable, str(script)],
                {"SystemRoot": os.environ.get("SystemRoot", "C:\\Windows")},
                str(root),
                TerminalPolicy(root, {}),
                job,
                Fernet(Fernet.generate_key()),
                root / "server.enc",
                lambda value: value,
            )
            try:
                url = f"ws://127.0.0.1:{gateway.port}"
                with self.assertRaises(InvalidStatus):
                    with connect(url, additional_headers={"Authorization": "Bearer wrong"}):
                        pass
                with connect(
                    url, additional_headers={"Authorization": "Bearer " + gateway.token}
                ) as ws:
                    for index, method in enumerate(
                        ("thread/shellCommand", "command/exec", "process/spawn", "fs/writeFile")
                    ):
                        ws.send(
                            json.dumps(
                                {"id": index, "method": method, "params": {"command": "unsafe"}}
                            )
                        )
                        result = json.loads(ws.recv(timeout=3))
                        self.assertEqual(result["error"]["code"], -32601)
                    text = "正常 ! != 标点\n原样保留"
                    ws.send(
                        json.dumps(
                            {"id": 10, "method": "thread/read", "params": {"threadId": text}}
                        )
                    )
                    self.assertEqual(
                        json.loads(ws.recv(timeout=3))["result"]["params"]["threadId"], text
                    )
                    ws.send(
                        json.dumps(
                            {
                                "id": 11,
                                "method": "turn/start",
                                "params": {"input": [{"type": "text", "text": text}]},
                            }
                        )
                    )
                    self.assertTrue(json.loads(ws.recv(timeout=3))["result"]["grant_denied"])
                    self.assertFalse((root / "MUST_NOT_EXIST").exists())
                    events = [
                        json.loads(gateway.cipher.decrypt(line))
                        for line in gateway.event_path.read_bytes().splitlines()
                    ]
                    self.assertEqual(len(events), 4)
                    self.assertTrue(all(event["reason"] == "method" for event in events))
                    self.assertNotIn(text, json.dumps(events, ensure_ascii=False))
                    self.assertNotIn("unsafe", json.dumps(events))
            finally:
                job.close()
                gateway.close()
