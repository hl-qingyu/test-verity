"""Prepare immutable authorized material/case snapshots and a reviewable batch plan."""

import copy
import hashlib
import json
import math
from uuid import uuid4

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import CaseGenerationRun, CaseVersion
from app.modules.case_generation import compact, contract
from app.modules.cases import service as cases
from app.modules.cases.schemas import DESIGN_FIELDS, EditScope
from app.modules.change_analysis import sources as change_sources
from app.modules.documents import service as documents
from app.modules.prototypes import directories
from app.modules.prototypes import service as prototypes
from app.modules.requirements import analysis_materials, risk_service
from app.modules.skills import files as skill_files


def generation_segments(segments):
    result = []
    for segment in segments:
        if not segment["text"]:
            result.append(segment)
            continue
        text = segment["text"].replace("\r\n", "\n").replace("\r", "\n")
        start, number = 0, 1
        while start < len(text):
            end = min(start + 1600, len(text))
            lines = text[start:end].splitlines(keepends=True)
            if len(lines) > 8:
                end = start + sum(len(line) for line in lines[:8])
            elif end < len(text):
                boundary = text.rfind("\n", start, end)
                if boundary > start:
                    end = boundary + 1
            result.append(
                {
                    **segment,
                    "segment_id": f"{segment['segment_id']}-g{number}",
                    "location": f"{segment['location']} · 本段字符{start + 1}–{end}",
                    "text": text[start:end],
                }
            )
            start, number = end, number + 1
    return result


def skill():
    return skill_files.snapshot("case-generation")


def preparation_request(payload):
    data = payload.model_dump(mode="json")
    # Empty new directory fields must not change earlier requests' idempotency hashes.
    for material in data.get("materials", []):
        if not material.get("before_paths"):
            material.pop("before_paths", None)
    return data


def recheck(project_id, metadata, actor, db):
    documents.access(project_id, actor, db)
    for b in metadata.get("bindings", []):
        row = change_sources.document(project_id, b["document_id"], actor, db)
        contract.require(
            row.kind == b["kind"] and row.purpose == b["purpose"], "generation_source_changed"
        )
        if b.get("version_id"):
            path, version = documents.stored_version(project_id, b["version_id"], actor, db)
            if version.extension == "directory":
                directories.checked(project_id, row.id, version.id, b["paths"], actor, db)
            contract.require(
                version.document_id == row.id
                and hashlib.sha256(path.read_bytes()).hexdigest() == b["binary_sha256"],
                "generation_source_changed",
            )
        if row.kind == "GITHUB":
            contract.require(
                row.repository_id == b["repository_id"] and (row.path or "") == b["path"],
                "generation_source_changed",
            )
            # Frozen retries use this operator's grant; never borrow the original token.
            from app.db.models import GitHubConnection, GitHubRepository, ProjectRepository

            repo = db.get(ProjectRepository, row.repository_id)
            grant = (
                db.scalar(
                    select(GitHubConnection.id)
                    .join(GitHubRepository, GitHubRepository.connection_id == GitHubConnection.id)
                    .where(
                        GitHubConnection.owner_id == actor.id,
                        GitHubRepository.github_id == repo.github_id,
                    )
                )
                if repo and repo.project_id == project_id
                else None
            )
            contract.require(grant, "github_repository_not_allowed")
        if row.kind == "LINK":
            contract.require(row.url == b["url"], "generation_source_changed")


def binaries(project_id, metadata, actor, db):
    recheck(project_id, metadata, actor, db)
    result = []
    for b in metadata.get("bindings", []):
        if b.get("version_id"):
            path, v = documents.stored_version(project_id, b["version_id"], actor, db)
            if v.extension == "directory":
                _, attached = directories.material(
                    project_id, b["document_id"], v.id, b["paths"], b["snapshot_ref"], actor, db
                )
                result.extend(attached)
            if v.extension in {"pdf", "png", "jpg", "jpeg", "webp"}:
                result.append((path, v.extension, b["snapshot_ref"], v.filename))
    return result


