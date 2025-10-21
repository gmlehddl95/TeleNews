import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import time
import re
import html
from datetime import datetime, timedelta
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
from difflib import SequenceMatcher

class NaverNewsCrawler:
    def __init__(self):
        self.client_id = NAVER_CLIENT_ID
        self.client_secret = NAVER_CLIENT_SECRET
        self.api_url = "https://openapi.naver.com/v1/search/news.json"
    
    def parse_keyword_expression(self, keyword):
        """
        키워드 표현식 파싱 및 추출된 키워드 목록 반환
        예: "삼성 and 전자" -> ["삼성", "전자"]
        예: "(속보 or 긴급) and 삼성" -> ["속보", "긴급", "삼성"]
        
        :param keyword: 키워드 표현식
        :return: (원본 표현식, 추출된 키워드 리스트, 논리 연산 포함 여부)
        """
        # and/or가 포함되어 있는지 확인 (대소문자 무시)
        has_logic = bool(re.search(r'\b(and|or)\b', keyword, re.IGNORECASE))
        
        if not has_logic:
            # 논리 연산자가 없으면 단순 키워드
            return (keyword, [keyword.strip()], False)
        
        # 괄호, and, or를 제거하고 개별 키워드만 추출
        temp = keyword.replace('(', ' ').replace(')', ' ')
        temp = re.sub(r'\b(and|or)\b', ' ', temp, flags=re.IGNORECASE)
        temp = re.sub(r'\s+', ' ', temp).strip()
        keywords = [kw.strip() for kw in temp.split() if kw.strip()]
        
        # 중복 제거
        keywords = list(dict.fromkeys(keywords))
        
        return (keyword, keywords, True)
    
    def evaluate_keyword_expression(self, expression, text):
        """
        키워드 표현식이 텍스트를 만족하는지 평가
        
        :param expression: 키워드 표현식 (예: "삼성 and 전자", "(속보 or 긴급) and 삼성")
        :param text: 확인할 텍스트 (뉴스 제목 + 설명)
        :return: True/False
        """
        text_lower = text.lower()
        
        # 단순 키워드인 경우 (and/or 없음)
        if not re.search(r'\b(and|or)\b', expression, re.IGNORECASE):
            return expression.lower() in text_lower
        
        # 논리 연산식 평가
        def evaluate_simple(expr):
            """괄호 없는 단순 표현식 평가"""
            expr = expr.strip()
            
            # OR 연산 (우선순위 낮음)
            if re.search(r'\bor\b', expr, re.IGNORECASE):
                parts = re.split(r'\bor\b', expr, flags=re.IGNORECASE)
                return any(evaluate_simple(part.strip()) for part in parts)
            
            # AND 연산 (우선순위 높음)
            elif re.search(r'\band\b', expr, re.IGNORECASE):
                parts = re.split(r'\band\b', expr, flags=re.IGNORECASE)
                return all(kw.strip().lower() in text_lower for kw in parts)
            
            # 단일 키워드
            else:
                return expr.lower() in text_lower
        
        # 괄호 처리
        working_expr = expression
        while '(' in working_expr:
            match = re.search(r'\(([^()]+)\)', working_expr)
            if match:
                inner_expr = match.group(1)
                result = evaluate_simple(inner_expr)
                working_expr = working_expr[:match.start()] + ('__TRUE__' if result else '__FALSE__') + working_expr[match.end():]
            else:
                break
        
        # 최종 평가
        def final_evaluate(expr):
            expr = expr.strip()
            expr = expr.replace('__TRUE__', 'True').replace('__FALSE__', 'False')
            
            # OR 연산
            if re.search(r'\bor\b', expr, re.IGNORECASE):
                parts = re.split(r'\bor\b', expr, flags=re.IGNORECASE)
                results = []
                for part in parts:
                    part = part.strip()
                    if part == 'True':
                        results.append(True)
                    elif part == 'False':
                        results.append(False)
                    else:
                        results.append(part.lower() in text_lower)
                return any(results)
            
            # AND 연산
            elif re.search(r'\band\b', expr, re.IGNORECASE):
                parts = re.split(r'\band\b', expr, flags=re.IGNORECASE)
                results = []
                for part in parts:
                    part = part.strip()
                    if part == 'True':
                        results.append(True)
                    elif part == 'False':
                        results.append(False)
                    else:
                        results.append(part.lower() in text_lower)
                return all(results)
            
            # 단일 값
            else:
                if expr == 'True':
                    return True
                elif expr == 'False':
                    return False
                else:
                    return expr.lower() in text_lower
        
        return final_evaluate(working_expr)
    
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
        """유사한 뉴스를 필터링하여 대표 뉴스만 반환 (유사 개수 포함)"""
        if not news_list:
            return []
        
        # 1단계: 유사한 뉴스들을 그룹화
        groups = []  # [{'representative': news, 'similar': [news1, news2, ...]}, ...]
        
        for news in news_list:
            found_group = False
            
            # 기존 그룹들과 유사도 비교
            for group in groups:
                representative = group['representative']
                similarity = self.calculate_similarity(news['title'], representative['title'])
                
                # 유사도가 threshold 이상이면 같은 그룹
                if similarity >= similarity_threshold:
                    group['similar'].append(news)
                    found_group = True
                    print(f"[DEBUG] 유사 뉴스 그룹화 (유사도 {similarity:.2f}): {news['title']}")
                    break
            
            # 새로운 그룹 생성
            if not found_group:
                groups.append({
                    'representative': news,
                    'similar': [news]  # 자기 자신도 포함
                })
        
        # 2단계: 각 그룹에서 최적의 대표 뉴스 선택
        filtered_news = []
        
        for group in groups:
            all_similar = group['similar']
            
            # 우선순위 1: 네이버 뉴스(news.naver.com) 중 가장 최신
            naver_news = [n for n in all_similar if 'news.naver.com' in n.get('url', '')]
            
            if naver_news:
                # 네이버 뉴스 중 가장 최신 선택
                representative = self._get_latest_news(naver_news)
                print(f"[DEBUG] 대표 선택 (네이버 뉴스): {representative['title']}")
            else:
                # 우선순위 2: 전체 중 가장 최신
                representative = self._get_latest_news(all_similar)
                print(f"[DEBUG] 대표 선택 (최신): {representative['title']}")
            
            # 유사 뉴스 개수 추가
            representative['similar_count'] = len(all_similar)
            filtered_news.append(representative)
        
        print(f"[DEBUG] 유사 뉴스 필터링: {len(news_list)}개 → {len(filtered_news)}개")
        return filtered_news
    
    def _get_latest_news(self, news_list):
        """뉴스 리스트에서 가장 최신 뉴스 반환"""
        if not news_list:
            return None
        
        try:
            def parse_date(news):
                try:
                    date_str = news['date']
                    if '+' in date_str or '-' in date_str:
                        return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %z')
                    else:
                        return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S')
                except:
                    return datetime.min
            
            # 날짜순 정렬 (최신 우선)
            sorted_list = sorted(news_list, key=parse_date, reverse=True)
            return sorted_list[0]
        except:
            # 파싱 실패 시 첫 번째 반환
            return news_list[0]
    
    def _search_single_keyword(self, keyword, max_count=20):
        """
        단일 키워드로 네이버 뉴스 검색
        :param keyword: 검색 키워드
        :param max_count: 가져올 최대 뉴스 수
        :return: 뉴스 리스트
        """
        try:
            headers = {
                'X-Naver-Client-Id': self.client_id,
                'X-Naver-Client-Secret': self.client_secret
            }
            
            params = {
                'query': keyword.strip(),
                'display': min(max_count, 30),
                'sort': 'sim'
            }
            
            response = requests.get(self.api_url, headers=headers, params=params, timeout=8)
            response.raise_for_status()
            
            data = response.json()
            news_list = []
            
            for item in data.get('items', []):
                try:
                    title = BeautifulSoup(item.get('title', ''), 'html.parser').get_text()
                    title = html.unescape(title)
                    
                    description = BeautifulSoup(item.get('description', ''), 'html.parser').get_text()
                    description = html.unescape(description)
                    
                    link = item.get('link', item.get('originallink', ''))
                    original_link = item.get('originallink', '')
                    pub_date = item.get('pubDate', '')
                    
                    if not title or not link:
                        continue
                    
                    # 날짜 필터링: 7일 이내
                    try:
                        news_date = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
                        now = datetime.now(news_date.tzinfo)
                        cutoff_date = now - timedelta(days=7)
                        
                        if news_date < cutoff_date:
                            continue
                    except:
                        pass
                    
                    # 언론사 정보 추출
                    source = '알 수 없음'
                    if original_link:
                        try:
                            from urllib.parse import urlparse
                            domain = urlparse(original_link).netloc
                            domain_map = {
                                'yna.co.kr': '연합뉴스', 'yonhapnews.co.kr': '연합뉴스',
                                'chosun.com': '조선일보', 'joongang.co.kr': '중앙일보',
                                'donga.com': '동아일보', 'hani.co.kr': '한겨레',
                                'khan.co.kr': '경향신문', 'kmib.co.kr': '국민일보',
                                'mk.co.kr': '매일경제', 'hankyung.com': '한국경제',
                                'mt.co.kr': '머니투데이', 'edaily.co.kr': '이데일리',
                                'kbs.co.kr': 'KBS', 'imbc.com': 'MBC', 'sbs.co.kr': 'SBS',
                                'jtbc.co.kr': 'JTBC', 'ytn.co.kr': 'YTN'
                            }
                            
                            for key, value in domain_map.items():
                                if key in domain:
                                    source = value
                                    break
                            
                            if source == '알 수 없음':
                                source = domain.replace('www.', '').split('.')[0].upper()
                        except:
                            pass
                    
                    news_list.append({
                        'title': title,
                        'url': link,
                        'source': source,
                        'date': pub_date,
                        'description': description  # OR 연산 필터링용
                    })
                    
                except Exception as e:
                    print(f"[DEBUG] 항목 파싱 오류: {e}")
                    continue
            
            return news_list
            
        except Exception as e:
            print(f"[DEBUG] 키워드 '{keyword}' 검색 오류: {e}")
            return []
    
    def search_news(self, keyword, max_results=10):
        """
        네이버 뉴스 검색 (공식 API 사용, AND/OR 논리 연산 지원)
        :param keyword: 검색 키워드 또는 논리 표현식 (예: "삼성 and 전자", "(속보 or 긴급) and 삼성")
        :param max_results: 유사도 필터링 후 최종 반환할 최대 뉴스 수
        :return: 뉴스 리스트 [{'title': '제목', 'url': 'URL', 'source': '언론사', 'date': '날짜'}]
        """
        if not self.client_id or not self.client_secret:
            print("❌ 네이버 API 키가 설정되지 않았습니다!")
            print("   .env 파일에 NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET를 추가하세요.")
            return []
        
        # 키워드 표현식 파싱
        original_expr, individual_keywords, has_logic = self.parse_keyword_expression(keyword)
        print(f"[DEBUG] 파싱 결과 - 원본: '{original_expr}', 키워드: {individual_keywords}, 논리연산: {has_logic}")
        
        # OR 연산이 있는지 확인
        has_or = has_logic and bool(re.search(r'\bor\b', keyword, re.IGNORECASE))
        print(f"[DEBUG] OR 연산 감지: {has_or}, has_logic={has_logic}, keyword='{keyword}'")
        
        # OR 연산이 있는 경우, 각 키워드로 개별 검색하여 합침
        if has_or:
            print(f"[DEBUG] ===== OR 연산 모드 시작 =====")
            print(f"[DEBUG] 원본 표현식: {original_expr}")
            print(f"[DEBUG] 개별 키워드: {individual_keywords}")
            
            # 키워드별로 뉴스 수집 및 필터링
            keyword_news = {}  # {keyword: [filtered_news_list]}
            all_news = []
            seen_urls = set()
            
            for idx, kw in enumerate(individual_keywords):
                try:
                    print(f"[DEBUG] OR 연산 [{idx+1}/{len(individual_keywords)}] - '{kw}' 검색 중...")
                    news_results = self._search_single_keyword(kw, max_results * 2)
                    
                    # 유사 뉴스 필터링 (각 키워드별로)
                    filtered = self.filter_similar_news(news_results, similarity_threshold=0.55)
                    
                    # 중복 제거하면서 추가
                    unique_filtered = []
                    for news in filtered:
                        if news['url'] not in seen_urls:
                            news['_keyword'] = kw  # 어느 키워드에서 온 뉴스인지 표시
                            all_news.append(news)
                            unique_filtered.append(news)
                            seen_urls.add(news['url'])
                    
                    keyword_news[kw] = unique_filtered
                    print(f"[DEBUG] OR 연산 - '{kw}': {len(news_results)}개 수집 → {len(filtered)}개 필터링 → {len(unique_filtered)}개 중복제거")
                except Exception as e:
                    print(f"[DEBUG] '{kw}' 검색 중 오류: {e}")
                    keyword_news[kw] = []
                    continue
            
            # AND도 함께 있는 복합 표현식인 경우만 추가 필터링
            has_and = re.search(r'\band\b', keyword, re.IGNORECASE)
            
            if has_and:
                # 복합 표현식 (예: "(속보 or 긴급) and 삼성")은 필터링 필요
                filtered_news = []
                for news in all_news:
                    full_text = news['title'] + ' ' + news.get('description', '')
                    if self.evaluate_keyword_expression(original_expr, full_text):
                        filtered_news.append(news)
                
                print(f"[DEBUG] 복합 OR+AND 필터링: {len(all_news)}개 → {len(filtered_news)}개")
                # 복합 표현식의 경우 앞에서부터 max_results개 반환
                return filtered_news[:max_results]
            
            # 단순 OR: 비율에 맞게 분배
            print(f"[DEBUG] 단순 OR 연산: 총 {len(all_news)}개 수집")
            
            # 각 키워드별 개수 계산
            total_count = sum(len(news_list) for news_list in keyword_news.values())
            
            if total_count == 0:
                return []
            
            # 비율에 맞게 각 키워드에서 가져올 개수 계산
            result_news = []
            allocated = {}
            
            for kw, news_list in keyword_news.items():
                if not news_list:
                    allocated[kw] = 0
                    continue
                
                # 비율 계산: (해당 키워드 개수 / 전체 개수) * max_results
                ratio = len(news_list) / total_count
                take_count = int(ratio * max_results)
                
                # 최소 1개는 보장 (뉴스가 있는 경우)
                if take_count == 0 and len(news_list) > 0:
                    take_count = 1
                
                allocated[kw] = take_count
                print(f"[DEBUG] '{kw}': {len(news_list)}개 중 {take_count}개 선택 (비율: {ratio:.2%})")
            
            # 할당된 개수의 합이 max_results보다 작으면 나머지를 가장 많은 키워드에 추가
            total_allocated = sum(allocated.values())
            if total_allocated < max_results:
                # 가장 많은 뉴스를 가진 키워드 찾기
                max_kw = max(keyword_news.keys(), key=lambda k: len(keyword_news[k]))
                remaining = max_results - total_allocated
                if len(keyword_news[max_kw]) >= allocated[max_kw] + remaining:
                    allocated[max_kw] += remaining
                    print(f"[DEBUG] 남은 {remaining}개를 '{max_kw}'에 추가")
            
            # 비율에 맞게 뉴스 선택
            for kw, take_count in allocated.items():
                news_list = keyword_news[kw]
                selected = news_list[:take_count]
                result_news.extend(selected)
                print(f"[DEBUG] '{kw}'에서 {len(selected)}개 추가")
            
            print(f"[DEBUG] 최종 선택: {len(result_news)}개")
            return result_news[:max_results]  # 혹시 모를 초과 방지
        
        # AND만 있거나 논리 연산이 없는 경우 (기존 로직)
        
        try:
            # 네이버 검색 API 요청
            headers = {
                'X-Naver-Client-Id': self.client_id,
                'X-Naver-Client-Secret': self.client_secret
            }
            
            # 논리 연산이 있는 경우 더 많은 결과 가져오기 (필터링 후 줄어들 수 있음)
            if has_logic:
                api_fetch_count = min(max_results * 3, 50)  # 논리 연산 시 3배
            else:
                api_fetch_count = min(max_results * 2, 30)  # 일반 검색 시 2배
            
            # API 검색어 선택: 논리 연산이 있으면 첫 번째 키워드, 없으면 그대로
            search_query = individual_keywords[0] if has_logic else keyword
            
            params = {
                'query': search_query,
                'display': api_fetch_count,  # API에서 가져올 개수
                'sort': 'sim'  # 관련도순 정렬 (정확도 높음)
            }
            
            if has_logic:
                print(f"[DEBUG] 네이버 API 검색 (논리 연산): {original_expr} -> 검색어: {search_query}")
            else:
                print(f"[DEBUG] 네이버 API 검색: {keyword}")
            
            response = requests.get(self.api_url, headers=headers, params=params, timeout=8)
            response.raise_for_status()
            
            data = response.json()
            news_list = []
            
            # API 응답 파싱
            for item in data.get('items', []):
                try:
                    # HTML 태그 제거 및 엔티티 디코딩
                    title = BeautifulSoup(item.get('title', ''), 'html.parser').get_text()
                    title = html.unescape(title)  # &middot; → ·, &hellip; → … 변환
                    
                    description = BeautifulSoup(item.get('description', ''), 'html.parser').get_text()
                    description = html.unescape(description)
                    link = item.get('link', item.get('originallink', ''))  # 네이버 뉴스 링크 우선
                    original_link = item.get('originallink', '')  # 언론사 정보 추출용
                    pub_date = item.get('pubDate', '')
                    
                    if not title or not link:
                        continue
                    
                    # 논리 연산이 있는 경우, 표현식을 만족하는지 확인
                    if has_logic:
                        # 제목과 설명을 합쳐서 평가
                        full_text = title + ' ' + description
                        if not self.evaluate_keyword_expression(original_expr, full_text):
                            # 표현식을 만족하지 않으면 건너뛰기
                            print(f"[DEBUG] 논리 연산 불일치, 제외: {title}")
                            continue
                    
                    # 제목이 잘린 경우 (... 또는 …으로 끝나는 경우) 전체 제목 크롤링
                    # 성능 최적화를 위해 비활성화 (잘린 제목 그대로 표시)
                    # if title.endswith('...') or title.endswith('…'):
                    #     full_title = self._fetch_full_title(link)
                    #     if full_title:
                    #         full_title = html.unescape(full_title)  # HTML 엔티티 디코딩
                    #         print(f"[DEBUG] 전체 제목 가져옴: {title} → {full_title}")
                    #         title = full_title
                    
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
                                'etoday.co.kr': '이투데이', 'newsprime.co.kr': '프라임경제',                                 'nongmin.com': '농민신문', 'kookje.co.kr': '국제신문', 
                                'newscj.com': '천지일보', 'pointdaily.co.kr': '포인트데일리', 
                                'daily.hankooki.com': '데일리한국', 'news.einfomax.co.kr': '연합인포맥스',
                                'view.asiae.co.kr' : "아시아경제", 'ohmynews.com' : '오마이뉴스',
                                'news.tf.co.kr': '더팩트', 'ichannela.com': '채널A',
                                'pressian.com': '프레시안'
                            
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
                    
                    # 날짜 필터링: 7일 이내의 뉴스만 가져오기
                    try:
                        # RFC 2822 형식 파싱 (예: "Mon, 18 Oct 2025 10:30:00 +0900")
                        news_date = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
                        # timezone-aware 현재 시간
                        now = datetime.now(news_date.tzinfo)
                        # 7일 이전 날짜
                        cutoff_date = now - timedelta(days=7)
                        
                        # 7일 이전 뉴스는 건너뛰기
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
                        'date': pub_date,
                        'description': description  # OR 연산 및 논리 연산 필터링용
                    })
                    
                    print(f"[DEBUG] 뉴스 추가: {title}")
                    
                except Exception as e:
                    print(f"[DEBUG] 항목 파싱 오류: {e}")
                    continue
            
            print(f"[DEBUG] 총 {len(news_list)}개 뉴스 수집 완료")
            
            # 유사 뉴스 필터링 (대표 뉴스만 반환)
            filtered_news = self.filter_similar_news(news_list, similarity_threshold=0.55)
            
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

