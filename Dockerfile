FROM python:3.12-slim
WORKDIR /service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
COPY requirements-postgres.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt
COPY app ./app
COPY migrations ./migrations
RUN useradd --uid 10001 --create-home appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
ENV DATABASE_PATH=/data/blitz.db
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
