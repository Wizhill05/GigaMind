import pytest

from gigamind.services.storage import StorageService


def service(client, enabled=True):
    # No configuration lookup or SDK construction against inherited credentials.
    storage = StorageService.__new__(StorageService)
    storage.enabled = enabled
    storage.s3_client = client
    storage.bucket_name = "isolated-test-bucket"
    return storage


def test_immutable_create_propagates_collision():
    class Store:
        def __init__(self):
            self.objects = {}

        def put_object(self, **request):
            assert request["IfNoneMatch"] == "*"
            key = request["Key"]
            if key in self.objects:
                raise RuntimeError("collision")
            self.objects[key] = request["Body"]

    storage = service(Store())
    storage.create_immutable_object("key", b"first", "text/plain")
    with pytest.raises(RuntimeError, match="collision"):
        storage.create_immutable_object("key", b"second", "text/plain")
    assert storage.s3_client.objects["key"] == b"first"


def test_installed_sdk_accepts_conditional_creation_contract():
    import boto3
    from botocore.stub import Stubber
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:1",
        region_name="auto",
        aws_access_key_id="test-only",
        aws_secret_access_key="test-only",
    )
    expected = {
        "Bucket": "isolated-test-bucket",
        "Key": "key",
        "Body": b"first",
        "ContentType": "text/plain",
        "IfNoneMatch": "*",
    }
    try:
        with Stubber(client) as stub:
            stub.add_response("put_object", {"ETag": '"test-etag"'}, expected)
            stub.add_client_error(
                "put_object",
                service_error_code="PreconditionFailed",
                http_status_code=412,
                expected_params=expected,
            )
            storage = service(client)
            storage.create_immutable_object("key", b"first", "text/plain")
            with pytest.raises(ClientError) as collision:
                storage.create_immutable_object("key", b"first", "text/plain")
            assert collision.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
            stub.assert_no_pending_responses()
    finally:
        client.close()


def test_disabled_storage_does_not_attempt_remote_creation():
    class Store:
        def put_object(self, **request):
            raise AssertionError("disabled storage attempted IO")

    with pytest.raises(RuntimeError, match="not configured"):
        service(Store(), enabled=False).create_immutable_object(
            "key", b"first", "text/plain"
        )


def test_unknown_remote_outcome_is_not_reported_as_success():
    objects = {}

    class Store:
        def put_object(self, **request):
            objects[request["Key"]] = request["Body"]
            raise TimeoutError("acknowledgement lost")

    with pytest.raises(TimeoutError, match="acknowledgement lost"):
        service(Store()).create_immutable_object("key", b"first", "text/plain")
    assert objects == {"key": b"first"}
