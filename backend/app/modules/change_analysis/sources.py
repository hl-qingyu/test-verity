"""Prepare authorized double snapshots; retain fixed content rather than live labels."""

import copy
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

from app.core.errors import AppError
from app.db.models import SourceDocument
from app.integrations import github
from app.modules.cases import service as cases
from app.modules.cases.schemas import EditScope
from app.modules.change_analysis import artifacts, contract
from app.modules.code_analysis import sources as code_sources
from app.modules.documents import service as documents
from app.modules.github.service import saved_token
from app.modules.prototypes import directories
from app.modules.prototypes import service as prototypes
from app.modules.prototypes.schemas import GitScope
from app.modules.requirements import analysis_materials, risk_service
from app.modules.skills import files as skill_files
from app.security.source_content import contains_private_key

digest = code_sources.digest
logger = logging.getLogger(__name__)


def skill_snapshot():
    return skill_files.snapshot("change-impact")


def document(project_id, source_id, actor, db):
    documents.access(project_id, actor, db)
    row = db.get(SourceDocument, source_id, populate_existing=True)
    contract.require(
        row is not None and row.project_id == project_id and row.deleted_at is None,
        "change_material_unavailable",
    )
    return row


def selection(pair, side):
    return {
        "kind": "LOCAL" if pair["kind"] == "LOCAL_CODE" else "GITHUB",
        "source_id": pair["source_id"],
        "source_version": pair["source_version"],
        "connection_id": pair["connection_id"],
        "commit": pair[side + "_ref"],
    }


