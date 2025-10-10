from flask import Flask, jsonify
import requests
import os

# --- 이 코드가 진짜 실행되는지 확인하고, 목적을 명시하기 위한 버전 ---
CODE_VERSION = "upbit_connection_deep_dive_v3"
# ----------------------------------------------------------------

# 테스트를 위한 가장 간단한 Upbit API 주소
UPBIT_URL = "https://api.upbit.com/v1/market/all"

app = Flask(__name__)

@app.route("/")
def deep_dive_diagnostics():
    print(f"## JANGPRO AGENT ({CODE_VERSION}): MISSION START ##")
    print(f"Attempting to connect ONLY to Upbit at: {UPBIT_URL}")
    
    try:
        # 타임아웃이 원인이 아님을 확실히 하기 위해 60초로 매우 길게 설정
        response = requests.get(UPBIT_URL, timeout=60)
        
        print(">>> Connection to Upbit was successful!")
        print(f"Upbit response status code: {response.status_code}")
        
        # Upbit 서버가 4xx 또는 5xx 에러를 반환하는지 확인
        response.raise_for_status() 
        
        report = {
            "agent_version": CODE_VERSION,
            "status": "SUCCESS",
            "details": "Successfully connected to Upbit and received a valid response.",
            "upbit_status_code": response.status_code
        }
        return jsonify(report)

    except requests.exceptions.Timeout as e:
        error_message = f"Timeout Error: The request to Upbit timed out after 60 seconds. This means the server is not responding or is blocked. Error: {e}"
        print(f"!! FATAL NETWORK ERROR: {error_message} !!")
        report = {"agent_version": CODE_VERSION, "status": "FAILED", "error_type": "Timeout", "details": error_message}
        return jsonify(report), 500

    except requests.exceptions.ConnectionError as e:
        error_message = f"Connection Error: A fundamental network problem occurred (e.g., DNS failure, refused connection). Upbit might be blocking us. Error: {e}"
        print(f"!! FATAL NETWORK ERROR: {error_message} !!")
        report = {"agent_version": CODE_VERSION, "status": "FAILED", "error_type": "ConnectionError", "details": error_message}
        return jsonify(report), 500
        
    except requests.exceptions.HTTPError as e:
        error_message = f"HTTP Error: Upbit's server responded with an error code (4xx or 5xx), but we were able to connect. Error: {e}"
        print(f"!! FATAL NETWORK ERROR: {error_message} !!")
        report = {"agent_version": CODE_VERSION, "status": "FAILED", "error_type": "HTTPError", "details": error_message}
        return jsonify(report), 500

    except Exception as e:
        error_message = f"An Unexpected Error Occurred during the network request: {type(e).__name__} - {e}"
        print(f"!! FATAL UNKNOWN ERROR: {error_message} !!")
        report = {"agent_version": CODE_VERSION, "status": "FAILED", "error_type": "Unexpected", "details": error_message}
        return jsonify(report), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
