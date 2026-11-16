data "aws_caller_identity" "current" {

}

data "aws_vpc" "default" {

  default = true
}

data "aws_subnets" "default" {

  filter {

    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

}

resource "random_id" "suffix" {

  byte_length = 4
}

locals {

  name   = "${var.project_name}-${var.environment}"
  bucket = "${local.name}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
}


resource "aws_s3_bucket" "artifacts" {

  bucket = local.bucket
}

resource "aws_s3_bucket_versioning" "artifacts" {

  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {

    status = "Enabled"
  }

}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {

  bucket = aws_s3_bucket.artifacts.id
  rule {

    apply_server_side_encryption_by_default {

      sse_algorithm = "AES256"
    }

  }

}

resource "aws_s3_bucket_public_access_block" "artifacts" {

  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {

  bucket = aws_s3_bucket.artifacts.id
  rule {

    id     = "attempt-retention"
    status = "Enabled"
    filter {

      prefix = "jobs/"
    }

    noncurrent_version_expiration {

      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {

      days_after_initiation = 7
    }

  }

}


resource "aws_dynamodb_table" "jobs" {

  name         = "${local.name}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"
  attribute {

    name = "job_id"
    type = "S"
  }

  attribute {

    name = "owner_id"
    type = "S"
  }

  attribute {

    name = "created_at"
    type = "S"
  }

  global_secondary_index {

    name            = "owner-created-index"
    hash_key        = "owner_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {

    enabled = true
  }

  server_side_encryption {

    enabled = true
  }

}

resource "aws_sqs_queue" "dlq" {

  name                      = "${local.name}-submissions-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "submissions" {

  name                       = "${local.name}-submissions"
  visibility_timeout_seconds = 180
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 5
    }
  )
  sqs_managed_sse_enabled = true
}

resource "aws_ecr_repository" "images" {

  for_each = toset(["api", "lambda-control", "msa-worker", "boltz-worker"])
  name     = "${local.name}/${each.key}"
  image_scanning_configuration {

    scan_on_push = true
  }

  image_tag_mutability = "IMMUTABLE"
}


resource "aws_iam_role" "lambda" {

  name = "${local.name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "lambda.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {

  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda" {

  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.jobs.arn, "${aws_dynamodb_table.jobs.arn}/index/*"]
      },
      {
        Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:HeadObject"], Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect = "Allow", Action = ["states:StartExecution"], Resource = aws_sfn_state_machine.workflow.arn
      },
      {
        Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.submissions.arn
      }
    ]
    }
  )
}

resource "aws_lambda_function" "dispatcher" {

  function_name = "${local.name}-dispatcher"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.lambda_image
  timeout       = 30
  image_config {
    command = ["services.dispatcher.handler.handler"]
  }
  environment {

    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name, STATE_MACHINE_ARN = aws_sfn_state_machine.workflow.arn
    }

  }

}

resource "aws_lambda_event_source_mapping" "dispatcher" {

  event_source_arn        = aws_sqs_queue.submissions.arn
  function_name           = aws_lambda_function.dispatcher.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_lambda_function" "scheduler" {

  function_name = "${local.name}-scheduler"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.lambda_image
  timeout       = 30
  image_config {
    command = ["services.scheduler.handler.handler"]
  }
  environment {

    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name, ARTIFACT_BUCKET = aws_s3_bucket.artifacts.id
    }

  }

}

resource "aws_lambda_function" "finalizer" {

  function_name = "${local.name}-finalizer"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.lambda_image
  timeout       = 900
  memory_size   = 2048
  image_config {
    command = ["services.finalizer.handler.handler"]
  }
  environment {

    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name, ARTIFACT_BUCKET = aws_s3_bucket.artifacts.id
    }

  }

}

resource "aws_lambda_function" "reconciler" {

  function_name = "${local.name}-reconciler"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.lambda_image
  timeout       = 30
  image_config {
    command = ["services.reconciler.handler.handler"]
  }
  environment {

    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name
    }

  }

}