def recheck(project_id, metadata, actor, db, *, shared_snapshot=False):
    documents.access(project_id, actor, db)
    for binding in metadata.get("bindings", []):
        if binding.get("definition"):
            row = document(project_id, binding["document_id"], actor, db)
            current = {
                "kind": row.kind,
                "repository_id": row.repository_id,
                "path": row.path,
                "url": row.url,
            }
            contract.require(current == binding["definition"], "change_source_changed")
    if metadata.get("origin") == "IMPORT":
        for binding in metadata.get("bindings", []):
            if binding.get("document_id"):
                row = document(project_id, binding["document_id"], actor, db)
                if binding.get("version_id"):
                    _, v = documents.stored_version(project_id, binding["version_id"], actor, db)
                    contract.require(v.document_id == row.id)
            if binding.get("source_id"):
                code_sources.source_authorization(
                    project_id, binding, actor, db, shared_snapshot=shared_snapshot
                )
        return
    raw = metadata["selections"]
    contract.require(raw["confirmed"], "change_scope_confirmation_required")
    for p in raw["pairs"]:
        kind = p["kind"]
        if kind in {"GITHUB_CODE", "LOCAL_CODE"}:
            contract.require(raw["mode"] == "CODE_CHANGE" and p["update_mode"] == "CODE_SNAPSHOT")
            code_sources.source_authorization(
                project_id, selection(p, "after"), actor, db, shared_snapshot=shared_snapshot
            )
        else:
            row = document(project_id, p["source_id"], actor, db)
            if kind == "DIRECTORY_PROTOTYPE":
                contract.require(raw["mode"] == "PROTOTYPE_CHANGE" and row.kind == "DIRECTORY")
                before, old = directories.checked(
                    project_id,
                    row.id,
                    p["before_version_id"],
                    p["paths"],
                    actor,
                    db,
                    allow_absent=True,
                )
                after, new = directories.checked(
                    project_id,
                    row.id,
                    p["after_version_id"],
                    p["paths"],
                    actor,
                    db,
                    allow_absent=True,
                )
                contract.require(
                    before.id != after.id
                    and all(path in old or path in new for path in p["paths"]),
                    "change_same_version",
                )
            elif kind == "FILE":
                expected = "REQUIREMENT" if raw["mode"] == "REQUIREMENT_CHANGE" else "PROTOTYPE"
                contract.require(
                    raw["mode"] != "CODE_CHANGE" and row.kind == "FILE" and row.purpose == expected
                )
                target = document(project_id, p.get("after_document_id") or row.id, actor, db)
                contract.require(target.kind == "FILE" and target.purpose == expected)
                for sid, vid in (
                    (row.id, p["before_version_id"]),
                    (target.id, p["after_version_id"]),
                ):
                    _, v = documents.stored_version(project_id, vid, actor, db)
                    contract.require(v.document_id == sid, "change_material_binding_mismatch")
                contract.require(
                    p["before_version_id"] != p["after_version_id"], "change_same_version"
                )
            else:
                contract.require(raw["mode"] == "PROTOTYPE_CHANGE" and row.purpose == "PROTOTYPE")
                if kind == "GITHUB_PROTOTYPE":
                    contract.require(row.kind == "GITHUB" and p["paths"] and p["connection_id"])
                    connection_id = p["connection_id"]
                    if shared_snapshot:
                        connection_id = next(
                            (
                                c["id"]
                                for c in prototypes.options(project_id, actor, db)
                                if any(r["id"] == row.repository_id for r in c["repositories"])
                            ),
                            None,
                        )
                        contract.require(connection_id, "github_repository_not_allowed")
                    prototypes.authorization(
                        project_id,
                        GitScope(
                            connection_id=connection_id,
                            repository_id=row.repository_id,
                            branch=p["after_ref"],
                            path=row.path or "",
                        ),
                        actor,
                        db,
                    )
                else:
                    contract.require(
                        row.kind == "LINK"
                        and row.url == p["url"]
                        and p["baseline_report_id"]
                        and p["paths"]
                        and re.fullmatch(r"[0-9a-f]{64}", p["snapshot"]),
                        "change_link_baseline_required",
                    )
                    link_baseline(project_id, p, actor, db)
        if kind.startswith("GITHUB"):
            contract.require(
                p["before_ref"] != p["after_ref"]
                and all(re.fullmatch(r"[0-9a-f]{40}", p[s + "_ref"]) for s in ("before", "after")),
                "change_ref_invalid",
            )
        if kind == "LOCAL_CODE":
            contract.require(
                p["before_local"]
                and p["after_local"]
                and p["before_local"]["ref"] != p["after_local"]["ref"],
                "change_local_baseline_required",
            )
    if raw["sources"]:
        code_sources.validate_selections(
            project_id,
            {"sources": raw["sources"], "materials": raw["materials"], "targets": ["BUG"]},
            actor,
            db,
            shared_snapshot=shared_snapshot,
        )
    else:
        for m in raw["materials"]:
            code_sources.material_authorization(project_id, m, actor, db)
    if "FRONTEND_BACKEND_MISMATCH" in raw["targets"]:
        roles = set()
        for p in raw["pairs"]:
            if p["kind"] in {"GITHUB_CODE", "LOCAL_CODE"}:
                row, _ = code_sources.source_authorization(
                    project_id, selection(p, "after"), actor, db, shared_snapshot=shared_snapshot
                )
                if p["paths"] and (
                    p["kind"] == "GITHUB_CODE"
                    or p["after_local"]
                    and any(f["content"].strip() for f in p["after_local"]["files"])
                ):
                    roles.add(row.kind)
        for src in raw["sources"]:
            row, _ = code_sources.source_authorization(
                project_id, src, actor, db, shared_snapshot=shared_snapshot
            )
            if src["files"] and (
                src["kind"] == "GITHUB" or any(f.get("content", "").strip() for f in src["files"])
            ):
                roles.add(row.kind)
        contract.require(
            "BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}), "change_both_sides_required"
        )
    for h in raw["historical_items"]:
        if h["module"] == "REQUIREMENT_ANALYSIS":
            report = risk_service.detail(project_id, h["report_id"], actor, db)
            contract.require(
                any(r["key"] == h["item_key"] for r in report["report"]["risks"]),
                "change_history_unavailable",
            )
        else:
            from app.modules.code_analysis import service as code_service

            report = code_service.detail(project_id, h["report_id"], actor, db)
            contract.require(
                report["status"] == "COMPLETED"
                and any(r["key"] == h["item_key"] for r in report["report"]["findings"]),
                "change_history_unavailable",
            )


