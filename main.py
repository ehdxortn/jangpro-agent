from flask import Flask, jsonify
import requests, json, os, time
from datetime import datetime

app = Flask(__name__)

# 형님의 실제 API 키
GEMINI_API_KEY = "AIzaSyDvrIdBfc3x0O3syU58XGwgtLi7rCEC0M0" 
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]
GCP_PROJECT_ID = "jangprofamily" # 우리 프로젝트 ID
GCP_REGION = "asia-northeast3" # 우리 서비스 지역

@app.route("/")
def jangpro_mission_start():
    print("## JANGPRO AGENT: MISSION START ##")
    gemini_result_json = {} 
    try:
        # 1. Upbit 데이터 호출
        print("[1/5] Calling Upbit API...")
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=10)
        upbit_response.raise_for_status() 
        upbit_data = upbit_response.json()
        print("[2/5] Upbit API call successful.")

        # 2. 프롬프트 생성
        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)를 분석하고, 그 핵심 근거를 한 줄로 요약하여 보고하라."
        )
        print("[3/5] Prompt generation successful.")

        # 3. Gemini API 호출 (Google Cloud 정식 주소 및 양식으로 최종 수정)
        print("[4/5] Calling Vertex AI (Gemini) API...")
        # --- 여기가 완전히 바뀐 부분입니다 ---
        gemini_url = f"https://{GCP_REGION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}/publishers/google/models/gemini-pro:streamGenerateContent"
        headers = {
            "Authorization": f"Bearer {GEMINI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        # ------------------------------------

        gemini_response = requests.post(gemini_url, headers=headers, json=payload, timeout=30)
        gemini_response.raise_for_status()
        
        # streamGenerateContent는 여러 조각으로 응답이 오므로, 마지막 조각을 사용합니다.
        response_data = gemini_response.text.strip().split('\n')[-1]
        gemini_result_json = json.loads(response_data)
        print("[5/5] Gemini API response received.")

        # 4. 안정적인 응답 파싱
        analysis_text = gemini_result_json['candidates'][0]['content']['parts'][0]['text']
        
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
