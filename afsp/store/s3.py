"""S3 backing store adapter — stub for MVP."""


class S3Store:
    def __init__(self, bucket: str, prefix: str = ""):
        self.bucket = bucket
        self.prefix = prefix
        self.type = "s3"

    def resolve(self, path: str) -> str:
        raise NotImplementedError("S3 backing store is not implemented in MVP")

    def exists(self, path: str) -> bool:
        raise NotImplementedError("S3 backing store is not implemented in MVP")

    def as_dict(self) -> dict:
        return {"type": "s3", "bucket": self.bucket, "prefix": self.prefix}
