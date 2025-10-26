from flask import Flask, jsonify, request
import os, json, time, asyncio, hashlib
from datetime import datetime
import requests
import httpx

app = Flask(__name__)

# ----------------- 설정 로더 -----------------
def get_cfg():
    return {
        # API Keys
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "pplx_api_key": os.getenv("PERPLEXITY_API_KEY", "").strip(),
        # Models (최신)
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip(),
        "openai_model": os.getenv("OPENAI_MODEL", "o4-mini").strip(),
        "pplx_model": os.getenv("PPLX_MODEL", "sonar-pro").strip(),
        # Coins
        "target_coins": (os.getenv(
            "TARGET_COINS",
            "KRW-BTC,KRW-ETH,KRW-NEAR,KRW-POL,KRW-WAVES,KRW-SOL"
        ).strip()).split(","),
        # Cloud SQL(Postgres) - 옵션
        "pg_instance": os.getenv("INSTANCE_CONNECTION_NAME", "").strip(),  # proj:region:instance
        "pg_user": os.getenv("DB_USER", "").strip(),
        "pg_pass": os.getenv("DB_PASS", "").strip(),
        "pg_db": os.getenv("DB_NAME", "").strip(),
        # BigQuery - 옵션
        "bq_table": os.getenv("BQ_TABLE", "").strip(),
    }

def utcnow():
    return datetime.utcnow().isoformat() + "Z"

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

# ----------------- 간단 TTL 캐시 -----------------
class TTLCache:
    def __init__(self, ttl_sec=30, max_items=256):
        self.ttl = ttl_sec
        self.max = max_items
        self.store = {}

    def _evict(self):
        if len(self.store) <= self.max:
            return
        oldest = sorted(self.store.items(), key=lambda kv: kv[1]["ts"])[: max(1, len(self.store)-self.max)]
        for k, _ in oldest:
            self.store.pop(k, None)

    def get(self, key):
        item = self.store.get(key)
        if not item:
            return None
        if time.time() - item["ts"] > self.ttl:
            self.store.pop(key, None)
            return None
        return item["val"]

    def set(self, key, val):
        self.store[key] = {"val": val, "ts": time.time()}
        self._evict()

cache_upbit = TTLCache(ttl_sec=5, max_items=8)        # 시세 캐시
cache_parallel = TTLCache(ttl_sec=60, max_items=64)   # 멀티모델 응답 캐시

# ----------------- 공통 유틸 -----------------
def fetch_upbit_with_retry(markets_csv: str, tries: int = 3, timeout: int = 10):
    url = f"https://api.upbit.com/v1/ticker?markets={markets_csv}"
    headers = {"User-Agent": "jangpro-agent/1.0"}
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(1.0 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (i + 1))
    raise RuntimeError(f"Upbit fetch failed: {last_err}")

