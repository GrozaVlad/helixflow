FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml .
COPY shared ./shared
COPY services ./services
COPY ui ./ui
RUN pip install --no-cache-dir .
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
