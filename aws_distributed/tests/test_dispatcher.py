import os

os.environ.setdefault("AWS_DEFAULT_REGION","us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID","testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY","testing")
os.environ.setdefault("JOBS_TABLE","jobs")
os.environ.setdefault("STATE_MACHINE_ARN","arn:aws:states:us-east-1:123456789012:stateMachine:test")
from services.dispatcher.handler import execution_name


def test_execution_name_is_stable_and_bounded():
    assert execution_name("abc") == execution_name("abc")
    assert len(execution_name("x"*500)) <= 80
