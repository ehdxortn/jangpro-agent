import os
import json
import logging
import requests
from flask import Flask, request, jsonify

# ========= 환경변수 =========
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
PPLX_MODEL  = os.getenv("PPLX_MODEL",  "sonar-small-online")

# ========= 로깅 =========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jangpro-agent")

# ========= 클라이언트 =========
# OpenAI
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception as e:
    log.warning("OpenAI init warning: %s", e)
    openai_client = None

# Gemini
try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    log.warning("Gemini init warning: %s", e)

app = Flask(__name__)

# ========= 유틸 =========
def call_perplexity(query: str) -> dict:
    if not PERPLEXITY_API_KEY:
        return {"ok": False, "text": "", "error": "PERPLEXITY_API_KEY missing"}
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": PPLX_MODEL,
                "messages": [{"role": "user", "content": query}],
            },
            timeout=60,
        )
        if resp.status_code == 401:
            return {"ok": False, "text": "", "error": "Perplexity 401 Unauthorized (키/헤더 확인)"}
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"Perplexity error: {e}"}

def call_gemini(context_text: str) -> dict:
    if not GEMINI_API_KEY:
        return {"ok": False, "text": "", "error": "GEMINI_API_KEY missing"}
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = (
            "아래 정보를 근거 중심으로 요약하고, 확인 필요한 리스크를 bullet로 정리하고, 끝에 1문장 요약:\n\n"
            f"{context_text}"
        )
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", "") or ""
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"Gemini error: {e}"}

def call_openai(decision_context: str) -> dict:
    if not OPENAI_API_KEY or not openai_client:
        return {"ok": False, "text": "", "error": "OPENAI_API_KEY missing or client init failed"}
    try:
        resp = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "너는 신중하고 근거 중심의 수석 애널리스트다."},
                {"role": "user", "content": (
                    "다음 메모를 바탕으로 실행 가능한 결론을 만들어라. "
                    "1) 상/중/하 시나리오, 2) 트리거·무효화 조건, 3) 액션 체크리스트, 4) 한 줄 결론:\n\n"
                    f"{decision_context}"
                )},
            ],
            temperature=0.4,
        )
        text = resp.choices[0].message.content
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"OpenAI error: {e}"}

# ========= 라우트 =========
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "jangpro-agent",
        "status": "OK",
        "endpoints": ["/healthz (GET)", "/routes (GET)", "/analyze (GET,POST)"],
        "models": {
            "gemini_model": GEMINI_MODEL,
            "openai_model": OPENAI_MODEL,
            "perplexity_model": PPLX_MODEL
        }
    })

@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200

# 현재 등록된 라우트 목록 보기(디버그용)
@app.route("/routes", methods=["GET"])
def routes():
    rules = []
    for r in app.url_map.iter_rules():
        rules.append({"rule": str(r), "methods": sorted([m for m in r.methods if m not in ["HEAD", "OPTIONS"]])})
    return jsonify({"routes": rules})

# 🔥 핵심: /analyze 는 GET/POST 둘 다 허용 (POST 권장)
@app.route("/analyze", methods=["GET", "POST"])
def analyze():
    # GET 테스트 지원: /analyze?query=비트코인 단기 전망
    if request.method == "GET":
        user_query = request.args.get("query", "시장 분석 요청")
    else:
        body = request.get_json(silent=True) or {}
        user_query = body.get("query", "시장 분석 요청")

    # 1) Perplexity
    pplx = call_perplexity(user_query)
    pplx_text = pplx.get("text", "")
    if not pplx["ok"]:
        log.error("Perplexity fail: %s", pplx.get("error"))

    # 2) Gemini
    gem = call_gemini(pplx_text if pplx_text else user_query)
    gem_text = gem.get("text", "")
    if not gem["ok"]:
        log.error("Gemini fail: %s", gem.get("error"))

    # 3) OpenAI
    oai = call_openai(gem_text if gem_text else (pplx_text or user_query))
    if not oai["ok"]:
        log.error("OpenAI fail: %s", oai.get("error"))

    status = "SUCCESS" if (pplx["ok"] and gem["ok"] and oai["ok"]) else \
             "PARTIAL_SUCCESS" if (gem["ok"] or oai["ok"]) else "ERROR"

    return jsonify({
        "mission_status": status,
        "input_query": user_query,
        "perplexity_summary": pplx_text,
        "gemini_analysis": gem_text,
        "openai_decision": oai.get("text", ""),
        "errors": {
            "perplexity": pplx.get("error"),
            "gemini": gem.get("error"),
            "openai": oai.get("error"),
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
