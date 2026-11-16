# Distributed Boltz on AWS

This directory implements the cloud instantiation of the architecture described in `../paper`. It separates admission, orchestration, CPU data preparation, GPU inference, and immutable publication so each stage can scale and fail independently.

## Request path

1. The FastAPI control plane issues an encrypted presigned S3 upload and creates a DynamoDB job record.
2. Submission writes a versioned manifest and sends a small message to SQS. The API never carries a large scientific asset.
3. A Lambda dispatcher starts one idempotently named Step Functions execution.
4. AWS Batch prepares MSAs on CPU capacity backed by an AWS-hosted ColabFold database and attaches a trusted p50/p90 runtime and p90 VRAM prediction.
5. A scheduler Lambda maps the conservative runtime to AWS Batch priority and the researcher identity to a privacy-preserving fair-share identifier. Missing predictions use priority `1` and remain processable.
6. GPU work goes to Spot first. Infrastructure/capacity failure is caught and submitted to an On-Demand fair-share queue with the same decision. Application errors are not blindly retried.
7. A finalizer verifies every object size and SHA-256 digest before atomically publishing the result manifest. The UI only exposes published results through short-lived S3 URLs.

## Layout

- `shared/`: versioned job and artifact contracts.
- `services/`: API and Lambda control-plane components.
- `workers/`: CPU MSA and GPU Boltz container entrypoints.
- `terraform/`: dev/experiment AWS infrastructure.
- `experiments/`: workload replay and experiment protocol.
- `tests/`: contract and idempotency tests.
- `ui/`: lightweight job/results browser with vendored Mol* assets.

## Build and validate

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check shared services workers tests
pytest
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
```

Build and push the API, Lambda control plane, MSA worker, and Boltz worker using the immutable Git SHA as the tag, then pass immutable image URIs to Terraform. The Lambda and MSA images must be built from the repository root:

```bash
docker build -f aws_distributed/services/Dockerfile.lambda \\
  -t boltz-lambda-control:${GIT_SHA} .
docker build -f aws_distributed/workers/msa/Dockerfile -t boltz-msa-worker:${GIT_SHA} .
```

The checked-in Terraform creates repositories, but experimental deployments must use immutable image digests.

## Deploy

Use a dedicated AWS research account and a remote encrypted Terraform backend. Configure GitHub's `AWS_DEPLOY_ROLE_ARN` as an OIDC-trusted role—do not create long-lived AWS keys. Review costs before applying: GPU instances and the approximately terabyte-scale MSA data path are material expenses.

```bash
cd terraform
terraform init
terraform plan -var environment=dev -var alarm_email=you@example.org
terraform apply
```

The current infrastructure establishes the scientific execution plane (S3, SQS/DLQ, DynamoDB, Step Functions, Lambda, AWS Batch CPU/GPU pools, EventBridge, SNS, alarms and budget). The API container and UI are implemented, but an HTTPS ingress and identity provider are intentionally site-specific because they require a DNS name and certificate. Deploy the API image to ECS/Fargate or App Runner with the Terraform outputs as environment variables; keep `AUTH_DISABLED=false`, and configure the ingress to supply a verified researcher identity header. Do not expose the development header mode publicly.

## MSA database

For reproducible experiments, snapshot the chosen ColabFold database release to S3, hydrate it onto FSx for Lustre, mount it read-only into the CPU Batch launch template, and set `MSA_DB_PATH`. Database version and object inventory belong in every experiment record. This costly data resource is documented rather than automatically created so `terraform apply` cannot accidentally start a large transfer. The worker uploads generated A3M files and a prepared manifest; before a real run, add and test the corpus-specific adapter that maps those A3Ms into each protein entry of the Boltz YAML. Precomputed `msa_keys` already pass through the manifest boundary, but automatic chain-to-A3M mapping is deliberately not guessed.

## Scheduler model

Train the predictor in `../multi_gpu_scheduler`, upload the trusted model to the artifact bucket, and identify both its object key and immutable version in Terraform:

```bash
aws s3 cp ../multi_gpu_scheduler/results/predictor.pkl \
  s3://$(terraform -chdir=terraform output -raw artifact_bucket)/scheduler/predictor.pkl

terraform -chdir=terraform apply \
  -var scheduler_model_s3_key=scheduler/predictor.pkl \
  -var scheduler_model_version=campaign-2026-01
```

The model is executed by the CPU preparation worker, never from an untrusted client hint. AWS Batch uses the prediction only to order GPU-ready jobs; SQS still provides durable admission, and every accepted job remains in the workflow. Cross-user allocation is handled by Batch fair-share scheduling, while conservative predicted runtime determines order within each user's share. This is an AWS-native projection of the method: the controlled VM implements exact uncertainty-aware fair SJF with a hard aging threshold, whereas Batch combines fair-share decay with per-share priority. The distinction must be retained in experimental reporting.

## Experiment matrix

Compare (A) fixed On-Demand, (B) elastic On-Demand, and (C) elastic Spot-first/fallback under the same public input corpus, seeds, arrival traces, cache state and region. Report makespan, queue delay, stage time, success/retry/interruption rate, GPU utilization, cost per successful job, tail latency, and provenance completeness. Run repeated trials and report uncertainty.

## Important implementation boundary

This is a research artifact, not a clinical service. Before production use, add private subnets/NAT or VPC endpoints, KMS customer-managed keys, WAF, Cognito/OIDC at HTTPS ingress, CloudTrail data events, image signing, vulnerability gates, retention approval and an operational restore exercise.
