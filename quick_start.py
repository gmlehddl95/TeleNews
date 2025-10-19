"""
빠른 시작 스크립트 - .env 파일 생성을 도와줍니다
"""

import os

def create_env_file():
    """대화형으로 .env 파일 생성"""
    print("=" * 60)
    print("TeleNews Bot - 빠른 시작 설정")
    print("=" * 60)
    print()
    
    # .env 파일이 이미 있는지 확인
    if os.path.exists('.env'):
        print("⚠️ .env 파일이 이미 존재합니다.")
        response = input("덮어쓰시겠습니까? (y/n): ").strip().lower()
        if response != 'y':
            print("설정을 취소했습니다.")
            return
        print()
    
    print("텔레그램 봇 설정을 시작합니다.")
    print()
    print("1️⃣ 텔레그램 봇 토큰이 필요합니다:")
    print("   - 텔레그램에서 @BotFather 검색")
    print("   - /newbot 명령으로 새 봇 생성")
    print("   - 받은 토큰을 복사하세요")
    print()
    
    bot_token = input("봇 토큰을 입력하세요: ").strip()
    
    if not bot_token:
        print("❌ 봇 토큰이 입력되지 않았습니다.")
        return
    
    print()
    print("2️⃣ 텔레그램 Chat ID가 필요합니다:")
    print("   - 텔레그램에서 @userinfobot 검색")
    print("   - /start 명령으로 ID 확인")
    print("   - Id 번호를 복사하세요")
    print()
    
    chat_id = input("Chat ID를 입력하세요: ").strip()
    
    if not chat_id:
        print("❌ Chat ID가 입력되지 않았습니다.")
        return
    
    # .env 파일 생성
    env_content = f"""# TeleNews Bot 환경변수 설정
# 자동 생성됨

# 텔레그램 봇 토큰
TELEGRAM_BOT_TOKEN={bot_token}

# 텔레그램 채팅 ID
TELEGRAM_CHAT_ID={chat_id}
"""
    
    try:
        with open('.env', 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print()
        print("=" * 60)
        print("✅ .env 파일이 생성되었습니다!")
        print("=" * 60)
        print()
        print("다음 단계:")
        print("1. python bot.py 명령으로 봇 실행")
        print("2. 텔레그램에서 봇과 대화 시작")
        print("3. /start 명령으로 사용법 확인")
        print()
        print("💡 테스트하려면: python test_features.py")
        print()
        
    except Exception as e:
        print(f"❌ .env 파일 생성 중 오류 발생: {e}")

def check_dependencies():
    """필요한 패키지가 설치되어 있는지 확인"""
    print("\n패키지 설치 확인 중...")
    
    required_packages = [
        'telegram',
        'bs4',
        'requests',
        'yfinance',
        'apscheduler',
        'dotenv'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - 설치 필요")
            missing_packages.append(package)
    
    if missing_packages:
        print()
        print("⚠️ 누락된 패키지가 있습니다.")
        print("다음 명령으로 설치하세요:")
        print("   pip install -r requirements.txt")
        print()
        return False
    else:
        print()
        print("✅ 모든 필수 패키지가 설치되어 있습니다!")
        return True

def main():
    print()
    print("🤖 TeleNews Bot 빠른 시작")
    print()
    
    # 패키지 확인
    if not check_dependencies():
        print("\n먼저 필요한 패키지를 설치해주세요.")
        input("\n계속하려면 Enter를 누르세요...")
        return
    
    print()
    
    # .env 파일 생성
    create_env_file()
    
    input("\n완료! Enter를 눌러 종료...")

if __name__ == '__main__':
    main()


