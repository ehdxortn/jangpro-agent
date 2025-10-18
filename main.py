from flask import Flask, jsonify, request
import os, requests, json
import openai
import google.generativeai as genai

# --- API 키 설정 ---
openai.api_key = os.getenv("OPENAI_API_KEY")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
PERPLEXITY_KEY = os.getenv("PERPLEXITY_API_KEY")

app = Flask(__name__)

@app.route("/analyze", methods=["POST"])
def analyze():
    user_query = request.json.get("query", "현재 시장 분석")

    # 1️⃣ Perplexity: 최신 뉴스 / 데이터 수집
    headers = {"Authorization": f"Bearer {PERPLEXITY_KEY}"}
    ppx_resp = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers=headers,
        json={
            "model": "sonar-small-online",
            "messages": [{"role": "user", "content": user_query}]
        },
        timeout=60
    )
    ppx_text = ppx_resp.json().get("choices",[{}])[0].get("message",{}).get("content","")

    # 2️⃣ Gemini: 현실 검증 및 요약
    gem_model = genai.GenerativeModel("gemini-2.5-pro")
    gem_resp = gem_model.generate_content(
        f"다음 정보를 현실적으로 요약하고 핵심 리스크를 분석해줘:\n{ppx_text}"
    ).text

    # 3️⃣ OpenAI: 논리 판단 및 결론 생성
    oa_resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "너는 분석가다."},
            {"role": "user", "content": f"다음 내용을 논리적으로 판단하고 투자 방향을 제시해줘:\n{gem_resp}"}
        ]
    )
    final_text = oa_resp["choices"][0]["message"]["content"]

    return jsonify({
        "status": "SUCCESS",
        "query": user_query,
        "perplexity_summary": ppx_text,
        "gemini_analysis": gem_resp,
        "openai_decision": final_text
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
