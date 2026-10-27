FROM python:3.12.14-slim-bookworm
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN python -m pip install --no-cache-dir duckdb==1.3.2
COPY src ./src
COPY fixtures ./fixtures
RUN mkdir -p /state /control /console-config /sources/advertising /sources/website /sources/crm && chown -R 10001:10001 /state /control /console-config /sources
USER 10001:10001
CMD ["python", "-m", "reliability_ops.service", "console", "--config", "/console-config/console.json", "--host", "0.0.0.0", "--port", "8602"]
