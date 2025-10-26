from flask import Flask, jsonify, request
import requests, json, os, time, asyncio
from datetime import datetime
import httpx

app = Flask(__name__)

# ==================== 환경 변수 (키 하드코딩 금지) ====================
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]           # 필수 (시크릿/환경변수로 주입)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")        # 선택
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")# 선택

# ==================== 모델/설정 (환경변수로 재정의 가능) ====================
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
PPLX_MODEL   = os.getenv("PPLX_MODEL",   "sonar-pro")

TARGET_COINS = os.getenv(
    "TARGET_COINS",
    "KRW-BTC,KRW-ETH,KRW-NEAR,KRW-POL,KRW-WAVES,KRW-SOL"
).split(",")

# ==================== 공통 유틸 ====================
def fetch_upbit_with_retry(markets_csv: str, tries: int = 3, timeout: int = 10):
    """Upbit Ticker API 호출에 재시도/백오프 적용"""
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
    """LLM에 꼭 필요한 핵심만 추려 토큰/비용 절감"""
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

def gemini_prompt_instructions():
    """Gemini에 JSON만 반환하도록 강제 지시"""
    return (
        "너는 '장프로' 트레이딩 어시스턴트다.\n"
        "입력은 업비트 티커의 핵심 JSON 배열이다.\n"
        "출력은 오직 아래 스키마의 JSON 배열로만 반환하라.\n"
        "[{\"코인명\": string, \"신호\": \"매수\"|\"매도\"|\"관망\", \"근거\": string, \"목표가\": number}]\n"
        "JSON 이외의 텍스트(설명/코드블록/마크다운)는 절대 포함하지 마라."
    )

# ==================== 상태/안내 ====================
@app.get("/health")
def health_check():
    return jsonify({
        "status": "OK",
        "service": "jangpro-ai-trading",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "v6.0"
    }), 200

@app.get("/")
def index():
    return jsonify({
        "service": "장프로 AI 트레이딩 시스템",
        "status": "running",
        "endpoints": {
            "health_check": "/health",
            "single_analysis": "/analyze",
            "parallel_analysis": "/analyze-parallel",
            "upbit_data": "/upbit-data"
        },
        "models": {
            "gemini": GEMINI_MODEL,
            "openai": OPENAI_MODEL if OPENAI_API_KEY else "미사용",
            "perplexity": PPLX_MODEL if PERPLEXITY_API_KEY else "미사용"
        },
        "supported_coins": TARGET_COINS,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }), 200

# ==================== 업비트 데이터 ====================
@app.get("/upbit-data")
def get_upbit_data():
    try:
        raw = fetch_upbit_with_retry(",".join(TARGET_COINS))