def link_baseline(project_id, pair, actor, db):
    report = risk_service.detail(project_id, pair["baseline_report_id"], actor, db)
    binding = next(
        (
            b
            for b in report["bindings"]
            if b["document_id"] == pair["source_id"]
            and b.get("kind") == "LINK"
            and b.get("url") == pair["url"]
            and not b["deleted"]
        ),
        None,
    )
    material = next(
        (
            m
            for m in report["input"]["materials"]
            if binding and m["source_id"] == binding["source_id"]
        ),
        None,
    )
    contract.require(
        material
        and material.get("origin") == "PROTOTYPE"
        and material.get("kind") == "LINK"
        and bool(material.get("snapshot_ref"))
        and material["snapshot_ref"].upper() not in {"URL", "NOT_LOADED"}
        and not material["snapshot_ref"].startswith(("http://", "https://"))
        and material["read_state"] in {"READABLE", "PARTIAL"}
        and any(
            s["text"].strip() and s["text"].strip() != pair["url"] for s in material["segments"]
        ),
        "change_link_baseline_required",
    )
    return copy.deepcopy(material)


def unit(uid, path, text=None, *, state="READABLE", note="", presence="PRESENT", segments=None):
    if segments is None:
        segments = (
            []
            if text is None or text == ""
            else [
                {
                    "segment_id": "full",
                    "location": path,
                    "start_line": 1,
                    "text": text,
                    "image_ref": "",
                }
            ]
        )
    readable = presence == "PRESENT" and state in {"READABLE", "PARTIAL"}
    return {
        "unit_id": uid,
        "path": path,
        "presence": presence,
        "read_state": state,
        "read_note": note,
        "content_sha256": hashlib.sha256(
            "\n".join(s["text"] for s in segments).encode()
        ).hexdigest()
        if readable
        else "",
        "segments": segments,
    }


def snapshot(
    ref,
    sid,
    kind,
    name,
    version,
    origin,
    units,
    *,
    role="NONE",
    commit="",
    complete=True,
    note="",
    captured=None,
):
    return {
        "snapshot_ref": ref,
        "source_id": sid,
        "kind": kind,
        "repository_kind": role,
        "name": name or sid,
        "provenance": {
            "source_kind": origin,
            "version_ref": version,
            "commit": commit,
            "captured_at": captured or datetime.now(UTC).isoformat(),
        },
        "scope_complete": complete,
        "scope_note": note,
        "units": units,
    }


def file_snapshot(project_id, sid, vid, ref, actor, db):
    row = document(project_id, sid, actor, db)
    path, version = documents.stored_version(project_id, vid, actor, db)
    contract.require(row.kind == "FILE" and version.document_id == row.id)
    material = analysis_materials.file_material(path, version.extension, ref, version.filename)
    contract.require(material["snapshot_ref"] == version.sha256, "change_source_changed")
    segments = [{**s, "start_line": None} for s in material["segments"]]
    u = unit(
        "document",
        version.filename,
        state=material["read_state"],
        note=material["read_note"],
        segments=segments,
    )
    result = snapshot(
        ref, f"document-{sid}", row.purpose, version.filename, f"version-{vid}", "UPLOAD", [u]
    )
    binding = {
        "snapshot_ref": ref,
        "document_id": sid,
        "version_id": vid,
        "binary_sha256": material["snapshot_ref"],
    }
    binaries = (
        [(path, version.extension, ref, version.filename)]
        if version.extension in {"pdf", "png", "jpg", "jpeg", "webp"}
        else []
    )
    return result, binding, binaries


def directory_snapshot(project_id, pair, side, ref, actor, db):
    sid, vid, paths = pair["source_id"], pair[side + "_version_id"], pair["paths"]
    row = document(project_id, sid, actor, db)
    version, index = directories.checked(project_id, sid, vid, paths, actor, db, allow_absent=True)
    present = [p for p in paths if p in index]
    material, binaries = (
        directories.material(project_id, sid, vid, present, ref, actor, db)
        if present
        else ({"segments": []}, [])
    )
    numbers = {p: n for n, p in enumerate(present, 1)}
    units = []
    for n, path in enumerate(paths):
        prefix = f"f{numbers.get(path, 0)}"
        segments = [
            {**s, "start_line": None}
            for s in material["segments"]
            if s["segment_id"] == prefix or s["segment_id"].startswith(prefix + "-")
        ]
        units.append(
            unit(
                f"u{n}",
                path,
                presence="PRESENT" if path in index else "VERIFIED_ABSENT",
                state="NOT_LOADED"
                if path not in index
                else "READABLE"
                if segments
                else "UNREADABLE",
                note="固定目录版本内不存在此路径"
                if path not in index
                else "未执行脚本；仅提供所选文件；原件SHA-256=" + index[path]["sha256"],
                segments=segments,
            )
        )
    result = snapshot(
        ref,
        f"document-{sid}",
        "PROTOTYPE",
        row.name,
        f"version-{vid}",
        "UPLOAD",
        units,
        note="按两个固定目录版本的所选相对路径核对；未选择的依赖未读取",
    )
    return (
        result,
        {
            "snapshot_ref": ref,
            "document_id": sid,
            "version_id": vid,
            "binary_sha256": version.sha256,
            "paths": present,
            "directory": True,
        },
        binaries,
    )


