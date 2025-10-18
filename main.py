from flask import Flask, request, jsonify
import requests, os, json
import google.generativeai as genai
from openai import OpenAI

# 🔑 API Keys
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
PERPLEXITY_API_KEY = "YOUR_PERPLEXITY_API_KEY"

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

@app.route("/healthz", methods=["GET"])
def health_check():
    return jsonify({
        "service": "jangpro-agent",
        "status": "OK",
        "models": {
            "gemini_model": "gemini-2.5-pro",
            "openai_model": "gpt-4o-mini",
            "perplexity_model": "sonar-small-online"
        }
    })

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        query = data.get("query", "시장 분석 요청")

        # 1️⃣ Perplexity 호출
        perplexity_resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sonar-small-online",
                "messages": [{"role": "user", "content": query}]
            },
            timeout=30
        )
        perplexity_text = perplexity_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "No response")

        # 2️⃣ Gemini 분석
        gemini_model = genai.GenerativeModel("gemini-2.5-pro")
        gemini_result = gemini_model.generate_content(
            f"이 텍스트를 분석해줘:\n{perplexity_text}\n\n핵심 요약 및 리스크를 포함해서 보고 형태로."
        )
        gemini_text = gemini_result.text

        # 3️⃣ OpenAI 검증
        openai_result = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "너는 논리적 금융 분석가야."},
                {"role": "user", "content": f"Gemini 분석 결과:\n{gemini_text}\n\n이 내용의 타당성을 검증해줘."}
            ]
        )
        openai_text = openai_result.choices[0].message.content

        return jsonify({
            "mission_status": "SUCCESS",
            "input_query": query,
            "perplexity_summary": perplexity_text,
            "gemini_analysis": gemini_text,
            "openai_decision": openai_text
        })

    except Exception as e:
        return jsonify({"mission_status": "ERROR", "error_message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
