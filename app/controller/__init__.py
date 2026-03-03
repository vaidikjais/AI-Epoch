"""Controller layer for FastAPI routes."""
from .pipelines_controller import router as pipelines_router
from .articles_controller import router as articles_router
from .admin_controller import router as admin_router
from .scout_controller import router as scout_router
from .curator_controller import router as curator_router
from .extractor_controller import router as extractor_router
from .email_controller import router as email_router
from .email_group_controller import router as email_groups_router

__all__ = [
    "pipelines_router",
    "articles_router",
    "admin_router",
    "scout_router",
    "curator_router",
    "extractor_router",
    "email_router",
    "email_groups_router",
]
