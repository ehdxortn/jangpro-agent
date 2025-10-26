from flask import Flask, jsonify, request
import os, json, time, asyncio
from datetime import datetime
import requests
import httpx

app = Flask(__name__)

# -------- 런타임 설정(임포트 시 실행 금지) --------
def get_cfg():
    return {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "pplx_api_key": os.getenv("PERPLEXITY_API_KEY", "").strip(),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip(),
        "openai_model": os.getenv("OPENAI_MODEL", "o4-mini").strip(),
        "pplx_model": os.getenv("PPLX_MODEL", "sonar-pro").strip(),
        "target_coins": (os.getenv(
            "TARGET_COINS",
            "KRW-BTC,KRW-ETH,KRW-NEAR,KRW-POL,KRW-WAVES,KRW-SOL"
        ).strip()).split(","),
    }

# -------- 공통 유틸 --------
def utcnow():
    return datetime.utcnow().isoformat() + "Z"

def fetch_upbit_with_retry(markets_csv: str, tries: int = 3, timeout: int = 10):
    url = f"https://api.upbit.com/v1/ticker?markets={markets_csv}"
    headers = {"User-Agent": "jangpro-agent/1.0"}
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(1.2 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"Upbit fetch failed: {last_err}")

def compact_ticker(raw):
    out = []
    for x in raw:
        out.append({
            "market": x.get("market"),
            "price": x.get("trade_price"),
            "change": x.get("change"),
            "change_pct": round((x.get("signed_change_rate") or 0) * 100, 3),
            "acc_trade_price_24h": x.get("acc_trade_price_24h"),
            "ts": x.get("timestamp"),
        })
    return out

def gemini_instruction():
    return (
        "너는 '장프로' 트레이딩 어시스턴트다.\n"
        "입력은 업비트 티커 핵심 JSON 배열이다.\n"
        "출력은 아래 스키마의 **JSON 배열만** 반환하라.\n"
        "[{\"코인명\": string, \"신호\": \"매수\"|\"매도\"|\"관망\", \"근거\": string, \"목표가\": number}]\n"
        "JSON 외 텍스트 금지."
    )

# -------- 상태/안내 --------
@app.get("/health")
def health():
    return jsonify({"status": "OK", "service": "jangpro-ai-trading", "ts": utcnow(), "version": "stable-2.5"}), 200

@app.get("/")
def root():
    cfg = get_cfg()
    return jsonify({
        "service": "장프로 AI 트레이딩 시스템",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "upbit": "/upbit-data",
            "single": "/analyze",
            "parallel": "/analyze-parallel"
        },
        "models": {
            "gemini": cfg["gemini_model"],
            "openai": cfg["openai_model"] if cfg["openai_api_key"] else "미사용",
            "perplexity": cfg["pplx_model"] if cfg["pplx_api_key"] else "미사용"
        },
        "supported_coins": cfg["target_coins"],
        "ts": utcnow()
    }), 200

# -------- 데이터 --------
@app.get("/upbit-data")
def upbit_data():
    try:
        cfg = get_cfg()
        raw = fetch_upbit_with_retry(",".join(cfg["target_coins"]))
        data = compact_ticker(raw)
        return jsonify({"status": "SUCCESS", "data": data, "count": len(data), "ts": utcnow()}), 200
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e), "ts": utcnow()}), 500

# -------- 단일 분석(Gemini 2.5 Pro) --------
@app.get("/analyze")
def analyze_single():
    try:
        cfg = get_cfg()
        if not cfg["gemini_api_key"]:
            return jsonify({"mission_status": "ERROR", "error": "GEMINI_API_KEY missing"}), 500

        raw = fetch_upbit_with_retry(",".join(cfg["target_coins"]))
        compact = compact_ticker(raw)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['gemini_model']}:generateContent?key={cfg['gemini_api_key']}"
        payload = {
            "generationConfig": {"responseMimeType": "application/json"},
            "contents": [
                {"parts": [{"text": gemini_instruction()}]},
                {"parts": [{"text": json.dumps(compact, ensure_ascii=False)}]}
            ]
        }
        r = requests.post(url, json=payload, timeout=40)
        r.raise_for_status()
        j = r.json()
        text = j["candidates"][0]["content"]["parts"][0]["text"]
        signals = json.loads(text)

        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "single_gemini_2_5_pro",
            "coin_signals": signals,
            "ts": utcnow()
        }), 200

    except Exception as e:
        return jsonify({"mission_status": "ERROR", "error": str(e), "ts": utcnow()}), 500

