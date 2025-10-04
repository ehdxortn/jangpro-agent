FROM python:3.11-slim

ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY . ./

RUN pip install --no-cache-dir -r requirements.txt

# CMD 라인에 --timeout 120 옵션을 추가하여 대기 시간을 120초로 늘립니다.
CMD exec gunicorn --bind "0.0.0.0:$PORT" --timeout 120 main:app
