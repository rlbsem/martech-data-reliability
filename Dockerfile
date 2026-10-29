FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-runtime.lock ./requirements-runtime.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-runtime.lock
COPY src ./src
COPY fixtures ./fixtures
RUN mkdir -p /state /control /console-config /sources/advertising /sources/website /sources/crm /backups && chown -R 10001:10001 /state /control /console-config /sources /backups
USER 10001:10001
CMD ["python", "-m", "reliability_ops.service", "console", "--config", "/console-config/console.json", "--host", "0.0.0.0", "--port", "8602"]
