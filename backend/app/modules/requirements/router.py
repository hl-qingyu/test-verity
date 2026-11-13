import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response

from app.api.dependencies import DB, Actor, check_origin
from app.modules.candidate_results.schemas import CandidateReviewInput
from app.modules.projects import record_deletion
from app.modules.requirements import (
    candidate_review,
    chat_service,
    risk_analysis_service,
    risk_service,
    service,
)
from app.modules.requirements.chat_schemas import ChatInput
from app.modules.requirements.risk_schemas import (
    AnalysisRequest,
    HandlingInput,
    ManualHandlingInput,
    ManualRiskInput,
)
from app.modules.requirements.schemas import (
    Assign,
    CategoryInput,
    DeleteCategory,
    Move,
    Revision,
    RuleInput,
)

router = APIRouter(prefix="/api/projects/{project_id}/requirements", tags=["requirements"])


@router.get("/risk-reports/{report_id}/chat")
def chat_history(
    project_id: int,
    report_id: int,
    actor: Actor,
    db: DB,
    before: int | None = Query(default=None, ge=1),
    function_key: str = Query(default="", max_length=200),
):
    return chat_service.listing(project_id, report_id, actor, db, before, function_key.strip())


@router.post(
    "/risk-reports/{report_id}/chat", dependencies=[Depends(check_origin)], status_code=202
)
def chat_send(
    project_id: int,
    report_id: int,
    payload: ChatInput,
    actor: Actor,
    db: DB,
    function_key: str = Query(default="", max_length=200),
):
    return chat_service.enqueue(project_id, report_id, payload, actor, db, function_key.strip())


@router.post(
    "/risk-reports/{report_id}/chat/{turn_id}/cancel", dependencies=[Depends(check_origin)]
)
def chat_cancel(project_id: int, report_id: int, turn_id: int, actor: Actor, db: DB):
    return chat_service.cancel(project_id, report_id, turn_id, actor, db)


@router.get("/risk-analyses")
def risk_analyses(project_id: int, actor: Actor, db: DB):
    return risk_analysis_service.listing(project_id, actor, db)


@router.post("/risk-analyses", dependencies=[Depends(check_origin)], status_code=202)
def start_risk_analysis(project_id: int, payload: AnalysisRequest, actor: Actor, db: DB):
    return risk_analysis_service.enqueue(project_id, payload, actor, db)


@router.get("/risk-analyses/{task_id}/candidate")
def risk_candidate(project_id: int, task_id: int, actor: Actor, db: DB):
    path = risk_analysis_service.candidate(project_id, task_id, actor, db)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=f"requirement-analysis-{task_id}-ai-candidate.txt",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/risk-analyses/{task_id}/revalidate", dependencies=[Depends(check_origin)])
def revalidate_risk_candidate(project_id: int, task_id: int, actor: Actor, db: DB):
    return risk_analysis_service.revalidate_candidate(project_id, task_id, actor, db)


@router.post("/risk-analyses/{task_id}/cancel", dependencies=[Depends(check_origin)])
def cancel_risk_analysis(project_id: int, task_id: int, actor: Actor, db: DB):
    return risk_analysis_service.cancel(project_id, task_id, actor, db)


@router.get("/risk-reports/options")
def risk_options(project_id: int, actor: Actor, db: DB):
    return risk_service.choices(project_id, actor, db)


@router.get("/risk-reports")
def risk_reports(project_id: int, actor: Actor, db: DB, page: int = Query(default=1, ge=1)):
    return risk_service.listing(project_id, actor, db, page)


@router.get("/risk-reports-catalog")
def risk_catalog(
    project_id: int,
    actor: Actor,
    db: DB,
    page: int = Query(default=1, ge=1),
    source: int = Query(default=0, ge=0),
    function: str = Query(default="", max_length=500),
    severity: str = Query(default="", pattern="^(|HIGH|MEDIUM|LOW)$"),
    state: str = Query(default="", pattern="^(|PENDING|NEEDS_INFO|RESOLVED|NOT_APPLICABLE)$"),
):
    return risk_service.catalog(project_id, actor, db, page, source, function, severity, state)


@router.get("/risk-reports-export")
def export_risk_catalog(
    project_id: int,
    actor: Actor,
    db: DB,
    source: int = Query(default=0, ge=0),
    function: str = Query(default="", max_length=500),
    severity: str = Query(default="", pattern="^(|HIGH|MEDIUM|LOW)$"),
    state: str = Query(default="", pattern="^(|PENDING|NEEDS_INFO|RESOLVED|NOT_APPLICABLE)$"),
):
    body = risk_service.export_markdown(project_id, actor, db, source, function, severity, state)
    return Response(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="requirement-risks.md"'},
    )


@router.post("/risk-reports/import", dependencies=[Depends(check_origin)], status_code=201)
async def import_risk_report(project_id: int, request: Request, actor: Actor, db: DB):
    return await risk_service.import_report(project_id, request.stream(), actor, db)


@router.get("/risk-reports/{report_id}")
def risk_detail(project_id: int, report_id: int, actor: Actor, db: DB):
    return risk_service.detail(project_id, report_id, actor, db)


