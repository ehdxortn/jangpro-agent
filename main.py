from flask import Flask, jsonify
import requests, json, os
import vertexai
from vertexai.generative_models import GenerativeModel

# --- Google Cloud 공식 라이브러리 초기화 ---
GCP_PROJECT_ID = "jangprofamily"
GCP_REGION = "us-central1"
vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)
# -----------------------------------------

app = Flask(__name__)

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

@app.route("/")
def jangpro_mission_start():
    print("## JANGPRO AGENT (v_final_stable): MISSION START ##")
    try:
        # 1. Upbit 데이터 호출
        print("[1/4] Calling Upbit API...")
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=10)
        upbit_response.raise_for_status()
        upbit_data = upbit_response.json()
        print("[2/4] Upbit API call successful.")

        # 2. 프롬프트 생성 (간단화)
        prompt = "안녕하세요. 간단한 테스트입니다."
        print("[3/4] Prompt generation successful.")

        # 3. Gemini API 호출 (기본 모델로 테스트)
        print("[4/4] Calling Gemini API via Vertex AI Library...")
        try:
            model = GenerativeModel("gemini-1.5-pro")
            response = model.generate_content(prompt)
            analysis_text = response.text
            print(f"Gemini response received: {analysis_text[:100]}...")
        except Exception as e:
            print(f"Gemini API Error: {str(e)}")
            analysis_text = f"Gemini 모델 호출 실패: {str(e)}"

        final_report = {"mission_status": "SUCCESS", "analysis_report": analysis_text}
        print("## JANGPRO AGENT: MISSION COMPLETE ##")
        return jsonify(final_report)

    except requests.exceptions.RequestException as re:
        print(f"Upbit API request error: {re}")
        error_report = {"mission_status": "ERROR", "error_message": f"Upbit API 오류: {re}"}
        return jsonify(error_report), 500
    except Exception as e:
        print(f"!! GENERAL EXCEPTION: {str(e)} !!")
        error_report = {"mission_status": "ERROR", "error_message": f"일반 오류: {str(e)}"}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
