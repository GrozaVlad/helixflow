output "artifact_bucket" { value = aws_s3_bucket.artifacts.id }
output "submission_queue_url" { value = aws_sqs_queue.submissions.url }
output "jobs_table" { value = aws_dynamodb_table.jobs.name }
output "workflow_arn" { value = aws_sfn_state_machine.workflow.arn }
output "ecr_repositories" { value = { for k, v in aws_ecr_repository.images : k => v.repository_url } }
output "api_url" { value = "http://${aws_lb.api.dns_name}" }
