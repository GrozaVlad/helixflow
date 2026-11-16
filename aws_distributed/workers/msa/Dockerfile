FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir boto3 pydantic colabfold[alphafold]
COPY multi_gpu_scheduler /opt/multi_gpu_scheduler
RUN pip3 install --break-system-packages --no-cache-dir /opt/multi_gpu_scheduler
WORKDIR /app
COPY aws_distributed/shared shared
COPY aws_distributed/workers workers
ENV PYTHONPATH=/app
ENTRYPOINT ["python3","-m","workers.msa.runner"]
