"""Keep evidence together and schedule explicit checks for split static relations."""

import copy
import hashlib
import json
import re
from collections import defaultdict, deque
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from app.modules.change_analysis import contract

IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
CLIENT_ROLES = {"WEB", "FLUTTER"}
SOURCE_EXTENSIONS = {
    ".java",
    ".kt",
    ".scala",
    ".groovy",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".dart",
    ".cs",
    ".go",
    ".php",
    ".swift",
    ".rs",
}


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def _fingerprint(data):
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in data.items() if k != "request_id"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _without_comments(text):
    # Preserve quoted URLs while ignoring comments that only mention a class name.
    return re.sub(
        r"/\*[\s\S]*?\*/|//[^\n]*|\#[^\n]*|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"",
        lambda m: m[0] if m[0].startswith(("'", '"')) else " ",
        text,
    )


def _route(value):
    try:
        path = urlsplit(value).path if "://" in value else value.split("?", 1)[0]
    except ValueError:
        return None
    if not path.startswith("/"):
        return None
    path = re.sub(r"\$\{[^}]+\}|\{[^}]+\}|:[A-Za-z_]\w*|<[^>]+>", "{}", path)
    return "/" + path.strip("/")


def _endpoints(text):
    text = _without_comments(text)
    result = set()
    class_at = re.search(r"\b(?:class|interface)\s+\w+", text)
    prefix = ""
    if class_at:
        annotation = re.search(
            r"@RequestMapping\s*\(\s*(?:(?:value|path)\s*=\s*)?[\"']([^\"']+)",
            text[: class_at.start()],
        )
        prefix = annotation[1].rstrip("/") if annotation else ""
    mappings = re.finditer(
        r"@(GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping|Get|Post|Put|Patch|Delete)"
        r"\s*\(\s*(?:(?:value|path)\s*=\s*)?[\"']([^\"']*)[\"']([^)]*)\)",
        text,
    )
    for mapping in mappings:
        if class_at and mapping.start() < class_at.start():
            continue
        method = mapping[1].removesuffix("Mapping").upper()
        if method == "REQUEST":
            match = re.search(
                r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)", mapping[3]
            )
            method = match[1] if match else "*"
        route = _route(prefix + "/" + mapping[2].lstrip("/"))
        if route:
            result.add((method, route))
    for match in re.finditer(
        r"\b(?:fetch|(?:\w+\.)?(get|post|put|patch|delete|request))\s*\(\s*[\"'`]([^\"'`]+)[\"'`]([^\n;]*)",
        text,
        re.IGNORECASE,
    ):
        method = (match[1] or "GET").upper()
        explicit = re.search(
            r"\bmethod\s*:\s*[\"'](GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)", match[3], re.I
        )
        if explicit:
            method = explicit[1].upper()
        if method == "REQUEST":
            method = "*"
        route = _route(match[2])
        if route:
            result.add((method, route))
    for match in re.finditer(
        r"@\w+\.(get|post|put|patch|delete|route)\s*\(\s*[\"']([^\"']+)",
        text,
        re.I,
    ):
        route = _route(match[2])
        if route:
            result.add((match[1].upper() if match[1].lower() != "route" else "*", route))
    return result


