from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.services.cloudinary_service import upload_image

router = APIRouter()


@router.post("", response_model=dict)
async def upload_file(
    file: UploadFile = File(...),
    kind: str = Form("general"),
):
    """
    Upload an image file to Cloudinary and return its secure URL.
    Accepts multipart/form-data with fields:
    - file: image file
    - kind: optional folder hint (profile, cover, signup, general)
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image uploads are allowed",
        )

    safe_kind = (kind or "general").strip().lower()
    safe_kind = "".join(ch for ch in safe_kind if ch.isalnum() or ch in ("-", "_")) or "general"

    try:
        secure_url = await upload_image(file.file, folder=f"bookmyshoot/{safe_kind}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cloudinary upload failed: {exc}",
        ) from exc

    return {"secure_url": secure_url}
