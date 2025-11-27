# TeleNews Bot

실시간 뉴스와 주가를 텔레그램으로 알려주는 봇입니다.

## 주요 기능

### 📰 실시간 뉴스 알림
- 키워드 기반 뉴스 자동 알림 (5분마다)
- 네이버 뉴스 API 활용
- 중복 뉴스 자동 필터링
- 유사 뉴스 제거 (60% 이상 유사도)

### 📊 주가 모니터링
- 나스닥 100 (^NDX) / TQQQ 실시간 추적
- 전고점 대비 하락률 알림 (5%부터 1%p 단위로 최초 1회)
- 매일 오전 10시 자동 체크

### 🔕 방해금지 시간
- 설정한 시간대 알림 중단
- 시작/종료 시간 개별 선택 (1시간 간격)
- 방해금지 해제 시 대기 중인 주가 알림 자동 전송
- 수동 뉴스 확인은 항상 작동

### 🎯 직관적인 UI
- 키보드 버튼 메뉴
- 인라인 버튼으로 간편 조작
- 대화형 키워드 입력

## 설치 방법

### 1. 저장소 클론
```bash
git clone https://github.com/your-username/TeleNews.git
cd TeleNews
```

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정
`.env` 파일을 생성하고 다음 내용을 입력:

```env
# 텔레그램 설정
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# 네이버 API 설정
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret
```

### 4. 봇 실행
```bash
python bot.py
```

## 명령어

- `/start` - 봇 시작
- `/add` - 키워드 추가
- `/list` - 키워드 목록 (삭제/추가)
- `/news` - 즉시 뉴스 확인
- `/stock` - 주가 정보
- `/setquiet` - 방해금지 시간 설정

## 기술 스택

- **Python 3.11**
- **python-telegram-bot 22.5** - 텔레그램 봇 API
- **BeautifulSoup4** - 웹 크롤링
- **yfinance 0.2.66** - 주가 정보
- **APScheduler** - 스케줄링
- **SQLite** - 데이터베이스

## API 키 발급

### 텔레그램 봇 토큰
1. [@BotFather](https://t.me/BotFather) 대화 시작
2. `/newbot` 입력
3. 봇 이름과 사용자명 설정
4. 받은 토큰을 `.env` 파일에 입력

### 네이버 API
1. [네이버 개발자 센터](https://developers.naver.com) 접속
2. 애플리케이션 등록
3. 검색 API 추가
4. Client ID와 Secret을 `.env` 파일에 입력

## 배포

### Render.com (무료)
1. [Render.com](https://render.com) 가입
2. New → Web Service
3. GitHub 저장소 연결
4. Environment Variables에 `.env` 내용 입력
5. Deploy!

### 웹사이트 (GitHub Pages)
`website/` 폴더를 별도 저장소로 푸시하거나 GitHub Pages 설정

## 라이선스

MIT License

## 개발자

- 개발: TeleNews Team
- 문의: gmlehddl95@gmail.com

## 기여

Pull Request 환영합니다!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request
