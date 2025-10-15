from flask import Flask, jsonify
import requests, json, os
import google.generativeai as genai
import openai
import re
import concurrent.futures

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Perplexity API Key
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

def parse_gemini_response(result_text):
    coin_signals = []
    lines = result_text.strip().split('\n')
    for line in lines:
        found = re.match(r"(.+?):\s*(매수|매도|관망)\s*-\s*(.+)", line)
        if found:
            name = found.group(1).strip()
            signal = found.group(2).strip()
            reason = found.group(3).strip()
            coin_signals.append({"코인명": name, "신호": signal, "근거": reason})
    return coin_signals if coin_signals else result_text

def gemini_call(prompt):
    model = genai.GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(prompt)
    return parse_gemini_response(response.text)

def openai_call(prompt):
    result = openai.ChatCompletion.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}]
    )
    ai_text = result['choices'][0]['message']['content']
    return parse_gemini_response(ai_text)

def perplexity_call(prompt):
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        # 최신 모델명으로 바꿈 — 예: sonar-deep-research
        "model": "perplexity/sonar-deep-research",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }
    resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    resp_json = resp.json()
    ai_text = resp_json['choices'][0]['message']['content']
    return parse_gemini_response(ai_text)

app = Flask(__name__)

@app.route("/")
def jangpro_mission_start():
    try:
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=30)
        upbit_response.raise_for_status()
        upbit_data = upbit_response.json()

        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)와 핵심 근거를 '코인명: 신호 - 근거' 형식으로 한 줄씩만 정리해서 보고하라."
        )

        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = list(executor.map(lambda f: f(prompt), [gemini_call, openai_call, perplexity_call]))
        
        return jsonify({
            "mission_status": "SUCCESS",
            "gemini_signals": results[0],
            "openai_signals": results[1],
            "perplexity_signals": results[2]
        })

    except Exception as e:
        error_report = {"mission_status": "ERROR", "error_message": str(e)}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
