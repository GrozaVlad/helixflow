from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import boto3

from workers.common import download, download_json
from workers.msa.scheduling import attach_scheduling_prediction


def main():
    bucket=os.environ["ARTIFACT_BUCKET"]; manifest_key=os.environ["MANIFEST_KEY"]; s3=boto3.client("s3"); m=download_json(s3,bucket,manifest_key)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); source=root/Path(m["input_key"]).name; download(s3,bucket,m["input_key"],source)
        if m.get("msa_keys"):
            provided=[]
            for index,key in enumerate(m["msa_keys"]):
                target=root/"provided-msa"/f"{index}-{Path(key).name}"
                download(s3,bucket,key,target); provided.append(target)
            m=attach_scheduling_prediction(s3,bucket,source,m,provided,root)
            prepared=f"jobs/{m['owner_id']}/{m['job_id']}/prepared/manifest.json"
            s3.put_object(Bucket=bucket,Key=prepared,Body=json.dumps(m).encode(),ContentType="application/json",ServerSideEncryption="AES256")
            return
        out=root/"msa"; out.mkdir()
        subprocess.run(["colabfold_search",str(source),os.environ["MSA_DB_PATH"],str(out)],check=True)
        keys=[]
        for path in out.rglob("*"):
            if path.is_file():
                key=f"jobs/{m['owner_id']}/{m['job_id']}/prepared/msa/{path.relative_to(out).as_posix()}"; s3.upload_file(str(path),bucket,key,ExtraArgs={"ServerSideEncryption":"AES256"}); keys.append(key)
        m["msa_keys"]=keys; m=attach_scheduling_prediction(s3,bucket,source,m,[path for path in out.rglob("*") if path.is_file()],root); prepared=f"jobs/{m['owner_id']}/{m['job_id']}/prepared/manifest.json"
        s3.put_object(Bucket=bucket,Key=prepared,Body=json.dumps(m).encode(),ContentType="application/json",ServerSideEncryption="AES256")
if __name__=="__main__": main()
