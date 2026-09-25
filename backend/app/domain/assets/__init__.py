"""Asset domain interface."""

from app.domain.assets.deletion import Deleted, delete_asset as delete_asset_with_clips
from app.domain.assets.importer import (
    import_binary_asset,
    import_uploaded_asset,
    reconcile_broken_media_info,
    register_file_asset,
)
from app.domain.assets.project_scope import AssetProjectError, asset_project

__all__ = [
    "AssetProjectError",
    "Deleted",
    "asset_project",
    "delete_asset_with_clips",
    "import_binary_asset",
    "import_uploaded_asset",
    "reconcile_broken_media_info",
    "register_file_asset",
]

