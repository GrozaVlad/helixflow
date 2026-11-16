# Build context is this directory, NOT the repository or a user's home directory.
# The default base is the locally validated experiment image; see README.md for rebuilds.
ARG HELIXFLOW_BASE=boltz2-multi-gpu-scheduler:prevm-20261021-ccd
FROM ${HELIXFLOW_BASE}
ARG HELIXFLOW_BASE

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       openssh-server openssh-client rsync tmux tini procps util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_* \
    && mkdir -p /opt/helixflow-vast /workspace

COPY entrypoint.py check.py /opt/helixflow-vast/
COPY README.md /opt/helixflow-vast/README.md
RUN printf '#!/bin/sh\nexec /opt/conda/bin/python /opt/helixflow-vast/check.py "$@"\n' \
       > /usr/local/bin/helixflow-check \
    && chmod 755 /usr/local/bin/helixflow-check \
    && python -m pip check \
    && python -c 'import importlib.metadata as m, json; from pathlib import Path; Path("/opt/helixflow-vast/packages.json").write_text(json.dumps({d.metadata["Name"]: d.version for d in m.distributions()}, sort_keys=True, indent=2))'

ENV BOLTZ_CACHE=/workspace/cache \
    HELIXFLOW_SOURCE=/opt/multi_gpu_scheduler \
    HELIXFLOW_LOCK_DIR=/workspace/results/gpu-locks \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

LABEL org.opencontainers.image.title="HelixFlow Boltz experiment — Vast.ai" \
      org.opencontainers.image.description="Pinned single-host Boltz scheduler with key-only SSH; no scientific assets or credentials" \
      io.helixflow.base-reference="${HELIXFLOW_BASE}"

WORKDIR /workspace
EXPOSE 22
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/conda/bin/python", "/opt/helixflow-vast/entrypoint.py"]
CMD ["sshd"]
