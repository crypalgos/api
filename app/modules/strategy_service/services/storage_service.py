import asyncio
from typing import Any

import boto3
import msgpack
import zstandard as zstd
import pyarrow as pa
from botocore.exceptions import ClientError

from app.config.settings import settings


class StorageService:
    def __init__(self):
        self.s3_bucket = settings.s3_bucket_name
        self.aws_access_key = settings.aws_access_key_id
        self.aws_secret_key = settings.aws_secret_access_key
        self.aws_region = settings.aws_default_region
        
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.aws_access_key,
            aws_secret_access_key=self.aws_secret_key,
            region_name=self.aws_region
        )
        self.compressor = zstd.ZstdCompressor(level=3)
        self.decompressor = zstd.ZstdDecompressor()

    async def upload_payload(self, key: str, data: Any) -> str:
        """Serializes data with msgpack, compresses with zstd, and uploads to S3 asynchronously."""
        serialized = msgpack.packb(data, use_bin_type=True)
        compressed = self.compressor.compress(serialized)
        
        await asyncio.to_thread(
            self.s3_client.put_object,
            Bucket=self.s3_bucket,
            Key=key,
            Body=compressed
        )
        return key

    async def upload_arrow_payload(self, key: str, table: pa.Table) -> str:
        """Serializes a pyarrow Table to IPC format, compresses with zstd, and uploads to S3."""
        import io
        sink = io.BytesIO()
        with pa.RecordBatchFileWriter(sink, table.schema) as writer:
            writer.write_table(table)
        serialized = sink.getvalue()
        compressed = self.compressor.compress(serialized)
        
        await asyncio.to_thread(
            self.s3_client.put_object,
            Bucket=self.s3_bucket,
            Key=key,
            Body=compressed
        )
        return key

    async def upload_raw_payload(self, key: str, data: bytes) -> str:
        """Uploads raw bytes to S3 without applying msgpack or zstd internally."""
        await asyncio.to_thread(
            self.s3_client.put_object,
            Bucket=self.s3_bucket,
            Key=key,
            Body=data
        )
        return key

    async def download_raw_payload(self, key: str) -> bytes:
        """Downloads raw bytes from S3 without decompressing or unpacking."""
        try:
            response = await asyncio.to_thread(
                self.s3_client.get_object,
                Bucket=self.s3_bucket,
                Key=key
            )
            return response["Body"].read()
        except ClientError as e:
            raise FileNotFoundError(f"Key {key} not found in S3: {e}")

    async def download_payload(self, key: str) -> Any:
        """Downloads compressed payload from S3, decompresses, and msgpack unpacks it asynchronously."""
        try:
            response = await asyncio.to_thread(
                self.s3_client.get_object,
                Bucket=self.s3_bucket,
                Key=key
            )
            compressed = response["Body"].read()
        except ClientError as e:
            raise FileNotFoundError(f"Key {key} not found in S3: {e}")
            
        decompressed = self.decompressor.decompress(compressed)
        return msgpack.unpackb(decompressed, raw=False)

    async def delete_payload(self, key: str) -> None:
        """Deletes object from S3 asynchronously."""
        try:
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.s3_bucket,
                Key=key
            )
        except ClientError:
            pass

    async def delete_directory(self, prefix: str) -> None:
        """Deletes all objects under a given directory prefix from S3 asynchronously."""
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = await asyncio.to_thread(
                list,
                paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix)
            )
            for page in pages:
                if "Contents" in page:
                    delete_keys = [{"Key": obj["Key"]} for obj in page["Contents"]]
                    await asyncio.to_thread(
                        self.s3_client.delete_objects,
                        Bucket=self.s3_bucket,
                        Delete={"Objects": delete_keys}
                    )
        except ClientError:
            pass

storage_service = StorageService()