def _nodes(data):
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    by_unit = {(s["snapshot_ref"], u["unit_id"]): u for s in data["snapshots"] for u in s["units"]}
    nodes, changed = {}, set()
    for pair in data["comparison_pairs"]:
        diffs = {d["mapping_ref"] for d in pair["text_diffs"]}
        for mapping in pair["unit_mappings"]:
            key = (pair["pair_id"], mapping["mapping_id"])
            members = [
                (pair[side + "_ref"], uid)
                for side in ("before", "after")
                for uid in mapping[side + "_unit_ids"]
            ]
            nodes[key] = members
            if mapping["mapping_id"] in diffs:
                changed.add(key)
    for ref in data["context_refs"]:
        for unit in snapshots[ref]["units"]:
            nodes[("@context", ref, unit["unit_id"])] = [(ref, unit["unit_id"])]
    meta = {}
    for key, members in nodes.items():
        source = snapshots[members[0][0]]["source_id"]
        roles = {snapshots[ref]["repository_kind"] for ref, _ in members}
        symbols, qualified, references, imports, relative_imports, packages, endpoints = (
            set(),
            set(),
            set(),
            set(),
            set(),
            set(),
            set(),
        )
        for ref, uid in members:
            path = PurePosixPath(by_unit[ref, uid]["path"])
            if path.suffix not in SOURCE_EXTENSIONS:
                continue
            clean = _without_comments("\n".join(s["text"] for s in by_unit[ref, uid]["segments"]))
            syntax = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", " ", clean)
            declarations = set(
                re.findall(r"\b(?:class|interface|enum|record|type)\s+(\w+)", syntax)
            )
            if len(path.stem) >= 3 and IDENTIFIER.fullmatch(path.stem):
                declarations.add(path.stem)
            symbols |= declarations
            package = re.search(r"\bpackage\s+([\w.]+)\s*;", syntax)
            if package:
                packages.add(package[1])
                qualified.update(package[1] + "." + symbol for symbol in declarations)
            # Explicit imports resolve duplicate simple names before any same-package fallback.
            imports.update(re.findall(r"\bimport\s+(?:static\s+)?([\w.]+)\s*;", syntax))
            for match in re.finditer(
                r"\b(?:from|import|export)\b[^\n;]*?[\"']([^\"']+)[\"']", clean
            ):
                if match[1].startswith("."):
                    relative_imports.add((str(path.parent), match[1]))
            for match in re.finditer(r"\bfrom\s+([\w.]+)\s+import\s+([\w, ]+)", syntax):
                imports.update(
                    match[1].strip(".") + "." + name.strip() for name in match[2].split(",")
                )
                references.update(name.strip() for name in match[2].split(","))
            references.update(
                re.findall(
                    r"\b(?:new|extends|implements|is|as)\s+([A-Z][\w$]*)|"
                    r"\b([A-Z][\w$]*)(?=\s*(?:<[^;{}]*>)?\s+[a-z_$]\w*\s*[,;=():])|"
                    r"\b([A-Z][\w$]*)(?=\s*\.[a-z_$]\w*\s*\()",
                    syntax,
                )
            )
            endpoints |= _endpoints(clean)
        references = {
            token
            for item in references
            for token in (item if isinstance(item, tuple) else (item,))
            if token
        }
        meta[key] = {
            "members": members,
            "source": source,
            "roles": roles,
            "symbols": symbols,
            "qualified": qualified,
            "packages": packages,
            "imports": imports,
            "relative_imports": relative_imports,
            "references": references,
            "paths": {by_unit[ref, uid]["path"] for ref, uid in members},
            "endpoints": endpoints,
            "weight": _size([by_unit[x] for x in members]),
            "code": any(snapshots[ref]["kind"] == "CODE" for ref, _ in members),
        }
    return snapshots, by_unit, meta, changed


def _graph(meta):
    definitions, qualified, paths, by_route = (defaultdict(set) for _ in range(4))
    outgoing, incoming, relations = defaultdict(set), defaultdict(set), {}
    for key, node in meta.items():
        if node["code"]:
            for symbol in node["symbols"]:
                definitions[node["source"], symbol].add(key)
            for symbol in node["qualified"]:
                qualified[node["source"], symbol].add(key)
            for path in node["paths"]:
                paths[node["source"], str(PurePosixPath(path).with_suffix(""))].add(key)
            for method, route in node["endpoints"]:
                by_route[route].add((key, method))

    def link(left, right, kind):
        if left == right:
            return
        outgoing[left].add(right)
        incoming[right].add(left)
        relations[left, right, kind] = None

    for key, node in meta.items():
        if not node["code"]:
            continue
        resolved = set()
        for reference in node["imports"]:
            names = reference.split(".")
            for end in range(len(names), 0, -1):
                matches = qualified.get((node["source"], ".".join(names[:end])), set())
                if matches:
                    if len(matches) == 1:
                        target = next(iter(matches))
                        link(key, target, "EXPLICIT_IMPORT")
                        resolved |= meta[target]["symbols"]
                    break
        for parent, relative in node["relative_imports"]:
            parts = []
            for part in (PurePosixPath(parent) / relative).parts:
                if part == ".." and parts:
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            target_path = str(PurePosixPath(*parts).with_suffix(""))
            matches = paths.get((node["source"], target_path), set())
            if len(matches) == 1:
                link(key, next(iter(matches)), "EXPLICIT_IMPORT")
        for token in node["references"] - resolved:
            matches = set().union(
                *(
                    qualified.get((node["source"], package + "." + token), set())
                    for package in node["packages"]
                )
            )
            if not matches:
                matches = definitions.get((node["source"], token), set())
            if len(matches) == 1:
                link(key, next(iter(matches)), "TYPE_REFERENCE")
        if node["roles"] & CLIENT_ROLES:
            for method, route in node["endpoints"]:
                for target, other_method in by_route[route]:
                    if "BACKEND" in meta[target]["roles"] and (
                        method == other_method or "*" in (method, other_method)
                    ):
                        link(key, target, "HTTP_CONTRACT")
    return outgoing, incoming, sorted(relations)


