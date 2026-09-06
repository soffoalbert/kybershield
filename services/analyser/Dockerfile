# Build context is the repository root because this service depends on
# packages/pycommon via a path install.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/pycommon /app/packages/pycommon
RUN pip install /app/packages/pycommon

COPY services/analyser/pyproject.toml /app/services/analyser/
COPY services/analyser/src /app/services/analyser/src
RUN pip install /app/services/analyser

# Drop privileges, matching the ingestion image. Done after the installs so
# pip still writes to site-packages as root.
RUN useradd --system --create-home --uid 10001 app
USER app

EXPOSE 8001
CMD ["uvicorn", "analyser.api:app", "--host", "0.0.0.0", "--port", "8001"]