def in_scope(path, scope):
    return any(p in {"", "/"} or path == p or p.endswith("/") and path.startswith(p) for p in scope)


def github_text(project_id, repository_id, token, full_name, entry):
    contract.require(type(entry["size"]) is int and entry["size"] >= 0, "github_invalid_response")
    content = artifacts.load_blob(project_id, repository_id, entry["sha"])
    cached = content is not None
    if content is None:
        content = github.prototype_content(token, full_name, entry["sha"])
    contract.require(len(content) == entry["size"], "github_invalid_response")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError:
        raise AppError(422, "code_text_required") from None
    contract.require("\x00" not in text, "code_text_required")
    contract.require(not contains_private_key(text), "code_private_key_content")
    if not cached:
        artifacts.save_blob(project_id, repository_id, entry["sha"], content)
    return text.replace("\r\n", "\n").replace("\r", "\n"), cached


def code_snapshot(project_id, pair, side, ref, actor, db, *, shared_snapshot=False):
    row, connection = code_sources.source_authorization(
        project_id, selection(pair, side), actor, db, shared_snapshot=shared_snapshot
    )
    role, name = row.kind, row.full_name if connection else row.name
    paths = pair["paths"]
    contract.require(paths and len(paths) == len(set(paths)))
    contract.require(all(contract.safe_path(p) for p in paths), "code_path_excluded")
    units = []
    if connection:
        token, gid, connection_version = saved_token(connection), row.github_id, connection.version
        commit = pair[side + "_ref"]
        db.rollback()
        logger.info(
            "change_source_read source_id=%s side=%s stage=tree total=%s",
            pair["source_id"],
            side,
            len(paths),
        )
        try:
            scope = github.code_scope(token, gid, commit, include_presence=True)
        except AppError:
            logger.warning(
                "change_source_read_failed source_id=%s side=%s stage=tree", pair["source_id"], side
            )
            raise
        contract.require(scope["commit"] == commit, "change_source_changed")
        manifest = {f["path"]: f for f in scope["files"]}
        reused = 0
        for n, path in enumerate(paths):
            entry = manifest.get(path)
            if entry is None:
                contract.require("present_paths" in scope, "github_invalid_response")
                if path in scope["present_paths"]:
                    units.append(
                        unit(
                            f"u{n}",
                            path,
                            state="UNREADABLE",
                            note="固定提交中路径存在，但不是可读普通代码文件；不作为删除",
                        )
                    )
                    continue
                units.append(
                    unit(
                        f"u{n}",
                        path,
                        state="NOT_LOADED",
                        presence="VERIFIED_ABSENT",
                        note="固定提交完整文件清单中不存在该路径",
                    )
                )
            else:
                try:
                    text, cached = github_text(project_id, gid, token, scope["full_name"], entry)
                except AppError:
                    logger.warning(
                        "change_source_read_failed source_id=%s side=%s "
                        "stage=blob index=%s total=%s",
                        pair["source_id"],
                        side,
                        n + 1,
                        len(paths),
                    )
                    raise
                reused += cached
                units.append(
                    unit(
                        f"u{n}",
                        path,
                        text,
                        note=("旧基准全文" if side == "before" else "新目标全文")
                        + f"；固定Git blob={entry['sha']}；"
                        + (
                            "复用经哈希校验的正文，版本归属仍以本快照提交为准"
                            if cached
                            else "本次只读取得正文"
                        ),
                    )
                )
            if (n + 1) % 100 == 0 or n + 1 == len(paths):
                logger.info(
                    "change_source_read source_id=%s side=%s "
                    "stage=blob completed=%s total=%s reused=%s",
                    pair["source_id"],
                    side,
                    n + 1,
                    len(paths),
                    reused,
                )
        _, current = code_sources.source_authorization(
            project_id, selection(pair, side), actor, db, shared_snapshot=shared_snapshot
        )
        contract.require(current.version == connection_version, "github_connection_changed")
        version, captured = commit, None
    else:
        local = pair[side + "_local"]
        contract.require(local and local["ref"])
        files = {f["path"]: f for f in local["files"]}
        contract.require(len(files) == len(local["files"]))
        for n, path in enumerate(paths):
            file = files.get(path)
            if file:
                contract.require(
                    hashlib.sha256(file["content"].encode()).hexdigest() == file["sha256"],
                    "code_content_changed",
                )
                units.append(
                    unit(f"u{n}", path, file["content"].replace("\r\n", "\n").replace("\r", "\n"))
                )
            elif not in_scope(path, local["scope"]):
                units.append(
                    unit(
                        f"u{n}",
                        path,
                        state="NOT_LOADED",
                        presence="OUT_OF_SCOPE",
                        note="该路径不在这次浏览器读取范围内，不代表磁盘删除",
                    )
                )
            elif any(path == p or path.startswith(p.rstrip("/") + "/") for p in local["skipped"]):
                units.append(
                    unit(
                        f"u{n}",
                        path,
                        state="UNREADABLE",
                        note="浏览器快照记录该文件或上级目录读取失败",
                    )
                )
            else:
                units.append(
                    unit(
                        f"u{n}",
                        path,
                        state="NOT_LOADED",
                        presence="VERIFIED_ABSENT",
                        note="浏览器已完成的此范围读取清单不存在该路径；非文件系统原子快照",
                    )
                )
        version, captured, commit = local["ref"], local["captured_at"], ""
    return snapshot(
        ref,
        f"{pair['kind']}-{pair['source_id']}",
        "CODE",
        name,
        version,
        "GITHUB" if connection else "LOCAL",
        units,
        role=role,
        commit=commit,
        captured=captured,
        note="旧基准：所选范围完整正文"
        if side == "before"
        else "新目标：按固定版本组装所选范围完整正文，不省略未变文件",
    )


