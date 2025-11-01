from flask import Flask, request, jsonify
import os, json, time, requests
from datetime import datetime

# -------------------- 서비스 메타 --------------------
APP_VERSION = "agent-sql-enabled-1.0"
SUPPORTED_COINS = ["KRW-BTC", "KRW-ETH", "KRW-NEAR", "KRW-POL", "KRW-WAVES", "KRW-SOL"]

# -------------------- 모델 & 키 --------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "o4-mini").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

PPLX_MODEL = os.getenv("PPLX_MODEL", "sonar-pro").strip()
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "").strip()

# -------------------- DB 연결 환경 --------------------
PG_INST = os.getenv("INSTANCE_CONNECTION_NAME", "").strip()  # <project>:us-central1:jangpro-pg
PG_USER = os.getenv("DB_USER", "").strip()                    # appuser
PG_PASS = os.getenv("DB_PASS", "").strip()
PG_DB   = os.getenv("DB_NAME", "").strip()                    # jangdb

app = Flask(__name__)

# =========================================================
# DB 커넥터 (Cloud SQL Connector + SQLAlchemy, pg8000)
# =========================================================
_engine = None
def db_enabled():
    return all([PG_INST, PG_USER, PG_PASS, PG_DB])

def get_engine():
    """엔진 1회 초기화. 실패 시 None 리턴(서비스는 계속 동작)"""
    global _engine
    if _engine is not None:
        return _engine
    if not db_enabled():
        return None
    try:
        from google.cloud.sql.connector import Connector, IPTypes
        import sqlalchemy
        from sqlalchemy.orm import declarative_base
        from sqlalchemy import Column, Integer, String, JSON, TIMESTAMP, text

        connector = Connector(ip_type=IPTypes.PUBLIC if os.getenv("USE_PRIVATE_IP") != "1" else IPTypes.PRIVATE)

        def getconn():
            return connector.connect(
                PG_INST,  # "<project>:us-central1:jangpro-pg"
                "pg8000",
                user=PG_USER,
                password=PG_PASS,
                db=PG_DB,
            )

        engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            pool_size=2,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=1800,
        )

        Base = declarative_base()

        class ModelRun(Base):
            __tablename__ = "model_runs"
            id         = Column(Integer, primary_key=True, autoincrement=True)
            model      = Column(String(64), nullable=False)
            ok         = Column(String(8), nullable=False)       # "true"/"false"
            latency_ms = Column(Integer, nullable=False)
            extra      = Column(JSON, nullable=True)
            ts         = Column(TIMESTAMP(timezone=False), server_default=text("NOW()"))

        engine.Base = Base
        engine.ModelRun = ModelRun
        Base.metadata.create_all(engine)
        _engine = engine
        return _engine
    except Exception:
        # DB 모듈 에러가 나도 서비스는 계속 동작하게 함
        return None

def log_run(model, ok, latency_ms, extra=None):
    engine = get_engine()
    if engine is None:
        return
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        s.add(engine.ModelRun(model=model, ok="true" if ok else "false",
                              latency_ms=int(latency_ms), extra=extra or {}))
        s.commit()

# =========================================================
# 유틸
# =========================================================
def nowz():
    return datetime.utcnow().isoformat() + "Z"

def call_gemini(prompt_text):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    t0 = time.time()
    r = requests.post(url, json=payload, timeout=40)
    r.raise_for_status()
    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    log_run(GEMINI_MODEL, True, int((time.time() - t0) * 1000), {"api": "gemini"})
    return txt

def call_openai(prompt_text):
    if not OPENAI_API_KEY:
        return "API 키 미설정"
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt_text}]}
    t0 = time.time()
    r = requests.post(url, headers=headers, json=payload, timeout=40)
    if r.status_code >= 400:
        log_run(OPENAI_MODEL, False, int((time.time() - t0) * 1000), {"api": "openai", "err": r.text[:400]})
        return f"오류: {r.text[:200]}"
    out = r.json().get("choices", [{}])[0].get("message", {}).get("content", "응답 없음")
    log_run(OPENAI_MODEL, True, int((time.time() - t0) * 1000), {"api": "openai"})
    return out

def call_perplexity(prompt_text):
    if not PERPLEXITY_API_KEY:
        return "API 키 미설정"
    url = "https://api.perplexity.ai/chat/completions"
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}"}
    payload = {"model": PPLX_MODEL, "messages": [{"role": "user", "content": prompt_text}]}
    t0 = time.time()
    r = requests.post(url, headers=headers, json=payload, timeout=40)
    if r.status_code >= 400:
        log_run(PPLX_MODEL, False, int((time.time() - t0) * 1000), {"api": "perplexity", "err": r.text[:400]})
        return f"오류: {r.text[:200]}"
    out = r.json().get("choices", [{}])[0].get("message", {}).get("content", "응답 없음")
    log_run(PPLX_MODEL, True, int((time.time() - t0) * 1000), {"api": "perplexity"})
    return out

