"""Shared fixed configuration for the three supported Codex launch profiles."""

import json
from pathlib import Path
from typing import Literal

from app.integrations import codex_filesystem


def build(
    profile: Literal["exec", "terminal", "probe"],
    work: Path,
    base_url: str,
    effort: str,
    instruction_file: Path | None,
) -> list[str]:
    provider = {
        "name": "Verity",
        "base_url": base_url,
        "env_key": "VERITY_CODEX_KEY",
        "wire_api": "responses",
    }
    if profile == "probe":
        provider.update(request_max_retries=0, stream_max_retries=0)
    overrides = {
        "model_provider": '"verity"',
        "model_providers.verity": "{"
        + ",".join(f"{k}={json.dumps(v)}" for k, v in provider.items())
        + "}",
        "approval_policy": '"never"',
        "web_search": '"disabled"',
        "mcp_servers": "{}",
        "plugins": "{}",
        "project_doc_max_bytes": "0",
    }
    for feature in (
        "shell_tool",
        "multi_agent",
        "apply_patch_freeform",
        "view_image",
        "plugins",
        "apps",
        "hooks",
        "shell_snapshot",
    ):
        overrides["features." + feature] = "false"
    if profile == "probe":
        overrides["model_post_turn_compact_threshold_percent"] = "0"
    else:
        permissions = {":root": "deny", ":minimal": "read", str(work): "read"}
        overrides.update(
            {
                "default_permissions": '"verity"',
                "permissions.verity.filesystem": "{"
                + ",".join(f"{json.dumps(k)}={json.dumps(v)}" for k, v in permissions.items())
                + "}",
                "permissions.verity.network.enabled": "false",
            }
        )
    if profile == "terminal":
        spellings = dict.fromkeys(
            (str(work), str(work).lower(), work.as_posix(), work.as_posix().lower())
        )
        overrides["project_root_markers"] = '[".verity-cli-root"]'
        overrides["projects"] = (
            "{"
            + ",".join(json.dumps(path) + '={trust_level="trusted"}' for path in spellings)
            + "}"
        )
        overrides["mcp_servers"] = (
            "{filesystem={"
            + ",".join(
                f"{k}={json.dumps(v)}" for k, v in codex_filesystem.configuration(work).items()
            )
            + "}}"
        )
    if instruction_file is not None:
        overrides["model_instructions_file"] = json.dumps(str(instruction_file))
    if effort != "default":
        overrides["model_reasoning_effort"] = json.dumps(effort)
    return [arg for key, value in overrides.items() for arg in ("-c", f"{key}={value}")]
