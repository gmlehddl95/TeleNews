import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 텔레그램 봇 설정
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# 네이버 검색 API 설정
NAVER_CLIENT_ID = os.getenv('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.getenv('NAVER_CLIENT_SECRET', '')

# 뉴스 검색 간격 (분)
NEWS_CHECK_INTERVAL = int(os.getenv('NEWS_CHECK_INTERVAL', 10))

# 주가 알림 시간 (24시간 형식)
STOCK_ALERT_TIMES = ['20:00', '22:00', '00:00']

# 데이터베이스 URL (PostgreSQL - 환경 변수에서 가져옴)
DATABASE_URL = os.getenv('DATABASE_URL', '')

# 로깅 설정
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()  # DEBUG, INFO, WARNING, ERROR

