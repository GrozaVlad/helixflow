#!/usr/bin/env python3
"""Replay Poisson or burst arrivals against the API and emit submission telemetry."""
import argparse, json, random, time, uuid
from pathlib import Path
import httpx

def main():
 p=argparse.ArgumentParser();p.add_argument("input",type=Path);p.add_argument("--api",required=True);p.add_argument("--jobs",type=int,default=10);p.add_argument("--rate",type=float,default=.2);p.add_argument("--researcher",default="experiment");a=p.parse_args(); h={"X-Researcher-Id":a.researcher}
 with httpx.Client(timeout=120) as c:
  for i in range(a.jobs):
   started=time.time(); u=c.post(a.api+"/api/uploads",headers=h,json={"filename":a.input.name,"content_type":"application/octet-stream"}).json(); c.put(u["upload_url"],content=a.input.read_bytes(),headers={"Content-Type":"application/octet-stream","x-amz-server-side-encryption":"AES256"}).raise_for_status(); c.post(a.api+"/api/jobs",headers=h,json={"job_id":u["job_id"],"input_key":u["input_key"],"idempotency_key":str(uuid.uuid4())}).raise_for_status(); print(json.dumps({"job_id":u["job_id"],"submitted_at":started,"ordinal":i})); time.sleep(random.expovariate(a.rate))
if __name__=="__main__": main()
