"""Image hosting for refreshed help-article screenshots.

Intercom has no public image-upload API: an article ``body`` is an HTML subset and
images are plain ``<img src="…">`` tags. To swap a screenshot we host the new PNG in
an external object store and embed its public URL into the body.

The object key includes a short content hash, so a different image always gets a
different URL — this avoids overwriting a distinct image that happens to share a
filename and cache-busts the help centre when a screenshot is refreshed.

UNVERIFIED against live infrastructure. Before production use, confirm:
  1. the bucket is publicly readable at ``IMAGE_STORE_PUBLIC_BASE``; and
  2. Intercom renders an externally-hosted ``<img src>`` in a published help-centre
     article without stripping or proxying it.

The S3 backend imports ``boto3`` lazily (declared in the optional ``s3`` extra), so
the core server has no hard dependency on it; upload raises a clear error when the
store is unconfigured or the dependency is missing.
"""

import hashlib
import logging
import mimetypes
from pathlib import Path

from app.config import ImageStoreConfig

logger = logging.getLogger('tc_help_mcp.images')


class ImageStoreError(RuntimeError):
    """Raised when an image cannot be hosted (unconfigured, missing file, or upload failure)."""


class ImageStore:
    """Host local image files in an S3-compatible object store, returning public URLs."""

    def __init__(self, config: ImageStoreConfig, client=None) -> None:
        """Build a store.

        Args:
            config: Bucket / public-base / region / key-prefix settings.
            client: Optional pre-built S3 client (used in tests). When omitted, a
                boto3 S3 client is created lazily on first upload.
        """
        self._config = config
        self._client = client

    def _s3(self):
        """Return the S3 client, building a boto3 one lazily if none was injected."""
        if self._client is not None:
            return self._client
        try:
            import boto3  # ty: ignore[unresolved-import]  # optional 's3' extra; absent in base env
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the extra
            raise ImageStoreError(
                "Image upload needs boto3; install the 's3' extra (e.g. `uv sync --extra s3`)."
            ) from exc
        self._client = boto3.client('s3', region_name=self._config.region)
        return self._client

    def _key_for(self, path: Path, data: bytes) -> str:
        """Build the storage key: ``<prefix>/<stem>-<hash8><suffix>``."""
        digest = hashlib.sha256(data).hexdigest()[:8]
        name = f'{path.stem}-{digest}{path.suffix}'
        return '/'.join(part for part in (self._config.key_prefix, name) if part)

    def upload(self, image_path: str) -> str:
        """Upload a local image file and return its public URL.

        Args:
            image_path: Absolute path to the image on disk.

        Returns:
            The public URL the uploaded image is served from.

        Raises:
            ImageStoreError: If the store is unconfigured, the file is missing, or
                the upload fails.
        """
        if not self._config.configured:
            raise ImageStoreError('Image store not configured: set IMAGE_STORE_BUCKET and IMAGE_STORE_PUBLIC_BASE.')
        path = Path(image_path)
        if not path.is_file():
            raise ImageStoreError(f'Image not found: {image_path}')
        data = path.read_bytes()
        key = self._key_for(path, data)
        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        try:
            self._s3().put_object(Bucket=self._config.bucket, Key=key, Body=data, ContentType=content_type)
        except ImageStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any backend failure as a readable error
            raise ImageStoreError(f'Failed to upload {path.name} to the image store: {exc}') from exc
        url = f'{self._config.public_base}/{key}'
        logger.info('uploaded image %s -> %s', path.name, url)
        return url
