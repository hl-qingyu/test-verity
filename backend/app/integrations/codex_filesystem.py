"""Configuration for the upstream MCP filesystem server; no custom file tools."""

import shutil
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError

READ_ONLY_TOOLS = (
    "read_file",
    "read_text_file",
    "read_media_file",
    "read_multiple_files",
    "list_directory",
    "list_directory_with_sizes",
    "directory_tree",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
)


def configuration(work: Path) -> dict:
    node = Settings().ai_cli_node_executable or shutil.which("node")
    server = (
        Path(__file__).resolve().parents[2]
        / "mcp"
        / "node_modules"
        / "@modelcontextprotocol"
        / "server-filesystem"
        / "dist"
        / "index.js"
    )
    if not node or not Path(node).is_absolute() or not Path(node).is_file():
        raise AppError(503, "ai_cli_node_unavailable")
    if not server.is_file():
        raise AppError(503, "ai_cli_filesystem_not_installed")
    try:
        version = subprocess.run(
            [str(node), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if version.returncode or int(version.stdout.strip().lstrip("v").split(".")[0]) < 24:
            raise ValueError("unsupported_node")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise AppError(503, "ai_cli_node_unavailable") from None
    return {
        "command": str(node),
        "args": [str(server), "--read-only", "--confine-roots", str(work.resolve())],
        "cwd": str(work.resolve()),
        "required": True,
        "startup_timeout_sec": 15,
        "default_tools_approval_mode": "auto",
    }