def compact_ticker(raw):
    out = []
    for x in raw:
        out.append({
            "market": x.get("market"),
            "price": x.get("trade_price"),
            "change": x.get("change"),  # RISE/FALL/EVEN
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

# ----------------- BigQuery 로깅 (옵션) -----------------
def log_model_run_bq(cfg, *, model: str, latency_ms: int, prompt_hash: str, ok: bool, extra: dict=None):
    if not cfg["bq_table"]:
        return
    try:
        from google.cloud import bigquery  # 늦은 임포트 (부팅 안정)
        client = bigquery.Client()
        row = {
            "model": model,
            "latency_ms": int(latency_ms),
            "ok": bool(ok),
            "prompt_hash": prompt_hash,
            "ts": datetime.utcnow().isoformat()
        }
        if extra:
            row.update(extra)
        client.insert_rows_json(cfg["bq_table"], [row])
    except Exception:
        # 로깅 실패는 서비스 영향 X
        pass

# ----------------- Cloud SQL(Postgres) 연결 (옵션) -----------------
_engine = None
def get_engine(cfg):
    """
    Cloud SQL 연결을 초기화하고, 필요한 테이블(model_runs, messages)을 자동 생성.
    4개 변수(INSTANCE_CONNECTION_NAME, DB_USER, DB_PASS, DB_NAME)가 모두 있어야 활성화.
    """
    global _engine
    if _engine is not None:
        return _engine
    needed = [cfg["pg_instance"], cfg["pg_user"], cfg["pg_pass"], cfg["pg_db"]]
    if not all(needed):
        return None
    try:
        from google.cloud.sql.connector import Connector, IPTypes
        import sqlalchemy
        from sqlalchemy.orm import declarative_base
        from sqlalchemy import Column, Integer, String, Boolean, JSON, TIMESTAMP, text

        connector = Connector(ip_type=IPTypes.PRIVATE if os.getenv("USE_PRIVATE_IP") == "1" else IPTypes.PUBLIC)

        def getconn():
            return connector.connect(
                cfg["pg_instance"],
                "pg8000",
                user=cfg["pg_user"],
                password=cfg["pg_pass"],
                db=cfg["pg_db"],
                enable_iam_auth=False,
            )

        _engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=2,
            max_overflow=5,
        )

        Base = declarative_base()

        class ModelRun(Base):
            __tablename__ = "model_runs"
            id = Column(Integer, primary_key=True, autoincrement=True)
            model = Column(String(64), nullable=False)
            latency_ms = Column(Integer, nullable=False)
            ok = Column(Boolean, nullable=False)
            prompt_hash = Column(String(32), nullable=False)
            extra = Column(JSON, nullable=True)
            ts = Column(TIMESTAMP(timezone=False), server_default=text("NOW()"))

        class Message(Base):
            __tablename__ = "messages"
            id = Column(Integer, primary_key=True, autoincrement=True)
            role = Column(String(16), nullable=False)
            content = Column(String, nullable=False)
            ts = Column(TIMESTAMP(timezone=False), server_default=text("NOW()"))

        _engine.ModelRun = ModelRun
        _engine.Message = Message

        Base.metadata.create_all(_engine)
        return _engine
    except Exception:
        return None

def log_model_run_sql(cfg, *, model: str, latency_ms: int, prompt_hash: str, ok: bool, extra: dict=None):
    engine = get_engine(cfg)
    if engine is None:
        return
    try:
        from sqlalchemy.orm import Session
        row = engine.ModelRun(
            model=model,
            latency_ms=int(latency_ms),
            ok=bool(ok),
            prompt_hash=prompt_hash,
            extra=extra or {}
        )
        with Session(engine) as s:
            s.add(row)
            s.commit()
    except Exception:
        pass  # 저장 실패는 무시

# ----------------- 상태/안내 -----------------
@app.get("/health")
def health():
    return jsonify({
        "status": "OK",
        "service": "jangpro-ai-trading",
        "version": "stable-2.5+db",
        "ts": utcnow()
    }), 200

@app.get("/")
def index():
    cfg = get_cfg()
    db_mode = "enabled" if get_engine(cfg) is not None else "disabled"
    return jsonify({
        "service": "장프로 AI 트레이딩 시스템",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "upbit": "/upbit-data",
            "single": "/analyze",
            "parallel": "/analyze-parallel",
            "runs": "/runs"
        },
        "models": {
            "gemini": cfg["gemini_model"],
            "openai": cfg["openai_model"] if cfg["openai_api_key"] else "미사용",
            "perplexity": cfg["pplx_model"] if cfg["pplx_api_key"] else "미사용"
        },
        "db": db_mode,
        "supported_coins": cfg["target_coins"],
        "bq_table": cfg["bq_table"] or "disabled",
        "ts": utcnow()
    }), 200

# ----------------- 최근 실행 로그 조회 (DB가 켜진 경우) -----------------
@app.get("/runs")
def runs():
    cfg = get_cfg()
    engine = get_engine(cfg)
    if engine is None:
        return jsonify({"status": "ERROR", "error": "DB disabled"}), 400
    try:
        from sqlalchemy.orm import Session
        with Session(engine) as s:
            rows = s.query(engine.ModelRun).order_by(engine.ModelRun.id.desc()).limit(20).all()
            out = []
            for r in rows:
                out.append({
                    "id": r.id,
                    "model": r.model,
                    "latency_ms": r.latency_ms,
                    "ok": r.ok,
                    "prompt_hash": r.prompt_hash,
                    "extra": r.extra,
                    "ts": r.ts.isoformat()
                })
            return jsonify({"status": "SUCCESS", "rows": out, "count": len(out), "ts": utcnow()}), 200
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500

# ----------------- 업비트 데이터 -----------------
@app.get("/upbit-data")
def upbit_data():
    try:
        cfg = get_cfg()
        key = "upbit:" + ",".join(cfg["target_coins"])
        cached = cache_upbit.get(key)
        if cached:
            return jsonify({"status": "SUCCESS", "cached": True, "data": cached, "count": len(cached), "ts": utcnow()}), 200

        raw = fetch_upbit_with_retry(",".join(cfg["target_coins"]))
        data = compact_ticker(raw)
        cache_upbit.set(key, data)
        return jsonify({"status": "SUCCESS", "cached": False, "data": data, "count": len(data), "ts": utcnow()}), 200
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e), "ts": utcnow()}), 500

# ----------------- 단일 분석 (Gemini 2.5 Pro) -----------------
@app.get("/analyze")
def analyze_single():
    t0 = time.time()
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

        latency = int((time.time() - t0) * 1000)
        p_hash = sha1(json.dumps(compact, ensure_ascii=False))
        log_model_run_bq(cfg, model=cfg["gemini_model"], latency_ms=latency, prompt_hash=p_hash, ok=True)
        log_model_run_sql(cfg, model=cfg["gemini_model"], latency_ms=latency, prompt_hash=p_hash, ok=True)

        return jsonify({
            "mission_status": "SUCCESS",
            "analysis_type": "single_gemini_2_5_pro",
            "coin_signals": signals,
            "latency_ms": latency,
            "ts": utcnow()
        }), 200

    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        cfg = get_cfg()
        log_model_run_bq(cfg, model=cfg["gemini_model"], latency_ms=latency, prompt_hash="error", ok=False, extra={"error": str(e)})
        log_model_run_sql(cfg, model=cfg["gemini_model"], latency_ms=latency, prompt_hash="error", ok=False, extra={"error": str(e)})
        return jsonify({"mission_status": "ERROR", "error": str(e), "latency_ms": latency, "ts": utcnow()}), 500