@router.post("/risk-reports/{report_id}/handling", dependencies=[Depends(check_origin)])
def handle_risk(project_id: int, report_id: int, payload: HandlingInput, actor: Actor, db: DB):
    return risk_service.handle(project_id, report_id, payload, actor, db)


@router.post(
    "/risk-reports/{report_id}/manual-risks",
    dependencies=[Depends(check_origin)],
    status_code=201,
)
def create_manual_risk(
    project_id: int, report_id: int, payload: ManualRiskInput, actor: Actor, db: DB
):
    return risk_service.create_manual(project_id, report_id, payload, actor, db)


@router.post(
    "/risk-reports/{report_id}/manual-risks/{risk_id}/handling",
    dependencies=[Depends(check_origin)],
)
def handle_manual_risk(
    project_id: int,
    report_id: int,
    risk_id: int,
    payload: ManualHandlingInput,
    actor: Actor,
    db: DB,
):
    return risk_service.handle_manual(project_id, report_id, risk_id, payload, actor, db)


@router.get("/risk-reports/{report_id}/export")
def export_risk(
    project_id: int,
    report_id: int,
    actor: Actor,
    db: DB,
    kind: str = Query(pattern="^(input|report)$"),
):
    result = risk_service.detail(project_id, report_id, actor, db)
    return Response(
        json.dumps(result[kind], ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{kind}.json"'},
    )


@router.get("")
def state(project_id: int, actor: Actor, db: DB):
    return service.state(project_id, actor, db)


@router.get("/classification-history")
def classification_history(project_id: int, actor: Actor, db: DB):
    return service.classification_history(project_id, actor, db)


@router.post("/categories", dependencies=[Depends(check_origin)], status_code=201)
def create_category(project_id: int, payload: CategoryInput, actor: Actor, db: DB):
    return service.save_category(project_id, None, payload, actor, db)


@router.patch("/categories/{category_id}", dependencies=[Depends(check_origin)])
def edit_category(project_id: int, category_id: int, payload: CategoryInput, actor: Actor, db: DB):
    return service.save_category(project_id, category_id, payload, actor, db)


@router.post("/move", dependencies=[Depends(check_origin)])
def move(project_id: int, payload: Move, actor: Actor, db: DB):
    return service.move(project_id, payload, actor, db)


@router.post("/categories/{category_id}/delete", dependencies=[Depends(check_origin)])
def delete_category(
    project_id: int, category_id: int, payload: DeleteCategory, actor: Actor, db: DB
):
    return service.delete_category(project_id, category_id, payload, actor, db)


@router.post("/assign", dependencies=[Depends(check_origin)])
def assign(project_id: int, payload: Assign, actor: Actor, db: DB):
    return service.assign(project_id, payload, actor, db)


@router.post("/undo/{event_id}", dependencies=[Depends(check_origin)])
def undo(project_id: int, event_id: int, payload: Revision, actor: Actor, db: DB):
    return service.undo(project_id, event_id, payload.revision, actor, db)


@router.get("/rules/{rule_id}")
def detail(project_id: int, rule_id: int, actor: Actor, db: DB):
    return service.detail(project_id, rule_id, actor, db)


@router.post("/rules", dependencies=[Depends(check_origin)], status_code=201)
def create_rule(project_id: int, payload: RuleInput, actor: Actor, db: DB):
    return service.save_rule(project_id, None, payload, actor, db)


@router.patch("/rules/{rule_id}", dependencies=[Depends(check_origin)])
def edit_rule(project_id: int, rule_id: int, payload: RuleInput, actor: Actor, db: DB):
    return service.save_rule(project_id, rule_id, payload, actor, db)


@router.get("/risk-reports/{report_id}/deletion")
def deletion_requirements(project_id: int, report_id: int, actor: Actor, db: DB):
    return record_deletion.info(project_id, "requirements", report_id, actor, db)


@router.post("/risk-reports/{report_id}/delete", dependencies=[Depends(check_origin)])
def delete_requirements(
    project_id: int, report_id: int, payload: record_deletion.DeleteRequest, actor: Actor, db: DB
):
    return record_deletion.remove(project_id, "requirements", report_id, payload, actor, db)


@router.get("/risk-analyses/{task_id}/deletion")
def deletion_requirement_task(project_id: int, task_id: int, actor: Actor, db: DB):
    return record_deletion.info(project_id, "requirement-task", task_id, actor, db)


@router.post("/risk-analyses/{task_id}/delete", dependencies=[Depends(check_origin)])
def delete_requirement_task(
    project_id: int, task_id: int, payload: record_deletion.DeleteRequest, actor: Actor, db: DB
):
    return record_deletion.remove(project_id, "requirement-task", task_id, payload, actor, db)


@router.get("/risk-analyses/{task_id}/candidate-review")
def candidate_review_get(project_id: int, task_id: int, actor: Actor, db: DB):
    return candidate_review.review(project_id, task_id, actor, db)


@router.post("/risk-analyses/{task_id}/candidate-review", dependencies=[Depends(check_origin)])
def candidate_review_save(
    project_id: int, task_id: int, payload: CandidateReviewInput, actor: Actor, db: DB
):
    return candidate_review.review(project_id, task_id, actor, db, payload)
