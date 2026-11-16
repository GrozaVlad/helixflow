FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime@sha256:c16f4c749e2d9e96878875cdf6cc45cddda1d1a36fddd371dd6f2360f1b6e2a2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    BOLTZ_CACHE=/workspace/cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY local_install/requirements.txt /tmp/boltz-requirements.txt
COPY multi_gpu_scheduler/runtime-constraints.txt /tmp/runtime-constraints.txt
RUN python -m pip install -c /tmp/runtime-constraints.txt -r /tmp/boltz-requirements.txt

COPY multi_gpu_scheduler /opt/multi_gpu_scheduler
COPY LICENSE /opt/LICENSE
COPY local_install/requirements.txt /opt/local_install/requirements.txt
ENV HELIXFLOW_SOURCE=/opt/multi_gpu_scheduler
RUN python -m pip install -c /tmp/runtime-constraints.txt '/opt/multi_gpu_scheduler[experiment]' \
    && python -m pip check

WORKDIR /workspace
CMD ["bash"]
