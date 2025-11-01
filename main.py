from flask import Flask, request, jsonify
import os, json, time, requests, traceback, re
from datetime import datetime

APP_VERSION = "jangpro-agent v1.2-stable"
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

# ===== Flask =====
app = Flask(__name__)

def nowz(): return datetime.utcnow().isoformat() + "Z"

# ===== Env check =====
def db_env_ok():
    flags = {
        "INSTANCE_CONNECTION_NAME": bool(PG_INST),
        "DB_USER": bool(PG_USER),
        "DB_PASS": bool(PG_PASS),
        "DB_NAME": bool(PG_DB),
    }
    return flags, all(flags.values())

# ===== DB: Connector + SQLAlchemy =====
_engine = None

def get_engine():
    """Lazily create engine & tables; return None if env missing or import/conn fails."""
    global _engine
    if _engine is not None:
        return _engine
    flags, all_ok = db_env_ok()
    if not all_ok:
        return None
    try:
        from google.cloud.sql.connector import Connector, IPTypes
        import sqlalchemy
        from sqlalchemy.orm import declarative_base
        from sqlalchemy import Column, Integer, String, JSON, TIMESTAMP, Text, text

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
            model      = Column(String(64), nullable=False)          # gemini-2.5-pro / o4-mini / sonar-pro
            ok         = Column(String(8), nullable=False)           # "true"/"false"
            latency_ms = Column(Integer, nullable=False)
            extra      = Column(JSON, nullable=True)
            ts         = Column(TIMESTAMP(timezone=False), server_default=text("NOW()"))

        class CoinSignal(Base):
            __tablename__ = "coin_signals"
            id         = Column(Integer, primary_key=True, autoincrement=True)
            model      = Column(String(64), nullable=False)
            query      = Column(Text, nullable=True)
            raw_text   = Column(Text, nullable=True)
            parsed     = Column(JSON, nullable=True)                 # [{"coin":"KRW-BTC","signal":"매수","reason":"..."}]
            ts         = Column(TIMESTAMP(timezone=False), server_default=text("NOW()"))

        engine.Base = Base
        engine.ModelRun = ModelRun
        engine.CoinSignal = CoinSignal

        Base.metadata.create_all(engine)
        _engine = engine
        return _engine
    except Exception:
        return None

def log_run(model, ok, latency_ms, extra=None):
    eng = get_engine()
    if eng is None: return
    from sqlalchemy.orm import Session
    with Session(eng) as s:
        s.add(eng.ModelRun(model=model, ok="true" if ok else "false",
                           latency_ms=int(latency_ms), extra=extra or {}))
        s.commit()

def save_coin_signals(model, query, raw_text, parsed):
    eng = get_engine()
    if eng is None: return
    from sqlalchemy.orm import Session
    with Session(eng) as s:
        s.add(eng.CoinSignal(model=model, query=query, raw_text=raw_text, parsed=parsed))
        s.commit()

# ===== Utilities =====
def parse_signals_text(result_text):
    """
    '코인명: 매수 - 근거' 라인을 JSON 배열로 파싱.
    실패하면 [] 반환.
    """
    out = []
    if not result_text: return out
    for line in result_text.strip().splitlines():
        m = re.match(r"\s*([A-Za-z0-9\-\_\/]+)\s*:\s*(매수|매도|관망)\s*-\s*(.+)", line)
        if m:
            out.append({"coin": m.group(1).strip(), "signal": m.group(2).strip(), "reason": m.group(3).strip()})
    return out

# ===== LLM wrappers =====
def call_gemini(prompt_text):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents":[{"parts":[{"text":prompt_text}]}]}
    t0=time.time()
    r=requests.post(url, json=payload, timeout=45); r.raise_for_status()
    txt=r.json()["candidates"][0]["content"]["parts"][0]["text"]
    log_run(GEMINI_MODEL, True, int((time.time()-t0)*1000), {"api":"gemini"})
    return txt

