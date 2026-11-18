"""Fixed task RPC policy for the pinned native CLI; never inspect terminal keystrokes."""

import copy
import os
from pathlib import Path


class PolicyDenied(ValueError):
    pass


class TerminalPolicy:
    # Unknown/new protocol methods fail closed. These are the read/chat methods of CLI 0.166.0.
    METHODS = {
        "initialize",
        "initialized",
        "thread/start",
        "thread/resume",
        "thread/list",
        "thread/read",
        "thread/loaded/list",
        "thread/unsubscribe",
        "thread/name/set",
        "thread/readState/update",
        "thread/turns/list",
        "thread/items/list",
        "thread/items/read",
        "thread/compact/start",
        "thread/settings/update",
        "turn/start",
        "turn/steer",
        "turn/interrupt",
        "turn/settings/update",
        "model/list",
        "modelProvider/capabilities/read",
        "account/read",
        "account/rateLimits/read",
        "account/usage/read",
        "config/read",
        "configRequirements/read",
        "permissionProfile/list",
        "mcpServerStatus/list",
        "collaborationMode/list",
        "skills/list",
        "hooks/list",
        "plugin/list",
        "plugin/installed",
        "app/list",
        "app/installed",
        "experimentalFeature/list",
    }
    THREAD_METHODS = {"thread/start", "thread/resume", "thread/settings/update", "turn/start"}

    def __init__(self, work, overrides, image_paths=(), image_urls=()):
        self.work = Path(work).resolve()
        self.overrides = overrides
        self.image_paths = {os.path.normcase(str(Path(p).resolve())) for p in image_paths}
        self.image_urls = set(image_urls)
        self.config = {}
        for name, value in overrides.items():
            parts = name.split(".")
            target = self.config
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = copy.deepcopy(value)

    @staticmethod
    def subset(candidate, expected):
        if isinstance(candidate, dict) and isinstance(expected, dict):
            return all(
                key in expected and TerminalPolicy.subset(value, expected[key])
                for key, value in candidate.items()
            )
        return type(candidate) is type(expected) and candidate == expected

    def same_path(self, value):
        return isinstance(value, str) and os.path.normcase(
            str(Path(value).resolve())
        ) == os.path.normcase(str(self.work))

    def request(self, message):
        method = message.get("method")
        if not isinstance(method, str) or method not in self.METHODS:
            raise PolicyDenied("method")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise PolicyDenied("params")
        params = copy.deepcopy(params)
        cwds = params.get("cwds")
        if cwds is not None and (
            not isinstance(cwds, list) or any(not self.same_path(p) for p in cwds)
        ):
            raise PolicyDenied("cwds")
        if params.get("forceRefetch") is True:
            raise PolicyDenied("external_refresh")
        for field in (
            "path",
            "history",
            "selectedCapabilityRoots",
            "baseInstructions",
            "developerInstructions",
            "toolOutput",
            "additionalContext",
        ):
            if params.get(field) is not None:
                raise PolicyDenied(field)
        if params.get("cwd") is not None and not self.same_path(params["cwd"]):
            raise PolicyDenied("cwd")
        roots = params.get("runtimeWorkspaceRoots")
        if (
            roots is not None
            and roots != []
            and (not isinstance(roots, list) or len(roots) != 1 or not self.same_path(roots[0]))
        ):
            raise PolicyDenied("roots")
        if params.get("approvalPolicy") not in (None, "never"):
            raise PolicyDenied("approval")
        if params.get("permissions") not in (None, "verity", "read-only"):
            raise PolicyDenied("permissions")
        if params.get("sandbox") not in (None, "read-only"):
            raise PolicyDenied("sandbox")
        sandbox = params.get("sandboxPolicy")
        if sandbox is not None and not (
            isinstance(sandbox, dict)
            and sandbox.get("type") == "readOnly"
            and sandbox.get("networkAccess") in (None, False)
        ):
            raise PolicyDenied("sandbox")
        for field in ("environments", "disabledPluginIds"):
            if params.get(field) not in (None, []):
                raise PolicyDenied(field)
        if params.get("modelProvider") not in (None, "verity"):
            raise PolicyDenied("provider")
        if params.get("approvalsReviewer") not in (None, "user"):
            raise PolicyDenied("reviewer")
        collaboration = params.get("collaborationMode")
        if collaboration is not None:
            if not isinstance(collaboration, dict) or collaboration.get("mode") != "default":
                raise PolicyDenied("collaboration")
            # Native resume includes the CLI's default-mode developer template. It is
            # client supplied: discard it and keep the server's fixed task instructions.
            # Rejecting the whole turn here also rejects an ordinary "continue" message.
            params["collaborationMode"] = None
        config = params.get("config")
        if config is not None:
            if not isinstance(config, dict) or not self.subset(config, self.config):
                raise PolicyDenied("config")
        if "input" in params:
            if not isinstance(params["input"], list):
                raise PolicyDenied("input")
            for part in params["input"]:
                if not isinstance(part, dict):
                    raise PolicyDenied("attachment")
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    continue
                if part.get("type") == "localImage" and isinstance(part.get("path"), str):
                    if os.path.normcase(str(Path(part["path"]).resolve())) in self.image_paths:
                        continue
                if (
                    part.get("type") == "image"
                    and isinstance(part.get("url"), str)
                    and part["url"] in self.image_urls
                ):
                    continue
                raise PolicyDenied("attachment")
        if method in self.THREAD_METHODS:
            params.pop("sandbox", None)
            params.pop("sandboxPolicy", None)
            params.update(approvalPolicy="never", permissions="verity", cwd=str(self.work))
            if method != "thread/settings/update":
                params["runtimeWorkspaceRoots"] = [str(self.work)]
            if method in ("thread/start", "thread/resume"):
                params["config"] = copy.deepcopy(self.config)
            if method == "thread/start":
                params["dynamicTools"] = []
        return {**message, "params": params} if "params" in message or params else message

    @staticmethod
    def denial(identity):
        return {
            "id": identity,
            "error": {
                "code": -32601,
                "message": "本平台仅开放本记录的CLI对话；本机命令、外部文件和权限变更已禁止。",
            },
        }
