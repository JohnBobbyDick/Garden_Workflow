# Backend API + worker image (build context: repository root).
# Layout mirrors the repository so that REPO_ROOT-relative paths (fixtures/, cli/, scripts/) work unchanged.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# git: cloning allowlisted repositories and diff-aware scans (git is never given a token in a URL)
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 aisw

WORKDIR /app/backend
COPY backend/pyproject.toml ./
# dependencies only: the code runs from /app/backend (PYTHONPATH) so that repository-relative paths stay valid
RUN mkdir -p app && touch app/__init__.py && pip install . "aiosmtpd>=1.4" && pip uninstall -y aisw-backend \
    && rm -rf app build *.egg-info
COPY backend/ ./
COPY fixtures/ /app/fixtures/
COPY cli/ /app/cli/
COPY scripts/ /app/scripts/
COPY docker/entrypoint.sh /usr/local/bin/aisw-entrypoint
RUN chmod +x /usr/local/bin/aisw-entrypoint && mkdir -p /data && chown -R aisw /data

USER aisw
ENV APP_DATA_DIR=/data APP_SCAN_ROOTS=/app/fixtures PYTHONPATH=/app/backend
EXPOSE 8000
ENTRYPOINT ["aisw-entrypoint"]
CMD ["api"]