# =========================================================
# 라우트
# =========================================================
@app.get("/health")
def health():
    return jsonify({"status": "OK", "version": APP_VERSION, "ts": nowz()}), 200

@app.get("/")
def index():
    engine_ok = get_engine() is not None
    return jsonify({
        "service": "장프로 AI 트레이딩 시스템",
        "status": "running",
        "db": "enabled" if engine_ok else ("disabled" if db_enabled() else "vars-missing"),
        "endpoints": {
            "health": "/health",
            "upbit": "/upbit-data",
            "single": "/analyze",
            "parallel": "/analyze-parallel",
            "runs": "/runs",
            "debug": "/debug-config"
        },
        "models": {
            "gemini": GEMINI_MODEL,
            "openai": OPENAI_MODEL,
            "perplexity": PPLX_MODEL
        },
        "supported_coins": SUPPORTED_COINS,
        "ts": nowz()
    }), 200

@app.get("/debug-config")
def debug_config():
    flags = {
        "INSTANCE_CONNECTION_NAME": bool(PG_INST),
        "DB_USER": bool(PG_USER),
        "DB_PASS": bool(PG_PASS),
        "DB_NAME": bool(PG_DB),
    }
    return jsonify({"db_env_ok": flags, "db_env_all_set": all(flags.values()), "ts": nowz()})

@app.get("/upbit-data")
def get_upbit_data():
    try:
        url = f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        raw = r.json()
        compact = [{
            "market": it.get("market"),
            "trade_price": it.get("trade_price"),
            "change_rate": round(it.get("signed_change_rate", 0) * 100, 2),
            "acc_trade_price_24h": it.get("acc_trade_price_24h"),
            "timestamp": it.get("timestamp")
        } for it in raw]
        return jsonify({"status": "SUCCESS", "data": compact, "count": len(compact), "ts": nowz()})
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500

@app.get("/analyze")
def analyze_single():
    try:
        # 1) 업비트 데이터
        upbit_url = f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}"
        up = requests.get(upbit_url, timeout=10); up.raise_for_status()
        upbit_data = up.json()

        # 2) 프롬프트 → Gemini
        prompt = (
            "너는 '장프로' 트레이딩 분석가다.\n"
            "다음 업비트 실시간 데이터를 바탕으로 각 코인에 대해\n"
            "1) 매매 신호(매수/매도/관망), 2) 핵심 근거(1줄), 3) 24h 목표가를 제시하라.\n"
            "간결하고 표준 한국어 문장으로 출력하라.\n\n"
            f"{json.dumps(upbit_data, ensure_ascii=False)}"
        )
        txt = call_gemini(prompt)
        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "single_gemini",
            "report": txt,
            "ts": nowz()
        })
    except Exception as e:
        return jsonify({"mission_status": "ERROR", "error": str(e), "ts": nowz()}), 500

@app.post("/analyze-parallel")
def analyze_parallel():
    try:
        body = request.get_json(silent=True) or {}
        custom = body.get("query", "")
        # 업비트 데이터 간단 샘플
        up = requests.get(f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}", timeout=10)
        up.raise_for_status()
        upbit_data = up.json()[:3]
        if not custom:
            custom = "업비트 실시간 일부 데이터를 참고해 단기 전략을 제시하라: " + json.dumps(upbit_data, ensure_ascii=False)

        results = {
            "gemini": call_gemini(custom)
        }
        # OpenAI
        if OPENAI_API_KEY:
            results["openai"] = call_openai(custom)
        else:
            results["openai"] = "API 키 미설정"
        # Perplexity
        if PERPLEXITY_API_KEY:
            results["perplexity"] = call_perplexity(custom)
        else:
            results["perplexity"] = "API 키 미설정"

        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "parallel_multi_model",
            "query": custom,
            "results": results,
            "ts": nowz()
        })
    except Exception as e:
        return jsonify({"mission_status": "ERROR", "error": str(e), "ts": nowz()}), 500

@app.get("/runs")
def runs():
    engine = get_engine()
    if engine is None:
        return jsonify({"status": "ERROR", "error": "DB disabled"}), 400
    from sqlalchemy.orm import Session
    from sqlalchemy import select, desc
    with Session(engine) as s:
        rows = s.execute(select(engine.ModelRun).order_by(desc(engine.ModelRun.id)).limit(30)).scalars().all()
        data = [{
            "id": r.id,
            "model": r.model,
            "ok": r.ok,
            "latency_ms": r.latency_ms,
            "extra": r.extra,
            "ts": r.ts.isoformat()
        } for r in rows]
        return jsonify({"status": "SUCCESS", "rows": data, "count": len(data)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
