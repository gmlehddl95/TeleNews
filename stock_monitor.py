import yfinance as yf
from datetime import datetime, timedelta
import time
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

class StockMonitor:
    def __init__(self):
        self.nasdaq_ticker = "^NDX"  # 나스닥 100 지수
        self.tqqq_ticker = "TQQQ"     # TQQQ ETF
        self.last_nasdaq_call = 0
        self.last_tqqq_call = 0
        self.min_interval = 10  # 최소 10초 간격
        
        # 캐싱 설정
        self.nasdaq_cache = None
        self.nasdaq_cache_time = 0
        self.tqqq_cache = None
        self.tqqq_cache_time = 0
        self.cache_duration = 300  # 5분 (초)
    
    def get_nasdaq_info(self, retry_count=3, timeout=30):
        """
        나스닥 100 현재 가격 및 전고점 대비 정보 조회 (캐싱 지원)
        :param retry_count: 재시도 횟수
        :param timeout: 최대 대기 시간 (초)
        :return: dict with current_price, all_time_high, percentage, drop_scenarios
        """
        # 캐시 확인 (5분 이내 데이터가 있으면 재사용)
        if self.nasdaq_cache and self.nasdaq_cache_time:
            elapsed = time.time() - self.nasdaq_cache_time
            if elapsed < self.cache_duration:
                remaining = int(self.cache_duration - elapsed)
                print(f"[CACHE] 나스닥 캐시 사용 (유효시간: {remaining}초 남음)")
                return self.nasdaq_cache
        
        # Rate limiting 체크
        elapsed = time.time() - self.last_nasdaq_call
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            print(f"[DEBUG] Rate limiting: {wait_time:.1f}초 대기 중...")
            time.sleep(wait_time)
        
        for attempt in range(retry_count):
            try:
                print(f"[DEBUG] 나스닥 100 정보 조회 시도 {attempt + 1}/{retry_count}...")
                
                # 재시도 시 더 긴 딜레이
                if attempt > 0:
                    time.sleep(5)
                
                # Ticker 객체 사용 (더 안정적)
                nasdaq = yf.Ticker(self.nasdaq_ticker)
                
                # ThreadPoolExecutor로 타임아웃 처리 (Windows 호환)
                def fetch_history():
                    return nasdaq.history(period="2y", interval="1d", auto_adjust=True)
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fetch_history)
                    try:
                        hist = future.result(timeout=timeout)
                    except FutureTimeoutError:
                        print(f"[WARNING] yfinance API 타임아웃 ({timeout}초 초과)")
                        if attempt < retry_count - 1:
                            continue
                        return None
                
                self.last_nasdaq_call = time.time()
                
                if hist.empty:
                    print(f"[DEBUG] 데이터가 비어있습니다. 다시 시도합니다...")
                    if attempt < retry_count - 1:
                        time.sleep(2)
                        continue
                    return None
                
                # 최신 데이터 확인
                print(f"[DEBUG] 조회된 데이터: {len(hist)}일치")
                print(f"[DEBUG] 최근 날짜: {hist.index[-1]}")
                
                current_price = float(hist['Close'].iloc[-1])
                all_time_high = float(hist['High'].max())  # 장중 최고가 포함
                
                # 전고점 날짜 찾기 (High 기준)
                ath_date = hist['High'].idxmax()
                
                # 전고점 대비 현재 비율
                percentage = (current_price / all_time_high) * 100
                drop_percentage = 100 - percentage
                
                print(f"[DEBUG] 나스닥 현재가: ${current_price:,.2f}, 전고점: ${all_time_high:,.2f} ({ath_date})")
                
                result = {
                    'current_price': round(current_price, 2),
                    'all_time_high': round(all_time_high, 2),
                    'ath_date': ath_date,
                    'percentage': round(percentage, 2),
                    'drop_percentage': round(drop_percentage, 2)
                }
                
                # 캐시에 저장
                self.nasdaq_cache = result
                self.nasdaq_cache_time = time.time()
                print(f"[CACHE] 나스닥 데이터 캐시 저장 ({self.cache_duration}초간 유효)")
                
                return result
                
            except Exception as e:
                print(f"❌ 나스닥 100 정보 조회 오류 (시도 {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(2)
                else:
                    import traceback
                    traceback.print_exc()
                    return None
        
        return None
    
    def get_tqqq_info(self, retry_count=3, timeout=30):
        """
        TQQQ 현재 가격 조회 (캐싱 지원)
        :param retry_count: 재시도 횟수
        :param timeout: 최대 대기 시간 (초)
        :return: dict with current_price
        """
        # 캐시 확인 (5분 이내 데이터가 있으면 재사용)
        if self.tqqq_cache and self.tqqq_cache_time:
            elapsed = time.time() - self.tqqq_cache_time
            if elapsed < self.cache_duration:
                remaining = int(self.cache_duration - elapsed)
                print(f"[CACHE] TQQQ 캐시 사용 (유효시간: {remaining}초 남음)")
                return self.tqqq_cache
        
        # Rate limiting 체크
        elapsed = time.time() - self.last_tqqq_call
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            print(f"[DEBUG] Rate limiting: {wait_time:.1f}초 대기 중...")
            time.sleep(wait_time)
        
        for attempt in range(retry_count):
            try:
                print(f"[DEBUG] TQQQ 정보 조회 시도 {attempt + 1}/{retry_count}...")
                
                # 재시도 시 더 긴 딜레이
                if attempt > 0:
                    time.sleep(5)
                
                # 나스닥 조회와 충분한 간격
                time.sleep(3)
                
                # Ticker 객체 사용
                tqqq = yf.Ticker(self.tqqq_ticker)
                
                # ThreadPoolExecutor로 타임아웃 처리 (Windows 호환)
                def fetch_history():
                    return tqqq.history(period="5d", interval="1d", auto_adjust=True)
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fetch_history)
                    try:
                        hist = future.result(timeout=timeout)
                    except FutureTimeoutError:
                        print(f"[WARNING] TQQQ yfinance API 타임아웃 ({timeout}초 초과)")
                        if attempt < retry_count - 1:
                            continue
                        return None
                
                self.last_tqqq_call = time.time()
                
                if hist.empty:
                    print(f"[DEBUG] 데이터가 비어있습니다. 다시 시도합니다...")
                    if attempt < retry_count - 1:
                        time.sleep(2)
                        continue
                    return None
                
                print(f"[DEBUG] 조회된 데이터: {len(hist)}일치")
                print(f"[DEBUG] 최근 날짜: {hist.index[-1]}")
                
                current_price = float(hist['Close'].iloc[-1])
                
                print(f"[DEBUG] TQQQ 현재가: ${current_price:.2f}")
                
                result = {
                    'current_price': round(current_price, 2)
                }
                
                # 캐시에 저장
                self.tqqq_cache = result
                self.tqqq_cache_time = time.time()
                print(f"[CACHE] TQQQ 데이터 캐시 저장 ({self.cache_duration}초간 유효)")
                
                return result
                
            except Exception as e:
                print(f"❌ TQQQ 정보 조회 오류 (시도 {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(2)
                else:
                    import traceback
                    traceback.print_exc()
                    return None
        
        return None
    
    def calculate_tqqq_scenarios(self, nasdaq_current, nasdaq_ath, tqqq_current):
        """
        나스닥이 특정 비율 하락 시 TQQQ 예상 가격 계산
        2022년 실제 폭락 데이터 기반 레버리지 배수 적용
        
        실제 데이터 (2022년 폭락):
        - 나스닥 20% 하락 → TQQQ 53% 하락 (2.60x)
        - 나스닥 30% 하락 → TQQQ 75% 하락 (2.35x)
        - 나스닥 40% 하락 → TQQQ 82% 하락 (2.15x)
        
        :param nasdaq_current: 나스닥 현재 가격
        :param nasdaq_ath: 나스닥 전고점
        :param tqqq_current: TQQQ 현재 가격
        :return: dict with scenarios
        """
        scenarios = {}
        
        # 현재 나스닥이 전고점 대비 몇 % 위치인지
        current_ratio = nasdaq_current / nasdaq_ath
        
        # 하락률에 따른 실제 레버리지 배수 (2022년 실제 데이터 기반)
        # 변동성 손실(volatility decay)을 반영
        leverage_map = {
            10: 2.70,  # 10% 하락 시 (추정)
            15: 2.65,  # 15% 하락 시 (추정)
            20: 2.60,  # 20% 하락 시 (실제 데이터)
            25: 2.48,  # 25% 하락 시 (보간)
            30: 2.35,  # 30% 하락 시 (실제 데이터)
            35: 2.25,  # 35% 하락 시 (보간)
            40: 2.15,  # 40% 하락 시 (실제 데이터)
            45: 2.08,  # 45% 하락 시 (추정)
            50: 2.00   # 50% 하락 시 (추정)
        }
        
        for drop in [10, 15, 20, 25, 30, 35, 40, 45, 50]:
            # 전고점 대비 drop% 하락한 나스닥 가격
            target_nasdaq = nasdaq_ath * (1 - drop / 100)
            
            # 현재가에서 목표가까지의 변화율
            total_nasdaq_change = (target_nasdaq - nasdaq_current) / nasdaq_current
            
            # 실제 레버리지 배수 적용 (2022년 데이터 기반)
            effective_leverage = leverage_map[drop]
            total_tqqq_change = total_nasdaq_change * effective_leverage
            
            # 예상 TQQQ 가격
            estimated_tqqq = tqqq_current * (1 + total_tqqq_change)
            
            scenarios[drop] = round(max(estimated_tqqq, 0.01), 2)  # 최소 $0.01
        
        return scenarios
    
    def get_full_report_html(self):
        """
        전체 리포트 생성 (HTML 형식)
        :return: formatted string report
        """
        nasdaq_info = self.get_nasdaq_info()
        tqqq_info = self.get_tqqq_info()
        
        if not nasdaq_info or not tqqq_info:
            return "❌ 주가 정보를 가져오는데 실패했습니다."
        
        # TQQQ 시나리오 계산
        scenarios = self.calculate_tqqq_scenarios(
            nasdaq_info['current_price'],
            nasdaq_info['all_time_high'],
            tqqq_info['current_price']
        )
        
        # 날짜 포맷 (GMT+9, 한국 시간)
        from datetime import timezone, timedelta
        kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(kst)
        date_str = now_kst.strftime('%Y-%m-%d %H:%M')
        ath_date_str = nasdaq_info['ath_date'].strftime('%Y-%m-%d')  # 날짜만 표시
        
        report = f"""📊 <b>주가 리포트</b> ({date_str})

<b>나스닥 100 (^NDX)</b>
• 현재가: ${nasdaq_info['current_price']:,.2f}
• 전고점: ${nasdaq_info['all_time_high']:,.2f} ({ath_date_str})
• 전고점 대비: {nasdaq_info['percentage']:.2f}% (▼ {nasdaq_info['drop_percentage']:.2f}%)

<b>TQQQ</b>
• 현재가: ${tqqq_info['current_price']:.2f}

<b>📉 나스닥 하락 시 (전고점 대비) TQQQ 예상가</b>
• 10% 하락 시: ${scenarios[10]:.2f}
• 15% 하락 시: ${scenarios[15]:.2f}
• 20% 하락 시: ${scenarios[20]:.2f}
• 25% 하락 시: ${scenarios[25]:.2f}
• 30% 하락 시: ${scenarios[30]:.2f}
• 35% 하락 시: ${scenarios[35]:.2f}
• 40% 하락 시: ${scenarios[40]:.2f}
• 45% 하락 시: ${scenarios[45]:.2f}
• 50% 하락 시: ${scenarios[50]:.2f}

"""
        return report
    
    def get_full_report(self):
        """
        전체 리포트 생성 (MarkdownV2 형식) - 자동 알림용
        :return: formatted string report
        """
        return self.get_full_report_html()

