from fastapi import APIRouter

from app.modules.acceptance.router import router as acceptance_router
from app.modules.accounts.router import router as accounts_router
from app.modules.ai.router import router as ai_router
from app.modules.auth.router import router as auth_router
from app.modules.case_analysis.router import router as case_analysis_router
from app.modules.case_generation.router import router as generation_router
from app.modules.cases.router import router as cases_router
from app.modules.change_analysis.router import router as change_analysis_router
from app.modules.code_analysis.router import router as code_analysis_router
from app.modules.documents.router import router as documents_router
from app.modules.github.router import router as github_router
from app.modules.local_code.router import router as local_code_router
from app.modules.overview.router import router as overview_router
from app.modules.projects.router import router as projects_router
from app.modules.prototypes.router import router as prototypes_router
from app.modules.requirements.router import router as requirements_router
from app.modules.skills.router import router as skills_router

router = APIRouter()
router.include_router(acceptance_router)
router.include_router(overview_router)
router.include_router(skills_router)
router.include_router(case_analysis_router)
router.include_router(local_code_router)
router.include_router(prototypes_router)
router.include_router(requirements_router)
router.include_router(cases_router)
router.include_router(generation_router)
router.include_router(code_analysis_router)
router.include_router(change_analysis_router)
for module_router in (
    auth_router,
    accounts_router,
    ai_router,
    github_router,
    projects_router,
    documents_router,
):
    router.include_router(module_router)
