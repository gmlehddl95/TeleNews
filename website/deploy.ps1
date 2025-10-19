# PowerShell 스크립트: 웹사이트를 GitHub Pages에 배포

Write-Host "🌐 TeleNews 웹사이트 배포 스크립트" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# Git 초기화 확인
if (-not (Test-Path ".git")) {
    Write-Host "📁 Git 저장소 초기화..." -ForegroundColor Yellow
    git init
    Write-Host "✅ Git 초기화 완료" -ForegroundColor Green
}

# 파일 추가
Write-Host "📝 파일 추가 중..." -ForegroundColor Yellow
git add .

# 커밋
Write-Host "💾 커밋 생성 중..." -ForegroundColor Yellow
$commitMsg = Read-Host "커밋 메시지를 입력하세요 (Enter = 'Website update')"
if ([string]::IsNullOrWhiteSpace($commitMsg)) {
    $commitMsg = "Website update"
}
git commit -m $commitMsg

# 원격 저장소 확인
$hasOrigin = git remote | Select-String "origin"
if (-not $hasOrigin) {
    Write-Host ""
    Write-Host "⚠️  원격 저장소가 설정되지 않았습니다." -ForegroundColor Yellow
    Write-Host "GitHub에서 저장소를 먼저 만들어주세요!" -ForegroundColor Yellow
    Write-Host ""
    $repoUrl = Read-Host "GitHub 저장소 URL을 입력하세요"
    git remote add origin $repoUrl
    Write-Host "✅ 원격 저장소 추가됨" -ForegroundColor Green
}

# 푸시
Write-Host "🚀 GitHub에 푸시 중..." -ForegroundColor Yellow
git branch -M main
git push -u origin main

Write-Host ""
Write-Host "✅ 배포 완료!" -ForegroundColor Green
Write-Host ""
Write-Host "📍 GitHub Pages 설정:" -ForegroundColor Cyan
Write-Host "   1. GitHub 저장소 → Settings → Pages"
Write-Host "   2. Source: main branch / (root)"
Write-Host "   3. Save"
Write-Host ""
Write-Host "🌐 1-2분 후 웹사이트가 활성화됩니다!" -ForegroundColor Green
Write-Host ""

