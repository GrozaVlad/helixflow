# Experiment harness

`workload.py` replays reproducible job submissions. Run each workload corpus and arrival trace against three Terraform configurations: fixed On-Demand capacity, elastic On-Demand, and elastic Spot-first with On-Demand fallback. Export Batch, Step Functions, SQS and EC2 metrics plus AWS Cost and Usage Report data. Record Git commit, container digest, region, instance types, model/database versions, random seed and all Terraform variables with every run. Never compare configurations across different input corpora or warm-cache conditions.
