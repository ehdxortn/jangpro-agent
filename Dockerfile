FROM python:3.11-slim

# --- 환경 변수 설정 ---
ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME

# --- 파일 복사 및 의존성 설치 ---
COPY . ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Gunicorn 서버 실행 ---
CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 300 main:app
