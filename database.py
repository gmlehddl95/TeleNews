import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
from datetime import datetime

class Database:
    def __init__(self):
        # Render 환경 변수에서 DATABASE_URL 가져오기
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL 환경 변수가 설정되지 않았습니다!")
        
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """DB 연결 (재연결 포함)"""
        try:
            if self.conn:
                self.conn.close()
            self.conn = psycopg2.connect(self.database_url)
            print("✅ DB 연결 성공")
        except Exception as e:
            print(f"❌ DB 연결 실패: {e}")
            raise
    
    def ensure_connection(self):
        """연결 상태 확인 및 재연결"""
        try:
            # 연결 상태 확인
            if self.conn is None or self.conn.closed:
                print("🔄 DB 연결 끊어짐, 재연결 시도...")
                self.connect()
        except Exception as e:
            print(f"🔄 DB 재연결 필요: {e}")
            self.connect()
    
    def create_tables(self):
        """데이터베이스 테이블 생성"""
        cursor = self.conn.cursor()
        
        # 키워드 테이블 (user_id 추가)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, keyword)
            )
        ''')
        
        # 이미 전송한 뉴스 URL 저장 (중복 방지, user_id 추가)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_news (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                keyword TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, keyword, url)
            )
        ''')
        
        # 주가 알림 레벨 저장 (중복 알림 방지)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_alert_levels (
                user_id BIGINT PRIMARY KEY,
                last_alert_level INTEGER DEFAULT 0,
                last_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ath_price REAL,
                ath_date TEXT
            )
        ''')
        
        # 방해금지 시간 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiet_hours (
                user_id BIGINT PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                enabled BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # 대기 중인 주가 알림 테이블 (방해금지 시간 동안 못 보낸 알림)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_stock_alerts (
                user_id BIGINT PRIMARY KEY,
                alert_level INTEGER,
                ath_price REAL,
                ath_date TEXT,
                nasdaq_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 나스닥 알림 설정 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nasdaq_alert_settings (
                user_id BIGINT PRIMARY KEY,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def add_keyword(self, user_id, keyword):
        """키워드 추가"""
        try:
            self.ensure_connection()
            cursor = self.conn.cursor()
            cursor.execute('INSERT INTO keywords (user_id, keyword) VALUES (%s, %s)', (user_id, keyword))
            self.conn.commit()
            return True
        except psycopg2.IntegrityError:
            try:
                self.conn.rollback()
            except:
                pass
            return False
        except Exception as e:
            print(f"❌ 키워드 추가 실패: {e}")
            try:
                self.conn.rollback()
            except:
                pass
            return False
    
    def remove_keyword(self, user_id, keyword):
        """키워드 제거"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM keywords WHERE user_id = %s AND keyword = %s', (user_id, keyword))
        rowcount = cursor.rowcount
        self.conn.commit()
        return rowcount > 0
    
    def remove_all_keywords(self, user_id):
        """특정 사용자의 모든 키워드 제거"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM keywords WHERE user_id = %s', (user_id,))
        deleted_count = cursor.rowcount
        self.conn.commit()
        return deleted_count
    
    def get_keywords(self, user_id):
        """특정 사용자의 모든 키워드 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT keyword FROM keywords WHERE user_id = %s', (user_id,))
        return [row[0] for row in cursor.fetchall()]
    
    def get_all_user_keywords(self):
        """모든 사용자의 키워드 조회 (user_id, keyword 쌍)"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT user_id, keyword FROM keywords')
        return cursor.fetchall()
    
    def is_news_sent(self, user_id, keyword, url):
        """해당 뉴스가 이미 전송되었는지 확인"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM sent_news WHERE user_id = %s AND keyword = %s AND url = %s', 
                      (user_id, keyword, url))
        return cursor.fetchone() is not None
    
    def mark_news_sent(self, user_id, keyword, url, title):
        """뉴스를 전송완료로 표시"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('INSERT INTO sent_news (user_id, keyword, url, title) VALUES (%s, %s, %s, %s)', 
                         (user_id, keyword, url, title))
            self.conn.commit()
            return True
        except psycopg2.IntegrityError:
            self.conn.rollback()
            return False
    
    def cleanup_old_news(self, days=7):
        """오래된 뉴스 기록 삭제 (기본 7일)"""
        try:
            # 연결 상태 확인 및 재연결
            self.ensure_connection()
            
            cursor = self.conn.cursor()
            
            # 삭제 전 개수 확인
            cursor.execute('''
                SELECT COUNT(*) FROM sent_news 
                WHERE sent_at < NOW() - INTERVAL '%s days'
            ''', (days,))
            old_count = cursor.fetchone()[0]
            
            if old_count == 0:
                print(f"🗑️  DB 정리: 삭제할 오래된 뉴스 기록 없음 ({days}일 이상)")
                return 0
            
            # 실제 삭제 실행
            cursor.execute('''
                DELETE FROM sent_news 
                WHERE sent_at < NOW() - INTERVAL '%s days'
            ''', (days,))
            
            deleted_count = cursor.rowcount
            self.conn.commit()
            
            print(f"🗑️  DB 정리 완료: {deleted_count}개의 오래된 뉴스 기록 삭제됨 ({days}일 이상)")
            return deleted_count
            
        except Exception as e:
            print(f"❌ DB 정리 실패: {e}")
            try:
                # 연결이 살아있을 때만 rollback 시도
                if self.conn and not self.conn.closed:
                    self.conn.rollback()
            except:
                pass  # rollback 실패해도 무시
            return 0
    
    def get_last_stock_alert_level(self, user_id):
        """마지막 주가 알림 레벨 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT last_alert_level, ath_price, ath_date FROM stock_alert_levels WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        if result:
            return {
                'last_level': result[0],
                'ath_price': result[1],
                'ath_date': result[2]
            }
        return None
    
    def update_stock_alert_level(self, user_id, level, ath_price, ath_date):
        """주가 알림 레벨 업데이트"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO stock_alert_levels 
            (user_id, last_alert_level, last_alert_time, ath_price, ath_date)
            VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                last_alert_level = EXCLUDED.last_alert_level,
                last_alert_time = CURRENT_TIMESTAMP,
                ath_price = EXCLUDED.ath_price,
                ath_date = EXCLUDED.ath_date
        ''', (user_id, level, ath_price, ath_date))
        self.conn.commit()
    
    def get_all_users(self):
        """모든 사용자 ID 조회 (키워드가 있는 사용자)"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM keywords')
        return [row[0] for row in cursor.fetchall()]
    
    def set_quiet_hours(self, user_id, start_time, end_time):
        """방해금지 시간 설정 (예: '23:00', '07:00')"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO quiet_hours 
            (user_id, start_time, end_time, enabled)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                enabled = TRUE
        ''', (user_id, start_time, end_time))
        self.conn.commit()
    
    def get_quiet_hours(self, user_id):
        """사용자의 방해금지 시간 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT start_time, end_time, enabled FROM quiet_hours WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        if result:
            return {
                'start_time': result[0],
                'end_time': result[1],
                'enabled': result[2]
            }
        return None
    
    def disable_quiet_hours(self, user_id):
        """방해금지 시간 비활성화"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE quiet_hours SET enabled = FALSE WHERE user_id = %s', (user_id,))
        rowcount = cursor.rowcount
        self.conn.commit()
        return rowcount > 0
    
    def enable_quiet_hours(self, user_id):
        """방해금지 시간 활성화"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE quiet_hours SET enabled = TRUE WHERE user_id = %s', (user_id,))
        rowcount = cursor.rowcount
        self.conn.commit()
        return rowcount > 0
    
    def set_pending_stock_alert(self, user_id, alert_level, ath_price, ath_date, nasdaq_info):
        """방해금지 시간 동안 못 보낸 주가 알림 저장"""
        cursor = self.conn.cursor()
        nasdaq_json = json.dumps({
            'current_price': nasdaq_info['current_price'],
            'all_time_high': nasdaq_info['all_time_high'],
            'drop_percentage': nasdaq_info['drop_percentage'],
            'ath_date': nasdaq_info['ath_date'].strftime('%Y-%m-%d') if hasattr(nasdaq_info['ath_date'], 'strftime') else nasdaq_info['ath_date']
        })
        cursor.execute('''
            INSERT INTO pending_stock_alerts 
            (user_id, alert_level, ath_price, ath_date, nasdaq_info)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                alert_level = EXCLUDED.alert_level,
                ath_price = EXCLUDED.ath_price,
                ath_date = EXCLUDED.ath_date,
                nasdaq_info = EXCLUDED.nasdaq_info
        ''', (user_id, alert_level, ath_price, ath_date, nasdaq_json))
        self.conn.commit()
    
    def get_pending_stock_alert(self, user_id):
        """사용자의 대기 중인 주가 알림 가져오기"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT alert_level, ath_price, ath_date, nasdaq_info
            FROM pending_stock_alerts
            WHERE user_id = %s
        ''', (user_id,))
        result = cursor.fetchone()
        if result:
            return {
                'alert_level': result[0],
                'ath_price': result[1],
                'ath_date': result[2],
                'nasdaq_info': json.loads(result[3])
            }
        return None
    
    def clear_pending_stock_alert(self, user_id):
        """대기 중인 주가 알림 삭제"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM pending_stock_alerts WHERE user_id = %s', (user_id,))
        self.conn.commit()
    
    def get_nasdaq_alert_setting(self, user_id):
        """나스닥 알림 설정 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT enabled FROM nasdaq_alert_settings WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            # 기본값: True (활성화)
            return True
    
    def set_nasdaq_alert_setting(self, user_id, enabled):
        """나스닥 알림 설정 저장/업데이트"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO nasdaq_alert_settings (user_id, enabled, updated_at) 
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) 
            DO UPDATE SET enabled = %s, updated_at = CURRENT_TIMESTAMP
        ''', (user_id, enabled, enabled))
        self.conn.commit()
    
    def get_user_count(self):
        """전체 사용자 수 조회"""
        try:
            self.ensure_connection()
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(DISTINCT user_id) FROM keywords')
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else 0
        except Exception as e:
            print(f"[ERROR] 사용자 수 조회 실패: {e}")
            return 0
    
    def close(self):
        """데이터베이스 연결 종료"""
        self.conn.close()
