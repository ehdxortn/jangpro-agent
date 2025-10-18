from flask import Flask, jsonify, request
import requests, json, os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# === 환경 변수 or 기본 키 설정 ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-xxxxxxxx")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyAUhg2nFtQxWfmYCfV5kEhbP1vHYiMBiT")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "pplx-xxxxxxxx")

# === 대상 코인 ===
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-NEAR", "KRW-POL"]

# === 병렬 처리 스레드 풀 ===
executor = ThreadPoolExecutor(max_workers=3)


# -------------------------------------------
# 1️⃣ 헬스체크
# -------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "OK",
        "service": "jangpro-multi-ai",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }), 200


# -------------------------------------------
# 2️⃣ 루트 경로
# -------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "🚀 JangPro Multi-AI Agent v5 is running",
        "available_endpoints": ["/health", "/analyze"]
    }), 200


# -------------------------------------------
# 3️⃣ AI 병렬 분석 함수들
# -------------------------------------------
def fetch_upbit_data():
    url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
    res = requests.get(url, timeout=10)
    res.raise_for_status()
    return res.json()


def analyze_with_gemini(query, upbit_data):
    prompt = (
        f"너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다.\n"
        f"업비트의 실시간 코인 데이터:\n{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
        f"사용자 요청: {query}\n"
        "각 코인별 단기 매매 신호(매수/매도/관망)와 근거를 간결히 정리해라."
    )

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    r = requests.post(gemini_url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "No response")


def analyze_with_openai(query, upbit_data):
    prompt = (
        f"너는 시장 데이터를 해석하는 금융분석 AI다.\n"
        f"업비트 데이터:\n{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
        f"질문: {query}\n"
        "각 코인별 논리적 판단에 따른 매수/매도/관망 결정을 내려라."
    )

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}]
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def analyze_with_perplexity(query, upbit_data):
    prompt = (
        f"너는 실시간 시장 정보를 수집하는 AI다.\n"
        f"업비트 데이터:\n{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
        f"요청: {query}\n"
        "최신 뉴스나 데이터 트렌드 기반으로 판단을 내려라."
    )

    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}"}
    payload = {
        "model": "sonar-small-online",
        "messages": [{"role": "user", "content": prompt}]
    }
    r = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# -------------------------------------------
# 4️⃣ 병렬 실행 엔드포인트
# -------------------------------------------
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        query = data.get("query", "비트코인 단기 전망")

        upbit_data = fetch_upbit_data()

        # 병렬 호출
        futures = {
            "gemini": executor.submit(analyze_with_gemini, query, upbit_data),
            "openai": executor.submit(analyze_with_openai, query, upbit_data),
            "perplexity": executor.submit(analyze_with_perplexity, query, upbit_data)
        }

        results = {}
        for name, future in futures.items():
            try:
                results[name] = future.result(timeout=90)
            except Exception as e:
                results[name] = f"Error: {str(e)}"

        return jsonify({
            "mission_status": "SUCCESS",
            "query": query,
            "results": results,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 200

    except Exception as e:
        return jsonify({
            "mission_status": "ERROR",
            "error_message": str(e)
        }), 500


# -------------------------------------------
# 5️⃣ 실행
# -------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
