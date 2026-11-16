import pytest
from pydantic import ValidationError

from shared.models import PredictionOptions, UploadRequest


def test_upload_rejects_path_traversal():
    with pytest.raises(ValidationError): UploadRequest(filename="../input.yaml")
def test_options_are_bounded():
    with pytest.raises(ValidationError): PredictionOptions(diffusion_samples=99)
