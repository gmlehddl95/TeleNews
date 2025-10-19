#!/bin/bash
# 웹사이트를 GitHub Pages에 배포하는 스크립트

echo "🌐 TeleNews 웹사이트 배포 스크립트"
echo "=================================="
echo ""

# Git 초기화 확인
if [ ! -d ".git" ]; then
    echo "📁 Git 저장소 초기화..."
    git init
    echo "✅ Git 초기화 완료"
fi

# 파일 추가
echo "📝 파일 추가 중..."
git add .

# 커밋
echo "💾 커밋 생성 중..."
read -p "커밋 메시지를 입력하세요 (기본: Website update): " commit_msg
commit_msg=${commit_msg:-"Website update"}
git commit -m "$commit_msg"

# 원격 저장소 확인
if ! git remote | grep -q origin; then
    echo ""
    echo "⚠️  원격 저장소가 설정되지 않았습니다."
    echo "GitHub에서 저장소를 먼저 만들어주세요!"
    echo ""
    read -p "GitHub 저장소 URL을 입력하세요: " repo_url
    git remote add origin "$repo_url"
    echo "✅ 원격 저장소 추가됨"
fi

# 푸시
echo "🚀 GitHub에 푸시 중..."
git branch -M main
git push -u origin main

echo ""
echo "✅ 배포 완료!"
echo ""
echo "📍 GitHub Pages 설정:"
echo "   1. GitHub 저장소 → Settings → Pages"
echo "   2. Source: main branch / (root)"
echo "   3. Save"
echo ""
echo "🌐 1-2분 후 웹사이트가 활성화됩니다!"
echo ""

