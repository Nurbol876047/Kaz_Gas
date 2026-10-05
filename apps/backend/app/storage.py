import hashlib
import io
import os
import uuid
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from app.config import get_settings

Image.MAX_IMAGE_PIXELS = 20_000_000


def normalize_image(raw: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported image")
                probe.verify()
            with Image.open(io.BytesIO(raw)) as original:
                clean = ImageOps.exif_transpose(original).convert("RGB")
                clean.thumbnail((4096, 4096))
                output = io.BytesIO()
                clean.save(output, "JPEG", quality=88)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise HTTPException(422, "Жарамды JPEG, PNG немесе WebP фотосын жіберіңіз") from exc


async def save_photo(upload: UploadFile, max_bytes: int) -> tuple[str, str]:
    """Returns (storage key, sha256 of the normalized bytes) so callers can spot resubmitted photos."""
    if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "Тек JPEG, PNG, WebP")
    raw = await upload.read(max_bytes + 1)
    if not raw or len(raw) > max_bytes:
        raise HTTPException(413, "Фото көлемі шектен асты")
    normalized = await run_in_threadpool(normalize_image, raw)
    key = f"{uuid.uuid4()}.jpg"
    directory = get_settings().upload_dir
    await run_in_threadpool(directory.mkdir, parents=True, exist_ok=True)

    def write():
        with open(directory / key, "xb") as file:
            file.write(normalized)
            file.flush()
            os.fsync(file.fileno())

    await run_in_threadpool(write)
    return key, hashlib.sha256(normalized).hexdigest()


def storage_path(key: str) -> Path:
    root = get_settings().upload_dir.resolve()
    path = (root / key).resolve()
    if path.parent != root or path.suffix != ".jpg":
        raise HTTPException(404, "Фото табылмады")
    return path
