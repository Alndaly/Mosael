"""Settings API composition.

The /settings URL prefix contains several independently owned domains.  This
module only composes their routers; behavior belongs to the matching module.
"""

from fastapi import APIRouter

from app.api.routes.settings.provider_defaults import router as provider_defaults_router
from app.api.routes.settings.provider_models import router as provider_models_router
from app.api.routes.settings.provider_oauth import router as provider_oauth_router
from app.api.routes.settings.provider_pricing import router as provider_pricing_router
from app.api.routes.settings.provider_profiles import router as provider_profiles_router
from app.api.routes.settings.system import router as system_router
from app.api.routes.settings.data import router as data_router

router = APIRouter()
for subrouter in (
    provider_profiles_router,
    provider_oauth_router,
    provider_models_router,
    provider_defaults_router,
    provider_pricing_router,
    system_router,
    data_router,
):
    router.include_router(subrouter)