def read_material(project_id, selection, side, ref, actor, db, old_run=None):
    row = change_sources.document(project_id, selection.document_id, actor, db)
    binding = {"snapshot_ref": ref, "document_id": row.id, "kind": row.kind, "purpose": row.purpose}
    version_ref = selection.before if side == "BEFORE" else selection.version
    if row.kind == "FILE":
        require_version = version_ref.isdigit()
        contract.require(require_version, "generation_version_required")
        path, v = documents.stored_version(project_id, int(version_ref), actor, db)
        contract.require(v.document_id == row.id)
        actual = analysis_materials.file_material(path, v.extension, ref, v.filename)
        contract.require(actual["snapshot_ref"] == v.sha256, "generation_source_changed")
        binding.update(version_id=v.id, binary_sha256=v.sha256)
        version_ref = f"version-{v.id}"
        name = v.filename
    elif row.kind == "DIRECTORY":
        contract.require(version_ref.isdigit(), "generation_version_required")
        selected_paths = selection.before_paths if side == "BEFORE" else selection.paths
        actual, _ = directories.material(
            project_id, row.id, int(version_ref), selected_paths, ref, actor, db
        )
        binding.update(
            version_id=int(version_ref),
            binary_sha256=actual["snapshot_ref"],
            paths=list(selected_paths),
        )
        version_ref = f"version-{version_ref}"
        name = row.name
    elif row.kind == "GITHUB":
        contract.require(
            len(version_ref) == 40 and all(c in "0123456789abcdef" for c in version_ref),
            "generation_version_required",
        )
        contract.require(selection.connection_id and selection.paths)
        snapshot = change_sources.prototype_git(
            project_id,
            {
                "source_id": row.id,
                "connection_id": selection.connection_id,
                "paths": selection.paths,
                "before_ref": version_ref,
                "after_ref": version_ref,
            },
            "before" if side == "BEFORE" else "after",
            ref,
            actor,
            db,
        )
        actual = {
            "segments": [],
            "read_state": "PARTIAL",
            "read_note": "仅固定所选HTML/说明；未执行页面脚本或外部资源。",
        }
        for unit in snapshot["units"]:
            contract.require(
                unit["presence"] == "PRESENT" and unit["segments"], "generation_material_unreadable"
            )
            for seg in unit["segments"]:
                actual["segments"].append(
                    {k: seg[k] for k in ("segment_id", "location", "text", "image_ref")}
                )
                actual["segments"][-1]["segment_id"] = f"{unit['unit_id']}-{seg['segment_id']}"
        binding.update(repository_id=row.repository_id, path=row.path or "", commit=version_ref)
        name = row.name
    elif row.kind == "LINK":
        binding.update(url=row.url)
        if side == "BEFORE":
            contract.require(old_run is not None, "generation_old_link_body_required")
            previous = next(
                (
                    m
                    for m in old_run.input_snapshot.get("materials", [])
                    if m["source_id"] == f"document-{row.id}"
                    and m["side"] in {"CURRENT", "SUPPLEMENT"}
                    and m["version_ref"] == version_ref
                ),
                None,
            )
            contract.require(previous and previous["segments"], "generation_old_link_body_required")
            actual = copy.deepcopy(previous)
        else:
            captured = prototypes.link_pages(
                project_id, row.id, selection.paths, version_ref, actor, db
            )
            version_ref = captured["snapshot_ref"]
            binding["paths"] = list(selection.paths)
            binding["annotation_blocks"] = sum(
                " · 批注：" in s["location"] for s in captured["segments"]
            )
            binding["markdown_files"] = sum(
                s["location"].startswith("批注引用 Markdown · ") for s in captured["segments"]
            )
            actual = {
                "read_state": "PARTIAL",
                "read_note": (
                    f"固定{len(selection.paths)}页HTML和{binding['annotation_blocks']}块对应批注；"
                    f"含{binding['markdown_files']}份批注引用Markdown全文；不执行脚本或读取其他资源。"
                ),
                "segments": [
                    {
                        "segment_id": f"p{n}",
                        "location": s["location"],
                        "text": s["text"],
                        "image_ref": "",
                    }
                    for n, s in enumerate(captured["segments"], 1)
                ],
            }
        name = row.name
    else:
        raise AppError(422, "generation_material_unreadable")
    # New records keep each supplied page/annotation body whole; old inputs remain frozen.
    actual["segments"] = [
        {**segment, "text": segment["text"].replace("\r\n", "\n").replace("\r", "\n")}
        for segment in actual["segments"]
    ]
    text = "\n".join(s["text"] for s in actual["segments"])
    result = {
        "snapshot_ref": ref,
        "source_id": f"document-{row.id}",
        "kind": row.purpose,
        "side": side,
        "name": name,
        "version_ref": version_ref,
        "read_state": actual["read_state"],
        "read_note": actual["read_note"],
        "segments": actual["segments"],
        "content_sha256": hashlib.sha256(text.encode()).hexdigest()
        if text
        else binding.get("binary_sha256", "")
        if actual["segments"]
        else "",
    }
    return result, binding


