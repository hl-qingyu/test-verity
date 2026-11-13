"""Fixed MCP stdio reader for one owned input.json; no shell, network or platform imports."""

import hashlib
import json
import mmap
import sys
from pathlib import Path

CHUNK = 32768


class TaskFiles:
    def __init__(self, directory):
        self.root = Path(directory).resolve(strict=True)
        self.path = self.root / "input.json"
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("invalid_task_file")
        self.size = self.path.stat().st_size
        with self.path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256")
        self.sha256 = digest.hexdigest()

    def check(self, arguments):
        if arguments.get("path", "input.json") != "input.json" or self.path.is_symlink():
            raise ValueError("task_file_not_allowed")
        if self.path.resolve(strict=True).parent != self.root:
            raise ValueError("task_file_not_allowed")

    def read(self, arguments):
        self.check(arguments)
        start = arguments.get("offset_bytes", 0)
        limit = arguments.get("max_bytes", CHUNK)
        if (
            type(start) is not int
            or type(limit) is not int
            or not 0 <= start <= self.size
            or not 4 <= limit <= CHUNK
        ):
            raise ValueError("invalid_range")
        with self.path.open("rb") as source:
            source.seek(start)
            data = source.read(limit)
        # The next byte position is always a UTF-8 boundary, preserving complete characters.
        while data:
            try:
                text = data.decode("utf-8")
                break
            except UnicodeDecodeError as error:
                if error.start < len(data) - 3:
                    raise ValueError("offset_must_be_utf8_boundary") from None
                data = data[: error.start]
        else:
            text = ""
        next_offset = start + len(data)
        return {
            "path": "input.json",
            "offset_bytes": start,
            "next_offset_bytes": next_offset,
            "size_bytes": self.size,
            "eof": next_offset == self.size,
            "sha256": self.sha256,
            "text": text,
        }

    def search(self, arguments):
        self.check(arguments)
        query, start = arguments.get("query"), arguments.get("offset_bytes", 0)
        if (
            not isinstance(query, str)
            or not 0 < len(query) <= 1000
            or type(start) is not int
            or not 0 <= start <= self.size
        ):
            raise ValueError("invalid_search")
        matches, next_offset = [], start
        if self.size:
            with (
                self.path.open("rb") as source,
                mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data,
            ):
                needle = query.encode()
                while len(matches) < 20:
                    position = data.find(needle, next_offset)
                    if position < 0:
                        next_offset = self.size
                        break
                    matches.append(position)
                    next_offset = position + len(needle)
        return {
            "path": "input.json",
            "match_offsets_bytes": matches,
            "next_offset_bytes": next_offset,
            "eof": next_offset >= self.size,
            "size_bytes": self.size,
            "sha256": self.sha256,
        }


def schema(name, description, properties, required=()):
    return {
        "name": name,
        "description": description,
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


TOOLS = [
    schema(
        "read_input",
        "Read a complete UTF-8 byte range of the fixed input.json; "
        "use next_offset_bytes to continue. All source roles and content are preserved.",
        {
            "path": {"type": "string", "enum": ["input.json"]},
            "offset_bytes": {"type": "integer", "minimum": 0},
            "max_bytes": {"type": "integer", "minimum": 4, "maximum": CHUNK},
        },
    ),
    schema(
        "search_input",
        "Find literal text in the complete fixed input.json; returns byte positions "
        "for read_input. No regular expressions or other files.",
        {
            "path": {"type": "string", "enum": ["input.json"]},
            "query": {"type": "string", "minLength": 1, "maxLength": 1000},
            "offset_bytes": {"type": "integer", "minimum": 0},
        },
        ["query"],
    ),
]


def main():
    files = TaskFiles(sys.argv[1])
    for line in sys.stdin.buffer:
        message = None
        if len(line) > 65536:
            continue
        try:
            message = json.loads(line)
            method = message.get("method")
            if "id" not in message:
                continue
            if method == "initialize":
                result = {
                    "protocolVersion": message.get("params", {}).get(
                        "protocolVersion", "2024-11-05"
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "verity-task-input", "version": "1"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = message.get("params", {})
                name = params.get("name")
                if name not in ("read_input", "search_input"):
                    raise ValueError("tool_not_allowed")
                value = (files.read if name == "read_input" else files.search)(
                    params.get("arguments", {})
                )
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                    "isError": False,
                }
            else:
                raise ValueError("method_not_allowed")
            response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32602, "message": "Invalid fixed task input request"},
            }
        sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
