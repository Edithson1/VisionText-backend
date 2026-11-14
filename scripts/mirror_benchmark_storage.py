"""Copy the local catalog's S3 objects into the isolated Linux test storage."""
from pathlib import Path
from dotenv import dotenv_values
from minio import Minio

root = Path(__file__).resolve().parents[1]
local = dotenv_values(root / ".env")
options = {"access_key": local["MINIO_ACCESS_KEY"], "secret_key": local["MINIO_SECRET_KEY"], "secure": False}
source = Minio("127.0.0.1:59000", **options)
target = Minio("127.0.0.1:59010", **options)
count = 0
for bucket in source.list_buckets():
    if not target.bucket_exists(bucket.name):
        target.make_bucket(bucket.name)
    for item in source.list_objects(bucket.name, recursive=True):
        response = source.get_object(bucket.name, item.object_name)
        try:
            target.put_object(bucket.name, item.object_name, response, item.size, content_type=response.headers.get("Content-Type", "application/octet-stream"))
            count += 1
        finally:
            response.close()
            response.release_conn()
print(f"Copied {count} catalog objects to the isolated Linux S3 server.")
