import hashlib

import pytest

from app.config import ImageStoreConfig
from app.images import ImageStore, ImageStoreError


class FakeS3:
    """Records put_object calls in place of a real boto3 S3 client."""

    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_unconfigured_store_raises(tmp_path):
    """With no bucket/public base set, upload fails closed with a clear message."""
    image = tmp_path / 'a.png'
    image.write_bytes(b'data')
    store = ImageStore(ImageStoreConfig(), client=FakeS3())

    with pytest.raises(ImageStoreError, match='not configured'):
        store.upload(str(image))


def test_upload_missing_file_raises():
    """A missing file is reported rather than handed to the backend."""
    config = ImageStoreConfig(bucket='bucket', public_base='https://cdn.example.com')
    store = ImageStore(config, client=FakeS3())

    with pytest.raises(ImageStoreError, match='not found'):
        store.upload('/no/such/file.png')


def test_upload_puts_object_and_returns_content_hashed_url(tmp_path):
    """Upload stores the bytes under a content-hashed key and returns its public URL."""
    image = tmp_path / 'shot.png'
    image.write_bytes(b'imagedata')
    config = ImageStoreConfig(
        bucket='bucket', public_base='https://cdn.example.com', region='eu-west-1', key_prefix='shots'
    )
    fake = FakeS3()
    store = ImageStore(config, client=fake)

    url = store.upload(str(image))

    digest = hashlib.sha256(b'imagedata').hexdigest()[:8]
    expected_key = f'shots/shot-{digest}.png'
    assert url == f'https://cdn.example.com/{expected_key}'
    assert fake.calls == [
        {
            'Bucket': 'bucket',
            'Key': expected_key,
            'Body': b'imagedata',
            'ContentType': 'image/png',
        }
    ]


def test_upload_without_prefix_keys_at_root(tmp_path):
    """With no key prefix the object key is just the hashed filename."""
    image = tmp_path / 'p.png'
    image.write_bytes(b'x')
    store = ImageStore(ImageStoreConfig(bucket='b', public_base='https://cdn.example.com'), client=FakeS3())

    url = store.upload(str(image))

    digest = hashlib.sha256(b'x').hexdigest()[:8]
    assert url == f'https://cdn.example.com/p-{digest}.png'