def call_openai(prompt_text):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    url="https://api.openai.com/v1/chat/completions"
    headers={"Authorization":f"Bearer {OPENAI_API_KEY}"}
    body={
        "model": OPENAI_MODEL,
        "messages":[{"role":"user","content":prompt_text}],
        "temperature":0.2
    }
    t0=time.time()
    r=requests.post(url, headers=headers, json=body, timeout=45); r.raise_for_status()
    txt=r.json()["choices"][0]["message"]["content"]
    log_run(OPENAI_MODEL, True, int((time.time()-t0)*1000), {"api":"openai"})
    return txt

def call_perplexity(prompt_text):
    if not PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY missing")
    url="https://api.perplexity.ai/chat/completions"
    headers={"Authorization":f"Bearer {PERPLEXITY_API_KEY}"}
    body={
        "model": PPLX_MODEL,
        "messages":[{"role":"user","content":prompt_text}],
        "temperature":0.2
    }
    t0=time.time()
    r=requests.post(url, headers=headers, json=body, timeout=45); r.raise_for_status()
    txt=r.json()["choices"][0]["message"]["content"]
    log_run(PPLX_MODEL, True, int((time.time()-t0)*1000), {"api":"perplexity"})
    return txt

# ===== Routes =====
@app.get("/health")
def health(): return jsonify({"status":"OK","version":APP_VERSION,"ts":nowz()})

