import pytest
from unittest.mock import MagicMock, patch
from app.modules.strategy_service.services.storage_service import StorageService


@pytest.mark.asyncio
@patch("app.modules.strategy_service.services.storage_service.boto3.client")
async def test_storage_service_s3_compression_roundtrip(mock_boto_client) -> None:
    """Test that StorageService correctly interacts with S3 without fallback code, compressing/decompressing payloads."""
    # Setup mock S3 client
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    # Store uploaded payload in a local dict to simulate S3 state
    s3_store = {}

    def put_object_side_effect(Bucket, Key, Body):
        s3_store[Key] = Body
        return {}

    def get_object_side_effect(Bucket, Key):
        if Key not in s3_store:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject"
            )
        return {"Body": MagicMock(read=lambda: s3_store[Key])}

    mock_s3.put_object.side_effect = put_object_side_effect
    mock_s3.get_object.side_effect = get_object_side_effect

    # Initialize service
    storage = StorageService()

    test_key = "reports/run_123/metadata.msgpack.zstd"
    test_data = {"net_profit": 12500.50, "win_rate": 0.68}

    # 1. Upload
    await storage.upload_payload(test_key, test_data)
    mock_s3.put_object.assert_called_once()

    # Verify the body was compressed with zstandard (starts with magic bytes \x28\xb5\x2f\xfd)
    body_passed = s3_store[test_key]
    assert body_passed.startswith(b"\x28\xb5\x2f\xfd")

    # 2. Download
    downloaded_data = await storage.download_payload(test_key)
    assert downloaded_data == test_data
    mock_s3.get_object.assert_called_once_with(Bucket=storage.s3_bucket, Key=test_key)

    # 3. Delete directory
    # Setup paginator
    mock_paginator = MagicMock()
    mock_s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [{"Contents": [{"Key": test_key}]}]

    await storage.delete_directory("reports/")
    mock_s3.delete_objects.assert_called_once()