def prototype_git(project_id, pair, side, ref, actor, db, *, shared_snapshot=False):
    row = document(project_id, pair["source_id"], actor, db)
    stored = (row.repository_id, row.path or "", row.current_version)
    connection_id = pair["connection_id"]
    if shared_snapshot:
        connection_id = next(
            (
                c["id"]
                for c in prototypes.options(project_id, actor, db)
                if any(r["id"] == stored[0] for r in c["repositories"])
            ),
            None,
        )
        contract.require(connection_id, "github_repository_not_allowed")
    payload = GitScope(
        connection_id=connection_id,
        repository_id=stored[0],
        branch=pair[side + "_ref"],
        path=stored[1],
    )
    repo, connection = prototypes.authorization(project_id, payload, actor, db)
    token, gid, version = saved_token(connection), repo.github_id, connection.version
    db.rollback()
    scope = github.prototype_scope(
        token, gid, payload.branch, payload.path, include_presence=True, allow_empty=True
    )
    contract.require(scope["commit"] == payload.branch, "change_ref_invalid")
    entries, units = {f["path"]: f for f in scope["files"]}, []
    for n, path in enumerate(pair["paths"]):
        contract.require(github.valid_material_path(path), "change_path_invalid")
        contract.require(
            path in entries
            or not stored[1]
            or path == stored[1]
            or path.startswith(stored[1] + "/")
        )
        entry = entries.get(path)
        if not entry:
            contract.require("present_paths" in scope, "github_invalid_response")
            if path in scope["present_paths"]:
                units.append(
                    unit(
                        f"u{n}",
                        path,
                        state="UNREADABLE",
                        note="固定提交中路径存在，但不是可读普通原型文件；不作为删除",
                    )
                )
                continue
            units.append(
                unit(
                    f"u{n}",
                    path,
                    state="NOT_LOADED",
                    presence="VERIFIED_ABSENT",
                    note="固定提交原型目录完整清单不存在该路径",
                )
            )
            continue
        contract.require(entry["size"] <= 2_000_000, "code_file_unavailable")
        text, _ = github_text(project_id, gid, token, scope["full_name"], entry)
        segs = [{**s, "start_line": None} for s in analysis_materials.text_segments(text, path)]
        units.append(
            unit(
                f"u{n}",
                path,
                state="PARTIAL",
                note="仅固定HTML/说明文本；未执行脚本或读取外部资源",
                segments=segs,
            )
        )
    _, current = prototypes.authorization(project_id, payload, actor, db)
    current_source = document(project_id, pair["source_id"], actor, db)
    contract.require(
        current.version == version
        and stored
        == (
            current_source.repository_id,
            current_source.path or "",
            current_source.current_version,
        ),
        "change_source_changed",
    )
    return snapshot(
        ref,
        f"document-{pair['source_id']}",
        "PROTOTYPE",
        row.name,
        payload.branch,
        "GITHUB",
        units,
        commit=payload.branch,
    )


