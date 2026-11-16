"""Small offline package/CUDA check. This does not download assets or run inference."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from importlib import metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", action="store_true", help="test every visible CUDA GPU")
    args = parser.parse_args()
    import torch

    packages = {
        name: metadata.version(name)
        for name in ("torch", "boltz", "boltz-multi-gpu-scheduler", "numpy", "scikit-learn")
    }
    if packages["boltz"] != "2.2.1" or packages["torch"].split("+")[0] != "2.7.1":
        raise RuntimeError("unexpected Boltz/PyTorch version; do not mix experiment environments")
    if platform.python_version_tuple()[:2] != ("3", "11") or torch.version.cuda != "12.8":
        raise RuntimeError("expected Python 3.11 and PyTorch CUDA 12.8")
    for command in ("boltz", "boltz-live", "boltz-vm", "boltz-campaign", "rsync", "tmux"):
        if not shutil.which(command):
            raise RuntimeError(f"missing command: {command}")
    payload = {
        "python": platform.python_version(),
        "packages": packages,
        "torch_cuda": torch.version.cuda,
        "gpu_test_requested": args.gpu,
    }
    if args.gpu:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; check host driver and assigned GPUs")
        devices = []
        for index in range(torch.cuda.device_count()):
            with torch.cuda.device(index):
                if not torch.cuda.is_bf16_supported(including_emulation=False):
                    raise RuntimeError(f"GPU {index} lacks native BF16 support")
                x = torch.ones((16, 16), device=f"cuda:{index}", dtype=torch.bfloat16)
                result = (x @ x).sum().item()
                torch.cuda.synchronize(index)
                if result != 4096:
                    raise RuntimeError(f"GPU {index} failed BF16 arithmetic")
                props = torch.cuda.get_device_properties(index)
                devices.append(
                    {
                        "index": index,
                        "name": props.name,
                        "memory_bytes": props.total_memory,
                        "capability": list(torch.cuda.get_device_capability(index)),
                    }
                )
        payload["gpus"] = devices
        for label, fields in (
            ("nvidia_smi_gpus", "--query-gpu=uuid,name,memory.total,utilization.gpu"),
            ("nvidia_smi_compute_apps", "--query-compute-apps=gpu_uuid,pid,used_memory"),
        ):
            payload[label] = subprocess.run(
                ["nvidia-smi", fields, "--format=csv,noheader"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
