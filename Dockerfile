FROM python:3.11-slim

ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY . ./

RUN pip install --no-cache-dir -r requirements.txt

# CMD 라인에 --timeout 300 옵션을 추가하여 대기 시간을 5분으로 늘립니다.
CMD exec gunicorn --bind "0.0.0.0:$PORT" --timeout 300 main:app
