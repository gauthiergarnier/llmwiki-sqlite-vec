"""Source-URL allowlisting so the service only fetches from the configured S3 bucket."""

from urllib.parse import urlparse

from fastapi import HTTPException


class S3UrlValidator:
    def __init__(self, bucket: str, region: str) -> None:
        self._bucket = bucket
        self._region = region

    def validate(self, url: str) -> None:
        parsed = urlparse(url)
        if not parsed.hostname:
            raise HTTPException(400, "URL has no hostname")
        if not self._bucket:
            # Self-hosters without a configured bucket get the broad S3-only check.
            if not parsed.hostname.endswith(".amazonaws.com"):
                raise HTTPException(400, "URLs must point to S3")
            return
        if not (self._is_virtual_host(parsed.hostname) or self._is_path_style(parsed.hostname, parsed.path)):
            raise HTTPException(400, "URL does not point to the configured S3 bucket")

    def _is_virtual_host(self, hostname: str) -> bool:
        return hostname in (
            f"{self._bucket}.s3.{self._region}.amazonaws.com",
            f"{self._bucket}.s3.amazonaws.com",
        )

    def _is_path_style(self, hostname: str, path: str) -> bool:
        return (
            hostname in (f"s3.{self._region}.amazonaws.com", "s3.amazonaws.com")
            and path.lstrip("/").startswith(f"{self._bucket}/")
        )
