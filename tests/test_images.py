import hashlib
import re

import pytest

from app.config import ImageStoreConfig
from app.images import ImageStore, ImageStoreError


class FakeS3:
    """Records put_object / generate_presigned_url calls in place of a boto3 client."""

    def __init__(self):
        self.calls = []
        self.presigned = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)

    def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803 - boto3 kwarg name
        self.presigned.append({'operation': operation, 'Params': Params, 'ExpiresIn': ExpiresIn})
        return f'https://s3.example.test/{Params["Key"]}?signature=fake&expires={ExpiresIn}'


def test_presign_put_returns_signed_and_public_urls():
    """presign_put builds a product-foldered, random-suffixed key and both URLs."""
    config = ImageStoreConfig(bucket='b', public_base='https://cdn.example.com', key_prefix='help')
    fake = FakeS3()
    store = ImageStore(config, client=fake)

    result = store.presign_put('tutors-add.png', product='bobbin')

    assert fake.presigned[0]['operation'] == 'put_object'
    key = fake.presigned[0]['Params']['Key']
    assert re.fullmatch(r'help/bobbin/tutors-add-[0-9a-f]{8}\.png', key)
    assert fake.presigned[0]['Params']['Bucket'] == 'b'
    assert result['public_url'] == f'https://cdn.example.com/{key}'
    assert result['put_url'].startswith('https://s3.example.test/')


def test_presign_put_unconfigured_raises():
    """presign_put fails closed when the store isn't configured."""
    store = ImageStore(ImageStoreConfig(), client=FakeS3())

    with pytest.raises(ImageStoreError, match='not configured'):
        store.presign_put('x.png', product='bobbin')


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


def test_upload_nests_under_product_folder(tmp_path):
    """A product is inserted as a key sub-folder so each product is kept separate."""
    image = tmp_path / 'shot.png'
    image.write_bytes(b'imagedata')
    store = ImageStore(ImageStoreConfig(bucket='b', public_base='https://cdn.example.com'), client=FakeS3())

    url = store.upload(str(image), product='bobbin')

    digest = hashlib.sha256(b'imagedata').hexdigest()[:8]
    assert url == f'https://cdn.example.com/bobbin/shot-{digest}.png'


def test_upload_product_nested_under_prefix(tmp_path):
    """When a base prefix is also set, the key is <prefix>/<product>/<file>."""
    image = tmp_path / 'shot.png'
    image.write_bytes(b'imagedata')
    config = ImageStoreConfig(bucket='b', public_base='https://cdn.example.com', key_prefix='help')
    fake = FakeS3()
    store = ImageStore(config, client=fake)

    store.upload(str(image), product='tutorcruncher')

    digest = hashlib.sha256(b'imagedata').hexdigest()[:8]
    assert fake.calls[0]['Key'] == f'help/tutorcruncher/shot-{digest}.png'
