# TeleNews Bot 홍보 웹사이트

TeleNews Bot을 홍보하기 위한 심플하고 모던한 웹사이트입니다.

**실시간 뉴스와 주가를 텔레그램으로 알려주는 스마트 봇!**

## 특징

- **블랙 & 블루 컬러 테마**: 모던하고 세련된 다크 테마
- **반응형 디자인**: 모바일, 태블릿, 데스크톱 모두 지원
- **애니메이션 효과**: 스크롤 애니메이션, 호버 효과 등
- **단일 페이지**: HTML, CSS, JavaScript로 구성된 단순한 구조

## 파일 구조

```
website/
├── index.html      # 메인 HTML 파일
├── style.css       # 스타일시트
├── script.js       # JavaScript 인터랙션
└── README.md       # 설명서 (이 파일)
```

## 사용 방법

1. **로컬에서 실행**
   - `index.html` 파일을 웹 브라우저로 열기

2. **웹 서버에 배포**
   - GitHub Pages, Netlify, Vercel 등에 배포 가능
   - `website` 폴더 전체를 업로드

3. **봇 링크 확인**
   - `index.html`의 `https://t.me/MoEFNewsBot?start=welcome`
   - 실제 봇 사용자명으로 수정되어 있는지 확인

## 섹션 구성

### 1. Hero Section
- 메인 타이틀과 CTA 버튼
- 그라데이션 배경 효과

### 2. Features Section
- 3가지 주요 기능 소개
  - 실시간 뉴스 알림
  - 주가 모니터링 (나스닥 100 & TQQQ)
  - 방해금지 시간

### 3. How It Works Section
- 3단계 사용 방법 안내

### 4. Commands Section
- 봇 명령어 목록
- 카테고리별 분류

### 5. CTA Section
- 재방문 유도 CTA 버튼

### 6. Footer
- 저작권 정보
- 기술 스택 정보

## 커스터마이징

### 색상 변경
`style.css`의 `:root` 변수를 수정:

```css
:root {
    --bg-primary: #0a0a0a;        /* 메인 배경색 */
    --bg-secondary: #111111;       /* 보조 배경색 */
    --accent-blue: #1e90ff;        /* 메인 블루 */
    --accent-blue-light: #4da6ff;  /* 밝은 블루 */
}
```

### 내용 수정
`index.html`에서 직접 텍스트 수정

### 애니메이션 조절
`script.js`에서 애니메이션 타이밍 조절 가능

## 브라우저 지원

- Chrome (최신)
- Firefox (최신)
- Safari (최신)
- Edge (최신)
- 모바일 브라우저

## 라이선스

이 웹사이트는 TeleNews Bot 프로젝트의 일부입니다.

