"""Read-only SQL projections for page display; exports retain the original snapshots."""

from sqlalchemy import case, cast, column, func, select
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by


def fields(value, names):
    return func.jsonb_build_object(*[part for name in names for part in (name, value[name])])


def array(value, project):
    entries = (
        func.jsonb_array_elements(func.coalesce(value, cast([], JSONB)))
        .table_valued(column("value", JSONB), with_ordinality="position")
        .render_derived()
    )

    return (
        select(
            func.coalesce(
                func.jsonb_agg(aggregate_order_by(project(entries.c.value), entries.c.position)),
                cast([], JSONB),
            )
        )
        .select_from(entries)
        .scalar_subquery()
    )


def page_input(value):
    names = (
        "analysis_type",
        "contract_version",
        "project_id",
        "request_id",
        "mode",
        "revision",
        "comparison_pairs",
        "context_refs",
        "snapshots",
        "cases",
        "historical_items",
    )
    # Decompose once so each header field does not decompress the entire fixed input.
    root = (
        func.jsonb_to_record(value)
        .table_valued(*[column(name, JSONB) for name in names])
        .render_derived(with_types=True)
    )
    source = root.c
    snapshots = array(
        source["snapshots"],
        lambda snapshot: fields(snapshot, ("snapshot_ref", "name", "provenance")).op("||")(
            func.jsonb_build_object(
                "units", array(snapshot["units"], lambda unit: fields(unit, ("unit_id", "path")))
            )
        ),
    )
    projected = fields(
        source,
        (
            "analysis_type",
            "contract_version",
            "project_id",
            "request_id",
            "mode",
            "revision",
            "comparison_pairs",
            "context_refs",
        ),
    ).op("||")(
        func.jsonb_build_object(
            "snapshots",
            snapshots,
            "cases",
            array(
                source["cases"],
                lambda item: fields(
                    item,
                    (
                        "case_id",
                        "display_number",
                        "title",
                        "design_version",
                    ),
                ),
            ),
            "historical_items",
            array(
                source["historical_items"],
                lambda item: fields(
                    item,
                    (
                        "module",
                        "report_id",
                        "item_key",
                        "title",
                        "review_warnings",
                    ),
                ),
            ),
        )
    )
    return (
        select(case((source["contract_version"].is_(None), cast({}, JSONB)), else_=projected))
        .select_from(root)
        .scalar_subquery()
    )


def page_metadata(value):
    return fields(
        value, ("origin", "batch_plan", "batch_summary", "bindings", "evidence_corrections")
    ).op("||")(
        func.jsonb_build_object(
            "selections",
            func.jsonb_build_object(
                "pairs",
                array(
                    value["selections"]["pairs"],
                    lambda pair: pair.op("-")("before_local").op("-")("after_local"),
                ),
            ),
        )
    )
