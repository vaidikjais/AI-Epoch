"""MinIO/S3 object storage utilities."""
import asyncio
import io
from uuid import uuid4

from minio import Minio

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("s3_utils")

_client = None


def get_s3_client():
    global _client
    if _client is None:
        endpoint = settings.S3_ENDPOINT.replace("http://", "").replace("https://", "")
        _client = Minio(
            endpoint,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            secure=getattr(settings, "S3_SECURE", False),
        )
        bucket_name = getattr(settings, "S3_BUCKET", "articles")
        if not _client.bucket_exists(bucket_name):
            _client.make_bucket(bucket_name)
            logger.info(f"Created bucket: {bucket_name}")
    return _client


def upload_text(data: bytes) -> str:
    client = get_s3_client()
    key = f"article-{uuid4()}"
    bucket_name = getattr(settings, "S3_BUCKET", "articles")

    client.put_object(
        bucket_name=bucket_name,
        object_name=key,
        data=io.BytesIO(data),
        length=len(data),
        content_type="text/plain",
    )

    logger.info(f"Uploaded text to S3: {key}")
    return key


def download_text(key: str) -> str:
    client = get_s3_client()
    bucket_name = getattr(settings, "S3_BUCKET", "articles")

    try:
        response = client.get_object(bucket_name, key)
        data = response.read()
        response.close()
        response.release_conn()

        return data.decode("utf-8")

    except Exception as e:
        logger.error(f"Failed to download text from S3 key {key}: {e}")
        raise


async def async_upload_text(data: bytes) -> str:
    """Async wrapper — runs sync MinIO call in thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, upload_text, data)


async def async_download_text(key: str) -> str:
    """Async wrapper — runs sync MinIO call in thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, download_text, key)
