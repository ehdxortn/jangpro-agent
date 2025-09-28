from flask import Flask, jsonify
import requests, json, os, time
from datetime import datetime

app = Flask(__name__)

# 형님의 실제 API 키 (정상)
GEMINI_API_KEY = "AIzaSyDvrIdBfc3x0O3syU58XGwgtLi7rCEC0M0" 
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

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

        # 3. Gemini API 호출 (v1beta 정식 주소로 최종 수정)
        print("[4/5] Calling Gemini API...")
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        gemini_response = None
        for i in range(3):
            try:
                gemini_response = requests.post(gemini_url, json=payload, timeout=20)
                gemini_response.raise_for_status()
                print(f"[Attempt {i+1}/3] Gemini API call successful.")
                break 
            except requests.exceptions.RequestException as e:
                print(f"[Attempt {i+1}/3] Gemini API call failed: {e}")
                if i < 2: 
                    time.sleep(5) 
                else:
                    raise 
                    
        gemini_result_json = gemini_response.json()
        print("[5/5] Gemini API response received.")

        # 4. 안정적인 응답 파싱
        if 'candidates' in gemini_result_json and gemini_result_json['candidates']:
            analysis_text = gemini_result_json['candidates'][0].get('content', {}).get('parts', [{}])[0].get('text', 'No text found in response')
        else:
            analysis_text = f"Analysis not available. Reason: {gemini_result_json.get('promptFeedback', 'Unknown error from API')}"
        
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