def prepare(project_id, payload, actor, db):
    documents.access(project_id, actor, db)
    contract.require(
        len(set(payload.case_ids)) == len(payload.case_ids) and all(c > 0 for c in payload.case_ids)
    )
    contract.require(set(payload.case_versions) == {str(c) for c in payload.case_ids})
    contract.require(len({s.document_id for s in payload.materials}) == len(payload.materials))
    old = db.get(CaseGenerationRun, payload.baseline_run_id) if payload.baseline_run_id else None
    contract.require(
        old is None
        and not payload.baseline_run_id
        or old
        and old.project_id == project_id
        and old.deleted_at is None,
        "generation_baseline_invalid",
    )
    snapshot = cases.edit_scope(
        project_id,
        EditScope(case_ids=payload.case_ids, lifecycle="ALL")
        if payload.case_ids
        else EditScope(lifecycle="ALL"),
        actor,
        db,
    )
    selected = [c for c in snapshot["items"] if c["id"] in payload.case_ids]
    contract.require(
        payload.case_library_revision is None
        or payload.case_library_revision == snapshot["revision"],
        "generation_case_changed",
    )
    contract.require(len(selected) == len(payload.case_ids))
    fixed_cases = []
    for c in selected:
        contract.require(
            c["version"] == payload.case_versions[str(c["id"])], "generation_case_changed"
        )
        baseline = None
        if old:
            adopted = old.handling.get("applications", {}).get(str(c["id"]))
            if adopted:
                version = db.scalar(
                    select(CaseVersion).where(
                        CaseVersion.case_id == c["id"], CaseVersion.number == adopted["version"]
                    )
                )
                contract.require(version is not None)
                baseline = {
                    "design_version": version.number,
                    "design": {f: getattr(version, f) for f in DESIGN_FIELDS},
                    "origin": "APPLIED",
                    "adoption_ref": adopted["ref"],
                }
        fixed_cases.append(
            {
                "case_ref": f"case-{c['id']}",
                "case_id": c["id"],
                "design_version": c["version"],
                "display_number": c["number"],
                "category_id": c["category_id"],
                "lifecycle": c["lifecycle"],
                "design": {f: c[f] for f in DESIGN_FIELDS},
                "baseline": baseline,
            }
        )
    # Freeze selected source versions and case designs before any model call.
    materials, bindings, pairs, group_refs = [], [], [], []
    for n, selection in enumerate(payload.materials, 1):
        pair_refs = []
        if selection.before:
            contract.require(
                payload.mode == "UPDATE" and selection.update, "generation_pair_required"
            )
            before, binding = read_material(
                project_id, selection, "BEFORE", f"M{n}-before", actor, db, old
            )
            materials.append(before)
            bindings.append(binding)
            pair_refs.append(before["snapshot_ref"])
        side = "SUPPLEMENT" if selection.before and selection.update == "增量补充" else "CURRENT"
        after, binding = read_material(project_id, selection, side, f"M{n}-current", actor, db)
        materials.append(after)
        bindings.append(binding)
        pair_refs.append(after["snapshot_ref"])
        if selection.before:
            pairs.append(
                {
                    "pair_ref": f"PAIR{n}",
                    "before_ref": before["snapshot_ref"],
                    "after_ref": after["snapshot_ref"],
                    "update_mode": "INCREMENTAL_SUPPLEMENT"
                    if side == "SUPPLEMENT"
                    else "FULL_REPLACEMENT",
                    "function_refs": ["F-SCOPE"],
                    "scope_confirmed": True,
                    "scope_note": payload.scope,
                    "comparison_complete": before["read_state"]
                    == after["read_state"]
                    == "READABLE",
                }
            )
        group_refs.append(pair_refs)
    related = []
    for rid in payload.risk_report_ids:
        detail = risk_service.detail(project_id, rid, actor, db)
        for risk in detail["report"].get("risks", []):
            related.append(
                {
                    "report_ref": f"risk-{rid}-{risk['key']}",
                    "analysis_type": "REQUIREMENT_ANALYSIS",
                    "report_id": str(rid),
                    "item_key": risk["key"],
                    "statement": json.dumps(risk, ensure_ascii=False),
                    "handling_snapshot": json.dumps(
                        detail.get("handling", {}).get(risk["key"], {}), ensure_ascii=False
                    ),
                    "review_warnings": detail.get("review_warnings", []),
                    "basis_refs": [],
                }
            )
    fixed_skill = skill()
    data = {
        "analysis_type": "CASE_GENERATION",
        "contract_version": fixed_skill["contract_version"],
        "request_id": str(payload.request_id),
        "project_id": project_id,
        "revision": 1,
        "mode": payload.mode,
        "scope": {
            "name": payload.scope,
            "full_scope": payload.full_scope,
            "functions": [
                {"function_ref": "F-SCOPE", "name": payload.scope, "scope_note": payload.scope}
            ],
            "target_ends": ["ALL_IN_MATERIALS"],
            "case_scope": {
                "description": payload.case_scope,
                "complete": True,
                "count": len(fixed_cases),
                "library_revision": snapshot["revision"],
            },
        },
        "focus": payload.focus,
        "materials": materials,
        "update_pairs": pairs,
        "decisions": [],
        "related_reports": related,
        "cases": fixed_cases,
        "supplement": None,
        "batch": {
            "plan_ref": str(payload.request_id),
            "batch_ref": "plan",
            "index": 1,
            "total": 1,
            "function_refs": ["F-SCOPE"],
            "namespace": "plan",
            "limitations": [],
        },
        "input_limitations": ["只分析所选固定范围；未执行业务测试。"],
    }
    if payload.mode == "UPDATE" and any(c["baseline"] is None for c in fixed_cases):
        data["input_limitations"].append(
            "部分用例没有历史成功应用基准，维护候选须人工核对，不能证明三方保护。"
        )
    contract.validate_input(data)
    metadata = {
        "skill": fixed_skill,
        "bindings": bindings,
        "origin": "AI",
        "request_hash": contract.digest(preparation_request(payload)),
    }
    attachment_bytes = sum(
        path.stat().st_size for path, _, _, _ in binaries(project_id, metadata, actor, db)
    )
    if attachment_bytes:
        data["input_limitations"].append(
            f"实际提供图片/PDF附件共{attachment_bytes}字节；发送附件不代表模型已正确解读，须人工审阅。"
        )
    metadata["attachment_bytes"] = attachment_bytes
    recheck(project_id, metadata, actor, db)
    return data, metadata


def input_notice(data, instructions="", attachment_bytes=0):
    # A heuristic, not a tokenizer or a model-specific context limit.
    content = instructions + (
        "".join(item["text"] for item in compact.model_content(data, []))
        if data.get("contract_version") == 3
        else json.dumps(data, ensure_ascii=False)
    )
    estimate = max(1, math.ceil(sum(1 if ord(c) > 127 else 0.25 for c in content)))
    note = f"完整资料一次生成；文本输入粗估约{estimate:,} token（含指令及JSON）。"
    if estimate >= 32_000:
        note += "输入较大，可能遗漏细节或输出截断；可继续生成，或缩小范围后重新准备。"
    note += "此估算不是模型硬限制；当前未配置可核实的模型上下文容量，不能保证能够容纳。"
    if attachment_bytes:
        note += f"另有{attachment_bytes:,}字节图片/PDF附件，其模型用量未计入文本估算。"
    return note + "本人AI按供应商计费，失败仅人工重试。"


def plan(data):
    # Keep the complete scope: segmentation locates evidence, never schedules generation.
    value = copy.deepcopy(data)
    value["request_id"] = str(uuid4())
    value["batch"].update(batch_ref="b1", index=1, total=1, namespace="b1")
    contract.validate_input(value)
    return [value]