@app.get("/")
def index():
    engine_ok = get_engine() is not None
    return jsonify({
        "service":"장프로 AI 트레이딩 시스템",
        "status":"running",
        "db": "enabled" if engine_ok else "disabled",
        "endpoints":{
            "health":"/health",
            "debug":"/debug-config",
            "db_probe":"/db-probe",
            "migrate":"/migrate",
            "upbit":"/upbit-data",
            "single":"/analyze",
            "parallel":"/analyze-parallel",
            "runs":"/runs",
            "signals":"/signals"
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
    info={"ts":nowz()}
    flags, all_ok = db_env_ok()
    info["env"]=flags
    if not all_ok:
        info["result"]="ENV_MISSING"; return jsonify(info),200
    try:
        from google.cloud.sql.connector import Connector, IPTypes  # noqa
        import sqlalchemy, pg8000  # noqa
    except Exception as e:
        info["result"]="IMPORT_ERROR"; info["error"]=f"{type(e).__name__}: {e}"
        info["trace"]=traceback.format_exc()[-800:]; return jsonify(info),200
    try:
        from google.cloud.sql.connector import Connector, IPTypes
        import sqlalchemy
        connector=Connector(ip_type=IPTypes.PUBLIC if os.getenv("USE_PRIVATE_IP")!="1" else IPTypes.PRIVATE)
        def getconn(): return connector.connect(PG_INST,"pg8000",user=PG_USER,password=PG_PASS,db=PG_DB)
        engine=sqlalchemy.create_engine("postgresql+pg8000://",creator=getconn)
        with engine.connect() as conn:
            r=conn.execute(sqlalchemy.text("SELECT 1")).scalar()
        info["result"]="OK"; info["select1"]=r; return jsonify(info),200
    except Exception as e:
        info["result"]="CONNECT_ERROR"; info["error"]=f"{type(e).__name__}: {e}"
        info["trace"]=traceback.format_exc()[-800:]; return jsonify(info),200

@app.post("/migrate")
def migrate():
    eng=get_engine()
    if eng is None: return jsonify({"status":"ERROR","error":"DB disabled"}),400
    eng.Base.metadata.create_all(eng)
    return jsonify({"status":"SUCCESS","message":"migrated","ts":nowz()})

@app.get("/upbit-data")
def upbit_data():
    try:
        u=f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}"
        r=requests.get(u, timeout=10); r.raise_for_status()
        raw=r.json()
        compact=[{
            "market":x.get("market"),
            "trade_price":x.get("trade_price"),
            "change_rate": round(x.get("signed_change_rate",0)*100,2),
            "acc_trade_price_24h":x.get("acc_trade_price_24h"),
            "timestamp":x.get("timestamp")
        } for x in raw]
        return jsonify({"status":"SUCCESS","data":compact,"count":len(compact),"ts":nowz()})
    except Exception as e:
        return jsonify({"status":"ERROR","error":str(e)}),500

@app.get("/analyze")
def analyze_single():
    """
    Upbit 데이터 → Gemini 분석 → 결과 저장(coin_signals/model_runs)
    """
    try:
        upbit_url=f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}"
        upbit_res=requests.get(upbit_url, timeout=10); upbit_res.raise_for_status()
        up_data=upbit_res.json()

        prompt=(
            "너는 '장프로' 트레이딩 분석가다.\n"
            "다음 업비트 실시간 데이터로 각 코인에 대해 '코인명: 매수/매도/관망 - 근거' 한 줄씩만 작성하라.\n"
            "가능하면 대상 코인 표기를 그대로 사용(KRW-BTC 등).\n\n"
            + json.dumps(up_data, ensure_ascii=False)
        )
        txt=call_gemini(prompt)
        parsed=parse_signals_text(txt)
        save_coin_signals(GEMINI_MODEL, "auto_upbit_single", txt, parsed)

        return jsonify({"mission_status":"SUCCESS","report":txt,"parsed":parsed,"ts":nowz()})
    except Exception as e:
        return jsonify({"mission_status":"ERROR","error":str(e),"ts":nowz()}),500

@app.post("/analyze-parallel")
def analyze_parallel():
    """
    custom_query가 오면 그걸 세 모델에 병렬(순차 호출) 분석. 저장은 하지 않음.
    """
    try:
        body=request.get_json(silent=True) or {}
        query=body.get("query","")
        if not query:
            upbit_url=f"https://api.upbit.com/v1/ticker?markets={','.join(SUPPORTED_COINS)}"
            upbit_res=requests.get(upbit_url, timeout=10); upbit_res.raise_for_status()
            query="업비트 실시간 일부 데이터 기준 단기 전략 요약: "+json.dumps(upbit_res.json()[:3], ensure_ascii=False)

        results={}
        errors={}

        for name, func in {
            "gemini": lambda q: call_gemini(q),
            "openai": lambda q: call_openai(q) if OPENAI_API_KEY else "API 키 미설정",
            "perplexity": lambda q: call_perplexity(q) if PERPLEXITY_API_KEY else "API 키 미설정"
        }.items():
            try:
                results[name]=func(query)
            except Exception as e:
                errors[name]=str(e)

        return jsonify({
            "mission_status":"SUCCESS",
            "analysis_type":"parallel_multi_model",
            "query":query,
            "results":results,
            "errors":errors,
            "ts":nowz()
        })
    except Exception as e:
        return jsonify({"mission_status":"ERROR","error":str(e),"ts":nowz()}),500

@app.get("/runs")
def runs():
    eng=get_engine()
    if eng is None: return jsonify({"status":"ERROR","error":"DB disabled"}),400
    from sqlalchemy.orm import Session
    from sqlalchemy import select, desc
    with Session(eng) as s:
        rows=s.execute(select(eng.ModelRun).order_by(desc(eng.ModelRun.id)).limit(50)).scalars().all()
        data=[{"id":r.id,"model":r.model,"ok":r.ok,"latency_ms":r.latency_ms,"extra":r.extra,"ts":r.ts.isoformat()} for r in rows]
        return jsonify({"status":"SUCCESS","rows":data,"count":len(data)})

@app.get("/signals")
def signals():
    eng=get_engine()
    if eng is None: return jsonify({"status":"ERROR","error":"DB disabled"}),400
    from sqlalchemy.orm import Session
    from sqlalchemy import select, desc
    with Session(eng) as s:
        rows=s.execute(select(eng.CoinSignal).order_by(desc(eng.CoinSignal.id)).limit(50)).scalars().all()
        data=[{
            "id":r.id, "model":r.model, "query":r.query, "raw_text":r.raw_text,
            "parsed":r.parsed, "ts":r.ts.isoformat()
        } for r in rows]
        return jsonify({"status":"SUCCESS","rows":data,"count":len(data)})

if __name__ == "__main__":
    port=int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port, debug=False)
