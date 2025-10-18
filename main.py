from flask import Flask, jsonify, request
import requests, json, os
from datetime import datetime

app = Flask(__name__)

# === Gemini API 설정 ===
GEMINI_API_KEY = "AIzaSyAUhg2nFtQxWfmYCfV5kEhbP1vHYiMBiT"
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

# === 헬스체크 ===
@app.route("/healthz", methods=["GET"])
def health_check():
    return jsonify({
        "service": "jangpro-agent",
        "status": "OK",
        "timestamp": datetime.utcnow().isoformat()
    })

# === 기본 페이지 ===
@app.route("/", methods=["GET"])
def root_page():
    return jsonify({
        "service": "jangpro-agent",
        "message": "Service is running",
        "usage": "POST /analyze with JSON {'query': '<질문 내용>'}"
    })

# === 분석 엔드포인트 ===
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        query = data.get("query", "비트코인 단기 전망")

        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=20)
        upbit_data = upbit_response.json()

        prompt = (
            f"너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다.\n"
            f"다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            f"사용자가 요청한 분석 주제는 '{query}'이다.\n"
            "각 코인에 대해 단기 매매 신호(매수/매도/관망)와 핵심 근거를 한 줄로 요약해라."
        )

        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        gemini_response = requests.post(gemini_url, json=payload, timeout=60)
        gemini_json = gemini_response.json()

        analysis_text = gemini_json['candidates'][0]['content']['parts'][0]['text']

        return jsonify({
            "mission_status": "SUCCESS",
            "query": query,
            "analysis_report": analysis_text
        })

    except Exception as e:
        return jsonify({
            "mission_status": "ERROR",
            "error_message": str(e)
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
