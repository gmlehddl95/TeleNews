import sqlite3
import json
from datetime import datetime
from config import DB_FILE

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        """데이터베이스 테이블 생성"""
        cursor = self.conn.cursor()
        
        # 키워드 테이블 (user_id 추가)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, keyword)
            )
        ''')
        
        # 이미 전송한 뉴스 URL 저장 (중복 방지, user_id 추가)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
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
                user_id INTEGER PRIMARY KEY,
                last_alert_level INTEGER DEFAULT 0,
                last_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ath_price REAL,
                ath_date TEXT
            )
        ''')
        
        # 방해금지 시간 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiet_hours (
                user_id INTEGER PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                enabled INTEGER DEFAULT 1
            )
        ''')
        
        # 대기 중인 주가 알림 테이블 (방해금지 시간 동안 못 보낸 알림)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_stock_alerts (
                user_id INTEGER PRIMARY KEY,
                alert_level INTEGER,
                ath_price REAL,
                ath_date TEXT,
                nasdaq_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def add_keyword(self, user_id, keyword):
        """키워드 추가"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('INSERT INTO keywords (user_id, keyword) VALUES (?, ?)', (user_id, keyword))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def remove_keyword(self, user_id, keyword):
        """키워드 제거"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM keywords WHERE user_id = ? AND keyword = ?', (user_id, keyword))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def remove_all_keywords(self, user_id):
        """특정 사용자의 모든 키워드 제거"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM keywords WHERE user_id = ?', (user_id,))
        deleted_count = cursor.rowcount
        self.conn.commit()
        return deleted_count
    
    def get_keywords(self, user_id):
        """특정 사용자의 모든 키워드 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT keyword FROM keywords WHERE user_id = ?', (user_id,))
        return [row[0] for row in cursor.fetchall()]
    
    def get_all_user_keywords(self):
        """모든 사용자의 키워드 조회 (user_id, keyword 쌍)"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT user_id, keyword FROM keywords')
        return cursor.fetchall()
    
    def is_news_sent(self, user_id, keyword, url):
        """해당 뉴스가 이미 전송되었는지 확인"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM sent_news WHERE user_id = ? AND keyword = ? AND url = ?', 
                      (user_id, keyword, url))
        return cursor.fetchone() is not None
    
    def mark_news_sent(self, user_id, keyword, url, title):
        """뉴스를 전송완료로 표시"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('INSERT INTO sent_news (user_id, keyword, url, title) VALUES (?, ?, ?, ?)', 
                         (user_id, keyword, url, title))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def cleanup_old_news(self, days=30):
        """오래된 뉴스 기록 삭제 (기본 30일)"""
        try:
            cursor = self.conn.cursor()
            # 30일 이전 날짜 계산
            cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)
            
            # SQLite의 CURRENT_TIMESTAMP는 UTC 기준이므로 datetime으로 변환
            cursor.execute('''
                DELETE FROM sent_news 
                WHERE datetime(sent_at) < datetime(?, 'unixepoch')
            ''', (cutoff_date,))
            
            deleted_count = cursor.rowcount
            self.conn.commit()
            
            if deleted_count > 0:
                print(f"🗑️  {deleted_count}개의 오래된 뉴스 기록 삭제됨 (30일 이상)")
            
            return deleted_count
        except Exception as e:
            print(f"❌ 오래된 뉴스 삭제 중 오류: {e}")
            return 0
    
    def get_last_stock_alert_level(self, user_id):
        """마지막 주가 알림 레벨 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT last_alert_level, ath_price, ath_date FROM stock_alert_levels WHERE user_id = ?', (user_id,))
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
            INSERT OR REPLACE INTO stock_alert_levels 
            (user_id, last_alert_level, last_alert_time, ath_price, ath_date)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
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
            INSERT OR REPLACE INTO quiet_hours 
            (user_id, start_time, end_time, enabled)
            VALUES (?, ?, ?, 1)
        ''', (user_id, start_time, end_time))
        self.conn.commit()
    
    def get_quiet_hours(self, user_id):
        """사용자의 방해금지 시간 조회"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT start_time, end_time, enabled FROM quiet_hours WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        if result:
            return {
                'start_time': result[0],
                'end_time': result[1],
                'enabled': result[2] == 1
            }
        return None
    
    def disable_quiet_hours(self, user_id):
        """방해금지 시간 비활성화"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE quiet_hours SET enabled = 0 WHERE user_id = ?', (user_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def enable_quiet_hours(self, user_id):
        """방해금지 시간 활성화"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE quiet_hours SET enabled = 1 WHERE user_id = ?', (user_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
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
            INSERT OR REPLACE INTO pending_stock_alerts 
            (user_id, alert_level, ath_price, ath_date, nasdaq_info)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, alert_level, ath_price, ath_date, nasdaq_json))
        self.conn.commit()
    
    def get_pending_stock_alert(self, user_id):
        """사용자의 대기 중인 주가 알림 가져오기"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT alert_level, ath_price, ath_date, nasdaq_info
            FROM pending_stock_alerts
            WHERE user_id = ?
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
        cursor.execute('DELETE FROM pending_stock_alerts WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def close(self):
        """데이터베이스 연결 종료"""
        self.conn.close()

