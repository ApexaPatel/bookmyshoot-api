import cloudinary
import cloudinary.uploader

from app.core.config import settings


def configure_cloudinary() -> None:
    cloudinary.config(
        cloud_name=settings.CLOUD_NAME,
        api_key=settings.API_KEY,
        api_secret=settings.API_SECRET,
        secure=True,
    )


async def upload_image(file_obj, folder: str) -> str:
    result = cloudinary.uploader.upload(file_obj, folder=folder, resource_type="image")
    return result["secure_url"]
