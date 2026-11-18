"""Stable review identities for native results within their original generation record."""

import copy
from uuid import NAMESPACE_URL, uuid5


def info(batch):
    return next(
        (
            a["native_result"]
            for a in reversed(batch.attempts)
            if isinstance(a.get("native_result"), dict)
        ),
        None,
    )


def review_input(original, result_id):
    value = copy.deepcopy(original)
    reference = "cli-" + result_id
    value["request_id"] = str(uuid5(NAMESPACE_URL, "generation-cli-round:" + result_id))
    value["batch"] = {**value["batch"], "batch_ref": reference, "namespace": reference}
    return value


def summaries(batches):
    return sorted(
        [
            {
                "id": info(b)["id"],
                "batchId": b.id,
                "batchRef": b.batch_ref,
                "timestamp": info(b)["timestamp"],
                "caseCount": len(b.report.get("suggestions", [])),
                "status": b.status,
            }
            for b in batches
            if info(b)
        ],
        key=lambda item: item["timestamp"],
        reverse=True,
    )
