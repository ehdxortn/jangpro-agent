from flask import Flask, jsonify
import requests, json, os
import vertexai
from vertexai.generative_models import GenerativeModel

# --- Google Cloud 공식 라이브러리 초기화 ---
GCP_PROJECT_ID = "jangprofamily"
GCP_REGION = "asia-northeast3"
vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)
# -----------------------------------------

app = Flask(__name__)

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

@app.route("/")
def jangpro_mission_start():
    print("## JANGPRO AGENT (v_final): MISSION START ##")
    try:
        # 1. Upbit 데이터 호출
        print("[1/4] Calling Upbit API...")
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=10)
        upbit_response.raise_for_status() 
        upbit_data = upbit_response.json()
        print("[2/4] Upbit API call successful.")

        # 2. 프롬프트 생성
        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)를 분석하고, 그 핵심 근거를 한 줄로 요약하여 보고하라."
        )
        print("[3/4] Prompt generation successful.")

        # 3. Gemini API 호출 (공식 라이브러리 사용)
        print("[4/4] Calling Gemini API via Vertex AI Library...")
        model = GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        analysis_text = response.text
        
        final_report = {"mission_status": "SUCCESS", "analysis_report": analysis_text}
        print("## JANGPRO AGENT: MISSION COMPLETE ##")
        return jsonify(final_report)

    except Exception as e:
        print(f"!! EXCEPTION OCCURRED: {str(e)} !!")
        error_report = {"mission_status": "ERROR", "error_message": str(e)}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
