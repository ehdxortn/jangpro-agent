FROM python:3.11-slim

ENV PYTHONUNBUFFERED True
WORKDIR /app

COPY . ./
RUN pip install --no-cache-dir Flask requests gunicorn

CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 300 main:app
