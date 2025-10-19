import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import time
import re
from datetime import datetime, timedelta
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
from difflib import SequenceMatcher

class NaverNewsCrawler:
    def __init__(self):
        self.client_id = NAVER_CLIENT_ID
        self.client_secret = NAVER_CLIENT_SECRET
        self.api_url = "https://openapi.naver.com/v1/search/news.json"
    
    def _fetch_full_title(self, url):
        """뉴스 링크에서 전체 제목 가져오기"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 네이버 뉴스인 경우
            if 'news.naver.com' in url:
                # 네이버 뉴스 제목 선택자들
                title_tag = (
                    soup.find('h2', {'id': 'title_area'}) or  # 새 레이아웃
                    soup.find('h3', {'id': 'articleTitle'}) or  # 구 레이아웃
                    soup.find('h2', class_='media_end_head_headline') or
                    soup.find('meta', {'property': 'og:title'})
                )
                
                if title_tag:
                    if title_tag.name == 'meta':
                        return title_tag.get('content', '').strip()
                    else:
                        return title_tag.get_text().strip()
            
            # 일반 뉴스 사이트인 경우 og:title 메타 태그 사용
            og_title = soup.find('meta', {'property': 'og:title'})
            if og_title:
                return og_title.get('content', '').strip()
            
            # 백업: title 태그
            title_tag = soup.find('title')
            if title_tag:
                full_title = title_tag.get_text().strip()
                # " - 언론사명" 형식에서 언론사명 제거
                if ' - ' in full_title:
                    full_title = full_title.split(' - ')[0].strip()
                if ' | ' in full_title:
                    full_title = full_title.split(' | ')[0].strip()
                return full_title
            
            return None
            
        except Exception as e:
            # 크롤링 실패 시 조용히 None 반환 (원본 제목 유지)
            return None
    
    def calculate_similarity(self, title1, title2):
        """두 제목의 유사도 계산 (0.0 ~ 1.0)"""
        # HTML 태그 제거
        title1_clean = re.sub(r'<[^>]+>', '', title1)
        title2_clean = re.sub(r'<[^>]+>', '', title2)
        
        # 특수문자 및 공백 정규화
        title1_norm = re.sub(r'[^\w\s가-힣]', '', title1_clean).strip().lower()
        title2_norm = re.sub(r'[^\w\s가-힣]', '', title2_clean).strip().lower()
        
        # SequenceMatcher로 유사도 계산
        return SequenceMatcher(None, title1_norm, title2_norm).ratio()
    
    def filter_similar_news(self, news_list, similarity_threshold=0.75):
        """유사한 뉴스를 필터링하여 대표 뉴스만 반환"""
        if not news_list:
            return []
        
        filtered_news = []
        
        for news in news_list:
            is_duplicate = False
            
            # 이미 선택된 뉴스들과 비교
            for selected in filtered_news:
                similarity = self.calculate_similarity(news['title'], selected['title'])
                
                # 유사도가 threshold 이상이면 중복으로 간주
                if similarity >= similarity_threshold:
                    is_duplicate = True
                    print(f"[DEBUG] 유사 뉴스 제외 (유사도 {similarity:.2f}): {news['title']}")
                    break
            
            # 중복이 아니면 추가
            if not is_duplicate:
                filtered_news.append(news)
        
        print(f"[DEBUG] 유사 뉴스 필터링: {len(news_list)}개 → {len(filtered_news)}개")
        return filtered_news
    
    def search_news(self, keyword, max_results=10):
        """
        네이버 뉴스 검색 (공식 API 사용)
        :param keyword: 검색 키워드
        :param max_results: 유사도 필터링 후 최종 반환할 최대 뉴스 수
        :return: 뉴스 리스트 [{'title': '제목', 'url': 'URL', 'source': '언론사', 'date': '날짜'}]
        """
        if not self.client_id or not self.client_secret:
            print("❌ 네이버 API 키가 설정되지 않았습니다!")
            print("   .env 파일에 NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET를 추가하세요.")
            return []
        
        try:
            # 네이버 검색 API 요청
            headers = {
                'X-Naver-Client-Id': self.client_id,
                'X-Naver-Client-Secret': self.client_secret
            }
            
            # 유사도 필터링을 고려해서 더 많이 가져옴 (API 최대 100개)
            api_fetch_count = min(max_results * 3, 100)  # 최종 목표의 3배 가져오기
            
            params = {
                'query': keyword,
                'display': api_fetch_count,  # API에서 가져올 개수
                'sort': 'sim'  # 관련도순 정렬 (정확도 높음, 중복체크로 새 뉴스만 필터링됨)
            }
            
            print(f"[DEBUG] 네이버 API 검색: {keyword}")
            
            response = requests.get(self.api_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            news_list = []
            
            # API 응답 파싱
            for item in data.get('items', []):
                try:
                    # HTML 태그 제거
                    title = BeautifulSoup(item.get('title', ''), 'html.parser').get_text()
                    description = BeautifulSoup(item.get('description', ''), 'html.parser').get_text()
                    link = item.get('link', item.get('originallink', ''))  # 네이버 뉴스 링크 우선
                    original_link = item.get('originallink', '')  # 언론사 정보 추출용
                    pub_date = item.get('pubDate', '')
                    
                    if not title or not link:
                        continue
                    
                    # 제목이 잘린 경우 (... 또는 …으로 끝나는 경우) 전체 제목 크롤링
                    if title.endswith('...') or title.endswith('…'):
                        full_title = self._fetch_full_title(link)
                        if full_title:
                            print(f"[DEBUG] 전체 제목 가져옴: {title} → {full_title}")
                            title = full_title
                    
                    # 언론사 정보 추출 (원본 링크에서 도메인 추출)
                    source = '알 수 없음'
                    
                    # 방법 1: originallink에서 도메인 추출
                    if original_link:
                        try:
                            from urllib.parse import urlparse
                            domain = urlparse(original_link).netloc
                            # 도메인을 언론사 이름으로 변환
                            domain_map = {
                                'yna.co.kr': '연합뉴스', 'yonhapnews.co.kr': '연합뉴스',
                                'chosun.com': '조선일보', 'joongang.co.kr': '중앙일보',
                                'donga.com': '동아일보', 'hani.co.kr': '한겨레',
                                'khan.co.kr': '경향신문', 'kmib.co.kr': '국민일보',
                                'segye.com': '세계일보', 'munhwa.com': '문화일보',
                                'seoul.co.kr': '서울신문', 'hankookilbo.com': '한국일보',
                                'mk.co.kr': '매일경제', 'hankyung.com': '한국경제',
                                'mt.co.kr': '머니투데이', 'edaily.co.kr': '이데일리',
                                'etnews.com': '전자신문', 'dt.co.kr': '디지털타임스',
                                'news1.kr': '뉴스1', 'newsis.com': '뉴시스',
                                'newspim.com': '뉴스핌', 'newsway.co.kr': '뉴스웨이',
                                'nocutnews.co.kr': '노컷뉴스', 'breaknews.com': '브레이크뉴스',
                                'kbs.co.kr': 'KBS', 'imbc.com': 'MBC',
                                'sbs.co.kr': 'SBS', 'jtbc.co.kr': 'JTBC',
                                'news.jtbc.co.kr': 'JTBC', 'tvchosun.com': 'TV조선',
                                'mbntv.co.kr': 'MBN', 'ytn.co.kr': 'YTN',
                                'osen.co.kr': 'OSEN', 'xportsnews.com': '엑스포츠뉴스',
                                'topstarnews.net': '톱스타뉴스', 'starnewskorea.com': '스타뉴스',
                                'sedaily.com': '서울경제', 'fnnews.com': '파이낸셜뉴스',
                                'biz.chosun.com': '조선비즈', 'wowtv.co.kr': '한국경제TV',
                                'hellot.net': '헬로티', 'ekn.kr': '에너지경제',
                                'newsworks.co.kr': '뉴스웍스', 'bntnews.co.kr': 'BNT뉴스',
                                'slownews.kr': '슬로우뉴스',
                                'imaeil.com': '매일신문', 'biz.heraldcorp.com': '해럴드경제',
                                'heraldcorp.com': '헤럴드경제', 'womaneconomy.co.kr': '여성경제신문',
                                'cm.asiae.co.kr': '아시아경제', 'busan.com': '부산일보',
                                'kado.net': '강원도민일보', 'pennmike.com': '펜엔마이크',
                                'etoday.co.kr': '이투데이', 'newsprime.co.kr': '프라임경제', 
                                'nongmin.com': '농민신문', 'kookje.co.kr': '국제신문'
                                
                            }
                            
                            for key, value in domain_map.items():
                                if key in domain:
                                    source = value
                                    break
                            
                            # 매핑되지 않은 경우 도메인 그대로 사용
                            if source == '알 수 없음':
                                source = domain.replace('www.', '').split('.')[0].upper()
                        except:
                            pass
                    
                    # 방법 2: description에서 추출 (백업)
                    if source == '알 수 없음' and description:
                        parts = description.split('.')
                        if parts and len(parts[0]) < 20:
                            source = parts[0].strip()
                    
                    # 날짜 필터링: 30일 이내의 뉴스만 가져오기
                    try:
                        # RFC 2822 형식 파싱 (예: "Mon, 18 Oct 2025 10:30:00 +0900")
                        news_date = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
                        # timezone-aware 현재 시간
                        now = datetime.now(news_date.tzinfo)
                        # 30일 이전 날짜
                        cutoff_date = now - timedelta(days=30)
                        
                        # 30일 이전 뉴스는 건너뛰기
                        if news_date < cutoff_date:
                            print(f"[DEBUG] 오래된 뉴스 제외: {title} (작성일: {news_date.strftime('%Y-%m-%d')})")
                            continue
                    except Exception as e:
                        # 날짜 파싱 실패 시에도 뉴스는 포함 (안전장치)
                        print(f"[DEBUG] 날짜 파싱 실패 (뉴스는 포함): {e}")
                    
                    news_list.append({
                        'title': title,
                        'url': link,
                        'source': source,
                        'date': pub_date
                    })
                    
                    print(f"[DEBUG] 뉴스 추가: {title}")
                    
                except Exception as e:
                    print(f"[DEBUG] 항목 파싱 오류: {e}")
                    continue
            
            print(f"[DEBUG] 총 {len(news_list)}개 뉴스 수집 완료")
            
            # 유사 뉴스 필터링 (대표 뉴스만 반환)
            filtered_news = self.filter_similar_news(news_list, similarity_threshold=0.60)
            
            # 최종적으로 max_results 개수만 반환
            final_news = filtered_news[:max_results]
            if len(filtered_news) > max_results:
                print(f"[DEBUG] 최종 제한: {len(filtered_news)}개 → {max_results}개")
            
            return final_news
            
        except requests.RequestException as e:
            print(f"❌ 네이버 API 요청 오류: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   응답 코드: {e.response.status_code}")
                try:
                    error_data = e.response.json()
                    print(f"   오류 메시지: {error_data.get('errorMessage', 'N/A')}")
                except:
                    pass
            return []
        except Exception as e:
            print(f"❌ 예상치 못한 오류: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_latest_news(self, keyword, last_check_count=10):
        """
        최신 뉴스만 가져오기 (첫 페이지 분량)
        :param keyword: 검색 키워드
        :param last_check_count: 확인할 최신 뉴스 개수 (기본 10개 = 네이버 첫 페이지)
        :return: 뉴스 리스트
        """
        return self.search_news(keyword, max_results=last_check_count)

