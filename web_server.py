"""
Render Web Service용 간단한 웹 서버
Health check를 통과시키기 위한 목적
"""
from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <h1>🤖 TeleNews Bot</h1>
    <p>텔레그램 봇이 정상적으로 실행 중입니다!</p>
    <p>Status: ✅ Running</p>
    """

@app.route('/health')
def health():
    return {'status': 'ok', 'bot': 'running'}, 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

