from flask import Flask, jsonify, request
import requests
import json
import os
from datetime import datetime

app = Flask(__name__)

# ==================== API 키 설정 ====================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyAUhg2nFtQxWfmYCfV5kEhbP1vHYiMBiT")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  # 형님이 추가하실 경우
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

# ==================== 설정 ====================
TARGET_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]
GEMINI_MODEL = "gemini-1.5-pro"


# ==================== 헬스체크 (Cloud Run 필수) ====================
@app.route("/health", methods=["GET"])
def health_check():
    """Cloud Run 헬스체크 엔드포인트"""
    return jsonify({
        "status": "OK",
        "service": "jangpro-ai-trading",
        "timestamp": datetime.now().isoformat(),
        "version": "v4.0"
    }), 200


# ==================== 메인 페이지 ====================
@app.route("/", methods=["GET"])
def index():
    """서비스 상태 및 사용 가능한 엔드포인트 안내"""
    return jsonify({
        "service": "장프로 AI 트레이딩 시스템",
        "status": "running",
        "endpoints": {
            "health_check": "/health",
            "single_analysis": "/analyze",
            "parallel_analysis": "/analyze-parallel",
            "upbit_data": "/upbit-data"
        },
        "supported_coins": TARGET_COINS,
        "timestamp": datetime.now().isoformat()
    }), 200


# ==================== 업비트 실시간 데이터 조회 ====================
@app.route("/upbit-data", methods=["GET"])
def get_upbit_data():
    """업비트 실시간 시세 데이터만 반환"""
    try:
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        response = requests.get(upbit_url, timeout=10)
        response.raise_for_status()
        
        upbit_data = response.json()
        
        # 데이터 정리
        formatted_data = []
        for coin in upbit_data:
            formatted_data.append({
                "market": coin.get("market"),
                "trade_price": coin.get("trade_price"),
                "change_rate": round(coin.get("signed_change_rate", 0) * 100, 2),
                "acc_trade_price_24h": coin.get("acc_trade_price_24h"),
                "timestamp": coin.get("timestamp")
            })
        
        return jsonify({
            "status": "SUCCESS",
            "data": formatted_data,
            "count": len(formatted_data),
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "ERROR",
            "error_message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


# ==================== 단일 AI 분석 (Gemini + Upbit) ====================
@app.route("/analyze", methods=["GET", "POST"])
def analyze_single():
    """Gemini를 사용한 단일 AI 분석"""
    try:
        # 1. 업비트 데이터 수집
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=10)
        upbit_response.raise_for_status()
        upbit_data = upbit_response.json()
        
        # 2. Gemini 프롬프트 생성
        prompt = f"""너는 '장프로'라는 이름의 AI 트레이딩 어시스턴트다.

**현재 시각:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}

**업비트 실시간 코인 데이터:**
{json.dumps(upbit_data, indent=2, ensure_ascii=False)}

**분석 요청:**
위 데이터를 기반으로, 각 코인에 대해 다음을 분석하라:
1. 현재 매매 신호 (매수/매도/관망)
2. 핵심 근거 (1-2줄 요약)
3. 단기 목표가 (24시간 기준)

**출력 형식:**
- 코인별로 명확히 구분
- 간결하고 실용적인 조언
- 리스크 요인 포함"""

        # 3. Gemini API 호출
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        gemini_response = requests.post(gemini_url, json=payload, timeout=30)
        gemini_response.raise_for_status()
        gemini_result = gemini_response.json()
        
        # 4. 결과 추출
        analysis_text = gemini_result['candidates'][0]['content']['parts'][0]['text']
        
        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "single_gemini",
            "analysis_report": analysis_text,
            "coins_analyzed": TARGET_COINS,
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except requests.exceptions.RequestException as e:
        return jsonify({
            "mission_status": "ERROR",
            "error_type": "API_REQUEST_FAILED",
            "error_message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500
        
    except KeyError as e:
        return jsonify({
            "mission_status": "ERROR",
            "error_type": "RESPONSE_PARSING_FAILED",
            "error_message": f"응답 구조 오류: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }), 500
        
    except Exception as e:
        return jsonify({
            "mission_status": "ERROR",
            "error_type": "UNKNOWN_ERROR",
            "error_message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


# ==================== 병렬 AI 분석 (멀티 모델) ====================
@app.route("/analyze-parallel", methods=["POST"])
def analyze_parallel():
    """여러 AI 모델을 병렬로 실행하여 교차 분석"""
    try:
        # 요청 데이터 확인
        data = request.get_json() if request.is_json else {}
        custom_query = data.get("query", "")
        
        # 1. 업비트 데이터 수집
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(TARGET_COINS)}"
        upbit_response = requests.get(upbit_url, timeout=10)
        upbit_response.raise_for_status()
        upbit_data = upbit_response.json()
        
        # 2. 기본 프롬프트 생성
        if not custom_query:
            custom_query = f"""업비트 실시간 데이터를 분석하여 단기 매매 전략을 제시하라.
데이터: {json.dumps(upbit_data[:3], ensure_ascii=False)}"""
        
        results = {}
        
        # 3. Gemini 분석
        try:
            gemini_payload = {
                "contents": [{
                    "parts": [{"text": custom_query}]
                }]
            }
            gemini_res = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                json=gemini_payload,
                timeout=30
            )
            gemini_res.raise_for_status()
            gemini_json = gemini_res.json()
            results["gemini"] = gemini_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "응답 없음")
        except Exception as e:
            results["gemini"] = f"오류: {str(e)}"
        
        # 4. OpenAI 분석 (API 키가 있을 경우)
        if OPENAI_API_KEY and OPENAI_API_KEY.startswith("sk-"):
            try:
                openai_payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": custom_query}]
                }
                openai_res = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json=openai_payload,
                    timeout=30
                )
                openai_res.raise_for_status()
                results["openai"] = openai_res.json().get("choices", [{}])[0].get("message", {}).get("content", "응답 없음")
            except Exception as e:
                results["openai"] = f"오류: {str(e)}"
        else:
            results["openai"] = "API 키 미설정"
        
        # 5. Perplexity 분석 (API 키가 있을 경우)
        if PERPLEXITY_API_KEY and PERPLEXITY_API_KEY.startswith("pplx-"):
            try:
                pplx_payload = {
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": custom_query}]
                }
                pplx_res = requests.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
                    json=pplx_payload,
                    timeout=30
                )
                pplx_res.raise_for_status()
                results["perplexity"] = pplx_res.json().get("choices", [{}])[0].get("message", {}).get("content", "응답 없음")
            except Exception as e:
                results["perplexity"] = f"오류: {str(e)}"
        else:
            results["perplexity"] = "API 키 미설정"
        
        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "parallel_multi_model",
            "query": custom_query,
            "results": results,
            "models_used": list(results.keys()),
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({
            "mission_status": "ERROR",
            "error_message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


# ==================== 서버 실행 ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
