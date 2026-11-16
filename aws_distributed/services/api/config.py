from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)

    aws_region: str = Field(alias="AWS_REGION")
    artifact_bucket: str = Field(alias="ARTIFACT_BUCKET")
    jobs_table: str = Field(alias="JOBS_TABLE")
    jobs_owner_index: str = Field(default="owner-created-index", alias="JOBS_OWNER_INDEX")
    submission_queue_url: str = Field(alias="SUBMISSION_QUEUE_URL")
    state_machine_arn: str = Field(alias="STATE_MACHINE_ARN")
    upload_expiry_seconds: int = Field(default=900, alias="UPLOAD_EXPIRY_SECONDS")
    asset_expiry_seconds: int = Field(default=900, alias="ASSET_EXPIRY_SECONDS")
    code_version: str = Field(default="development", alias="CODE_VERSION")
    model_version: str = Field(default="2.2.1", alias="BOLTZ_MODEL_VERSION")
    auth_disabled: bool = Field(default=False, alias="AUTH_DISABLED")


@lru_cache
def get_settings() -> Settings:
    return Settings()

