"""
API v1 router.

All v1 sub-routers are registered here. main.py includes this single router
with the /api/v1 prefix. Health endpoints are registered at root (no prefix).
"""

from fastapi import APIRouter

from api.v1.analytics.router import router as analytics_router
from api.v1.auth.router import router as auth_router
from api.v1.health.router import router as health_router
from api.v1.organizations.router import router as orgs_router
from api.v1.playground.router import router as playground_router
from api.v1.projects.router import router as projects_router
from api.v1.routes.router import router as routes_router
from api.v1.upstreams.router import router as upstreams_router

# Root-level routers (no /api/v1 prefix — health endpoints must be at /)
health_router_root = health_router

# v1 API router
api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(orgs_router)
api_v1_router.include_router(projects_router)
api_v1_router.include_router(upstreams_router)
api_v1_router.include_router(routes_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(playground_router)