# -------- 병렬 분석(Gemini/OpenAI/Perplexity) --------
async def ask_gemini_async(cfg, query_text: str):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['gemini_model']}:generateContent?key={cfg['gemini_api_key']}"
    payload = {
        "generationConfig": {"responseMimeType": "application/json"},
        "contents": [
            {"parts": [{"text": gemini_instruction()}]},
            {"parts": [{"text": query_text}]}
        ]
    }
    async with httpx.AsyncClient(timeout=50) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        j = r.json()
        text = j.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "[]")
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = []
        return {"model": cfg["gemini_model"], "answer": parsed, "citations": [], "error": None}

async def ask_openai_async(cfg, query_text: str):
    if not cfg["openai_api_key"]:
        return {"model": cfg["openai_model"], "answer": [], "citations": [], "error": "API 키 미설정"}
    headers = {"Authorization": f"Bearer {cfg['openai_api_key']}"}
    payload = {
        "model": cfg["openai_model"],
        "messages": [
            {"role": "system", "content": "Return ONLY a JSON array of objects with fields: 코인명, 신호(매수|매도|관망), 근거, 목표가(number)."},
            {"role": "user", "content": query_text}
        ]
    }
    async with httpx.AsyncClient(timeout=50) as client:
        try:
            r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "[]")
            try:
                arr = json.loads(content)
                if isinstance(arr, dict):
                    arr = [arr]
            except Exception:
                arr = []
            return {"model": cfg["openai_model"], "answer": arr, "citations": [], "error": None}
        except Exception as e:
            return {"model": cfg["openai_model"], "answer": [], "citations": [], "error": str(e)}

async def ask_pplx_async(cfg, query_text: str):
    if not (cfg["pplx_api_key"] and cfg["pplx_api_key"].startswith("pplx-")):
        return {"model": cfg["pplx_model"], "answer": [], "citations": [], "error": "API 키 미설정"}
    headers = {"Authorization": f"Bearer {cfg['pplx_api_key']}"}
    payload = {"model": cfg["pplx_model"], "messages": [{"role": "user", "content": query_text}], "return_citations": True}
    async with httpx.AsyncClient(timeout=50) as client:
        try:
            r = await client.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            j = r.json()
            text = j.get("choices", [{}])[0].get("message", {}).get("content", "")
            cits = j.get("choices", [{}])[0].get("message", {}).get("citations", [])
            return {"model": cfg["pplx_model"], "answer": text, "citations": cits, "error": None}
        except Exception as e:
            return {"model": cfg["pplx_model"], "answer": "", "citations": [], "error": str(e)}

@app.post("/analyze-parallel")
def analyze_parallel():
    try:
        cfg = get_cfg()
        raw = fetch_upbit_with_retry(",".join(cfg["target_coins"]))
        compact = compact_ticker(raw)
        compact_short = json.dumps(compact[:4], ensure_ascii=False)

        body = request.get_json(silent=True) or {}
        custom_query = body.get("query") or (
            "업비트 실시간 핵심 데이터를 보고 각 코인의 단기 신호를 산출하라. "
            "반드시 JSON 배열(코인명, 신호, 근거, 목표가)로만 반환하라. 데이터: " + compact_short
        )

        tasks = []
        if cfg["gemini_api_key"]:
            tasks.append(ask_gemini_async(cfg, custom_query))
        if cfg["openai_api_key"]:
            tasks.append(ask_openai_async(cfg, custom_query))
        if cfg["pplx_api_key"]:
            tasks.append(ask_pplx_async(cfg, custom_query))

        if not tasks:
            return jsonify({"mission_status": "ERROR", "error": "모든 모델 키 미설정", "ts": utcnow()}), 500

        results = asyncio.run(asyncio.gather(*tasks))

        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "parallel_multi_model",
            "query": custom_query,
            "models_used": [r["model"] for r in results],
            "results": {r["model"]: {"answer": r["answer"], "citations": r["citations"], "error": r["error"]} for r in results},
            "ts": utcnow()
        }), 200

    except Exception as e:
        return jsonify({"mission_status": "ERROR", "error": str(e), "ts": utcnow()}), 500

# -------- 엔트리포인트 --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
