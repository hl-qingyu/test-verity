"""Compact model output and full, unabridged material delivery for contract 3."""

import copy
import json
import re

from app.modules.case_generation import contract_base as contract
from app.modules.cases.schemas import DESIGN_FIELDS
from app.modules.requirements import analysis_materials


def quote_spans_segments(segments, quote):
    """Only join adjacent character ranges from the same fixed file, never pages or gaps."""
    previous, tail = None, ""
    for segment in segments:
        location = re.fullmatch(r"(.+) · 字符([1-9]\d*)–([1-9]\d*)", segment["location"])
        if not (
            previous
            and location
            and previous[1] == location[1]
            and int(previous[3]) + 1 == int(location[2])
        ):
            tail = ""
        text = segment["text"]
        if tail and quote in tail + text[: len(quote) - 1]:
            return True
        tail = (tail + text)[-(len(quote) - 1) :] if len(quote) > 1 else ""
        previous = location
    return False


def model_task(data):
    return {
        "mode": data["mode"],
        "scope": data["scope"]["name"],
        "full_scope": data["scope"]["full_scope"],
        "focus": data["focus"],
        "case_scope": data["scope"]["case_scope"]["description"],
        "existing_cases": data["cases"],
        "update_pairs": data["update_pairs"],
        "decisions": data["decisions"],
        "related_reports": data["related_reports"],
        "supplement": data["supplement"],
    }


def model_content(data, attachments):
    result = [
        {
            "type": "input_text",
            "text": "本次固定任务：\n" + json.dumps(model_task(data), ensure_ascii=False),
        }
    ]
    for material in data["materials"]:
        result.append(
            {
                "type": "input_text",
                "text": f"资料 sources={material['snapshot_ref']} / {material['name']} / "
                f"版本={material['version_ref']} / 侧别={material['side']}\n"
                f"读取说明：{material['read_note']}",
            }
        )
        for section in material["segments"]:
            result.append(
                {
                    "type": "input_text",
                    "text": f"正文位置：{section['location']}\n{section['text']}",
                }
            )
    # Attachments retain their fixed source mapping. No content is summarized or executed.
    result.extend(analysis_materials.model_content({}, attachments, attachment_key="image_ref")[1:])
    return result


def normalize(output, *, recover_titles=False):
    value, changes = copy.deepcopy(output), []
    if not isinstance(value, dict) or not isinstance(value.get("cases"), list):
        return value, changes
    for i, case in enumerate(value["cases"]):
        if not isinstance(case, dict) or not isinstance(case.get("design"), dict):
            continue
        for key, item in case["design"].items():
            if (
                key in DESIGN_FIELDS
                and isinstance(item, list)
                and all(isinstance(x, str) for x in item)
            ):
                case["design"][key] = "\n".join(item)
                changes.append(f"cases[{i}].design.{key}")
        design = case["design"]
        if (
            recover_titles
            and case.get("action") == "NEW"
            and "title" not in design
            and isinstance(design.get("description"), str)
            and design["description"].strip()
            and isinstance(case.get("note", ""), str)
        ):
            # Keep the model's wording verbatim; this is a review label, not a new assertion.
            design["title"] = design["description"]
            case["note"] = "\n".join(
                part
                for part in (
                    case.get("note", ""),
                    "AI未单独提供标题，候选标题原样沿用用例描述，请人工核对。",
                )
                if part
            )
            changes.extend((f"cases[{i}].design.title", f"cases[{i}].note"))
    return value, changes


