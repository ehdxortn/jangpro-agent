FROM python:3.11-slim

# (옵션) 인증서/네트워크 유틸
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app
ENV PORT=8080
WORKDIR $APP_HOME

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run은 $PORT로 리스닝해야 함
CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 300 main:app
