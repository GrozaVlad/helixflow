FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "boltz[cuda]==2.2.1" boto3 pydantic
WORKDIR /app
COPY shared shared
COPY workers workers
ENV PYTHONPATH=/app
ENTRYPOINT ["python","-m","workers.boltz.runner"]
