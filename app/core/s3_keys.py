"""
S3 key normalization helpers.

We store *keys* in Mongo (e.g. `plants/<user_id>/<plant_id>/...`) and generate
presigned GET URLs at response time.

Older records may have stored full S3 URLs (including presigned query params).
These helpers extract the canonical key so the backend can re-sign on demand.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse, unquote


def normalize_s3_key(value: Optional[str], *, bucket: str, region: str) -> Optional[str]:
    """
    Normalize an S3 reference into an object key.

    Accepts:
    - Raw key: `plants/...`
    - s3:// URL: `s3://bucket/plants/...`
    - Virtual-hosted style: `https://bucket.s3.<region>.amazonaws.com/plants/...`
    - Path style: `https://s3.<region>.amazonaws.com/bucket/plants/...`
    - Any of the above with query params (presigned URLs)

    Returns:
    - The extracted key, without a leading slash
    - None if `value` is empty or a non-S3 external URL (e.g. Unsplash)
    """
    if not value or not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    # Raw key (most common / desired)
    if not raw.startswith(("http://", "https://", "s3://")):
        key = raw.lstrip("/")
        # Handle accidental bucket/key storage.
        if key.startswith(f"{bucket}/"):
            key = key[len(bucket) + 1 :]
        return key

    # s3://bucket/key
    if raw.startswith("s3://"):
        without_scheme = raw[len("s3://") :]
        if "/" not in without_scheme:
            return None
        maybe_bucket, key = without_scheme.split("/", 1)
        if maybe_bucket != bucket:
            return None
        return unquote(key.lstrip("/"))

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path or "")

    # Not S3 / AWS: treat as external URL
    if "amazonaws.com" not in host:
        return None

    # Accept a few common S3 endpoint formats.
    virtual_hosts = {
        f"{bucket}.s3.{region}.amazonaws.com",
        f"{bucket}.s3.amazonaws.com",
        f"{bucket}.s3-{region}.amazonaws.com",
    }
    path_hosts = {
        f"s3.{region}.amazonaws.com",
        "s3.amazonaws.com",
        f"s3-{region}.amazonaws.com",
    }

    key: Optional[str] = None

    if host in virtual_hosts:
        # /<key>
        key = path.lstrip("/")
    elif host in path_hosts:
        # /<bucket>/<key>
        trimmed = path.lstrip("/")
        if trimmed.startswith(f"{bucket}/"):
            key = trimmed[len(bucket) + 1 :]

    if not key:
        return None

    # Sometimes callers accidentally include bucket prefix in the key.
    if key.startswith(f"{bucket}/"):
        key = key[len(bucket) + 1 :]

    return key.lstrip("/")
