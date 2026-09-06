# Build context is the repository root because this service depends on
# packages/pycommon via a path install.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/pycommon /app/packages/pycommon
RUN pip install /app/packages/pycommon

COPY services/insights/pyproject.toml /app/services/insights/
COPY services/insights/src /app/services/insights/src
RUN pip install /app/services/insights

EXPOSE 8002
CMD ["uvicorn", "insights.api:app", "--host", "0.0.0.0", "--port", "8002"]
