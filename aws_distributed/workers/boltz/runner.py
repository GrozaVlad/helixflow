from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import boto3

from shared.models import AttemptManifest
from workers.common import download, download_json, upload_tree


def main():
    bucket=os.environ["ARTIFACT_BUCKET"]; key=os.environ.get("PREPARED_MANIFEST_KEY",os.environ["MANIFEST_KEY"]); attempt=int(os.environ.get("ATTEMPT","1")); s3=boto3.client("s3"); m=download_json(s3,bucket,key)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); source=root/"input"/Path(m["input_key"]).name; output=root/"output"; download(s3,bucket,m["input_key"],source)
        command=["boltz","predict",str(source),"--out_dir",str(output),"--cache",os.environ.get("BOLTZ_CACHE","/opt/boltz-cache"),"--recycling_steps",str(m["options"]["recycling_steps"]),"--sampling_steps",str(m["options"]["sampling_steps"]),"--diffusion_samples",str(m["options"]["diffusion_samples"])]
        subprocess.run(command,check=True)
        prefix=f"jobs/{m['owner_id']}/{m['job_id']}/attempts/{attempt}/assets"; assets=upload_tree(s3,bucket,prefix,output)
        manifest=AttemptManifest(job_id=m["job_id"],attempt=attempt,model_name=m["model_name"],model_version=m["model_version"],assets=assets,provenance={"code_version":m["code_version"],"container_image":os.environ.get("IMAGE_URI","unknown")})
        manifest_key=f"jobs/{m['owner_id']}/{m['job_id']}/attempts/{attempt}/attempt-manifest.json"
        s3.put_object(Bucket=bucket,Key=manifest_key,Body=manifest.model_dump_json().encode(),ContentType="application/json",ServerSideEncryption="AES256")
if __name__=="__main__": main()
