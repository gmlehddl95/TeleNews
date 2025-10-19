# 🚀 TeleNews Bot 무료 배포 가이드

이 가이드는 **TeleNews Bot**과 **홍보 웹사이트**를 완전 무료로 호스팅하는 방법을 설명합니다.

## 📋 목차
1. [배포 준비](#1-배포-준비)
2. [봇 호스팅 (Render.com)](#2-봇-호스팅-rendercom)
3. [웹사이트 호스팅 (GitHub Pages)](#3-웹사이트-호스팅-github-pages)
4. [업데이트 방법](#4-업데이트-방법)

---

## 1. 배포 준비

### ✅ 필요한 것들

1. **GitHub 계정** (무료)
2. **Render.com 계정** (무료)
3. **텔레그램 봇 토큰**
4. **네이버 API 키**

### 📝 배포 전 체크리스트

- [x] `.gitignore` 파일 있음 (`.env`, `*.db` 제외됨)
- [x] `Procfile` 있음
- [x] `runtime.txt` 있음
- [x] `requirements.txt` 있음
- [x] 로컬에서 봇 정상 작동 확인

---

## 2. 봇 호스팅 (Render.com)

### ✅ 왜 Render.com?

- ✨ **영구 무료** (트래픽 제한 있지만 충분함)
- 🔄 **자동 재시작** (크래시 시)
- 🔐 **환경 변수 관리 편리**
- 📦 **GitHub 자동 배포**

### 📝 단계별 가이드

#### 2-1. GitHub 저장소 생성

1. **[GitHub](https://github.com)** 접속 → **New repository**

2. **저장소 설정**
   ```
   Repository name: TeleNews
   Description: 실시간 뉴스와 주가 알림 텔레그램 봇
   Public / Private: Public (무료) 또는 Private
   ✅ Add a README file (체크 안 함)
   ```

3. **Create repository** 클릭

#### 2-2. 코드 업로드

**로컬 PC (PowerShell)에서:**

```powershell
# 현재 위치: C:\Users\gmleh\Desktop\TeleNews

# Git 초기화 (처음만)
git init

# 원격 저장소 연결 (GitHub에서 받은 주소)
git remote add origin https://github.com/your-username/TeleNews.git

# 파일 추가 및 커밋
git add .
git commit -m "Initial commit - TeleNews Bot v1.0"

# 메인 브랜치로 푸시
git branch -M main
git push -u origin main
```

**✅ 확인:** GitHub 저장소 페이지에서 파일들이 업로드되었는지 확인

**⚠️ 중요:** `.env` 파일은 자동으로 제외됩니다 (`.gitignore`에 포함됨)

#### 2-3. Render.com 배포

1. **[Render.com](https://render.com)** 접속 → **Get Started for Free**

2. **GitHub 계정으로 로그인**

3. **Dashboard** → **New +** → **Web Service** 클릭

4. **GitHub 저장소 연결**
   - "Connect account" 클릭
   - TeleNews 저장소 선택
   - "Connect" 클릭

5. **서비스 설정**
   ```
   Name: telenews-bot
   Region: Singapore (한국과 가장 가까움)
   Branch: main
   Runtime: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: python bot.py
   Instance Type: Free
   ```

6. **환경 변수 설정** (매우 중요! 🔑)
   
   **Advanced** 섹션 펼치기 → **Add Environment Variable** 클릭
   
   다음 변수들을 하나씩 추가:
   
   ```
   TELEGRAM_BOT_TOKEN = 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz123456789
   TELEGRAM_CHAT_ID = 1234567890
   NAVER_CLIENT_ID = abcdefghijk1234567890
   NAVER_CLIENT_SECRET = ABCdef1234
   ```

7. **Create Web Service** 클릭!

8. **배포 대기** (5-10분 소요)
   
   **Logs** 탭에서 진행 상황 확인:
   ```
   ✅ 봇이 시작되었습니다!
   📱 텔레그램에서 봇과 대화를 시작하세요!
   ```
   
   이 메시지가 나오면 성공! 🎉

#### 2-4. 무료 티어 제한사항 및 해결책

**제한사항:**
- ✅ 750시간/월 무료 (31일 = 744시간이므로 충분!)
- ⚠️ 15분간 요청 없으면 슬립 모드 진입
- 💤 슬립 모드에서는 알림이 지연될 수 있음

**해결책 (선택사항):**

봇이 2시간마다 주가를 체크하므로 자동으로 깨어나지만, 더 확실하게 하려면:

`bot.py`의 `setup_scheduler` 함수에 추가:

```python
# Keep-alive 스케줄러 (Render 슬립 방지)
self.scheduler.add_job(
    self.keep_alive_ping,
    'interval',
    minutes=10,
    id='keep_alive'
)
logger.info("Keep-alive 스케줄러 등록: 10분 간격")
```

그리고 클래스에 메서드 추가:

```python
async def keep_alive_ping(self):
    """서버를 깨어있게 유지 (Render 슬립 방지)"""
    logger.info("🏓 Keep-alive ping")
```

---

## 3. 웹사이트 호스팅 (GitHub Pages)

### ✅ 왜 GitHub Pages?

- 💰 **완전 무료**
- ⚡ **빠른 속도** (CDN)
- 🔒 **HTTPS 자동 적용**
- 🌐 **커스텀 도메인 지원**

### 📝 단계별 가이드

#### 3-1. GitHub 저장소 생성

1. **GitHub에서 새 저장소 생성**
   ```
   Repository name: telenews-website
   Description: TeleNews Bot 홍보 웹사이트
   Public: ✅ (필수! GitHub Pages는 Public만 무료)
   ```

2. **Create repository** 클릭

#### 3-2. 웹사이트 업로드

**PowerShell에서:**

```powershell
# website 폴더로 이동
cd C:\Users\gmleh\Desktop\TeleNews\website

# Git 초기화
git init

# 파일 추가
git add .
git commit -m "Initial commit - TeleNews Website"

# 원격 저장소 연결
git remote add origin https://github.com/your-username/telenews-website.git

# 푸시
git branch -M main
git push -u origin main
```

#### 3-3. GitHub Pages 활성화

1. **GitHub 저장소 페이지**에서 **Settings** 클릭

2. **왼쪽 메뉴**에서 **"Pages"** 클릭

3. **Source 설정**
   ```
   Branch: main
   Folder: / (root)
   ```

4. **Save** 클릭

5. **대기 (1-2분)**
   
   페이지 새로고침하면 URL이 표시됨:
   ```
   ✅ Your site is live at https://your-username.github.io/telenews-website/
   ```

6. **웹사이트 접속 테스트!** 🎉

#### 3-4. 커스텀 도메인 (선택사항)

**무료 도메인:**
- [Freenom](https://www.freenom.com) - `.tk`, `.ml`, `.ga` 등
- [InfinityFree](https://www.infinityfree.com) - `.rf.gd`, `.wuaze.com` 등

**설정 방법:**
1. 도메인 발급 후 DNS 설정
2. GitHub Pages → Custom domain 입력
3. CNAME 레코드 추가

---

## 4. 업데이트 방법

### 🔄 봇 업데이트 (초간단!)

**로컬에서 코드 수정 후:**

```powershell
# TeleNews 폴더에서
git add .
git commit -m "주가 알림 로직 개선"
git push
```

→ Render.com이 **자동으로 감지**하고 **재배포**합니다! 🚀

**확인:** Render.com → 프로젝트 → Logs에서 진행 상황 확인

### 🌐 웹사이트 업데이트

**website 폴더에서 파일 수정 후:**

```powershell
cd C:\Users\gmleh\Desktop\TeleNews\website

git add .
git commit -m "디자인 개선"
git push
```

→ GitHub Pages가 **1-2분 내** 자동 업데이트! 

**확인:** GitHub → Actions 탭에서 배포 상태 확인

---

## 💰 비용 비교

| 서비스 | 봇 호스팅 | 웹사이트 | 총 비용 | 제한사항 |
|--------|-----------|----------|---------|---------|
| **Render + GitHub Pages** | 무료 | 무료 | **$0** ⭐ | 15분 슬립 |
| AWS Lightsail | $3.5/월 | 무료 | $3.5/월 | 없음 |
| Heroku | $7/월 | 무료 | $7/월 | 없음 |
| Oracle Cloud | 무료 | 무료 | $0 | 복잡함 |

**추천:** Render + GitHub Pages (완전 무료!)

---

## 🎯 빠른 시작 (한눈에 보기)

### 1️⃣ GitHub 저장소 2개 만들기
- `TeleNews` (봇)
- `telenews-website` (웹사이트)

### 2️⃣ 코드 업로드
```powershell
# 봇
cd C:\Users\gmleh\Desktop\TeleNews
git init
git remote add origin https://github.com/your-username/TeleNews.git
git add .
git commit -m "Initial commit"
git push -u origin main

# 웹사이트
cd C:\Users\gmleh\Desktop\TeleNews\website
git init
git remote add origin https://github.com/your-username/telenews-website.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

### 3️⃣ Render.com 설정
1. GitHub 연동
2. 환경 변수 입력
3. Deploy!

### 4️⃣ GitHub Pages 설정
1. Settings → Pages
2. Branch: main, Folder: / (root)
3. Save!

---

## 🔧 문제 해결

### 봇이 시작되지 않을 때

**Render Logs 확인:**
```
Error: TELEGRAM_BOT_TOKEN not found
```
→ 환경 변수를 제대로 입력했는지 확인

### 웹사이트가 표시되지 않을 때

1. GitHub → Settings → Pages에서 상태 확인
2. Actions 탭에서 배포 성공 여부 확인
3. 1-2분 기다려보기

### 봇이 슬립 모드에 빠질 때

- 2시간마다 주가 체크하므로 자동으로 깨어남
- 또는 위의 Keep-alive 코드 추가

---

## 📊 봇 현재 기능 (v1.0)

### 뉴스 알림
- 5분마다 키워드 뉴스 자동 체크
- 중복 뉴스 필터링
- 유사 뉴스 제거 (60% 이상 유사도)

### 주가 알림
- 나스닥 100 (^NDX) 전고점 대비 하락률 모니터링
- 5%부터 1%p 단위로 하락 시 최초 1회 알림 (예: 5%, 6%, 7%, ...)
- 2시간마다 자동 체크
- TQQQ 추가 하락 시나리오 제공

### 방해금지 시간
- 시작/종료 시간 개별 선택 (1시간 간격)
- 설정 시간 동안 자동 알림 중단
- 방해금지 해제 시 대기 중인 주가 알림 자동 전송
- 수동 뉴스 확인은 항상 작동

---

## 🌐 배포 후 접속 주소

### 봇
- Render.com 대시보드에서 URL 확인 가능
- 예: `https://telenews-bot.onrender.com`
- (이 주소는 사용자가 직접 접속할 일은 없음)

### 웹사이트
- GitHub Pages에서 자동 생성
- 예: `https://your-username.github.io/telenews-website/`
- 이 주소를 홍보용으로 사용!

---

## 💡 추가 팁

### 1. Render.com 무료 티어 최적화

**현재 설정:**
- 뉴스 체크: 5분 간격
- 주가 체크: 2시간 간격
- 총 API 호출: 약 300회/일

→ 무료 티어로 충분합니다! ✅

### 2. 업데이트 자동화

**Git 푸시만 하면:**
1. Render.com이 자동으로 감지
2. 새 코드로 재배포
3. 봇 자동 재시작

**다운타임:** 약 1-2분 (재배포 중)

### 3. 모니터링

**Render.com Logs:**
- 실시간 로그 확인 가능
- 에러 발생 시 이메일 알림 (설정 가능)

**봇 상태 확인:**
- 텔레그램에서 `/start` 명령어 보내기
- 응답 있으면 정상 작동 중!

---

## 📞 지원

문제가 발생하면:
1. Render.com Logs 확인
2. GitHub Issues에 문의
3. 이메일: gmlehddl95@gmail.com

---

## 🎉 완료!

이제 TeleNews Bot이 24/7 무료로 돌아갑니다!

**다음 단계:**
1. 텔레그램에서 봇 테스트
2. 웹사이트 주소 공유
3. 친구들에게 소개하기! 😊
