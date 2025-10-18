FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app
ENV PORT=8080
WORKDIR $APP_HOME

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# main.py 안의 app 객체를 실행
CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 300 main:app
