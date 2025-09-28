from flask import Flask, jsonify
import requests, json, os
from datetime import datetime

app = Flask(__name__)

# 중요: "AIza..." 로 시작하는 API 키는 예시이며, 실제 형님의 키로 사용해야 합니다.
GEMINI_API_KEY = "AIzaSyAUhg2nFtQxWfmYCfV5kEhbP1vHYiMBiT" 
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

@app.route("/")
def jangpro_mission_start():
    try:
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url)
        upbit_data = upbit_response.json()

        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)를 분석하고, 그 핵심 근거를 한 줄로 요약하여 보고하라."
        )

        gemini_url = f"https.://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        gemini_response = requests.post(gemini_url, json=payload)
        gemini_result_json = gemini_response.json()

        analysis_text = gemini_result_json['candidates'][0]['content']['parts'][0]['text']

        final_report = {"mission_status": "SUCCESS", "analysis_report": analysis_text}
        return jsonify(final_report)

    except Exception as e:
        error_report = {"mission_status": "ERROR", "error_message": str(e)}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