# ----------------- 멀티 모델 병렬 -----------------
async def ask_gemini_async(cfg, query_text: str):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['gemini_model']}:generateContent?key={cfg['gemini_api_key']}"
    payload = {
        "generationConfig": {"responseMimeType": "application/json"},
        "contents": [
            {"parts": [{"text": gemini_instruction()}]},
            {"parts": [{"text": query_text}]}
        ]
    }
    t0 = time.time()
    async with httpx.AsyncClient(timeout=50) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            j = r.json()
            text = j.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "[]")
            parsed = json.loads(text) if text else []
            return {"model": cfg["gemini_model"], "answer": parsed, "citations": [], "error": None, "latency_ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            return {"model": cfg["gemini_model"], "answer": [], "citations": [], "error": str(e), "latency_ms": int((time.time() - t0) * 1000)}

async def ask_openai_async(cfg, query_text: str):
    if not cfg["openai_api_key"]:
        return {"model": cfg["openai_model"], "answer": [], "citations": [], "error": "API 키 미설정", "latency_ms": 0}
    headers = {"Authorization": f"Bearer {cfg['openai_api_key']}"}
    payload = {
        "model": cfg["openai_model"],
        "messages": [
            {"role": "system", "content": "Return ONLY a JSON array of objects with fields: 코인명, 신호(매수|매도|관망), 근거, 목표가(number)."},
            {"role": "user", "content": query_text}
        ]
    }
    t0 = time.time()
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
            return {"model": cfg["openai_model"], "answer": arr, "citations": [], "error": None, "latency_ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            return {"model": cfg["openai_model"], "answer": [], "citations": [], "error": str(e), "latency_ms": int((time.time() - t0) * 1000)}

async def ask_pplx_async(cfg, query_text: str):
    if not (cfg["pplx_api_key"] and cfg["pplx_api_key"].startswith("pplx-")):
        return {"model": cfg["pplx_model"], "answer": [], "citations": [], "error": "API 키 미설정", "latency_ms": 0}
    headers = {"Authorization": f"Bearer {cfg['pplx_api_key']}"}
    payload = {"model": cfg["pplx_model"], "messages": [{"role": "user", "content": query_text}], "return_citations": True}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=50) as client:
        try:
            r = await client.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            j = r.json()
            text = j.get("choices", [{}])[0].get("message", {}).get("content", "")
            cits = j.get("choices", [{}])[0].get("message", {}).get("citations", [])
            return {"model": cfg["pplx_model"], "answer": text, "citations": cits, "error": None, "latency_ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            return {"model": cfg["pplx_model"], "answer": "", "citations": [], "error": str(e), "latency_ms": int((time.time() - t0) * 1000)}

@app.post("/analyze-parallel")
def analyze_parallel():
    try:
        cfg = get_cfg()

        # Upbit 데이터 (캐시 사용)
        key_upbit = "upbit:" + ",".join(cfg["target_coins"])
        data_cached = cache_upbit.get(key_upbit)
        if data_cached is None:
            raw = fetch_upbit_with_retry(",".join(cfg["target_coins"]))
            data_cached = compact_ticker(raw)
            cache_upbit.set(key_upbit, data_cached)

        compact_short = json.dumps(data_cached[:4], ensure_ascii=False)
        body = request.get_json(silent=True) or {}
        custom_query = body.get("query") or (
            "업비트 실시간 핵심 데이터를 보고 각 코인의 단기 신호를 산출하라. "
            "반드시 JSON 배열(코인명, 신호, 근거, 목표가)로만 반환하라. 데이터: " + compact_short
        )

        # 중복 캐시 (모델 비용 절감)
        cache_key = f"parallel:{sha1(custom_query)}:{cfg['gemini_model']}:{cfg['openai_model']}:{cfg['pplx_model']}"
        cached = cache_parallel.get(cache_key)
        if cached:
            return jsonify(cached), 200

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

        resp = {
            "mission_status": "SUCCESS",
            "analysis_type": "parallel_multi_model",
            "query": custom_query,
            "models_used": [r["model"] for r in results],
            "results": {
                r["model"]: {
                    "answer": r["answer"],
                    "citations": r["citations"],
                    "error": r["error"],
                    "latency_ms": r["latency_ms"]
                } for r in results
            },
            "ts": utcnow()
        }
        cache_parallel.set(cache_key, resp)

        # (옵션) 실행 로그 저장
        p_hash = sha1(custom_query)
        for r in results:
            ok = (r["error"] is None)
            log_model_run_bq(cfg, model=r["model"], latency_ms=r["latency_ms"], prompt_hash=p_hash, ok=ok)
            log_model_run_sql(cfg, model=r["model"], latency_ms=r["latency_ms"], prompt_hash=p_hash, ok=ok)

        return jsonify(resp), 200

    except Exception as e:
        return jsonify({"mission_status": "ERROR", "error": str(e), "ts": utcnow()}), 500

# ----------------- 엔트리포인트 -----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
