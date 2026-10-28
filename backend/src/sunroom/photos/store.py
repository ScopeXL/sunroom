"""The core photo store (PLAN §10.1, ADR 0009): files on the volume, indexed in SQLite.

    $DATA_DIR/photos/library/<id>.webp   up to 2560 px on the long side
    $DATA_DIR/photos/thumbs/<id>.webp    up to 400 px
    $DATA_DIR/photos/avatars/<id>.webp   512 by 512, centered
    $DATA_DIR/photos/inbox/              files dropped in by hand (the screensaver plugin, M4)
    $DATA_DIR/photos/.orphans/           files the reconcile found without a row

Re-encoding is the privacy step: a phone's photo carries EXIF (often the GPS position of the
home), and WebP written without ``exif=`` keeps none of it. The camera's rotation is applied
first, and the time it was taken is read before the rest is dropped. iPhone HEIC files are read
through pillow-heif. An upload identical to one already stored (same kind, same SHA-256) is the
same photo, brought back if it had been removed.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener  # pyright: ignore[reportUnknownVariableType]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunroom.core.errors import AppError
from sunroom.core.logging import get_logger
from sunroom.photos.models import Photo, PhotoKind

register_heif_opener()
log = get_logger(__name__)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
LIBRARY_SIDE = 2560
THUMB_SIDE = 400
AVATAR_SIDE = 512
QUALITY = 82
MIN_FREE_BYTES = 200 * 1024 * 1024
_EXIF_DATETIME_ORIGINAL = 0x9003
_EXIF_OFFSET_TIME_ORIGINAL = 0x9011
_EXIF_IFD = 0x8769

FOLDERS = {"library": "library", "thumbs": "thumbs", "avatars": "avatars"}


@dataclass(frozen=True, slots=True)
class Encoded:
    main: bytes
    thumb: bytes | None
    width: int
    height: int
    taken_at: datetime | None


def _unreadable() -> AppError:
    return AppError(422, "photo_unreadable", "That photo couldn't be read. Try a different one.")


def _open(data: bytes) -> tuple[Image.Image, datetime | None, str | None]:
    """The image upright in RGB, and when it was taken (naive) with its EXIF offset, if any."""
    try:
        with Image.open(io.BytesIO(data)) as original:
            original.load()
            exif = original.getexif()
            sub = exif.get_ifd(_EXIF_IFD)
            stamp = sub.get(_EXIF_DATETIME_ORIGINAL)
            offset = sub.get(_EXIF_OFFSET_TIME_ORIGINAL)
            upright = ImageOps.exif_transpose(original)
            image = upright.convert("RGB")
    except UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError:
        raise _unreadable() from None
    taken: datetime | None = None
    if isinstance(stamp, str):
        try:
            taken = datetime.strptime(stamp.strip(), "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007 - EXIF is local
        except ValueError:
            taken = None
    return image, taken, offset if isinstance(offset, str) else None


def _taken_utc(naive: datetime | None, offset: str | None, zone: ZoneInfo) -> datetime | None:
    if naive is None:
        return None
    if offset:
        try:
            return datetime.fromisoformat(naive.isoformat() + offset.strip()).astimezone(UTC)
        except ValueError:
            pass
    return naive.replace(tzinfo=zone).astimezone(UTC)


def _webp(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="WEBP", quality=QUALITY, method=4)
    return out.getvalue()


def encode_library(data: bytes, zone: ZoneInfo) -> Encoded:
    image, taken, offset = _open(data)
    image.thumbnail((LIBRARY_SIDE, LIBRARY_SIDE), Image.Resampling.LANCZOS)
    thumb = image.copy()
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    return Encoded(
        _webp(image), _webp(thumb), image.width, image.height, _taken_utc(taken, offset, zone)
    )


def encode_avatar(data: bytes) -> Encoded:
    image, _taken, _offset = _open(data)
    square = ImageOps.fit(image, (AVATAR_SIDE, AVATAR_SIDE), Image.Resampling.LANCZOS)
    return Encoded(_webp(square), None, AVATAR_SIDE, AVATAR_SIDE, None)


def _write_atomic(path: Path, data: bytes) -> None:
    partial = path.with_name(path.name + ".partial")
    with partial.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


class PhotoStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure_folders(self) -> None:
        for name in ("library", "thumbs", "avatars", "inbox", ".orphans"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def file(self, folder: str, photo_id: str) -> Path:
        return self.root / FOLDERS[folder] / f"{photo_id}.webp"

    @property
    def inbox(self) -> Path:
        """Files dropped in by hand; the screensaver plugin imports them (PLAN §11.4)."""
        return self.root / "inbox"

    def thumb_missing(self, photo: Photo) -> bool:
        """A library photo whose picture is here but whose thumbnail isn't (a crash mid-import)."""
        return (
            photo.kind == PhotoKind.LIBRARY
            and self.file("library", photo.id).is_file()
            and not self.file("thumbs", photo.id).is_file()
        )

    def rebuild_thumb(self, photo: Photo) -> bool:
        """Make a library photo's thumbnail again from its stored picture. Blocking: run it in a
        thread. False when there's no picture to make it from."""
        source = self.file("library", photo.id)
        if photo.kind != PhotoKind.LIBRARY or not source.is_file():
            return False
        try:
            with Image.open(source) as stored:
                thumb = stored.convert("RGB")
        except UnidentifiedImageError, OSError:
            return False
        thumb.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
        _write_atomic(self.file("thumbs", photo.id), _webp(thumb))
        return True

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root if self.root.exists() else self.root.parent).free

    def _check_room(self) -> None:
        if self.free_bytes() < MIN_FREE_BYTES:
            raise AppError(
                507,
                "storage_full",
                "Photos need room. Remove some, or move photos to a bigger disk (About → Storage).",
            )

    async def encode(self, data: bytes, *, kind: PhotoKind, zone: ZoneInfo) -> Encoded:
        """Re-encode a photo (in a thread). Call it before the write transaction and hand the
        result to ``ingest``: on a Pi it takes a second or more, and every other change in the
        app waits while the write lock is held."""
        self._check_room()
        if kind is PhotoKind.AVATAR:
            return await asyncio.to_thread(encode_avatar, data)
        return await asyncio.to_thread(encode_library, data, zone)

    async def ingest(
        self,
        session: AsyncSession,
        data: bytes,
        *,
        kind: PhotoKind,
        zone: ZoneInfo,
        now: datetime,
        source_key: str = "upload",
        original_name: str | None = None,
        encoded: Encoded | None = None,
        taken_at: datetime | None = None,
    ) -> Photo:
        """Store a photo (or bring back the same one, removed or not). ``encoded``: from
        ``encode``, done outside the transaction; without it the encoding happens here.
        ``taken_at``: when it was taken, if its EXIF doesn't say (a photo library's preview
        carries none; the library's record does)."""
        self._check_room()
        digest = hashlib.sha256(data).hexdigest()
        existing = await session.scalar(
            select(Photo).where(Photo.kind == kind.value, Photo.sha256 == digest)
        )
        if existing is not None and self._files_present(existing):
            existing.deleted_at = None
            return existing
        if encoded is None:
            encoded = await self.encode(data, kind=kind, zone=zone)
        photo = existing or Photo(kind=kind.value, sha256=digest)
        photo.source_key = source_key
        photo.original_name = (original_name or "")[:255] or None
        photo.taken_at = encoded.taken_at or taken_at
        photo.width, photo.height = encoded.width, encoded.height
        photo.bytes = len(encoded.main)
        photo.deleted_at = None
        if existing is None:
            photo.created_at = now
            session.add(photo)
            await session.flush()
        await asyncio.to_thread(self._write_files, photo, encoded)
        return photo

    def _main_folder(self, photo: Photo) -> str:
        return "avatars" if photo.kind == PhotoKind.AVATAR else "library"

    def _files_present(self, photo: Photo) -> bool:
        if not self.file(self._main_folder(photo), photo.id).is_file():
            return False
        return photo.kind == PhotoKind.AVATAR or self.file("thumbs", photo.id).is_file()

    def _write_files(self, photo: Photo, encoded: Encoded) -> None:
        self.ensure_folders()
        _write_atomic(self.file(self._main_folder(photo), photo.id), encoded.main)
        if encoded.thumb is not None:
            _write_atomic(self.file("thumbs", photo.id), encoded.thumb)

    def delete_files(self, photo: Photo) -> None:
        for folder in (self._main_folder(photo), "thumbs"):
            self.file(folder, photo.id).unlink(missing_ok=True)

    async def reconcile(self, session: AsyncSession) -> tuple[int, int]:
        """Hide rows whose file is gone; move files without a row to .orphans/ (every 6 hours).
        Returns (rows hidden, files moved)."""
        rows = {photo.id: photo for photo in await session.scalars(select(Photo))}
        hidden = 0
        for photo in rows.values():
            if photo.deleted_at is None and not photo.hidden and not self._files_present(photo):
                photo.hidden = True
                hidden += 1
        moved = await asyncio.to_thread(self._quarantine, set(rows))
        if hidden or moved:
            log.warning("photos.reconciled", hidden=hidden, quarantined=moved)
        return hidden, moved

    def _quarantine(self, known: set[str]) -> int:
        moved = 0
        orphans = self.root / ".orphans"
        for folder in FOLDERS.values():
            directory = self.root / folder
            if not directory.is_dir():
                continue
            for path in directory.glob("*.webp"):
                if path.stem not in known:
                    orphans.mkdir(parents=True, exist_ok=True)
                    os.replace(path, orphans / f"{folder}-{path.name}")
                    moved += 1
        return moved
