"""Public, versioned brand images used by invitation emails (no user data)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


router = APIRouter(prefix="/invitations/assets")
_ASSET_DIR = Path(__file__).resolve().parents[2] / "brainrh" / "assets" / "invitations"
_ASSETS = {
    "brain-b-v1.gif": (_ASSET_DIR / "brain-b-v1.gif", "image/gif"),
    "brain-b-v1.png": (_ASSET_DIR / "brain-b-v1.png", "image/png"),
}


@router.get("/{asset_name}", include_in_schema=False)
def invitation_asset(asset_name: str) -> FileResponse:
    asset = _ASSETS.get(asset_name)
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    path, media_type = asset
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
