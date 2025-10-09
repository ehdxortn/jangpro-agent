from flask import Flask, jsonify
import requests, json, os, time
import vertexai
from vertexai.generative_models import GenerativeModel
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Google Cloud Vertex AI 초기화 ---
GCP_PROJECT_ID = "jangprofamily"
GCP_REGION = "us-central1"  # Cloud Run 권장 리전
vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)
# -------------------------------------

app = Flask(__name__)

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

# --- Requests 세션 설정 (재시도 + 타임아웃 강화) ---
session = requests.Session()
retry_strategy = Retry(
    total=3,                # 총 3회 재시도
    backoff_factor=2,       # 2초, 4초, 8초 간격으로 재시도
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)
# ---------------------------------------------------

@app.route("/")
def jangpro_mission_start():
    print("## JANGPRO AGENT (v_stable): MISSION START ##")
    try:
        # 1. Upbit 데이터 호출
        print("[1/4] Calling Upbit API...")
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        start_time = time.time()
        upbit_response = session.get(upbit_url, timeout=30)
        upbit_response.raise_for_status()
        upbit_data = upbit_response.json()
        elapsed = round(time.time() - start_time, 2)
        print(f"[2/4] Upbit API call successful (took {elapsed}s).")

        # 2. Gemini 분석 프롬프트 생성
        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 "
            "단기 매매 신호(매수/매도/관망)를 분석하고, 그 핵심 근거를 한 줄로 요약하라."
        )
        print("[3/4] Prompt generation successful.")

        # 3. Vertex AI (Gemini 2.5 Pro) 호출
        print("[4/4] Calling Gemini API via Vertex AI Library...")
        model = GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)
        analysis_text = response.text.strip()

        # 4. 결과 응답
        final_report = {
            "mission_status": "SUCCESS",
            "analysis_report": analysis_text,
            "upbit_coins": [coin["market"] for coin in upbit_data],
            "latency_sec": elapsed
        }
        print("## JANGPRO AGENT: MISSION COMPLETE ##")
        return jsonify(final_report)

    except requests.exceptions.ConnectTimeout:
        msg = "Upbit API 연결이 30초 이내에 응답하지 않았습니다 (Connection Timeout)."
        print(f"!! TIMEOUT ERROR: {msg}")
        return jsonify({"mission_status": "ERROR", "error_message": msg}), 504

    except requests.exceptions.RequestException as re:
        msg = f"Upbit API 요청 중 오류 발생: {str(re)}"
        print(f"!! REQUEST ERROR: {msg}")
        return jsonify({"mission_status": "ERROR", "error_message": msg}), 502

    except Exception as e:
        msg = f"시스템 내부 오류 발생: {str(e)}"
        print(f"!! EXCEPTION: {msg}")
        return jsonify({"mission_status": "ERROR", "error_message": msg}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
