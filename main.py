from flask import Flask, jsonify
import requests, json, os
from datetime import datetime

app = Flask(__name__)

# 형님의 실제 API 키를 사용해야 합니다.
GEMINI_API_KEY = "AIzaSyDvrIdBfc3x0O3syU58XGwgtLi7rCEC0M0" 
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

@app.route("/")
def jangpro_mission_start():
    gemini_result_json = {} # 에러 발생 시 로그 출력을 위해 변수를 미리 선언
    try:
        # 1. Upbit 데이터 호출
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url)
        upbit_response.raise_for_status() # HTTP 에러 발생 시 여기서 중단
        upbit_data = upbit_response.json()

        # 2. 프롬프트 생성
        prompt = (
            "너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다. "
            "다음은 업비트의 실시간 코인 데이터다:\n\n"
            f"{json.dumps(upbit_data, indent=2, ensure_ascii=False)}\n\n"
            "이 데이터를 기반으로, 각 코인에 대해 '프로핏 스태킹' 모델에 따른 단기 매매 신호(매수/매도/관망)를 분석하고, 그 핵심 근거를 한 줄로 요약하여 보고하라."
        )

        # 3. Gemini API 호출
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        gemini_response = requests.post(gemini_url, json=payload)
        gemini_response.raise_for_status() # HTTP 에러 발생 시 여기서 중단
        gemini_result_json = gemini_response.json()

        # 4. 안정적인 응답 파싱
        if 'candidates' in gemini_result_json and gemini_result_json['candidates']:
            analysis_text = gemini_result_json['candidates'][0].get('content', {}).get('parts', [{}])[0].get('text', 'No text found in response')
        else:
            analysis_text = f"Analysis not available. Reason: {gemini_result_json.get('promptFeedback', 'Unknown error from API')}"
        
        final_report = {"mission_status": "SUCCESS", "analysis_report": analysis_text}
        return jsonify(final_report)

    except requests.exceptions.RequestException as e:
        # 네트워크 또는 HTTP 에러 처리
        error_report = {"mission_status": "ERROR", "error_type": "RequestException", "error_message": str(e)}
        return jsonify(error_report), 500
    except (KeyError, IndexError, TypeError) as e:
        # JSON 파싱 또는 데이터 구조 에러 처리
        error_report = {"mission_status": "ERROR", "error_type": "ParsingError", "error_message": f"Failed to parse API response: {str(e)}", "raw_response": gemini_result_json}
        return jsonify(error_report), 500
    except Exception as e:
        # 그 외 모든 예측 불가능한 에러 처리
        error_report = {"mission_status": "ERROR", "error_type": "GeneralException", "error_message": str(e)}
        return jsonify(error_report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