def comparison(pid, a, b, update):
    mappings, diffs = [], []
    # File/whole-material pairing is user-confirmed. Rule matching remains the model's work.
    for n, (old, new) in enumerate(zip(a["units"], b["units"], strict=True)):
        mid = f"m{n}"
        left, right = (
            "\n".join(s["text"] for s in old["segments"]),
            "\n".join(s["text"] for s in new["segments"]),
        )
        note = "用户确认的比较范围；名称相似不证明规则对应"
        if a["kind"] == "CODE":
            if old["presence"] == "VERIFIED_ABSENT" and new["read_state"] == "READABLE":
                change = "新增"
            elif new["presence"] == "VERIFIED_ABSENT" and old["read_state"] == "READABLE":
                change = "删除"
            elif old["read_state"] != "READABLE" or new["read_state"] != "READABLE":
                change = "无法确定，须核对存在性或读取缺口"
            else:
                change = "正文修改" if left != right else "正文未变"
            note += (
                f"；文件状态={change}；旧基准={a['snapshot_ref']}:{old['path']}"
                f"；新目标={b['snapshot_ref']}:{new['path']}"
            )
        mappings.append(
            {
                "mapping_id": mid,
                "before_unit_ids": [old["unit_id"]],
                "after_unit_ids": [new["unit_id"]],
                "relation": "MATCH",
                "confirmed": True,
                "note": note,
            }
        )
        binary_change = (
            any(s["image_ref"] for s in old["segments"] + new["segments"])
            and old["read_note"] != new["read_note"]
        )
        if left != right or old["presence"] != new["presence"] or binary_change:
            opcodes = SequenceMatcher(
                None, left.splitlines(), right.splitlines(), autojunk=True
            ).get_opcodes()
            diffs.append(
                {
                    "diff_id": f"d{n}",
                    "mapping_ref": mid,
                    "before_segment_refs": [
                        {"unit_id": old["unit_id"], "segment_id": s["segment_id"]}
                        for s in old["segments"]
                    ],
                    "after_segment_refs": [
                        {"unit_id": new["unit_id"], "segment_id": s["segment_id"]}
                        for s in new["segments"]
                    ],
                    "note": "图片原件或存在状态发生变化，请对照双侧附件核对"
                    if binary_change
                    else json.dumps(
                        [list(op) for op in opcodes if op[0] != "equal"], ensure_ascii=False
                    ),
                }
            )
    return {
        "pair_id": pid,
        "name": f"{a['name']} → {b['name']}",
        "before_ref": a["snapshot_ref"],
        "after_ref": b["snapshot_ref"],
        "update_mode": update,
        "scope": list(dict.fromkeys(u["path"] for u in a["units"] + b["units"])),
        "scope_confirmed": True,
        "unit_mappings": mappings,
        "text_diffs": diffs,
    }


