"""Strict paired imports bind existing project originals and real design versions."""

import copy
import hashlib
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.db.models import CaseGenerationBatch, CaseGenerationRun
from app.modules.case_generation import contract, service, sources
from app.modules.cases import service as cases
from app.modules.cases.schemas import DESIGN_FIELDS
from app.modules.change_analysis import sources as change_sources
from app.modules.documents import service as documents
from app.modules.prototypes import directories
from app.modules.requirements import analysis_materials


def pairs(data, report):
    if data.get("analysis_type") != "CASE_GENERATION_BUNDLE":
        return [(data, report)]
    fields = {"analysis_type", "contract_version", "project_id", "request_id", "batches"}
    contract.require(set(data) == set(report) == fields)
    for key in fields - {"batches"}:
        contract.require(data[key] == report[key])
    contract.require(data["contract_version"] in {2, 3})
    inputs = contract.index(data["batches"], "batch_ref")
    outputs = contract.index(report["batches"], "batch_ref")
    contract.require(set(inputs) == set(outputs))
    result = []
    namespaces = set()
    for ref, item in inputs.items():
        namespace = item["input"]["batch"]["namespace"]
        contract.require(namespace not in namespaces)
        namespaces.add(namespace)
        contract.require(set(item) == {"batch_ref", "request_id", "status", "input"})
        other = outputs[ref]
        contract.require(set(other) == {"batch_ref", "request_id", "status", "report"})
        contract.require(
            item["request_id"] == other["request_id"]
            and item["input"]["request_id"] == item["request_id"]
        )
        # Partial bundles preserve failed/unexecuted inputs.
        if other["report"]:
            contract.require(item["status"] == other["status"] == "COMPLETED")
            result.append((item["input"], other["report"]))
        else:
            contract.require(item["status"] != "COMPLETED")
            contract.validate_input(item["input"])
            result.append((item["input"], None))
    contract.require(result)
    return result


def bind(project_id, data, mapping, actor, db):
    bindings = []
    for m in data["materials"]:
        contract.require(m["snapshot_ref"] in mapping, "generation_bindings_required")
        b = mapping[m["snapshot_ref"]]
        row = change_sources.document(project_id, b.document_id, actor, db)
        contract.require(row.purpose == m["kind"], "generation_binding_mismatch")
        actual_binding = {
            "snapshot_ref": m["snapshot_ref"],
            "document_id": row.id,
            "purpose": row.purpose,
            "kind": row.kind,
        }
        if row.kind == "FILE":
            contract.require(b.version_id, "generation_bindings_required")
            path, v = documents.stored_version(project_id, b.version_id, actor, db)
            contract.require(v.document_id == row.id)
            actual = analysis_materials.file_material(
                path, v.extension, m["snapshot_ref"], v.filename
            )
            if data["contract_version"] == 2:
                actual["segments"] = sources.generation_segments(actual["segments"])
            else:
                actual["segments"] = [
                    {**s, "text": s["text"].replace("\r\n", "\n").replace("\r", "\n")}
                    for s in actual["segments"]
                ]
            text = "\n".join(s["text"] for s in actual["segments"])
            supplied = "\n".join(s["text"] for s in m["segments"])
            if not supplied and m["segments"]:
                contract.require(m["content_sha256"] == v.sha256, "generation_attachment_mismatch")
            if m["source_id"].startswith("document-"):
                contract.require(
                    m["source_id"] == f"document-{row.id}", "generation_binding_mismatch"
                )
            if m["version_ref"].startswith("version-"):
                contract.require(
                    m["version_ref"] == f"version-{v.id}", "generation_binding_mismatch"
                )
            for s in m["segments"]:
                if s["text"]:
                    contract.require(s["text"] in text, "generation_binding_mismatch")
                if s["image_ref"]:
                    contract.require(
                        v.extension in {"pdf", "png", "jpg", "jpeg", "webp"}
                        and s["image_ref"] == m["snapshot_ref"],
                        "generation_attachment_mismatch",
                    )
            if m["read_state"] == "READABLE":
                contract.require(
                    supplied == text and actual["read_state"] == "READABLE",
                    "generation_binding_mismatch",
                )
            actual_binding.update(
                version_id=v.id, binary_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
            )
        elif row.kind == "DIRECTORY":
            v, paths = directories.bind_material(
                project_id, row.id, b.version_id, m["segments"], m["snapshot_ref"], actor, db
            )
            contract.require(m["version_ref"] == f"version-{v.id}", "generation_binding_mismatch")
            actual_binding.update(version_id=v.id, binary_sha256=v.sha256, paths=paths)
        else:
            contract.require(not b.version_id)
            saved = None
            # Imported text must match a prior fixed snapshot, not just its URL/commit.
            for run in db.scalars(
                select(CaseGenerationRun).where(CaseGenerationRun.project_id == project_id)
            ):
                known = {x["snapshot_ref"]: x for x in run.metadata_snapshot.get("bindings", [])}
                for fixed in run.input_snapshot.get("materials", []):
                    binding = known.get(fixed["snapshot_ref"], {})
                    if (
                        binding.get("document_id") == row.id
                        and fixed["version_ref"] == m["version_ref"]
                        and fixed["content_sha256"] == m["content_sha256"]
                        and fixed["segments"] == m["segments"]
                    ):
                        saved = binding
                        break
                if saved:
                    break
            contract.require(saved, "generation_fixed_snapshot_binding_required")
            actual_binding = {**saved, "snapshot_ref": m["snapshot_ref"]}
        bindings.append(actual_binding)
    for c in data["cases"]:
        detail = cases.detail(project_id, c["case_id"], actor, db)
        version = next((v for v in detail["versions"] if v["number"] == c["design_version"]), None)
        contract.require(
            version and all(version[f] == c["design"][f] for f in DESIGN_FIELDS),
            "generation_case_binding_mismatch",
        )
        if c["baseline"]:
            b = c["baseline"]
            v = next((v for v in detail["versions"] if v["number"] == b["design_version"]), None)
            contract.require(v and all(v[f] == b["design"][f] for f in DESIGN_FIELDS))
            if b["origin"] == "APPLIED":
                contract.require(
                    any(
                        run.handling.get("applications", {}).get(str(c["case_id"]), {}).get("ref")
                        == b["adoption_ref"]
                        for run in db.scalars(
                            select(CaseGenerationRun).where(
                                CaseGenerationRun.project_id == project_id
                            )
                        )
                    ),
                    "generation_baseline_binding_required",
                )
    for d in data["decisions"]:
        if d["applicability"] == "VERIFIED_CURRENT":
            contract.require(
                any(
                    any(
                        x["key"] == d["decision_ref"]
                        and x["version"] == d["version"]
                        and x["conclusion"] == d["statement"]
                        and x["actor"] == d["actor"]
                        and x["time"] == d["confirmed_at"]
                        for x in run.handling.get("decisions", [])
                    )
                    for run in db.scalars(
                        select(CaseGenerationRun).where(CaseGenerationRun.project_id == project_id)
                    )
                ),
                "generation_decision_binding_required",
            )
    # Related external reports must be actual project records, not imported claims.
    from app.modules.change_analysis import service as change_service
    from app.modules.code_analysis import service as code_service
    from app.modules.requirements import risk_service

    for r in data["related_reports"]:
        rid = int(r["report_id"]) if r["report_id"].isdigit() else 0
        contract.require(rid)
        if r["analysis_type"] == "REQUIREMENT_ANALYSIS":
            risk_service.detail(project_id, rid, actor, db)
        elif r["analysis_type"] == "CODE_REVIEW":
            code_service.detail(project_id, rid, actor, db)
        else:
            change_service.detail(project_id, rid, actor, db)
    return bindings


