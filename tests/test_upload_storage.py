import pytest

from gigamind.services.storage import StorageService


def test_immutable_create_propagates_collision():
    class Store:
        def __init__(self):
            self.objects = {}

        def put_object(self, **request):
            assert request['IfNoneMatch'] == '*'
            key = request['Key']
            if key in self.objects:
                raise RuntimeError('collision')
            self.objects[key] = request['Body']

    storage = StorageService()
    storage.enabled = True
    storage.s3_client = Store()
    storage.create_immutable_object('key', b'first', 'text/plain')
    with pytest.raises(RuntimeError, match='collision'):
        storage.create_immutable_object('key', b'second', 'text/plain')
    assert storage.s3_client.objects['key'] == b'first'