def prepare(project_id, request_id, raw, actor, db, *, shared_snapshot=False):
    metadata = {"origin": "AI", "selections": raw}
    recheck(project_id, metadata, actor, db, shared_snapshot=shared_snapshot)
    data = {
        "contract_version": 2,
        "analysis_type": "CHANGE_IMPACT",
        "request_id": request_id,
        "project_id": project_id,
        "revision": 1,
        "mode": raw["mode"],
        "targets": raw["targets"],
        "focus": raw["focus"],
        "comparison_pairs": [],
        "snapshots": [],
        "context_refs": [],
        "cases": [],
        "historical_items": [],
        "input_limitations": [],
    }
    bindings, binaries = [], []
    for n, p in enumerate(raw["pairs"], 1):
        if p["kind"] in {"GITHUB_PROTOTYPE", "LINK_PROTOTYPE"}:
            row = document(project_id, p["source_id"], actor, db)
            bindings.append(
                {
                    "snapshot_ref": f"p{n}-source",
                    "document_id": row.id,
                    "definition": {
                        "kind": row.kind,
                        "repository_id": row.repository_id,
                        "path": row.path,
                        "url": row.url,
                    },
                }
            )
        sides = []
        for side in ("before", "after"):
            ref = f"p{n}-{side}"
            if p["kind"] == "DIRECTORY_PROTOTYPE":
                s, binding, files = directory_snapshot(project_id, p, side, ref, actor, db)
                bindings.append(binding)
                binaries.extend(files)
            elif p["kind"] == "FILE":
                sid = (
                    (p.get("after_document_id") or p["source_id"])
                    if side == "after"
                    else p["source_id"]
                )
                s, binding, files = file_snapshot(
                    project_id, sid, p[side + "_version_id"], ref, actor, db
                )
                bindings.append(binding)
                binaries.extend(files)
            elif p["kind"] in {"GITHUB_CODE", "LOCAL_CODE"}:
                s = code_snapshot(
                    project_id, p, side, ref, actor, db, shared_snapshot=shared_snapshot
                )
            elif p["kind"] == "GITHUB_PROTOTYPE":
                s = prototype_git(
                    project_id, p, side, ref, actor, db, shared_snapshot=shared_snapshot
                )
            else:
                if side == "before":
                    m = link_baseline(project_id, p, actor, db)
                    segs, version = m["segments"], m["snapshot_ref"]
                else:
                    m = prototypes.link_pages(
                        project_id, p["source_id"], p["paths"], p["snapshot"], actor, db
                    )
                    segs, version = m["segments"], m["snapshot_ref"]
                segs = [
                    {
                        "segment_id": f"s{i}",
                        "location": s["location"],
                        "start_line": None,
                        "text": s["text"],
                        "image_ref": "",
                    }
                    for i, s in enumerate(segs)
                ]
                s = snapshot(
                    ref,
                    f"document-{p['source_id']}",
                    "PROTOTYPE",
                    "原型链接页面",
                    version,
                    "LINK",
                    [
                        unit(
                            "pages",
                            "selected-pages.html",
                            state="PARTIAL",
                            note="已固定所选页面HTML、说明及当时采集的批注引用正文；未执行脚本/视觉资源",
                            segments=segs,
                        )
                    ],
                    complete=False,
                    note="比较所选页面正文，未核实站点全部页面或跨版本页面对应",
                )
            sides.append(s)
        data["snapshots"].extend(sides)
        data["comparison_pairs"].append(comparison(f"p{n}", *sides, p["update_mode"]))
    if raw["sources"]:
        context, cb, files = code_sources.prepare(
            project_id,
            request_id,
            {
                "sources": raw["sources"],
                "materials": raw["materials"],
                "targets": ["BUG"],
                "focus": "",
            },
            actor,
            db,
            shared_snapshot=shared_snapshot,
            input_limit=None,
        )
        for n, src in enumerate(context["sources"]):
            ref = f"context-code-{n}"
            units = [
                unit(
                    f["file_id"],
                    f["path"],
                    segments=[
                        {**seg, "location": f["path"], "image_ref": ""} for seg in f["segments"]
                    ],
                )
                for f in src["files"]
            ]
            data["snapshots"].append(
                snapshot(
                    ref,
                    f"context-{n}",
                    "CODE",
                    src["name"],
                    src["snapshot_ref"],
                    src["source_kind"],
                    units,
                    role=src["repository_kind"],
                    commit=src["commit"],
                )
            )
            data["context_refs"].append(ref)
        # Material contexts below use the same existing readers and immutable file versions.
    for n, m in enumerate(raw["materials"]):
        ref = f"context-material-{n}"
        row = document(project_id, m["document_id"], actor, db)
        if row.kind == "FILE":
            s, binding, files = file_snapshot(project_id, row.id, m["version_id"], ref, actor, db)
            bindings.append(binding)
            binaries.extend(files)
        elif row.kind == "DIRECTORY":
            s, binding, files = directory_snapshot(
                project_id,
                {"source_id": row.id, "before_version_id": m["version_id"], "paths": m["paths"]},
                "before",
                ref,
                actor,
                db,
            )
            bindings.append(binding)
            binaries.extend(files)
        else:
            # Current live materials can be read by the existing code reader with a code context.
            contract.require(bool(raw["sources"]), "change_material_version_required")
            mat = context["materials"][n]
            segments = [{**seg, "start_line": None} for seg in mat["segments"]]
            s = snapshot(
                ref,
                f"document-{row.id}",
                row.purpose,
                row.name,
                mat["snapshot_ref"],
                row.kind,
                [
                    unit(
                        "material",
                        "selected-material",
                        state=mat["read_state"],
                        note=mat["read_note"],
                        segments=segments,
                    )
                ],
            )
        data["snapshots"].append(s)
        data["context_refs"].append(ref)
    if raw["case_ids"]:
        frozen = cases.edit_scope(project_id, EditScope(case_ids=raw["case_ids"]), actor, db)
        for c in frozen["items"]:
            contract.require(
                raw.get("case_versions", {}).get(str(c["id"]), c["version"]) == c["version"],
                "change_case_version_changed",
            )
            data["cases"].append(
                {
                    "case_ref": f"case-{c['id']}",
                    "case_id": c["id"],
                    "design_version": c["version"],
                    "library_revision": frozen["revision"],
                    "display_number": str(c["number"]),
                    "title": c["title"],
                    "design": {
                        k: c[k] for k in ("preconditions", "data_requirements", "steps", "expected")
                    },
                }
            )
    for n, h in enumerate(raw["historical_items"]):
        if h["module"] == "REQUIREMENT_ANALYSIS":
            r = risk_service.detail(project_id, h["report_id"], actor, db)
            item = next(x for x in r["report"]["risks"] if x["key"] == h["item_key"])
            handling = next((x for x in r["handling"] if x["risk_key"] == h["item_key"]), {})
            statement, warnings = item["description"], r["review_warnings"]
        else:
            from app.modules.code_analysis import service as code_service

            r = code_service.detail(project_id, h["report_id"], actor, db)
            item = next(x for x in r["report"]["findings"] if x["key"] == h["item_key"])
            handling, statement, warnings = r["handling"].get(h["item_key"], {}), item["actual"], []
        data["historical_items"].append(
            {
                "history_ref": f"history-{n}",
                **h,
                "title": item["title"],
                "statement": statement,
                "handling_revision": r["revision"],
                "handling_snapshot": json.dumps(handling, ensure_ascii=False),
                "basis_refs": [],
                "review_warnings": [
                    json.dumps(w, ensure_ascii=False) if not isinstance(w, str) else w
                    for w in warnings
                ],
            }
        )
        data["input_limitations"].append(
            f"history-{n}仅带入已选问题摘要和处理，旧正文未带入不能证明修复"
        )
    recheck(
        project_id,
        {**metadata, "bindings": bindings},
        actor,
        db,
        shared_snapshot=shared_snapshot,
    )
    contract.validate_input(contract.AnalysisInput.model_validate(data))
    db.rollback()
    return data, bindings, binaries


def frozen_binaries(project_id, metadata, actor, db):
    result = []
    for b in metadata.get("bindings", []):
        if b.get("version_id"):
            path, v = documents.stored_version(project_id, b["version_id"], actor, db)
            contract.require(v.document_id == b["document_id"])
            if v.extension == "directory" and b.get("paths"):
                _, attached = directories.material(
                    project_id, b["document_id"], v.id, b["paths"], b["snapshot_ref"], actor, db
                )
                result.extend(attached)
            if v.extension in {"pdf", "png", "jpg", "jpeg", "webp"}:
                contract.require(
                    hashlib.sha256(path.read_bytes()).hexdigest() == b["binary_sha256"],
                    "change_source_changed",
                )
                result.append((path, v.extension, b["snapshot_ref"], v.filename))
    return result