def validate(data, supplied, *, source_indices=None):
    contract.validate_input(data)
    # Exported platform views are recomputed from the model output, never trusted as claims.
    stored = isinstance(supplied, dict) and "model_output" in supplied
    original = supplied.get("model_output") if stored else supplied
    output, _ = normalize(original)
    contract.require(isinstance(output, dict) and set(output) == {"cases", "notes", "complete"})
    contract.require(type(output["complete"]) is bool)
    contract.require(isinstance(output["cases"], list) and len(output["cases"]) <= 20000)
    contract.require(isinstance(output["notes"], list) and len(output["notes"]) <= 20000)
    source_indices = supplied.get("source_indices") if stored else source_indices
    partitioned = source_indices is not None
    if partitioned:
        contract.require(
            isinstance(source_indices, dict)
            and set(source_indices) == {"cases", "notes", "case_total", "note_total"}
        )
        for name, total_key in (("cases", "case_total"), ("notes", "note_total")):
            indices, total = source_indices[name], source_indices[total_key]
            contract.require(type(total) is int and 0 <= total <= 20000)
            contract.require(
                isinstance(indices, list)
                and len(indices) == len(output[name])
                and all(type(index) is int and 1 <= index <= total for index in indices)
                and indices == sorted(set(indices))
            )
    case_indices = source_indices["cases"] if partitioned else range(1, len(output["cases"]) + 1)
    note_indices = source_indices["notes"] if partitioned else range(1, len(output["notes"]) + 1)
    materials = contract.index(data["materials"], "snapshot_ref")
    decisions = contract.index(data["decisions"], "decision_ref")
    targets = contract.index(data["cases"], "case_ref")
    namespace, function = data["batch"]["namespace"], data["batch"]["function_refs"][0]
    current = {
        ref
        for ref, material in materials.items()
        if material["kind"] != "CODE"
        and material["segments"]
        and (
            material["side"] in {"CURRENT", "SUPPLEMENT", "CONTEXT"}
            or any(
                pair["before_ref"] == ref and pair["update_mode"] == "INCREMENTAL_SUPPLEMENT"
                for pair in data["update_pairs"]
            )
        )
    }
    superseded = {ref for decision in decisions.values() for ref in decision["supersedes"]}
    current |= {
        ref
        for ref, d in decisions.items()
        if d["applicability"] == "VERIFIED_CURRENT" and ref not in superseded
    }
    contract.require(
        any(
            m["kind"] in {"REQUIREMENT", "PROTOTYPE"}
            and m["segments"]
            and (
                m["side"] in {"CURRENT", "SUPPLEMENT"}
                or any(
                    p["before_ref"] == m["snapshot_ref"]
                    and p["update_mode"] == "INCREMENTAL_SUPPLEMENT"
                    for p in data["update_pairs"]
                )
            )
            for m in materials.values()
        ),
        "generation_material_unreadable",
    )
    evidence, suggestions, questions, notes = [], [], [], []
    evidence_by_source = {}

    def sources(refs, *, business=True):
        contract.require(isinstance(refs, list) and refs and all(isinstance(r, str) for r in refs))
        contract.require(
            len(set(refs)) == len(refs) and set(refs) <= materials.keys() | decisions.keys()
        )
        if business:
            contract.require(set(refs) & current, "generation_business_basis_required")
        keys = []
        for ref in refs:
            if ref not in evidence_by_source:
                key = (
                    f"{namespace}:ES{contract.digest(ref)[:24]}"
                    if partitioned
                    else f"{namespace}:E{len(evidence) + 1}"
                )
                material = materials.get(ref)
                evidence.append(
                    {
                        "key": key,
                        "kind": "MATERIAL" if material else "DECISION",
                        "target_ref": ref,
                        "segment_id": "",
                        "field": "",
                        "quote": "",
                        "side": material["side"] if material else "CONTEXT",
                        "note": "资料级来源引用，未做逐段摘录或语义证明；请对照固定原件审阅。",
                    }
                )
                evidence_by_source[ref] = key
            keys.append(evidence_by_source[ref])
        return keys

    def case_quotes(case, fallback):
        if "evidence_quotes" not in case:
            return fallback
        quotes = case["evidence_quotes"]
        contract.require(isinstance(quotes, list) and len(quotes) <= 5)
        keys = []
        for quote_index, excerpt in enumerate(quotes, 1):
            contract.require(isinstance(excerpt, dict) and set(excerpt) == {"source", "quote"})
            ref, quote = excerpt["source"], excerpt["quote"]
            contract.require(
                isinstance(ref, str) and ref in case["sources"] and ref in materials,
                "generation_evidence_source_invalid",
            )
            material = materials[ref]
            contract.require(material["kind"] in {"REQUIREMENT", "PROTOTYPE"})
            contract.require(isinstance(quote, str) and 0 < len(quote) <= 1000 and quote.strip())
            matches = [s for s in material["segments"] if quote in s["text"]]
            verified = bool(matches or quote_spans_segments(material["segments"], quote))
            key = (
                f"{namespace}:EC{index}Q{quote_index}"
                if partitioned
                else f"{namespace}:E{len(evidence) + 1}"
            )
            evidence.append(
                {
                    "key": key,
                    "kind": "MATERIAL",
                    "target_ref": ref,
                    "segment_id": matches[0]["segment_id"] if len(matches) == 1 else "",
                    "field": "",
                    "quote": quote,
                    "side": material["side"],
                    "note": (
                        "已核对摘录存在于固定资料原文；与本条用例的业务关联仍需人工审核。"
                        if verified
                        else "AI摘录未逐字匹配固定资料原文，请对照关联资料核对；用例已保留待审阅。"
                    ),
                    **({"quote_verified": False} if not verified else {}),
                }
            )
            keys.append(key)
        # Preserve references without excerpts (for example confirmed decisions or images).
        quoted_sources = {q["source"] for q in quotes}
        return keys + [
            evidence_by_source[ref] for ref in case["sources"] if ref not in quoted_sources
        ]

    for index, case in zip(case_indices, output["cases"], strict=True):
        contract.require(
            isinstance(case, dict)
            and {"action", "sources"} <= case.keys()
            and set(case) <= {"action", "target", "design", "sources", "note", "evidence_quotes"}
        )
        kind, target = case["action"], case.get("target")
        contract.require(isinstance(kind, str) and kind in {"NEW", "REUSE", "UPDATE", "RETIRE"})
        contract.shape(case.get("note", ""), "s")
        ev = case_quotes(case, sources(case["sources"]))
        contract.require(
            target is None if kind == "NEW" else isinstance(target, str) and target in targets
        )
        existing = targets.get(target)
        proposed = case.get("design", {})
        contract.require(isinstance(proposed, dict) and set(proposed) <= set(DESIGN_FIELDS))
        if kind in {"REUSE", "RETIRE"}:
            contract.require(not proposed)
        design = dict(existing["design"]) if existing else dict.fromkeys(DESIGN_FIELDS, "")
        design.update(proposed)
        contract.shape(design, "design")
        if kind in {"NEW", "UPDATE"}:
            contract.require(all(design[key].strip() for key in ("title", "steps", "expected")))
        if kind == "REUSE":
            contract.require(existing["lifecycle"] != "RETIRED")
        if kind == "RETIRE":
            paired = any(
                pair["before_ref"] in case["sources"]
                and pair["after_ref"] in case["sources"]
                and pair["comparison_complete"]
                for pair in data["update_pairs"]
            )
            contract.require(
                paired or bool(set(case["sources"]) & decisions.keys() & current),
                "generation_retire_basis_required",
            )
            contract.require(case.get("note", "").strip())
        patches = [
            {
                "field": key,
                "before": existing["design"][key],
                "after": design[key],
                "reason": case.get("note", "") or "当前依据要求的设计变化，待人工核对",
                "evidence_refs": ev,
            }
            for key in proposed
            if existing and kind == "UPDATE" and existing["design"][key] != design[key]
        ]
        contract.require(kind != "UPDATE" or patches)
        suggestions.append(
            {
                "key": f"{namespace}:C{index}",
                "kind": kind,
                "function_ref": function,
                "case_ref": target,
                "base_version": existing["design_version"] if existing else None,
                "design": design if kind == "NEW" else None,
                "changes": patches,
                "reason": case.get("note", "") or "依据完整资料生成，业务内容及执行准备由人工审核",
                "priority_reason": "设计建议",
                "evidence_refs": ev,
                "basis_status": "NEEDS_REVIEW"
                if kind in {"UPDATE", "RETIRE"} or case.get("note")
                else "SUPPORTED",
            }
        )
    for index, note in zip(note_indices, output["notes"], strict=True):
        contract.require(isinstance(note, dict) and set(note) == {"kind", "text", "sources"})
        contract.require(
            isinstance(note["kind"], str)
            and note["kind"] in {"BUSINESS_QUESTION", "EXECUTION_SETUP", "UNFINISHED"}
        )
        contract.shape(note["text"], "s")
        contract.require(note["text"].strip())
        ev = sources(note["sources"], business=False)
        notes.append(note)
        if note["kind"] == "BUSINESS_QUESTION":
            questions.append(
                {
                    "key": f"{namespace}:Q{index}",
                    "function_ref": function,
                    "parent_key": None,
                    "trigger": "",
                    "question": note["text"],
                    "options": [],
                    "evidence_refs": ev,
                    "impact": "相关业务预期待人工确认；其他明确用例继续",
                }
            )
    completed = (
        output["complete"]
        and not any(n["kind"] != "EXECUTION_SETUP" for n in notes)
        and (
            not partitioned
            or (
                len(output["cases"]) == source_indices["case_total"]
                and len(output["notes"]) == source_indices["note_total"]
            )
        )
    )
    result = {
        **{
            key: data[key]
            for key in (
                "analysis_type",
                "contract_version",
                "request_id",
                "project_id",
                "revision",
                "mode",
            )
        },
        "batch_ref": data["batch"]["batch_ref"],
        "outcome": "COMPLETE" if completed else "PARTIAL",
        "summary": (
            f"返回{len(suggestions)}条用例建议、{len(notes)}条简短说明；"
            "范围完成为AI声明，仍需人工核对。"
        ),
        "suggestions": suggestions,
        "evidence": evidence,
        "requirement_questions": questions,
        "notes": notes,
        "model_output": output,
        "limitations": list(data["input_limitations"])
        + (
            ["部分AI摘录未逐字匹配固定资料原文，已保留原文与来源供人工核对；不影响候选保存。"]
            if any(e.get("quote_verified") is False for e in evidence)
            else []
        ),
    }
    if stored:
        if partitioned:
            result["source_indices"] = copy.deepcopy(source_indices)
        contract.require(supplied == result, "generation_compact_projection_mismatch")
    elif partitioned:
        result["source_indices"] = copy.deepcopy(source_indices)
    return result
