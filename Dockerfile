FROM python:3.11-slim

ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY . ./
RUN pip install --no-cache-dir -r requirements.txt

# Gunicorn의 대기 시간을 300초로 늘리고, 워커 설정을 최적화합니다.
CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 300 main:app
