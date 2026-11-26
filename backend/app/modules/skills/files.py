"""Fixed local Skill packages, shared locking, backups and atomic body updates."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from app.core.errors import AppError

ROOT = Path(__file__).resolve().parents[4] / "skill"
BACKUPS = Path(__file__).resolve().parents[3] / "storage" / "skill-backups"
REQUIREMENT_CONTRACT_HEADING = "# 需求风险报告调用契约（v{}）"
_CONTRACT_HEADING = re.compile(
    r"^# (?:需求风险报告调用契约（v|代码分析调用契约 v|变更分析调用契约 v|"
    r"用例生成(?:简化输出|调用)契约 v|CASE_REVIEW 契约)([1-9][0-9]*)）?[ \t]*$",
    re.MULTILINE,
)
REGISTRY = {
    "requirement-analysis": ("需求分析", 4, "spark"),
    "case-generation": ("用例生成", 3, "list"),
    "case-analysis": ("用例分析", 1, "chart"),
    "code-review": ("代码分析", 3, "code"),
    "change-impact": ("变更分析", 3, "branch"),
}
LIMIT = 200000
_VIEW_CACHE = {}
_VIEW_LOCKS = {key: RLock() for key in REGISTRY}
VIEW_TTL = 5


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def directory(key):
    if key not in REGISTRY:
        raise AppError(404, "skill_not_found")
    target = ROOT / key
    if ROOT.is_symlink() or target.is_symlink() or not target.is_dir():
        raise AppError(409, "skill_file_unavailable")
    return target


@contextmanager
def locked(key):
    directory(key)
    try:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        if BACKUPS.is_symlink():
            raise AppError(409, "skill_file_unavailable")
        with (BACKUPS / f"{key}.lock").open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b"1")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    except (OSError, UnicodeError):
        raise AppError(409, "skill_file_busy_or_unwritable") from None


def parts(text):
    prefix = re.match(r"^---\r?\n[\s\S]*?\r?\n---(?:\r?\n)*", text)
    prefix = prefix[0] if prefix else ""
    return prefix, text[len(prefix) :].replace("\r\n", "\n")


def _entries(key):
    folder = directory(key)
    resolved = folder.resolve()
    result = []
    for target in sorted(folder.rglob("*")):
        relative = target.relative_to(folder)
        if any(p.startswith(".") or p == "__pycache__" for p in relative.parts):
            continue
        if target.suffix == ".pyc" or target.is_dir():
            continue
        if target.is_symlink() or not target.resolve().is_relative_to(resolved):
            raise AppError(409, "skill_file_unavailable")
        info = target.stat()
        if len(result) >= 256 or info.st_size > 2 * 1024 * 1024:
            raise AppError(422, "skill_package_too_large")
        result.append((target, info))
    return result


def _signature(key, entries):
    return (
        str(ROOT.absolute()),
        tuple(
            (
                str(p.relative_to(ROOT / key)),
                s.st_dev,
                s.st_ino,
                s.st_size,
                s.st_mtime_ns,
                s.st_ctime_ns,
            )
            for p, s in entries
        ),
    )


def _bundle(key, entries=None):
    folder = directory(key)
    entries = _entries(key) if entries is None else entries
    signature = _signature(key, entries)
    result = []
    for target, _ in entries:
        relative = target.relative_to(folder)
        raw = target.read_bytes()
        text_type = target.suffix in {".md", ".json", ".py", ".txt"}
        name = relative.as_posix()
        result.append(
            {
                "id": digest(name)[:24],
                "path": name,
                "text": raw.decode("utf-8").replace("\r\n", "\n") if text_type else "",
                "type": target.suffix.lstrip(".") if text_type else "unsupported",
                "sha256": digest(raw),
                "usage": "current"
                if name in ("SKILL.md", "contract.md")
                else ("legacy" if name == "legacy-contract.md" else "reference"),
                "editable": name == "SKILL.md",
            }
        )
    if not all(any(f["path"] == n for f in result) for n in ("SKILL.md", "contract.md")):
        raise AppError(409, "skill_file_unavailable")
    current = instruction_paths(result)
    for file in result:
        if file["path"] in current:
            file["usage"] = "current"
    if _signature(key, _entries(key)) != signature:
        raise AppError(409, "skill_content_changed")
    main = next(f["text"] for f in result if f["path"] == "SKILL.md")
    version = re.search(r'^\s+version:\s*["\']?([0-9]+\.[0-9]+\.[0-9]+)', main, re.M)
    version = version[1] if version else (re.search(r"^# .*?([0-9]+\.[0-9]+\.[0-9]+)", main, re.M))
    version = version[1] if not isinstance(version, str) and version else version
    return {
        "key": key,
        "name": REGISTRY[key][0],
        "icon": REGISTRY[key][2],
        "version": version or "未标注",
        "token": digest(json.dumps([(f["path"], f["sha256"]) for f in result])),
        "files": result,
    }


def bundle(key):
    with locked(key):
        return _bundle(key)


def cached_bundle(key):
    """Management reads only; writes, AI enqueue and analysis snapshots bypass this cache."""
    from copy import deepcopy

    directory(key)
    with _VIEW_LOCKS[key], locked(key):
        try:
            entries = _entries(key)
            signature = _signature(key, entries)
            previous = _VIEW_CACHE.get(key)
            if previous and previous[1] == signature and time.monotonic() - previous[0] < VIEW_TTL:
                return deepcopy(previous[2])
            package = _bundle(key, entries)
            if _signature(key, _entries(key)) != signature:
                raise AppError(409, "skill_content_changed")
            # Five fixed keys, with a bounded cache even if development reference files grow.
            if sum(s.st_size for _, s in entries) <= 8 * 1024 * 1024:
                _VIEW_CACHE[key] = (time.monotonic(), signature, package)
            else:
                _VIEW_CACHE.pop(key, None)
            return deepcopy(package)
        except Exception:
            _VIEW_CACHE.pop(key, None)
            raise


def instruction_paths(entries):
    by_path = {f["path"]: f for f in entries}
    manifest = by_path.get("resources.json")
    if manifest is None:
        if re.search(
            r'^\s+resources:\s*["\']?resources\.json["\']?\s*$', by_path["SKILL.md"]["text"], re.M
        ):
            raise AppError(409, "skill_resources_invalid")
        return ["SKILL.md", "contract.md"]
    try:

        def unique_pairs(pairs):
            if len(dict(pairs)) != len(pairs):
                raise ValueError()
            return dict(pairs)

        value = json.loads(manifest["text"], object_pairs_hook=unique_pairs)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "instructions"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValueError()
        paths = value["instructions"]
        if (
            not isinstance(paths, list)
            or not 2 <= len(paths) <= 256
            or any(not isinstance(p, str) for p in paths)
            or len(set(paths)) != len(paths)
            or paths[0] != "SKILL.md"
            or paths[-1] != "contract.md"
        ):
            raise ValueError()
        for path in paths:
            if (
                path not in by_path
                or by_path[path]["type"] != "md"
                or any(p in ("", ".", "..") or p.startswith(".") for p in path.split("/"))
                or any(c in path for c in "\\:\x00")
                or not by_path[path]["text"].strip()
            ):
                raise ValueError()
        return paths
    except (ValueError, TypeError):
        raise AppError(409, "skill_resources_invalid") from None


def snapshot(key):
    package = bundle(key)
    by_path = {f["path"]: f for f in package["files"]}
    contract_version = REGISTRY[key][1]
    heading = _CONTRACT_HEADING.match(by_path["contract.md"]["text"])
    if heading is None or int(heading[1]) != contract_version:
        raise AppError(409, "skill_contract_mismatch")
    selected = [by_path[name] for name in instruction_paths(package["files"])]
    manifest = by_path.get("resources.json")
    text = "\n\n".join(
        f"文件：{f['path']}\n\n{f['text']}" if manifest else f["text"] for f in selected
    )
    result = {
        "version": package["version"],
        "contract_version": contract_version,
        "sha256": digest(text),
        "instructions": text,
    }
    if manifest:
        result["files"] = [{k: f[k] for k in ("path", "text", "sha256")} for f in selected]
        result["resources"] = {k: manifest[k] for k in ("path", "text", "sha256")}
    return result


def public(package):
    return {
        **package,
        "file_count": len(package["files"]),
        "files": [{k: v for k, v in f.items() if k != "text"} for f in package["files"]],
    }


def verify_snapshot_contract(snapshot):
    """Reject known mismatches in frozen instructions before sending a model request."""
    versions = _CONTRACT_HEADING.findall(snapshot["instructions"])
    version = snapshot.get("contract_version")
    if versions and version is not None and int(versions[-1]) != version:
        raise AppError(409, "skill_contract_mismatch")


def model_context(snapshot):
    """Build protocol messages only from frozen rules; never read current files on retry."""
    verify_snapshot_contract(snapshot)
    instructions = snapshot["instructions"]
    entries = snapshot.get("files")
    if entries is None:
        return instructions, []
    try:
        if not isinstance(entries, list) or len(entries) < 2:
            raise ValueError()
        paths = [f["path"] for f in entries]
        if (
            paths[0] != "SKILL.md"
            or paths[-1] != "contract.md"
            or len(set(paths)) != len(paths)
            or snapshot["sha256"] != digest(instructions)
        ):
            raise ValueError()
        parts = [f"文件：{f['path']}\n\n{f['text']}" for f in entries]
        if "\n\n".join(parts) != instructions:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise AppError(409, "skill_snapshot_missing") from None
    messages = (
        [{"role": "developer", "content": [{"type": "input_text", "text": p} for p in parts[1:-1]]}]
        if len(parts) > 2
        else []
    )
    return "\n\n".join((parts[0], parts[-1])), messages


def _atomic(path, raw):
    handle, name = tempfile.mkstemp(prefix=".skill-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            shutil.copymode(path, name, follow_symlinks=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_body(key, payload, actor_id):
    with locked(key):
        package = _bundle(key)
        target = directory(key) / "SKILL.md"
        old = target.read_bytes()
        prefix, _ = parts(old.decode("utf-8"))
        body = payload.body.replace("\r\n", "\n")
        if not body.strip() or len(body) > LIMIT:
            raise AppError(422, "skill_body_invalid")
        newline = "\r\n" if b"\r\n" in old else "\n"
        new = (prefix + body.replace("\n", newline)).encode("utf-8")
        receipt = BACKUPS / f"{key}-{payload.request_id}.json"
        fingerprint = digest(f"{actor_id}:{payload.expected_token}:{body}")
        if receipt.exists():
            record = json.loads(receipt.read_text(encoding="utf-8"))
            if record["fingerprint"] != fingerprint:
                raise AppError(409, "skill_request_conflict")
            if digest(old) == record["after"]:
                if record.get("state") != "SAVED":
                    record["state"] = "SAVED"
                    _atomic(receipt, json.dumps(record, ensure_ascii=False).encode())
                return public(package)
            if record.get("state") == "SAVED":
                raise AppError(409, "skill_content_changed")
        else:
            record = {
                "actor_id": actor_id,
                "skill": key,
                "fingerprint": fingerprint,
                "before": digest(old),
                "after": digest(new),
                "created_at": datetime.now(UTC).isoformat(),
            }
        if package["token"] != payload.expected_token:
            raise AppError(409, "skill_content_changed")
        if old == new:
            return public(package)
        backup = BACKUPS / f"{key}-{payload.request_id}.before"
        if not backup.exists():
            with backup.open("xb") as stream:
                stream.write(old)
                stream.flush()
                os.fsync(stream.fileno())
        elif digest(backup.read_bytes()) != record["before"]:
            raise AppError(409, "skill_request_conflict")
        _atomic(receipt, json.dumps(record, ensure_ascii=False).encode())
        # Recheck after durable backup: editors outside this application do not share its lock.
        if target.is_symlink() or target.read_bytes() != old:
            raise AppError(409, "skill_content_changed")
        _atomic(target, new)
        _VIEW_CACHE.pop(key, None)
        record["state"] = "SAVED"
        _atomic(receipt, json.dumps(record, ensure_ascii=False).encode())
        return public(_bundle(key))
