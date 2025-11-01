from flask import Flask, request, jsonify
import os, json, time, requests, traceback
from datetime import datetime

APP_VERSION = "agent-sql-diagnoser-1.1"
SUPPORTED_COINS = ["KRW-BTC","KRW-ETH","KRW-NEAR","KRW-POL","KRW-WAVES","KRW-SOL"]

# ===== Models & Keys =====
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "o4-mini").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

PPLX_MODEL     = os.getenv("PPLX_MODEL", "sonar-pro").strip()
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "").strip()

# ===== DB Env =====
PG_INST = os.getenv("INSTANCE_CONNECTION_NAME", "").strip()  # <project>:us-central1:jangpro-pg
PG_USER = os.getenv("DB_USER", "").strip()
PG_PASS = os.getenv("DB_PASS", "").strip()
PG_DB   = os.getenv("DB_NAME", "").strip()

app = Flask(__name__)

# ===================== Helpers =====================
def nowz(): return datetime.utcnow().isoformat() + "Z"
def db_env_ok():
    flags = {
        "INSTANCE_CONNECTION_NAME": bool(PG_INST),
        "DB_USER": bool(PG_USER),
        "DB_PASS": bool(PG_PASS),
        "DB_NAME": bool(PG_DB),
    }
    return flags, all(flags.values())

# ===================== DB engine =====================
_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    flags, all_ok = db_env_ok()
    if not all_ok:
        return None
    try:
        # import 단계 오류를 잡아내기 위해 try 내부에서 임포트
        from google.cloud.sql.connector import Connector, IPTypes
        import sqlalchemy
        from sqlalchemy.orm import declarative_base
        from sqlalchemy import Column, Integer, String, JSON, TIMESTAMP, text

        connector = Connector(ip_type=IPTypes.PUBLIC if os.getenv("USE_PRIVATE_IP")!="1" else IPTypes.PRIVATE)

        def getconn():
            return connector.connect(PG_INST, "pg8000", user=PG_USER, password=PG_PASS, db=PG_DB)

        engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            pool_size=2, max_overflow=5, pool_pre_ping=True, pool_recycle=1800
        )

        Base = declarative_base()

        class ModelRun(Base):
            __tablename__ = "model_runs"
            id         = Column(Integer, primary_key=True, autoincrement=True)
            model      = Column(String(64), nullable=False)
            ok         = Column(String(8), nullable=False)   # "true"/"false"
            latency_ms = Column(Integer, nullable=False)
            extra      = Column(JSON, nullable=True)
            ts         = Column(TIMESTAMP(timezone=False), server_default=text("NOW()"))

        engine.Base = Base
        engine.ModelRun = ModelRun
        Base.metadata.create_all(engine)
        _engine = engine
        return _engine
    except Exception:
        # 실패 시 None (원인은 /db-probe로 노출)
        return None

def log_run(model, ok, latency_ms, extra=None):
    eng = get_engine()
    if eng is None: return
    from sqlalchemy.orm import Session
    with Session(eng) as s:
        s.add(eng.ModelRun(model=model, ok="true" if ok else "false",
                           latency_ms=int(latency_ms), extra=extra or {}))
        s.commit()

# ===================== LLM calls (간단) =====================
def call_gemini(prompt_text):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents":[{"parts":[{"text":prompt_text}]}]}
    t0=time.time()
    r=requests.post(url, json=payload, timeout=40); r.raise_for_status()
    txt=r.json()["candidates"][0]["content"]["parts"][0]["text"]
    log_run(GEMINI_MODEL, True, int((time.time()-t0)*1000), {"api":"gemini"})
    return txt

# ===================== Routes =====================
@app.get("/health")
def health(): return jsonify({"status":"OK","version":APP_VERSION,"ts":nowz()})

@app.get("/")
def index():
    engine_ok = get_engine() is not None
    return jsonify({
        "service":"장프로 AI 트레이딩 시스템",
        "status":"running",
        "db": "enabled" if engine_ok else "disabled",
        "endpoints": {
            "health":"/health","debug":"/debug-config","db_probe":"/db-probe",
            "upbit":"/upbit-data","single":"/analyze","parallel":"/analyze-parallel","runs":"/runs"
        },
        "models":{"gemini":GEMINI_MODEL,"openai":OPENAI_MODEL,"perplexity":PPLX_MODEL},
        "supported_coins": SUPPORTED_COINS,
        "ts": nowz()
    })

@app.get("/debug-config")
def debug_config():
    flags, all_ok = db_env_ok()
    return jsonify({"db_env_ok":flags,"db_env_all_set":all_ok,"ts":nowz()})