resource "aws_iam_role" "batch_service" {

  name = "${local.name}-batch-service"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "batch.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy_attachment" "batch_service" {

  role       = aws_iam_role.batch_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
}

resource "aws_iam_role" "spot_fleet" {
  name               = "${local.name}-spot-fleet"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "spotfleet.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "spot_fleet" {
  role       = aws_iam_role.spot_fleet.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetTaggingRole"
}

resource "aws_iam_role" "ecs_instance" {

  name = "${local.name}-ecs-instance"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "ec2.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy_attachment" "ecs_instance" {

  role       = aws_iam_role.ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "ecs" {

  name = "${local.name}-ecs"
  role = aws_iam_role.ecs_instance.name
}

resource "aws_iam_role" "job" {

  name = "${local.name}-job"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "ecs-tasks.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy" "job" {

  role = aws_iam_role.job.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"], Resource = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      },
      {
        Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*"
      }
    ]
    }
  )
}

resource "aws_security_group" "batch" {

  name   = "${local.name}-batch"
  vpc_id = data.aws_vpc.default.id
  egress {

    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

}


resource "aws_batch_compute_environment" "cpu" {

  compute_environment_name = "${local.name}-cpu-od"
  type                     = "MANAGED"
  service_role             = aws_iam_role.batch_service.arn
  compute_resources {

    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    max_vcpus           = var.cpu_max_vcpus
    min_vcpus           = 0
    instance_role       = aws_iam_instance_profile.ecs.arn
    instance_type       = ["c7i", "m7i"]
    subnets             = data.aws_subnets.default.ids
    security_group_ids  = [aws_security_group.batch.id]
  }

}

resource "aws_batch_compute_environment" "gpu_spot" {

  compute_environment_name = "${local.name}-gpu-spot"
  type                     = "MANAGED"
  service_role             = aws_iam_role.batch_service.arn
  compute_resources {

    type                = "SPOT"
    allocation_strategy = "SPOT_CAPACITY_OPTIMIZED"
    max_vcpus           = var.gpu_max_vcpus
    min_vcpus           = 0
    bid_percentage      = 100
    instance_role       = aws_iam_instance_profile.ecs.arn
    instance_type       = ["g5", "g6", "g6e"]
    subnets             = data.aws_subnets.default.ids
    security_group_ids  = [aws_security_group.batch.id]
    spot_iam_fleet_role = aws_iam_role.spot_fleet.arn
  }

}

resource "aws_batch_compute_environment" "gpu_od" {

  compute_environment_name = "${local.name}-gpu-od"
  type                     = "MANAGED"
  service_role             = aws_iam_role.batch_service.arn
  compute_resources {

    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    max_vcpus           = var.gpu_max_vcpus
    min_vcpus           = 0
    instance_role       = aws_iam_instance_profile.ecs.arn
    instance_type       = ["g5", "g6", "g6e"]
    subnets             = data.aws_subnets.default.ids
    security_group_ids  = [aws_security_group.batch.id]
  }

}

resource "aws_batch_scheduling_policy" "gpu_fair_share" {

  name = "${local.name}-gpu-fair-share"
  fair_share_policy {
    share_decay_seconds = 3600
    compute_reservation = 0
  }

}


resource "aws_batch_job_queue" "cpu" {

  name     = "${local.name}-cpu"
  state    = "ENABLED"
  priority = 10
  compute_environment_order {

    order               = 1
    compute_environment = aws_batch_compute_environment.cpu.arn
  }

}

resource "aws_batch_job_queue" "gpu_spot" {

  name                  = "${local.name}-gpu-spot"
  state                 = "ENABLED"
  priority              = 10
  scheduling_policy_arn = aws_batch_scheduling_policy.gpu_fair_share.arn
  compute_environment_order {

    order               = 1
    compute_environment = aws_batch_compute_environment.gpu_spot.arn
  }

}

resource "aws_batch_job_queue" "gpu_od" {

  name                  = "${local.name}-gpu-od"
  state                 = "ENABLED"
  priority              = 10
  scheduling_policy_arn = aws_batch_scheduling_policy.gpu_fair_share.arn
  compute_environment_order {

    order               = 1
    compute_environment = aws_batch_compute_environment.gpu_od.arn
  }

}

resource "aws_batch_job_definition" "msa" {

  name                  = "${local.name}-msa"
  type                  = "container"
  platform_capabilities = ["EC2"]
  container_properties = jsonencode({
    image = var.msa_image, jobRoleArn = aws_iam_role.job.arn, resourceRequirements = [{
      type = "VCPU", value = "8"
      },
      {
        type = "MEMORY", value = "30000"
      }
      ], environment = [{
        name = "ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.id
      },
      {
        name = "SCHEDULER_MODEL_S3_KEY", value = var.scheduler_model_s3_key
      },
      {
        name = "SCHEDULER_MODEL_VERSION", value = var.scheduler_model_version
      }
    ]
    }
  )
  retry_strategy {

    attempts = 3
    evaluate_on_exit {

      action           = "RETRY"
      on_status_reason = "Host EC2*"
    }

    evaluate_on_exit {

      action       = "EXIT"
      on_exit_code = "2"
    }

  }

}

resource "aws_batch_job_definition" "boltz" {

  name                  = "${local.name}-boltz"
  type                  = "container"
  platform_capabilities = ["EC2"]
  container_properties = jsonencode({
    image = var.boltz_image, jobRoleArn = aws_iam_role.job.arn, resourceRequirements = [{
      type = "VCPU", value = "8"
      },
      {
        type = "MEMORY", value = "60000"
      },
      {
        type = "GPU", value = "1"
      }
      ], environment = [{
        name = "ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.id
      }
    ]
    }
  )
  retry_strategy {

    attempts = 2
    evaluate_on_exit {

      action           = "RETRY"
      on_status_reason = "Host EC2*"
    }

    evaluate_on_exit {

      action       = "EXIT"
      on_exit_code = "2"
    }

  }

}


resource "aws_iam_role" "sfn" {

  name = "${local.name}-sfn"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "states.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy" "sfn" {

  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = ["batch:SubmitJob", "batch:DescribeJobs", "batch:TerminateJob"], Resource = "*"
      },
      {
        Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [aws_lambda_function.finalizer.arn, aws_lambda_function.scheduler.arn]
      },
      {
        Effect = "Allow", Action = ["events:PutTargets", "events:PutRule", "events:DescribeRule"], Resource = "*"
      }
    ]
    }
  )
}

