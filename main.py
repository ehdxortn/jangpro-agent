from flask import Flask, jsonify
import requests
import os

# --- 이 코드가 진짜 실행되는지 확인하기 위한 버전 각인 ---
CODE_VERSION = "network_diagnostic_v2_final_check"
# ----------------------------------------------------

app = Flask(__name__)

# 테스트할 URL 정의
UPBIT_URL = "https://api.upbit.com/v1/market/all"
GOOGLE_URL = "https://www.google.com"

def diagnose_connection(name, url):
    """지정된 URL에 대한 네트워크 연결을 진단하고 결과를 반환하는 함수"""
    print(f"--- ({CODE_VERSION}) Diagnosing connection to {name} ({url}) ---")
    try:
        response = requests.get(url, timeout=15)
        print(f"[{name}] Response received. Status code: {response.status_code}")
        response.raise_for_status()
        return "SUCCESS", f"Successfully connected. Status code: {response.status_code}"
    except requests.exceptions.RequestException as e:
        error_message = f"{type(e).__name__}: {str(e)}"
        print(f"!! [{name}] FAILED: {error_message} !!")
        return "FAILED", error_message

@app.route("/")
def network_diagnostics_start():
    print(f"## JANGPRO AGENT ({CODE_VERSION}): MISSION START ##")
    
    google_status, google_message = diagnose_connection("Google.com", GOOGLE_URL)
    upbit_status, upbit_message = diagnose_connection("Upbit API", UPBIT_URL)
    
    report = {
        "agent_version": CODE_VERSION, # <--- JSON 응답에 버전 정보 '각인'
        "mission_status": "DIAGNOSTICS_COMPLETE",
        "results": [
            {"target": "Google.com (Control Test)", "status": google_status, "details": google_message},
            {"target": "Upbit API (Primary Test)", "status": upbit_status, "details": upbit_message}
        ]
    }
    
    print(f"## JANGPRO AGENT ({CODE_VERSION}): MISSION COMPLETE ##")
    return jsonify(report)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
