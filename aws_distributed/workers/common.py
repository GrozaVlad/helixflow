from __future__ import annotations

import hashlib
import json
import mimetypes

from shared.models import ResultAsset


def download_json(s3,bucket,key): return json.loads(s3.get_object(Bucket=bucket,Key=key)["Body"].read())
def download(s3,bucket,key,target): target.parent.mkdir(parents=True,exist_ok=True); s3.download_file(bucket,key,str(target))
def upload_tree(s3,bucket,prefix,root):
    assets=[]
    for path in sorted(root.rglob("*")):
        if not path.is_file(): continue
        key=f"{prefix}/{path.relative_to(root).as_posix()}"; h=hashlib.sha256(path.read_bytes()).hexdigest()
        s3.upload_file(str(path),bucket,key,ExtraArgs={"ServerSideEncryption":"AES256"})
        assets.append(ResultAsset(key=key,name=path.name,size=path.stat().st_size,sha256=h,media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream"))
    return assets