@app.get("/db-probe")
def db_probe():
    """
    실패 지점을 상세히 돌려주는 진단 엔드포인트 (UI로 바로 확인 가능)
    1) env 체크
    2) 모듈 임포트 체크
    3) 커넥터 연결 시도 (SELECT 1)
    """
    info = {"ts":nowz()}
    flags, all_ok = db_env_ok()
    info["env"] = flags
    if not all_ok:
        info["result"] = "ENV_MISSING"
        return jsonify(info), 200

    # 2) import 단계
    try:
        from google.cloud.sql.connector import Connector, IPTypes  # noqa
        import sqlalchemy  # noqa
        import pg8000      # noqa
    except Exception as e:
        info["result"] = "IMPORT_ERROR"
        info["error"] = f"{type(e).__name__}: {e}"
        info["trace"] = traceback.format_exc()[-800:]
        return jsonify(info), 200

    # 3) 실제 연결/쿼리
    try:
        from google.cloud.sql.connector import Connector, IPTypes
        import sqlalchemy
        connector = Connector(ip_type=IPTypes.PUBLIC if os.getenv("USE_PRIVATE_IP")!="1" else IPTypes.PRIVATE)
        def getconn():
            return connector.connect(PG_INST, "pg8000", user=PG_USER, password=PG_PASS, db=PG_DB)
        engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn)
        with engine.connect() as conn:
            r = conn.execute(sqlalchemy.text("SELECT 1")).scalar()
        info["result"] = "OK"
        info["select1"] = r
        return jsonify(info), 200
    except Exception as e:
        info["result"] = "CONNECT_ERROR"
        info["error"] = f"{type(e).__name__}: {e}"
        info["trace"] = traceback.format_exc()[-800:]
        return jsonify(info), 200

@app.get("/upbit-data")
def upbit_data():
    try:
        u = f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}"
        r = requests.get(u, timeout=10); r.raise_for_status()
        raw = r.json()
        compact=[{
            "market":x.get("market"),
            "trade_price":x.get("trade_price"),
            "change_rate": round(x.get("signed_change_rate",0)*100,2),
            "acc_trade_price_24h":x.get("acc_trade_price_24h"),
            "timestamp":x.get("timestamp")
        } for x in raw]
        return jsonify({"status":"SUCCESS","data":compact,"count":len(compact),"ts":nowz()})
    except Exception as e:
        return jsonify({"status":"ERROR","error":str(e)}), 500

@app.get("/analyze")
def analyze_single():
    try:
        r = requests.get(f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}", timeout=10)
        r.raise_for_status()
        prompt = (
            "너는 '장프로' 트레이딩 분석가다.\n"
            "데이터를 바탕으로 각 코인에 대해 (매수/매도/관망) 신호와 24h 목표가를 간결히 제시하라.\n\n"
            + json.dumps(r.json(), ensure_ascii=False)
        )
        txt = call_gemini(prompt)
        return jsonify({"mission_status":"SUCCESS","analysis_type":"single_gemini","report":txt,"ts":nowz()})
    except Exception as e:
        return jsonify({"mission_status":"ERROR","error":str(e),"ts":nowz()}), 500

@app.post("/analyze-parallel")
def analyze_parallel():
    try:
        body = request.get_json(silent=True) or {}
        query = body.get("query","")
        if not query:
            r = requests.get(f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}", timeout=10); r.raise_for_status()
            query = "업비트 실시간 일부 데이터 기준 단기 전략 요약: " + json.dumps(r.json()[:3], ensure_ascii=False)
        res = {"gemini": call_gemini(query)}
        return jsonify({"mission_status":"SUCCESS","analysis_type":"parallel_multi_model","query":query,"results":res,"ts":nowz()})
    except Exception as e:
        return jsonify({"mission_status":"ERROR","error":str(e),"ts":nowz()}), 500

@app.get("/runs")
def runs():
    eng = get_engine()
    if eng is None:
        return jsonify({"status":"ERROR","error":"DB disabled"}), 400
    from sqlalchemy.orm import Session
    from sqlalchemy import select, desc
    with Session(eng) as s:
        rows = s.execute(select(eng.ModelRun).order_by(desc(eng.ModelRun.id)).limit(30)).scalars().all()
        data=[{"id":r.id,"model":r.model,"ok":r.ok,"latency_ms":r.latency_ms,"extra":r.extra,"ts":r.ts.isoformat()} for r in rows]
        return jsonify({"status":"SUCCESS","rows":data,"count":len(data)})

if __name__ == "__main__":
    port=int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port, debug=False)