def _closure(start, graph):
    result, pending = set(start), deque(sorted(start))
    while pending:
        current = pending.popleft()
        for other in sorted(graph.get(current, ())):
            if other not in result:
                result.add(other)
                pending.append(other)
    return result


def input_for(data, batch):
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    selected, pairs = defaultdict(set), []
    mapping_keys = {tuple(k) for k in batch["mappings"]}
    for pair in data["comparison_pairs"]:
        mappings = [
            m for m in pair["unit_mappings"] if (pair["pair_id"], m["mapping_id"]) in mapping_keys
        ]
        if not mappings:
            continue
        paths = set()
        for side in ("before", "after"):
            ref = pair[side + "_ref"]
            selected[ref].update(uid for m in mappings for uid in m[side + "_unit_ids"])
            paths.update(
                u["path"] for u in snapshots[ref]["units"] if u["unit_id"] in selected[ref]
            )
        pairs.append(
            {
                **pair,
                "scope": sorted(paths),
                "unit_mappings": mappings,
                "text_diffs": [
                    d
                    for d in pair["text_diffs"]
                    if (pair["pair_id"], d["mapping_ref"]) in mapping_keys
                ],
            }
        )
    context_refs = []
    for ref, ids in batch["context_units"].items():
        selected[ref].update(ids)
        context_refs.append(ref)
    histories = [h for h in data["historical_items"] if h["history_ref"] in batch["history_refs"]]
    for history in histories:
        for ref in history["basis_refs"]:
            if ref not in selected:
                selected[ref].update(u["unit_id"] for u in snapshots[ref]["units"])
                context_refs.append(ref)
    result = {
        **data,
        "comparison_pairs": pairs,
        "snapshots": [
            {**s, "units": [u for u in s["units"] if u["unit_id"] in selected[s["snapshot_ref"]]]}
            for s in data["snapshots"]
            if s["snapshot_ref"] in selected
        ],
        "context_refs": list(dict.fromkeys(context_refs)),
        "cases": [c for c in data["cases"] if c["case_ref"] in batch["case_refs"]],
        "historical_items": histories,
        "targets": [t for t in data["targets"] if t not in batch.get("blocked_targets", [])],
        "input_limitations": [*data["input_limitations"], *batch.get("limitations", [])],
    }
    return copy.deepcopy(result)


