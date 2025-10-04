from flask import Flask, jsonify
import requests

app = Flask(__name__)

@app.route("/")
def network_test():
    try:
        print("Attempting to connect to Google.com...")
        response = requests.get("https://www.google.com", timeout=10)
        response.raise_for_status() # 에러가 있으면 여기서 멈춤
        print("Connection to Google.com successful.")
        return jsonify({"status": "SUCCESS", "message": "Successfully connected to the public internet (google.com)."}), 200
    except Exception as e:
        print(f"!! NETWORK TEST FAILED: {str(e)} !!")
        return jsonify({"status": "ERROR", "message": f"Failed to connect to the public internet: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
