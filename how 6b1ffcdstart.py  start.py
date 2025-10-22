"""
봇과 웹 서버를 동시에 실행하는 스크립트
"""
import threading
import subprocess
import time

def run_bot():
    """텔레그램 봇 실행"""
    print("🤖 텔레그램 봇 시작 중...")
    subprocess.run(['python', 'bot.py'])

def run_web_server():
    """웹 서버 실행"""
    print("🌐 웹 서버 시작 중...")
    time.sleep(2)  # 봇이 먼저 시작되도록 2초 대기
    subprocess.run(['python', 'web_server.py'])

if __name__ == '__main__':
    # 두 개의 스레드로 동시 실행
    bot_thread = threading.Thread(target=run_bot)
    web_thread = threading.Thread(target=run_web_server)
    
    bot_thread.start()
    web_thread.start()
    
    # 두 스레드가 종료될 때까지 대기
    bot_thread.join()
    web_thread.join()