def plan(data, target_bytes=1024 * 1024):
    if _size(data) <= target_bytes:
        return None
    snapshots, by_unit, meta, changed = _nodes(data)
    if not changed:
        return None
    outgoing, incoming, relations = _graph(meta)
    symbol_incoming = defaultdict(set)
    for left, right, kind in relations:
        if kind != "HTTP_CONTRACT":
            symbol_incoming[right].add(left)
    upstream_by_change = {key: _closure({key}, symbol_incoming) for key in changed}
    affected = _closure(changed, incoming)
    relevant = affected | _closure(changed, outgoing)
    adjacent = {key: outgoing[key] | incoming[key] for key in relevant}
    common = {
        key
        for key in meta
        if key[0] == "@context" and (not meta[key]["code"] or data["mode"] != "CODE_CHANGE")
    }
    batches, batch_nodes, uncovered = [], [], set(changed)

    def make(keys, primary, kind, depends_on=()):
        keys = set(keys) | common
        # Keep the decision/case packet together even when it exceeds the soft target.
        context = defaultdict(set)
        for key in keys:
            if key[0] == "@context":
                context[key[1]].add(key[2])
        blocked = []
        unpaired = []
        for root in primary:
            if not any(
                kind == "HTTP_CONTRACT"
                and left in keys
                and right in keys
                and (left in upstream_by_change[root] or right in upstream_by_change[root])
                for left, right, kind in relations
            ):
                unpaired.append(list(root))
        if "FRONTEND_BACKEND_MISMATCH" in data["targets"] and unpaired:
            blocked.append("FRONTEND_BACKEND_MISMATCH")
        batch = {
            "id": len(batches) + 1,
            "plan_version": 2,
            "kind": kind,
            "depends_on": sorted(set(depends_on)),
            "primary": [list(k) for k in sorted(primary)],
            "mappings": [list(k) for k in sorted(keys) if k[0] != "@context"],
            "context_units": {ref: sorted(ids) for ref, ids in sorted(context.items())},
            "case_refs": [c["case_ref"] for c in data["cases"]],
            "history_refs": [h["history_ref"] for h in data["historical_items"]],
            "blocked_targets": blocked,
            "unpaired_primary": sorted(unpaired)
            if "FRONTEND_BACKEND_MISMATCH" in data["targets"]
            else [],
            "callable": len(blocked) < len(data["targets"]),
            "blocking_reason": "没有按方法及路由匹配到本批实际消费端，不以无关文件满足角色门槛"
            if blocked
            else "",
            "limitations": ["本批按静态引用和接口候选关系组织；动态调用仍需证据核实"],
            "status": "QUEUED",
            "error_code": "",
            "report": None,
            "candidate_task_id": None,
            "attempts": [],
            "relation_refs": [],
        }
        if not batch["callable"]:
            batch.update(status="FAILED", error_code="change_batch_pairing_unavailable")
        subset = input_for(data, batch)
        if batch["callable"]:
            contract.validate_input(contract.AnalysisInput.model_validate(subset))
        batch["input_bytes"] = _size(subset)
        batch["oversized"] = batch["input_bytes"] > target_bytes
        batch["files"] = sorted(
            {f"{s['name']} / {u['path']}" for s in subset["snapshots"] for u in s["units"]}
        )
        batches.append(batch)
        batch_nodes.append(keys)
        return batch

    weights = {k: node["weight"] for k, node in meta.items()}
    paths = set()
    paths_by_root = defaultdict(list)
    for root in sorted(changed):
        for graph in (outgoing, incoming):
            found, queue = {root: (root,)}, deque([root])
            while queue:
                current = queue.popleft()
                for other in sorted(graph[current]):
                    if other not in found:
                        found[other] = (*found[current], other)
                        queue.append(other)
            for path in found.values():
                if len(path) > 1:
                    value = frozenset(path)
                    paths.add(value)
                    paths_by_root[root].append(value)
    # Group changes before shared evidence so each small file does not start a call.
    while uncovered:
        first = min(uncovered, key=lambda k: (-len(adjacent.get(k, ()) & changed), k))
        primary, used = {first}, weights[first]
        choices = uncovered - primary
        while choices:
            candidate = min(
                choices,
                key=lambda k: (
                    -len(adjacent.get(k, ()) & primary),
                    weights[k],
                    k,
                ),
            )
            choices.remove(candidate)
            if used + weights[candidate] <= target_bytes // 2:
                primary.add(candidate)
                used += weights[candidate]
        selected = set(primary)
        budget = max(target_bytes, used + target_bytes // 2)
        relevant_paths = set().union(*(set(paths_by_root[k]) for k in primary))
        for path in sorted(relevant_paths, key=lambda p: (-len(p), sorted(p))):
            extra = path - selected
            if used + sum(weights[k] for k in extra) <= budget:
                selected |= path
                used += sum(weights[k] for k in extra)
        make(selected, primary, "ANALYSIS")
        uncovered -= primary

    analysis_count = len(batches)
    # Unchanged dependency edges describe context; checks are for full change-to-dependency paths.
    paths.update(frozenset((a, b)) for a, b, _ in relations if a in changed or b in changed)
    remaining = [
        p
        for p in sorted(paths, key=lambda p: (-len(p), sorted(p)))
        if not any(p <= keys for keys in batch_nodes)
    ]
    while remaining:
        first = remaining.pop(0)
        if any(first <= keys for keys in batch_nodes):
            continue
        selected = set(first)
        used = sum(weights[k] for k in selected)
        for path in list(remaining):
            extra = path - selected
            if used + sum(weights[k] for k in extra) <= target_bytes:
                selected |= path
                used += sum(weights[k] for k in extra)
                remaining.remove(path)
        primary = selected & changed
        dependencies = [
            b["id"] for b in batches[:analysis_count] if primary & {tuple(k) for k in b["primary"]}
        ]
        make(selected, primary, "INTEGRATION", dependencies)

    serialized = []
    for n, (left, right, kind) in enumerate(relations, 1):
        if left not in relevant or right not in relevant:
            continue
        ref = f"relation-{n}"
        reviewed_by = []
        for batch, selected in zip(batches, batch_nodes, strict=True):
            if left in selected and right in selected:
                batch["relation_refs"].append(ref)
                reviewed_by.append(batch["id"])
        serialized.append(
            {
                "relation_id": ref,
                "kind": kind,
                "from": list(left),
                "to": list(right),
                "review_batch_ids": reviewed_by,
                "review_required": left in changed or right in changed,
                "scope": "CHANGE_RELATION"
                if left in changed or right in changed
                else "CONTEXT_ONLY",
            }
        )
    return {
        "version": 2,
        "input_hash": _fingerprint(data),
        "batches": batches,
        "relations": serialized,
        "limitations": ["静态候选关系不证明运行时可达；不存在匹配不代表无影响"],
    }
