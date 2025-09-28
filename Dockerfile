FROM python:3.11-slim

ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY . ./

RUN pip install --no-cache-dir -r requirements.txt

# CMD 라인을 수정하여 $PORT 변수가 올바르게 적용되도록 합니다.
CMD exec gunicorn --bind "0.0.0.0:$PORT" main:app
