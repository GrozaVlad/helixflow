variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "project_name" {
  type    = string
  default = "distributed-boltz"
}
variable "environment" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "experiment"], var.environment)
    error_message = "Use dev or experiment."
  }
}
variable "alarm_email" {
  type    = string
  default = ""
}
variable "monthly_budget_usd" {
  type    = number
  default = 500
}
variable "gpu_max_vcpus" {
  type    = number
  default = 128
}
variable "cpu_max_vcpus" {
  type    = number
  default = 256
}
variable "api_image" {
  type        = string
  description = "Immutable API container image URI."
}
variable "lambda_image" {
  type        = string
  description = "Immutable Lambda control-plane container image URI."
}
variable "msa_database_s3_uri" {
  type    = string
  default = ""
}
variable "api_auth_disabled" {
  type        = bool
  default     = false
  description = "Development only; never enable on a public ingress."
}
variable "api_allowed_cidrs" {
  type        = list(string)
  default     = []
  description = "CIDRs allowed to reach the HTTP development listener. Keep empty until HTTPS/OIDC is configured."
}

variable "msa_image" {
  type        = string
  description = "Immutable MSA worker image URI (prefer an ECR sha256 digest)."
}
variable "boltz_image" {
  type        = string
  description = "Immutable GPU worker image URI (prefer an ECR sha256 digest)."
}
variable "scheduler_model_s3_key" {
  type        = string
  default     = ""
  description = "Trusted PredictorBundle object key in the artifact bucket; empty enables FCFS fallback."
}
variable "scheduler_model_version" {
  type        = string
  default     = "unconfigured"
  description = "Immutable identifier recorded with scheduling predictions."
}
