import os
import re
import uuid
import mimetypes
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, BotoCoreError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal or invalid S3 characters."""
    clean = os.path.basename(filename or "unnamed_file").strip()
    clean = re.sub(r'[^a-zA-Z0-9_.\-]', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean or "file"


class StorageService:
    """
    Cloudflare R2 Storage Service (S3-Compatible).
    Decoupled binary object storage with zero egress fees.
    """

    def __init__(self):
        self.account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
        self.access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        self.secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        self.bucket_name = os.getenv("R2_BUCKET_NAME", "gigamind-storage").strip()
        self.public_domain = os.getenv("R2_PUBLIC_DOMAIN", "").strip().rstrip("/")
        
        endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()
        if not endpoint_url and self.account_id:
            endpoint_url = f"https://{self.account_id}.r2.cloudflarestorage.com"
        self.endpoint_url = endpoint_url

        self.enabled = False
        self.s3_client = None

        if not BOTO3_AVAILABLE:
            print("⚠️ boto3 is not installed; R2 StorageService disabled.")
            return

        if self.access_key_id and self.secret_access_key and self.endpoint_url and self.bucket_name:
            try:
                s3_config = Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=5,
                    read_timeout=15,
                )
                self.s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key_id,
                    aws_secret_access_key=self.secret_access_key,
                    region_name="auto",
                    config=s3_config
                )
                self.enabled = True
            except Exception as e:
                print(f"⚠️ Failed to initialize R2 S3 client: {e}")
                self.enabled = False
        else:
            # Running in local mode without R2 configured
            self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled and self.s3_client is not None

    def generate_storage_key(self, filename: str, prefix: str = "files") -> str:
        """Generate isolated hierarchical storage key: prefix/YYYY/MM/{uuid}_{filename}"""
        now = datetime.now(timezone.utc)
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        unique_token = uuid.uuid4().hex[:12]
        clean_name = sanitize_filename(filename)
        prefix_clean = (prefix or "files").strip("/")
        return f"{prefix_clean}/{year_str}/{month_str}/{unique_token}_{clean_name}"

    def upload_file(
        self,
        data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
        prefix: str = "files"
    ) -> Optional[Dict[str, Any]]:
        """Uploads in-memory bytes to R2 bucket."""
        if not self.is_enabled():
            return None

        key = self.generate_storage_key(filename, prefix=prefix)
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        try:
            extra_args = {"ContentType": mime_type}
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=mime_type
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            url = self.get_presigned_download_url(key, filename=filename)

            return {
                "key": key,
                "filename": filename,
                "mime_type": mime_type,
                "size_bytes": len(data),
                "url": url,
                "created_at": now_iso
            }
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error uploading file to R2: {e}")
            return None

    def upload_fileobj(
        self,
        fileobj,
        filename: str,
        mime_type: Optional[str] = None,
        size_bytes: int = 0,
        prefix: str = "files"
    ) -> Optional[Dict[str, Any]]:
        """Uploads streaming file object to R2 bucket to avoid high RAM consumption."""
        if not self.is_enabled():
            return None

        key = self.generate_storage_key(filename, prefix=prefix)
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        try:
            extra_args = {"ContentType": mime_type}
            self.s3_client.upload_fileobj(
                Fileobj=fileobj,
                Bucket=self.bucket_name,
                Key=key,
                ExtraArgs=extra_args
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            url = self.get_presigned_download_url(key, filename=filename)

            return {
                "key": key,
                "filename": filename,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "url": url,
                "created_at": now_iso
            }
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error uploading fileobj to R2: {e}")
            return None

    def download_file(self, key: str) -> Optional[bytes]:
        """Downloads raw bytes of an object from R2."""
        if not self.is_enabled():
            return None

        try:
            resp = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read()
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error downloading file from R2 ({key}): {e}")
            return None

    def get_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: Optional[str] = None,
        inline: bool = True
    ) -> Optional[str]:
        """Generates secure time-limited presigned GET URL with proper Content-Disposition."""
        if not self.is_enabled():
            return None

        if self.public_domain:
            return f"{self.public_domain}/{key}"

        try:
            params: Dict[str, Any] = {"Bucket": self.bucket_name, "Key": key}
            disposition_type = "inline" if inline else "attachment"
            clean_name = sanitize_filename(filename or key.split("/")[-1])
            params["ResponseContentDisposition"] = f'{disposition_type}; filename="{clean_name}"'

            url = self.s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expires_in
            )
            return url
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error generating presigned download URL for {key}: {e}")
            return None

    def get_presigned_upload_url(
        self,
        filename: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
        prefix: str = "files"
    ) -> Optional[Dict[str, Any]]:
        """Generates direct presigned PUT URL for client-side direct-to-R2 streaming uploads."""
        if not self.is_enabled():
            return None

        key = self.generate_storage_key(filename, prefix=prefix)
        try:
            params = {
                "Bucket": self.bucket_name,
                "Key": key,
                "ContentType": content_type
            }
            url = self.s3_client.generate_presigned_url(
                ClientMethod="put_object",
                Params=params,
                ExpiresIn=expires_in
            )
            return {
                "upload_url": url,
                "key": key,
                "filename": filename,
                "content_type": content_type,
                "expires_in": expires_in
            }
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error generating presigned upload URL: {e}")
            return None

    def delete_file(self, key: str) -> bool:
        """Deletes a single object from R2."""
        if not self.is_enabled() or not key:
            return False

        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            return True
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error deleting file from R2 ({key}): {e}")
            return False

    def delete_files(self, keys: List[str]) -> int:
        """Deletes up to 1000 objects per S3 DeleteObjects request."""
        if not self.is_enabled() or not keys:
            return 0

        valid_keys = [k for k in keys if k and isinstance(k, str)]
        if not valid_keys:
            return 0

        total_deleted = 0
        chunk_size = 1000
        for i in range(0, len(valid_keys), chunk_size):
            batch = valid_keys[i:i + chunk_size]
            delete_payload = {"Objects": [{"Key": k} for k in batch], "Quiet": True}
            try:
                resp = self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete=delete_payload
                )
                deleted_count = len(resp.get("Deleted", batch))
                total_deleted += deleted_count
            except (ClientError, BotoCoreError, Exception) as e:
                print(f"Error deleting batch from R2: {e}")

        return total_deleted

    def list_files(self, prefix: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """Lists files in the R2 bucket."""
        if not self.is_enabled():
            return []

        try:
            resp = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=min(limit, 1000)
            )
            contents = resp.get("Contents", [])
            results = []
            for item in contents:
                key = item["Key"]
                filename = key.split("/")[-1]
                mime_type, _ = mimetypes.guess_type(filename)
                results.append({
                    "key": key,
                    "filename": filename,
                    "size_bytes": item.get("Size", 0),
                    "last_modified": item.get("LastModified", datetime.now(timezone.utc)).isoformat() if hasattr(item.get("LastModified"), "isoformat") else str(item.get("LastModified")),
                    "mime_type": mime_type or "application/octet-stream",
                    "url": self.get_presigned_download_url(key, filename=filename)
                })
            return results
        except (ClientError, BotoCoreError, Exception) as e:
            print(f"Error listing files from R2: {e}")
            return []


# Global singleton storage service
storage_service = StorageService()
