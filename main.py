from flask import Flask, jsonify
import requests, json, os
import vertexai
from vertexai.generative_models import GenerativeModel

# --- 환경 변수에서 프로젝트와 리전 가져오기 (외부 가이드 적용) ---
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
REGION = os.environ.get("GOOGLE_CLOUD_REGION")
# ---------------------------------------------------------

app = Flask(__name__)

# --- Vertex AI 초기화 ---
# 코드 실행 전에 환경 변수가 먼저 설정되어 있어야 함
if PROJECT_ID and REGION:
    vertexai.init(project=PROJECT_ID, location=REGION)
# -------------------------

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

@app.route("/")
def jangpro_mission_start():
    print("## JANGPRO AGENT (v_expert_guide): MISSION START ##")
    try:
        # 1. Upbit 데이터 호출
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=10)
        upbit_response.raise_for_status() 
        upbit_data = upbit_response.json()

        # 2. 프롬프트 생성
        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)를 분석하고, 그 핵심 근거를 한 줄로 요약하여 보고하라."
        )

        # 3. Gemini API 호출 (2.5 Pro 모델로 수정)
        model = GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)
        analysis_text = response.text
        
        final_report = {"mission_status": "SUCCESS", "analysis_report": analysis_text}
        return jsonify(final_report)

    except Exception as e:
        error_report = {"mission_status": "ERROR", "error_message": str(e)}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
