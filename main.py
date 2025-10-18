import os
import json
import logging
import requests
from flask import Flask, request, jsonify

# -------------------------------------------------
# 환경변수 (Cloud Run → 서비스 편집 → 환경 변수)
# -------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
PPLX_MODEL  = os.getenv("PPLX_MODEL",  "sonar-small-online")

# -------------------------------------------------
# 로깅
# -------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jangpro-agent")

# -------------------------------------------------
# 외부 라이브러리 초기화
# -------------------------------------------------
# OpenAI
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    log.warning("OpenAI client init warning: %s", e)
    openai_client = None

# Gemini
try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    log.warning("Gemini init warning: %s", e)

# Flask
app = Flask(__name__)

# -------------------------------------------------
# Perplexity API 호출
# -------------------------------------------------
def call_perplexity(query: str) -> dict:
    """
    Perplexity API(via chat/completions)로 최신 팩트/요약 수집
    리턴: {"ok": bool, "text": str, "raw": dict}
    """
    if not PERPLEXITY_API_KEY:
        return {"ok": False, "text": "", "raw": {}, "error": "PERPLEXITY_API_KEY missing"}

    url = "https://api.perplexity.ai/chat/completions"  # 엔드포인트 주의
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": PPLX_MODEL,
        "messages": [{"role": "user", "content": query}],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 401:
            return {"ok": False, "text": "", "raw": resp.text, "error": "Perplexity 401 Unauthorized (키/헤더 확인)"}
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        return {"ok": True, "text": text, "raw": data}
    except Exception as e:
        return {"ok": False, "text": "", "raw": {}, "error": f"Perplexity error: {e}"}

# -------------------------------------------------
# Gemini 호출 (현실 검증/비판적 요약)
# -------------------------------------------------
def call_gemini(context_text: str) -> dict:
    """
    Gemini로 Perplexity 요약을 비판적으로 검토하고 리스크/변수 정리
    리턴: {"ok": bool, "text": str}
    """
    if not GEMINI_API_KEY:
        return {"ok": False, "text": "", "error": "GEMINI_API_KEY missing"}
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = (
            "아래 정보를 바탕으로 핵심 사실, 불확실성, 즉시 확인이 필요한 리스크를 "
            "간결히 bullet로 정리해줘. 마지막엔 1문장 요약을 추가:\n\n"
            f"{context_text}"
        )
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", "") or ""
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"Gemini error: {e}"}

# -------------------------------------------------
# OpenAI 호출 (논리적 판단/결론)
# -------------------------------------------------
def call_openai(decision_context: str) -> dict:
    """
    OpenAI(GPT-4o-mini 기본)로 최종 논리 판단/권고안 생성
    리턴: {"ok": bool, "text": str}
    """
    if not OPENAI_API_KEY or not openai_client:
        return {"ok": False, "text": "", "error": "OPENAI_API_KEY missing or client init failed"}

    try:
        resp = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "너는 신중하고 근거 중심의 수석 애널리스트다."},
                {
                    "role": "user",
                    "content": (
                        "다음 분석 메모를 기반으로 실행 가능한 결론을 만들어라. "
                        "1) 시나리오(상/중/하), 2) 트리거/무효화 조건, 3) 액션 체크리스트, 4) 한 줄 결론:\n\n"
                        f"{decision_context}"
                    ),
                },
            ],
            temperature=0.4,
        )
        text = resp.choices[0].message.content
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"OpenAI error: {e}"}

# -------------------------------------------------
# 라우트
# -------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return jsonify(
        {
            "service": "jangpro-agent",
            "status": "OK",
            "endpoints": ["/healthz (GET)", "/analyze (POST)"],
            "models": {
                "openai_model": OPENAI_MODEL,
                "gemini_model": GEMINI_MODEL,
                "perplexity_model": PPLX_MODEL,
            },
        }
    )

@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200

@app.route("/analyze", methods=["POST"])
def analyze():
    """
    요청 JSON 예:
    {
      "query": "비트코인 단기 전망",
      "return_raw": false
    }
    """
    body = request.get_json(silent=True) or {}
    user_query = body.get("query") or "시장 핵심 이슈 요약"
    return_raw = bool(body.get("return_raw", False))

    # 1) Perplexity
    pplx = call_perplexity(user_query)
    if not pplx["ok"]:
        log.error("Perplexity fail: %s", pplx.get("error"))
    pplx_text = pplx.get("text", "")

    # 2) Gemini
    gem = call_gemini(pplx_text if pplx_text else user_query)
    if not gem["ok"]:
        log.error("Gemini fail: %s", gem.get("error"))
    gem_text = gem.get("text", "")

    # 3) OpenAI
    oai = call_openai(gem_text if gem_text else (pplx_text or user_query))
    if not oai["ok"]:
        log.error("OpenAI fail: %s", oai.get("error"))

    # 상태 판단
    ok_all = pplx["ok"] and gem["ok"] and oai["ok"]
    status = "SUCCESS" if ok_all else "PARTIAL_SUCCESS" if (gem["ok"] or oai["ok"]) else "ERROR"

    resp_payload = {
        "mission_status": status,
        "input_query": user_query,
        "perplexity_summary": pplx_text,
        "gemini_analysis": gem_text,
        "openai_decision": oai.get("text", ""),
        "errors": {
            "perplexity": pplx.get("error"),
            "gemini": gem.get("error"),
            "openai": oai.get("error"),
        },
    }
    if return_raw:
        resp_payload["raw"] = {"perplexity": pplx.get("raw")}

    return jsonify(resp_payload), (200 if status != "ERROR" else 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
