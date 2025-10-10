from flask import Flask, jsonify
import requests, json, os
import google.generativeai as genai
import re

# Gemini API 키 입력 (새로운 키)
GEMINI_API_KEY = "AIzaSyBQcRI97vzwfstcbLz8wNIqbmVQp9nKGU0"
genai.configure(api_key=GEMINI_API_KEY)

app = Flask(__name__)

TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

def parse_gemini_response(result_text):
    # 코인별 신호/근거를 파싱해서 JSON 리스트로 반환
    coin_signals = []
    lines = result_text.strip().split('\n')
    for line in lines:
        found = re.match(r"(.+?):\s*(매수|매도|관망)\s*-\s*(.+)", line)
        if found:
            name = found.group(1).strip()
            signal = found.group(2).strip()
            reason = found.group(3).strip()
            coin_signals.append({"코인명": name, "신호": signal, "근거": reason})
    return coin_signals if coin_signals else result_text # 만약 파싱 실패시 원본 결과 제공

@app.route("/")
def jangpro_mission_start():
    try:
        # Upbit 실시간 시세 가져오기
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=30)
        upbit_response.raise_for_status()
        upbit_data = upbit_response.json()
        
        # Gemini 프롬프트 생성 및 분석
        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)와 핵심 근거를 '코인명: 신호 - 근거' 형식으로 한 줄씩만 정리해서 보고하라."
        )
        model = genai.GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)

        signals = parse_gemini_response(response.text)

        # 성공 결과 반환 (간결 출력)
        return jsonify({"mission_status": "SUCCESS", "coin_signals": signals})

    except Exception as e:
        error_report = {"mission_status": "ERROR", "error_message": str(e)}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