def import_report(project_id, payload, actor, db):
    documents.access(project_id, actor, db, lock=True)
    data, report = contract.read(payload.input_json), contract.read(payload.report_json)
    matched = [(i, contract.validate_report(i, r) if r else r) for i, r in pairs(data, report)]
    contract.require(data["project_id"] == project_id)
    source_hash = contract.digest([data, report])
    bindings_hash = contract.digest([b.model_dump() for b in payload.bindings])
    old = db.scalar(
        select(CaseGenerationRun).where(
            CaseGenerationRun.project_id == project_id,
            CaseGenerationRun.metadata_snapshot["source_hash"].astext == source_hash,
        )
    )
    if old:
        service.require_visible(old)
        contract.require(
            old.metadata_snapshot["bindings_hash"] == bindings_hash,
            "generation_import_rebinding_forbidden",
        )
        return service.projection(old, actor, db)
    mapping = {b.snapshot_ref: b for b in payload.bindings}
    contract.require(
        len(mapping) == len(payload.bindings)
        and set(mapping) == {m["snapshot_ref"] for i, _ in matched for m in i["materials"]},
        "generation_bindings_required",
    )
    all_bindings = {}
    material_definitions = {}
    refs = set()
    for i, r in matched:
        contract.require(i["project_id"] == project_id and len(i["request_id"]) <= 36)
        contract.validate_input(i)
        if r:
            contract.validate_report(i, r)
        contract.require(i["batch"]["batch_ref"] not in refs)
        refs.add(i["batch"]["batch_ref"])
        for m in i["materials"]:
            if m["snapshot_ref"] in material_definitions:
                contract.require(
                    material_definitions[m["snapshot_ref"]] == m, "generation_binding_mismatch"
                )
            material_definitions[m["snapshot_ref"]] = m
        for b in bind(project_id, i, mapping, actor, db):
            if b["snapshot_ref"] in all_bindings:
                contract.require(
                    all_bindings[b["snapshot_ref"]] == b, "generation_binding_mismatch"
                )
            all_bindings[b["snapshot_ref"]] = b
    metadata = {
        "origin": "IMPORT",
        "source_hash": source_hash,
        "bindings_hash": bindings_hash,
        "bindings": list(all_bindings.values()),
        "original_input": data,
        "original_report": report,
        "skill": sources.skill(),
    }
    sources.recheck(project_id, metadata, actor, db)
    snapshot = copy.deepcopy(matched[0][0])
    snapshot["materials"] = list(
        {m["snapshot_ref"]: m for i, _ in matched for m in i["materials"]}.values()
    )
    row = CaseGenerationRun(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(uuid5(NAMESPACE_URL, f"generation-import:{project_id}:{source_hash}")),
        title=payload.title,
        mode=snapshot["mode"],
        input_snapshot=snapshot,
        metadata_snapshot=metadata,
        handling={},
        status="COMPLETED" if any(r for _, r in matched) else "FAILED",
    )
    db.add(row)
    db.flush()
    for i, r in matched:
        db.add(
            CaseGenerationBatch(
                run_id=row.id,
                batch_ref=i["batch"]["batch_ref"],
                request_id=i["request_id"],
                actor_id=actor.id,
                status="COMPLETED" if r else "FAILED",
                input_snapshot=i,
                report=r or {},
                ai_config={},
                attempts=[],
                error_code="" if r else "generation_import_missing_batch_report",
            )
        )
    db.commit()
    return service.projection(row, actor, db)