resource "aws_sfn_state_machine" "workflow" {

  name     = "${local.name}-workflow"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/workflow_scheduled.asl.json", {
    cpu_queue = aws_batch_job_queue.cpu.arn, gpu_spot_queue = aws_batch_job_queue.gpu_spot.arn, gpu_od_queue = aws_batch_job_queue.gpu_od.arn, msa_definition = aws_batch_job_definition.msa.arn, boltz_definition = aws_batch_job_definition.boltz.arn, scheduler = aws_lambda_function.scheduler.arn, finalizer = aws_lambda_function.finalizer.arn
    }
  )
}


resource "aws_cloudwatch_event_rule" "batch" {

  name = "${local.name}-batch-state"
  event_pattern = jsonencode({
    source = ["aws.batch"], "detail-type" = ["Batch Job State Change"]
    }
  )
}

resource "aws_cloudwatch_event_target" "reconciler" {

  rule = aws_cloudwatch_event_rule.batch.name
  arn  = aws_lambda_function.reconciler.arn
}

resource "aws_lambda_permission" "events" {

  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reconciler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.batch.arn
}

resource "aws_sns_topic" "alarms" {

  name = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {

  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "dlq" {

  alarm_name  = "${local.name}-dlq-not-empty"
  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }

  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_budgets_budget" "monthly" {

  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  dynamic "notification" {

    for_each = var.alarm_email == "" ? [] : [1]
    content {

      comparison_operator        = "GREATER_THAN"
      threshold                  = 80
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = [var.alarm_email]
    }

  }

}



resource "aws_s3_bucket_cors_configuration" "artifacts" {


  bucket = aws_s3_bucket.artifacts.id

  cors_rule {

    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 900
  }


}

resource "aws_cloudwatch_log_group" "api" {

  name              = "/ecs/${local.name}/api"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "api" {

  name = "${local.name}-api"
  setting {

    name  = "containerInsights"
    value = "enabled"
  }

}

resource "aws_iam_role" "ecs_task_execution" {

  name = "${local.name}-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "ecs-tasks.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {

  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "api" {

  name = "${local.name}-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = {
        Service = "ecs-tasks.amazonaws.com"
      },
      Action = "sts:AssumeRole"
      }
    ]
    }
  )
}

resource "aws_iam_role_policy" "api" {

  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.jobs.arn, "${aws_dynamodb_table.jobs.arn}/index/*"]
      },
      {
        Effect = "Allow", Action = "sqs:SendMessage", Resource = aws_sqs_queue.submissions.arn
      },
      {
        Effect = "Allow", Action = ["states:StopExecution"], Resource = "*"
      },
      {
        Effect = "Allow", Action = ["batch:TerminateJob"], Resource = "*"
      }
    ]
    }
  )
}

resource "aws_security_group" "alb" {

  name   = "${local.name}-alb"
  vpc_id = data.aws_vpc.default.id
  ingress {

    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.api_allowed_cidrs
  }

  egress {

    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

}

resource "aws_security_group" "api" {

  name   = "${local.name}-api"
  vpc_id = data.aws_vpc.default.id
  ingress {

    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {

    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

}

resource "aws_lb" "api" {

  name               = substr("${local.name}-api", 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "api" {

  name        = substr("${local.name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"
  health_check {

    path    = "/api/health"
    matcher = "200"
  }

}

resource "aws_lb_listener" "api" {

  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {

    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

}

resource "aws_ecs_task_definition" "api" {

  family                   = "${local.name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.api.arn
  container_definitions = jsonencode([{
    name = "api", image = var.api_image, essential = true, portMappings = [{
      containerPort = 8000, protocol = "tcp"
      }
      ], environment = [{
        name = "AWS_REGION", value = var.aws_region
      },
      {
        name = "ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.id
      },
      {
        name = "JOBS_TABLE", value = aws_dynamodb_table.jobs.name
      },
      {
        name = "SUBMISSION_QUEUE_URL", value = aws_sqs_queue.submissions.url
      },
      {
        name = "STATE_MACHINE_ARN", value = aws_sfn_state_machine.workflow.arn
      },
      {
        name = "AUTH_DISABLED", value = tostring(var.api_auth_disabled)
      }
      ], logConfiguration = {
      logDriver = "awslogs", options = {
        "awslogs-group" = aws_cloudwatch_log_group.api.name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "api"
      }

    }

    }
  ])
}

resource "aws_ecs_service" "api" {

  name            = "api"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {

    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }

  load_balancer {

    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.api]
}

