import asyncio
import logging
from datetime import datetime
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.request import HTTPXRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NEWS_CHECK_INTERVAL, STOCK_ALERT_TIMES, LOG_LEVEL
from database import Database
from news_crawler import NaverNewsCrawler
from stock_monitor import StockMonitor

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
logger = logging.getLogger(__name__)

# httpx 로그만 숨김 (너무 많은 HTTP 요청 로그 방지)
logging.getLogger('httpx').setLevel(logging.WARNING)

class TeleNewsBot:
    def __init__(self):
        self.db = Database()
        self.news_crawler = NaverNewsCrawler()
        self.stock_monitor = StockMonitor()
        self.scheduler = AsyncIOScheduler()
        self.application = None
        self.waiting_for_keyword = {}  # 사용자가 키워드 입력 대기 중인지 추적
    
    
    def normalize_keyword(self, keyword):
        """복합연산 키워드를 기본 키워드로 분해 (단순화)"""
        if " and " in keyword.lower():
            return [kw.strip() for kw in keyword.split(" and ")]
        elif " or " in keyword.lower():
            return [kw.strip() for kw in keyword.split(" or ")]
        else:
            return [keyword.strip()]
    
    def _remove_duplicates(self, news_list):
        """URL 기준으로 중복 뉴스 제거"""
        seen_urls = set()
        unique_news = []
        
        for news in news_list:
            if news['url'] not in seen_urls:
                unique_news.append(news)
                seen_urls.add(news['url'])
        
        return unique_news
    
    def get_unique_base_keywords(self, user_keywords):
        """고유한 기본 키워드만 추출"""
        base_keywords = set()
        keyword_mapping = {}  # 원본 키워드 → 기본 키워드들
        
        for user_id, keyword in user_keywords:
            normalized = self.normalize_keyword(keyword)
            base_keywords.update(normalized)
            keyword_mapping[keyword] = normalized
        
        return list(base_keywords), keyword_mapping
    
    def apply_operation(self, keyword, base_news_map):
        """복합연산에 따라 뉴스 조합 (단순화된 AND/OR 연산)"""
        base_keywords = self.normalize_keyword(keyword)
        logger.info(f"키워드 '{keyword}': 기본 키워드 {base_keywords}, base_news_map 키: {list(base_news_map.keys())}")
        
        if " and " in keyword.lower():
            # AND 연산: 네이버 + 연산자 활용
            if not base_keywords:
                logger.warning(f"키워드 '{keyword}': 기본 키워드 없음")
                return []
            
            if len(base_keywords) == 2:
                # 2개 키워드: A +B, B +A 검색
                query1 = f"{base_keywords[0]} +{base_keywords[1]}"
                query2 = f"{base_keywords[1]} +{base_keywords[0]}"
                
                logger.info(f"키워드 '{keyword}': AND 연산 - '{query1}' 검색")
                news1 = self.news_crawler._search_single_keyword(query1, max_count=100)
                logger.info(f"키워드 '{keyword}': AND 연산 - '{query2}' 검색")
                news2 = self.news_crawler._search_single_keyword(query2, max_count=100)
                
                # 결과 합치기
                all_news = news1 + news2
                logger.info(f"키워드 '{keyword}': AND 연산 - 총 {len(all_news)}개 뉴스 수집")
                
                # 중복 제거
                unique_news = self._remove_duplicates(all_news)
                logger.info(f"키워드 '{keyword}': AND 연산 - 중복 제거 후 {len(unique_news)}개 뉴스")
                
                # 유사뉴스 필터링
                filtered_news = self.news_crawler.filter_similar_news(unique_news, similarity_threshold=0.55)
                logger.info(f"키워드 '{keyword}': AND 연산 - 유사뉴스 필터링 후 {len(filtered_news)}개 뉴스")
                
                return filtered_news[:15]  # 15개 제한
                
            elif len(base_keywords) >= 3:
                # 3개 이상: 대표 조합 3가지 검색 (방안 3)
                queries = [
                    f"{base_keywords[0]} +{base_keywords[1]} +{base_keywords[2]}",
                    f"{base_keywords[1]} +{base_keywords[0]} +{base_keywords[2]}",
                    f"{base_keywords[2]} +{base_keywords[0]} +{base_keywords[1]}"
                ]
                
                all_news = []
                for i, query in enumerate(queries, 1):
                    logger.info(f"키워드 '{keyword}': AND 연산 - '{query}' 검색 ({i}/3)")
                    news = self.news_crawler._search_single_keyword(query, max_count=100)
                    all_news.extend(news)
                    logger.info(f"키워드 '{keyword}': AND 연산 - '{query}'에서 {len(news)}개 뉴스")
                
                # 중복 제거
                unique_news = self._remove_duplicates(all_news)
                logger.info(f"키워드 '{keyword}': AND 연산 - 중복 제거 후 {len(unique_news)}개 뉴스")
                
                # 유사뉴스 필터링
                filtered_news = self.news_crawler.filter_similar_news(unique_news, similarity_threshold=0.55)
                logger.info(f"키워드 '{keyword}': AND 연산 - 유사뉴스 필터링 후 {len(filtered_news)}개 뉴스")
                
                return filtered_news[:15]  # 15개 제한
            
        elif " or " in keyword.lower():
            # OR 연산: 합집합 (비례 배분으로 15개 제한)
            logger.info(f"키워드 '{keyword}': OR 연산 시작")
            all_news = []
            keyword_news_map = {}  # {keyword: [news_list]}
            
            # 1. 각 키워드별 뉴스 수집
            for base_kw in base_keywords:
                base_news = base_news_map.get(base_kw, [])
                keyword_news_map[base_kw] = base_news
                all_news.extend(base_news)
                logger.info(f"키워드 '{keyword}': OR 연산, 키워드 '{base_kw}'에서 {len(base_news)}개 뉴스")
            
            # 2. 중복 제거
            seen_urls = set()
            unique_news = []
            for news in all_news:
                if news['url'] not in seen_urls:
                    unique_news.append(news)
                    seen_urls.add(news['url'])
            
            logger.info(f"키워드 '{keyword}': OR 연산 중복 제거 후 {len(unique_news)}개 뉴스 (전체 {len(all_news)}개 중)")
            
            # 3. 15개 이하면 그대로 반환
            if len(unique_news) <= 15:
                logger.info(f"키워드 '{keyword}': OR 연산 결과 {len(unique_news)}개 뉴스 (15개 이하)")
                return unique_news
            
            # 4. 15개 초과 시 비례 배분
            result = []
            total_news = sum(len(news_list) for news_list in keyword_news_map.values())
            
            for base_kw, news_list in keyword_news_map.items():
                if not news_list:
                    continue
                    
                # 비례 배분 계산
                proportion = len(news_list) / total_news
                target_count = int(proportion * 15)
                
                # 해당 키워드에서 target_count개만 선택
                selected_news = news_list[:target_count]
                
                # 중복 제거하면서 추가
                for news in selected_news:
                    if news['url'] not in {n['url'] for n in result}:
                        result.append(news)
                        if len(result) >= 15:
                            break
                
                if len(result) >= 15:
                    break
            
            return result[:15]
        else:
            # 단일 키워드
            result = base_news_map.get(base_keywords[0], [])
            logger.info(f"키워드 '{keyword}': 단일 키워드 '{base_keywords[0]}'에서 {len(result)}개 뉴스")
            return result[:15]  # 15개 제한
    
    def unblock_user_if_needed(self, user_id):
        """사용자가 봇을 다시 사용하려고 할 때 차단 목록에서 제거"""
        if self.db.is_user_blocked(user_id):
            self.db.remove_blocked_user(user_id)
            logger.info(f"사용자 {user_id} - 차단 목록에서 제거됨 (봇 재사용)")
    
    def is_quiet_time(self, user_id):
        """현재 시간이 사용자의 방해금지 시간인지 확인"""
        quiet_hours = self.db.get_quiet_hours(user_id)
        if not quiet_hours or not quiet_hours['enabled']:
            logger.debug(f"[방해금지] 사용자 {user_id} - 방해금지 설정 없음 또는 비활성화")
            return False
        
        from datetime import datetime, timezone, timedelta
        # 한국 시간 (GMT+9)
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        current_time = now.strftime('%H:%M')
        
        start = quiet_hours['start_time']
        end = quiet_hours['end_time']
        
        # 시간 비교 (자정을 넘는 경우도 고려)
        if start <= end:
            # 예: 09:00 ~ 18:00 (자정을 넘지 않음)
            is_quiet = start <= current_time <= end
        else:
            # 예: 22:00 ~ 07:00 (자정을 넘는 경우)
            is_quiet = current_time >= start or current_time <= end
        
        # 디버깅 로그 (항상 출력)
        logger.debug(f"[방해금지] 사용자 {user_id} - 현재시간: {current_time}, 설정: {start}~{end}, 활성: {quiet_hours['enabled']}, 결과: {is_quiet}")
        
        return is_quiet
    
    async def safe_reply(self, message, text, parse_mode='HTML', reply_markup=None):
        """안전한 메시지 응답 (강화된 재시도 포함)"""
        max_retries = 3  # 재시도 횟수
        base_delay = 2  # 기본 대기 시간
        
        for attempt in range(max_retries):
            try:
                await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
                if attempt > 0:
                    logger.info(f"✅ 메시지 응답 성공 ({attempt + 1}번째 시도)")
                
                # 성공 시 짧은 딜레이
                await asyncio.sleep(0.3)
                return
                
            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__
                
                # 사용자가 봇을 차단한 경우 - 재시도 불필요
                if 'bot was blocked' in error_str or 'Forbidden' in error_type:
                    logger.warning(f"⚠️ 메시지 응답 실패 - 봇 차단됨")
                    break
                
                # 재시도 가능한 오류인지 확인
                is_retryable_error = any(err in error_str or err in error_type for err in [
                    'ConnectError', 'NetworkError', 'TimedOut', 'TimeoutError',
                    'ConnectionError', 'ReadTimeout', 'ConnectTimeout',
                    'RemoteDisconnected', 'BadGateway', 'ServiceUnavailable'
                ])
                
                if attempt < max_retries - 1:
                    if is_retryable_error:
                        # 지수 백오프: 3초, 6초, 12초, 24초, 48초
                        wait_time = base_delay * (2 ** attempt)
                        logger.warning(f"🔄 응답 실패, {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})")
                        logger.debug(f"   오류 상세: {error_type}: {error_str[:150]}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # 재시도 불가능한 오류
                        logger.error(f"❌ 재시도 불가능한 응답 오류: {error_type}: {error_str[:150]}")
                        break
                else:
                    # 최종 실패
                    logger.error(f"❌ 메시지 응답 최종 실패 ({max_retries}회 시도)")
                    logger.error(f"   최종 오류: {error_type}: {error_str[:150]}")
                    break
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """봇 시작 명령어"""
        user_id = update.effective_chat.id
        
        # 사용자 명령어 실행 로그
        logger.info(f"사용자 {user_id} - /start 명령어 실행")
        
        # 차단 목록에서 제거 (사용자가 다시 봇을 사용하려고 함)
        self.unblock_user_if_needed(user_id)
        
        welcome_message = f"""🤖 <b>TeleNews 봇에 오신 것을 환영합니다!</b>

📌 <b>자동 알림</b>
• 뉴스: {NEWS_CHECK_INTERVAL}분마다 키워드 뉴스 자동 확인 후 메세지로 전송
  * 이미 전송한 뉴스는 보내지 않음
• 주가: 나스닥 100 전고점 대비 5%부터 1%p 단위로 하락시 알림

💡 <b>사용 방법</b>
하단 버튼을 클릭하여 시작
"""
        
        # 메인 메뉴 키보드 버튼
        keyboard = [
            [KeyboardButton("📋 키워드 목록"), KeyboardButton("📰 즉시 뉴스 확인")],
            [KeyboardButton("📊 주가 정보"), KeyboardButton("🔕 방해금지 설정")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await self.safe_reply(update.message, welcome_message, parse_mode='HTML', reply_markup=reply_markup)
    
    async def add_keyword_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """키워드 추가 (콤마로 구분하여 여러 개 동시 입력 가능)"""
        user_id = update.effective_chat.id
        
        # 사용자 명령어 실행 로그
        logger.info(f"사용자 {user_id} - /add 명령어 실행")
        
        self.unblock_user_if_needed(user_id)
        
        # 인자가 있으면 바로 추가
        if context.args:
            input_text = ' '.join(context.args)
            
            # 콤마가 있으면 분리, 없으면 그대로 사용
            if ',' in input_text:
                keywords = [kw.strip() for kw in input_text.split(',') if kw.strip()]
            else:
                keywords = [input_text.strip()]
            
            # 로딩 메시지 표시
            loading_msg = await self.safe_reply(update.message, f"➕ 키워드를 추가하는 중...")
            await asyncio.sleep(0.4)  # 애니메이션 효과
            
            added = []
            already_exist = []
            
            for keyword in keywords:
                if self.db.add_keyword(user_id, keyword):
                    added.append(keyword)
                    logger.info(f"사용자 {user_id} - 키워드 추가됨: {keyword}")
                else:
                    already_exist.append(keyword)
            
            # 결과 메시지 생성
            message = ""
            if added:
                if len(added) == 1:
                    message += f"✅ 키워드 '{added[0]}' 추가되었습니다!"
                else:
                    message += f"✅ {len(added)}개 키워드 추가:\n"
                    message += ", ".join(added)
            
            if already_exist:
                if message:
                    message += "\n\n"
                if len(already_exist) == 1:
                    message += f"⚠️ 키워드 '{already_exist[0]}' 이미 등록되어 있습니다."
                else:
                    message += f"⚠️ {len(already_exist)}개 이미 등록됨:\n"
                    message += ", ".join(already_exist)
            
            # 로딩 메시지 삭제
            if loading_msg:
                try:
                    await loading_msg.delete()
                except:
                    pass
            
            # 결과 메시지 표시
            if message:
                await self.safe_reply(update.message, message)
            
            # 키워드 목록 자동 표시
            all_keywords = self.db.get_keywords(user_id)
            if all_keywords:
                keyword_list = '\n'.join([f"• {kw}" for kw in all_keywords])
                
                # 각 키워드마다 삭제 버튼 생성 (2열로 배치)
                keyboard = []
                for i in range(0, len(all_keywords), 2):
                    row = []
                    # 첫 번째 키워드
                    keyword1 = all_keywords[i]
                    row.append(InlineKeyboardButton(f"🗑️ {keyword1}", callback_data=f"remove:{keyword1}"))
                    
                    # 두 번째 키워드 (있으면)
                    if i + 1 < len(all_keywords):
                        keyword2 = all_keywords[i + 1]
                        row.append(InlineKeyboardButton(f"🗑️ {keyword2}", callback_data=f"remove:{keyword2}"))
                    
                    keyboard.append(row)
                
                # 모두 삭제, 즉시 뉴스 확인 및 키워드 추가 버튼
                keyboard.append([InlineKeyboardButton("🗑️ 모두 삭제", callback_data="removeall")])
                keyboard.append([InlineKeyboardButton("📰 즉시 뉴스 확인", callback_data="check_news_now")])
                keyboard.append([InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.safe_reply(
                    update.message,
                    f"📝 <b>등록된 키워드 목록:</b>\n\n{keyword_list}\n\n버튼을 눌러 삭제할 수 있습니다.", 
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
        else:
            # 인자가 없으면 대화형 모드 시작
            input_msg = await update.message.reply_text(
                "📝 <b>추가할 키워드를 입력해주세요</b>\n\n"
                "🔹 <b>단순 키워드</b>\n"
                "예시: 삼성전자, AI, 나스닥\n"
                "💡 콤마(,)로 구분하여 여러 개 동시 입력 가능\n\n"
                "🔹 <b>논리 연산 (AND/OR)</b>\n"
                "• <code>삼성 and 애플</code> - 삼성과 애플 모두 관련된 기사\n"
                "• <code>삼성 or 애플</code> - 삼성 또는 애플 관련 기사\n"
                "and 와 or은 혼합하여 사용 불가\n", 
                parse_mode='HTML')
            
            # 대기 상태 저장 (입력 안내 메시지 ID 저장)
            self.waiting_for_keyword[user_id] = {
                'action': 'add_direct',
                'input_message_id': input_msg.message_id,
                'chat_id': update.effective_chat.id
            }
            logger.info(f"대화형 모드 시작, 입력 메시지 ID: {input_msg.message_id}")
    
    async def remove_keyword_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """키워드 제거"""
        if not context.args:
            await update.message.reply_text("❌ 사용법: /remove [키워드]\n예시: /remove 삼성전자")
            return
        
        user_id = update.effective_chat.id
        keyword = ' '.join(context.args)
        
        if self.db.remove_keyword(user_id, keyword):
            await update.message.reply_text(f"✅ 키워드 '{keyword}'가 제거되었습니다.")
            logger.info(f"사용자 {user_id} - 키워드 제거됨: {keyword}")
        else:
            await update.message.reply_text(f"❌ 키워드 '{keyword}'를 찾을 수 없습니다.")
    
    async def list_keywords_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """등록된 키워드 목록 (삭제 버튼 포함)"""
        user_id = update.effective_chat.id
        
        # 사용자 명령어 실행 로그
        logger.info(f"사용자 {user_id} - /list 명령어 실행")
        keywords = self.db.get_keywords(user_id)
        
        if not keywords:
            await update.message.reply_text("📝 등록된 키워드가 없습니다.\n/add 명령으로 키워드를 추가하세요.")
        else:
            # 키워드 목록 텍스트
            keyword_list = '\n'.join([f"• {kw}" for kw in keywords])
            
            # 각 키워드마다 삭제 버튼 생성 (2열로 배치)
            keyboard = []
            for i in range(0, len(keywords), 2):
                row = []
                # 첫 번째 키워드
                keyword1 = keywords[i]
                row.append(InlineKeyboardButton(f"🗑️ {keyword1}", callback_data=f"remove:{keyword1}"))
                
                # 두 번째 키워드 (있으면)
                if i + 1 < len(keywords):
                    keyword2 = keywords[i + 1]
                    row.append(InlineKeyboardButton(f"🗑️ {keyword2}", callback_data=f"remove:{keyword2}"))
                
                keyboard.append(row)
            
            # 모두 삭제, 즉시 뉴스 확인 및 키워드 추가 버튼
            keyboard.append([InlineKeyboardButton("🗑️ 모두 삭제", callback_data="removeall")])
            keyboard.append([InlineKeyboardButton("📰 즉시 뉴스 확인", callback_data="check_news_now")])
            keyboard.append([InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📝 <b>등록된 키워드 목록:</b>\n\n{keyword_list}\n\n키워드별 최대 15개 뉴스 전송\n버튼을 눌러 삭제할 수 있습니다.", 
                parse_mode='HTML',
                reply_markup=reply_markup
            )
    
    async def remove_all_keywords_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """모든 키워드 제거"""
        user_id = update.effective_chat.id
        deleted_count = self.db.remove_all_keywords(user_id)
        
        if deleted_count > 0:
            await update.message.reply_text(f"✅ 모든 키워드가 제거되었습니다. (총 {deleted_count}개)")
            logger.info(f"사용자 {user_id} - 모든 키워드 제거됨 ({deleted_count}개)")
        else:
            await update.message.reply_text("📝 제거할 키워드가 없습니다.")
    
    async def set_quiet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """방해금지 시간 설정 (버튼 UI)"""
        user_id = update.effective_chat.id
        quiet_hours = self.db.get_quiet_hours(user_id)
        
        from datetime import datetime, timezone, timedelta
        # 한국 시간 (GMT+9)
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        current_time = now.strftime('%H:%M')
        
        # 현재 설정 정보 및 상태
        if quiet_hours and quiet_hours['enabled']:
            # 방해금지가 활성화된 상태일 때만 설정 시간 표시
            is_currently_quiet = self.is_quiet_time(user_id)
            current_status = "⚠️ 방해금지중" if is_currently_quiet else "✅ 알림중"
            
            current_info = f"""

📌 <b>현재 상태</b>
• 현재 시간 및 상태: {current_time} {current_status}
• 방해금지 설정시간: {quiet_hours['start_time']} ~ {quiet_hours['end_time']}
"""
        else:
            # 방해금지가 비활성화되었거나 설정이 없는 상태
            current_info = f"""

📌 <b>현재 상태</b>
• ✅ 알림중(방해금지 비활성화)"""
        
        # 시작 시간 선택 버튼
        keyboard = [
            [InlineKeyboardButton("⏰ 시작 시간 선택", callback_data="quiet:select_start")]
        ]
        
        # 해제 버튼 (활성화된 상태일 때만)
        if quiet_hours and quiet_hours['enabled']:
            keyboard.append([InlineKeyboardButton("🔔 방해금지 해제", callback_data="quiet:off")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔕 <b>방해금지 설정</b>{current_info}\n\n"
            "방해금지 시작 시간과 종료 시간을 각각 선택할 수 있습니다.\n\n"
            "💡 설정한 시간대에는 자동 알림이 전송되지 않습니다.",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """관리자 전용 사용자 수 확인 명령어"""
        user_id = update.effective_chat.id
        
        # 관리자 권한 확인
        if user_id != 2140208898:
            await update.message.reply_text("❌ 이 명령어는 관리자만 사용할 수 있습니다.")
            return
        
        try:
            # 사용자 수 조회
            total_users = self.db.get_user_count()
            
            # 키워드 통계
            all_keywords = self.db.get_all_user_keywords()
            total_keywords = len(all_keywords)
            
            # 사용자별 키워드 수 계산
            from collections import defaultdict
            user_keyword_count = defaultdict(int)
            for user_id, keyword in all_keywords:
                user_keyword_count[user_id] += 1
            
            avg_keywords = total_keywords / total_users if total_users > 0 else 0
            
            users_message = f"""👥 <b>TeleNews Bot 사용자 현황</b>

📊 <b>사용자 통계</b>
• 전체 사용자: {total_users:,}명
• 전체 키워드: {total_keywords:,}개
• 사용자당 평균: {avg_keywords:.1f}개

🕐 <b>조회 시간</b>
• {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            await update.message.reply_text(users_message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"사용자 수 조회 중 오류: {e}")
            await update.message.reply_text("❌ 사용자 수 조회 중 오류가 발생했습니다.")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """인라인 버튼 클릭 처리"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data == "removeall":
            # 모두 삭제 - 애니메이션 효과
            # 1단계: 삭제 중 표시
            await query.edit_message_text("🗑️ 모든 키워드를 삭제하는 중...")
            await asyncio.sleep(0.4)  # 애니메이션 효과
            
            # 2단계: 실제 삭제
            deleted_count = self.db.remove_all_keywords(user_id)
            
            # 3단계: 키워드 목록 화면 표시 (키워드 추가 버튼만)
            keyboard = [[InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if deleted_count > 0:
                await query.edit_message_text(
                    f"✅ 모든 키워드가 제거되었습니다. (총 {deleted_count}개)\n\n"
                    "📝 <b>등록된 키워드가 없습니다.</b>\n\n"
                    "➕ 키워드 추가 버튼을 눌러 키워드를 등록해주세요!",
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                logger.info(f"사용자 {user_id} - 모든 키워드 제거됨 ({deleted_count}개)")
            else:
                await query.edit_message_text(
                    "📝 <b>등록된 키워드가 없습니다.</b>\n\n"
                    "➕ 키워드 추가 버튼을 눌러 키워드를 등록해주세요!",
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
        
        elif data.startswith("remove:"):
            # 개별 키워드 삭제 - 애니메이션 효과
            keyword = data.split(":", 1)[1]
            
            # 1단계: 삭제 중 표시
            await query.edit_message_text(f"🗑️ '{keyword}' 삭제 중...")
            await asyncio.sleep(0.4)  # 애니메이션 효과
            
            # 2단계: 실제 삭제
            if self.db.remove_keyword(user_id, keyword):
                # 키워드 제거 후 남은 키워드 목록 다시 표시
                keywords = self.db.get_keywords(user_id)
                
                if keywords:
                    keyword_list = '\n'.join([f"• {kw}" for kw in keywords])
                    keyboard = []
                    # 키워드 버튼 2열로 배치
                    for i in range(0, len(keywords), 2):
                        row = []
                        row.append(InlineKeyboardButton(f"🗑️ {keywords[i]}", callback_data=f"remove:{keywords[i]}"))
                        if i + 1 < len(keywords):
                            row.append(InlineKeyboardButton(f"🗑️ {keywords[i + 1]}", callback_data=f"remove:{keywords[i + 1]}"))
                        keyboard.append(row)
                    keyboard.append([InlineKeyboardButton("🗑️ 모두 삭제", callback_data="removeall")])
                    keyboard.append([InlineKeyboardButton("📰 즉시 뉴스 확인", callback_data="check_news_now")])
                    keyboard.append([InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        f"✅ '{keyword}' 제거됨!\n\n📝 <b>남은 키워드:</b>\n\n{keyword_list}\n\n버튼을 눌러 삭제할 수 있습니다.",
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                else:
                    # 마지막 키워드도 삭제됨 - 키워드 추가 버튼 표시
                    keyboard = [[InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        f"✅ '{keyword}' 제거됨!\n\n"
                        "📝 <b>등록된 키워드가 없습니다.</b>\n\n"
                        "➕ 키워드 추가 버튼을 눌러 키워드를 등록해주세요!",
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                
                logger.info(f"사용자 {user_id} - 키워드 제거됨: {keyword}")
            else:
                await query.edit_message_text(f"❌ 키워드 '{keyword}'를 찾을 수 없습니다.")
        
        elif data.startswith("quiet:") or data.startswith("quiet-"):
            # 방해금지 시간 설정
            if data == "quiet:off":
                # 방해금지 해제
                if self.db.disable_quiet_hours(user_id):
                    # 현재 상태 확인
                    from datetime import datetime, timezone, timedelta
                    kst = timezone(timedelta(hours=9))
                    now = datetime.now(kst)
                    current_time = now.strftime('%H:%M')
                    
                    await query.edit_message_text(
                        f"🔔 방해금지 시간이 해제되었습니다!\n\n"
                        f"📌 <b>현재 상태</b>\n"
                        f"💡 모든 자동 알림을 받습니다.",
                        parse_mode='HTML'
                    )
                    logger.info(f"사용자 {user_id} - 방해금지 시간 해제")
                    
                    # 대기 중인 주가 알림 확인 및 전송
                    pending = self.db.get_pending_stock_alert(user_id)
                    if pending:
                        logger.info(f"사용자 {user_id} - 대기 중인 주가 알림 전송: {pending['alert_level']}% 하락")
                        # 나스닥 정보 재구성
                        nasdaq_info_dict = pending['nasdaq_info']
                        nasdaq_info_dict['ath_date'] = datetime.strptime(nasdaq_info_dict['ath_date'], '%Y-%m-%d')
                        
                        # 알림 전송
                        success = await self._send_drop_alert(user_id, pending['alert_level'], nasdaq_info_dict)
                        if success:
                            self.db.update_stock_alert_level(user_id, pending['alert_level'], pending['ath_price'], pending['ath_date'])
                            self.db.clear_pending_stock_alert(user_id)
                else:
                    await query.edit_message_text("⚠️ 설정된 방해금지 시간이 없습니다.")
            
            elif data == "quiet:on":
                # 방해금지 재활성화 (이전 설정으로)
                if self.db.enable_quiet_hours(user_id):
                    # 현재 상태 확인
                    from datetime import datetime, timezone, timedelta
                    kst = timezone(timedelta(hours=9))
                    now = datetime.now(kst)
                    current_time = now.strftime('%H:%M')
                    
                    # 방해금지 시간 정보 가져오기
                    quiet_hours = self.db.get_quiet_hours(user_id)
                    start_time = quiet_hours['start_time']
                    end_time = quiet_hours['end_time']
                    
                    await query.edit_message_text(
                        f"🔕 방해금지 시간이 설정되었습니다!\n\n"
                        f"💡 설정된 시간대에는 자동 알림이 전송되지 않습니다.",
                        parse_mode='HTML'
                    )
                    logger.info(f"사용자 {user_id} - 방해금지 시간 재활성화: {start_time} ~ {end_time}")
                else:
                    await query.edit_message_text("⚠️ 재활성화할 방해금지 설정이 없습니다.")
            
            elif data == "quiet:select_start":
                # 시작 시간 선택 화면 (19:00 ~ 02:00, 1시간 간격)
                keyboard = []
                hours = [19, 20, 21, 22, 23, 0, 1, 2]
                # 2열로 배치
                for i in range(0, len(hours), 2):
                    row = []
                    for j in range(2):
                        if i + j < len(hours):
                            hour = hours[i + j]
                            time_str = f"{hour:02d}:00"
                            # 하이픈으로 구분 (콜론 문제 해결)
                            row.append(InlineKeyboardButton(f"🕐 {time_str}", callback_data=f"quiet-start-{hour:02d}00"))
                    keyboard.append(row)
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    "🔕 <b>방해금지 시작 시간 선택</b>\n\n"
                    "알림을 받지 않을 시작 시간을 선택하세요.",
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            
            elif data.startswith("quiet-start-"):
                # 시작 시간이 선택됨 -> 종료 시간 선택
                start_hour = data.split("-")[2]  # "2200"
                start_time = f"{start_hour[:2]}:{start_hour[2:]}"  # "22:00"
                
                keyboard = []
                # 05:00 ~ 10:00까지 1시간 간격
                hours = [5, 6, 7, 8, 9, 10]
                # 2열로 배치
                for i in range(0, len(hours), 2):
                    row = []
                    for j in range(2):
                        if i + j < len(hours):
                            hour = hours[i + j]
                            time_str = f"{hour:02d}:00"
                            # quiet-end-시작시간-종료시간
                            row.append(InlineKeyboardButton(f"🕐 {time_str}", callback_data=f"quiet-end-{start_hour}-{hour:02d}00"))
                    keyboard.append(row)
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"🔕 <b>방해금지 종료 시간 선택</b>\n\n"
                    f"시작 시간: {start_time}\n\n"
                    f"알림을 다시 받을 종료 시간을 선택하세요.",
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            
            elif data.startswith("quiet-end-"):
                # 종료 시간까지 선택됨 -> 설정 완료
                parts = data.split("-")  # ["quiet", "end", "2200", "0700"]
                start_hour = parts[2]  # "2200"
                end_hour = parts[3]    # "0700"
                
                start_time = f"{start_hour[:2]}:{start_hour[2:]}"  # "22:00"
                end_time = f"{end_hour[:2]}:{end_hour[2:]}"        # "07:00"
                
                self.db.set_quiet_hours(user_id, start_time, end_time)
                
                # 현재 상태 확인
                from datetime import datetime, timezone, timedelta
                kst = timezone(timedelta(hours=9))
                now = datetime.now(kst)
                current_time = now.strftime('%H:%M')
                is_currently_quiet = self.is_quiet_time(user_id)
                current_status = "⚠️ 방해금지중" if is_currently_quiet else "✅ 알림중"
                
                await query.edit_message_text(
                    f"✅ 방해금지 시간이 설정되었습니다!\n\n"
                    f"📌 <b>현재 상태</b>\n"
                    f"• 현재 시간 및 상태: {current_time} {current_status}\n"
                    f"• 방해금지 시간: {start_time} ~ {end_time}\n\n"
                    f"💡 이 시간대에는 자동 알림이 전송되지 않습니다.\n"
                    f"(수동 명령어는 사용 가능합니다)",
                    parse_mode='HTML'
                )
                logger.info(f"사용자 {user_id} - 방해금지 시간 설정: {start_time} ~ {end_time}")
        
        elif data == "check_news_now":
            # 즉시 뉴스 확인 버튼
            await query.answer()  # 버튼 클릭 응답
            
            # 로딩 메시지 전송
            loading_msg = await query.message.reply_text("📰 뉴스를 확인하는 중...")
            
            # 뉴스 확인 실행 (수동 체크로 처리)
            await self.check_news_for_user(user_id, manual_check=True)
            
            # 로딩 메시지 삭제
            try:
                await loading_msg.delete()
            except:
                pass
        
        elif data == "add_keyword":
            # 키워드 추가 버튼 - 새 메시지로 보내기 (기존 목록 유지)
            await query.answer()  # 버튼 클릭 응답
            
            # 취소 버튼 추가
            cancel_keyboard = [[InlineKeyboardButton("❌ 취소", callback_data="cancel_add_keyword")]]
            reply_markup = InlineKeyboardMarkup(cancel_keyboard)
            
            # 입력 안내 메시지 전송
            input_msg = await query.message.reply_text(
                "📝 <b>키워드 추가</b>\n\n"
                "추가할 키워드를 입력해주세요.\n\n"
                "🔹 <b>단순 키워드</b>\n"
                "예시: 삼성전자, AI, 나스닥\n"
                "💡 콤마(,)로 구분하여 여러 개 동시 입력 가능\n\n"
                "🔹 <b>논리 연산 (AND/OR)</b>\n"
                "• <code>삼성 and 애플</code> - 삼성과 애플 모두 관련된 뉴스\n"
                "• <code>삼성 or 애플</code> - 삼성 또는 애플과 관련된 뉴스\n"
                "and 와 or은 혼합하여 사용 불가\n",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
            # 대기 상태 저장 (기존 목록 메시지 ID와 입력 안내 메시지 ID 저장)
            self.waiting_for_keyword[user_id] = {
                'action': 'add_from_list',
                'list_message_id': query.message.message_id,
                'input_message_id': input_msg.message_id,
                'chat_id': query.message.chat_id
            }
            logger.info(f"사용자 {user_id} - 키워드 추가 대기 모드 진입 (목록에서)")
        
        elif data == "cancel_add_keyword":
            # 키워드 추가 취소
            await query.answer("취소되었습니다.")
            if user_id in self.waiting_for_keyword:
                del self.waiting_for_keyword[user_id]
            # 입력 안내 메시지만 삭제 (목록은 유지)
            try:
                await query.message.delete()
            except:
                pass
            logger.info(f"사용자 {user_id} - 키워드 추가 취소")
        
        elif data.startswith("nasdaq_alert:"):
            # 나스닥 알림 on/off 처리
            action = data.split(":")[1]  # "on" 또는 "off"
            
            if action == "on":
                # 알림 켜기
                self.db.set_nasdaq_alert_setting(user_id, True)
                await query.answer("✅ 나스닥 알림이 켜졌습니다!")
                logger.info(f"사용자 {user_id} - 나스닥 알림 켜짐")
            elif action == "off":
                # 알림 끄기
                self.db.set_nasdaq_alert_setting(user_id, False)
                await query.answer("🔕 나스닥 알림이 꺼졌습니다!")
                logger.info(f"사용자 {user_id} - 나스닥 알림 꺼짐")
            
            # 업데이트된 나스닥 알림 설정으로 리포트 재생성
            nasdaq_alert_enabled = self.db.get_nasdaq_alert_setting(user_id)
            
            # 새로운 리포트 생성 (동기 함수를 별도 스레드에서 실행)
            updated_report = await asyncio.to_thread(
                self.stock_monitor.get_full_report_html, 
                user_id, 
                nasdaq_alert_enabled
            )
            
            # 버튼 상태 업데이트
            if nasdaq_alert_enabled:
                button_text = "🔕 나스닥 알림 끄기"
                callback_data = "nasdaq_alert:off"
            else:
                button_text = "🔔 나스닥 알림 켜기"
                callback_data = "nasdaq_alert:on"
            
            keyboard = [[InlineKeyboardButton(button_text, callback_data=callback_data)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 전체 메시지 업데이트 (리포트 내용 + 버튼)
            await query.edit_message_text(
                text=updated_report, 
                parse_mode='HTML', 
                reply_markup=reply_markup
            )
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """일반 텍스트 메시지 처리 (대화형 키워드 입력 + 버튼 클릭)"""
        user_id = update.effective_chat.id
        text = update.message.text
        
        # 메인 메뉴 버튼 처리
        if text == "📋 키워드 목록":
            logger.info(f"사용자 {user_id} - 키워드 목록 버튼 클릭")
            await self.list_keywords_command(update, None)
            return
        elif text == "📰 즉시 뉴스 확인":
            logger.info(f"사용자 {user_id} - 즉시 뉴스 확인 버튼 클릭")
            await self.check_news_command(update, None)
            return
        elif text == "📊 주가 정보":
            logger.info(f"사용자 {user_id} - 주가 정보 버튼 클릭")
            await self.stock_info_command(update, None)
            return
        elif text == "🔕 방해금지 설정":
            logger.info(f"사용자 {user_id} - 방해금지 설정 버튼 클릭")
            await self.set_quiet_command(update, None)
            return
        
        # 사용자가 키워드 입력 대기 중인지 확인
        if user_id in self.waiting_for_keyword:
            waiting_info = self.waiting_for_keyword[user_id]
            del self.waiting_for_keyword[user_id]
            
            # dict 형태인지 확인
            is_dict = isinstance(waiting_info, dict)
            
            if is_dict and waiting_info['action'] in ['add_from_list', 'add_direct']:
                input_text = text.strip()
                
                # 콤마가 있으면 분리, 없으면 그대로 사용
                if ',' in input_text:
                    keywords = [kw.strip() for kw in input_text.split(',') if kw.strip()]
                else:
                    keywords = [input_text]
                
                # 목록에서 추가한 경우 또는 대화형 모드
                if is_dict:
                    try:
                        # 1. 사용자가 입력한 키워드 메시지 삭제
                        try:
                            await update.message.delete()
                        except:
                            pass
                        
                        # 2. 입력 안내 메시지 삭제
                        if 'input_message_id' in waiting_info and waiting_info['input_message_id']:
                            try:
                                await self.application.bot.delete_message(
                                    chat_id=waiting_info['chat_id'],
                                    message_id=waiting_info['input_message_id']
                                )
                                logger.info(f"입력 안내 메시지 삭제 성공: {waiting_info['input_message_id']}")
                            except Exception as e:
                                logger.error(f"입력 안내 메시지 삭제 실패: {e}")
                        
                        # 3. 키워드 추가 실행
                        added = []
                        already_exist = []
                        
                        for keyword in keywords:
                            if self.db.add_keyword(user_id, keyword):
                                added.append(keyword)
                                logger.info(f"사용자 {user_id} - 키워드 추가됨: {keyword}")
                            else:
                                already_exist.append(keyword)
                        
                        # 4. 업데이트된 전체 키워드 목록 가져오기
                        all_keywords = self.db.get_keywords(user_id)
                        
                        if all_keywords:
                            keyword_list = '\n'.join([f"• {kw}" for kw in all_keywords])
                            
                            # 키워드 버튼 2열로 배치
                            keyboard = []
                            for i in range(0, len(all_keywords), 2):
                                row = []
                                row.append(InlineKeyboardButton(f"🗑️ {all_keywords[i]}", callback_data=f"remove:{all_keywords[i]}"))
                                if i + 1 < len(all_keywords):
                                    row.append(InlineKeyboardButton(f"🗑️ {all_keywords[i + 1]}", callback_data=f"remove:{all_keywords[i + 1]}"))
                                keyboard.append(row)
                            keyboard.append([InlineKeyboardButton("🗑️ 모두 삭제", callback_data="removeall")])
                            keyboard.append([InlineKeyboardButton("📰 즉시 뉴스 확인", callback_data="check_news_now")])
                            keyboard.append([InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")])
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            # 5. 성공 메시지 생성
                            result_msg = ""
                            if added:
                                if len(added) == 1:
                                    result_msg = f"✅ '{added[0]}' 추가됨!\n\n"
                                else:
                                    result_msg = f"✅ {len(added)}개 키워드 추가됨: {', '.join(added)}\n\n"
                            
                            if already_exist:
                                if len(already_exist) == 1:
                                    result_msg += f"⚠️ '{already_exist[0]}' 이미 등록되어 있습니다.\n\n"
                                else:
                                    result_msg += f"⚠️ {len(already_exist)}개 이미 등록됨: {', '.join(already_exist)}\n\n"
                            
                            # 6. 목록 메시지 업데이트 또는 새로 전송
                            if waiting_info['action'] == 'add_from_list':
                                # 목록에서 추가: 기존 목록 메시지 업데이트
                                await self.application.bot.edit_message_text(
                                    chat_id=waiting_info['chat_id'],
                                    message_id=waiting_info['list_message_id'],
                                    text=f"{result_msg}📝 <b>등록된 키워드 목록:</b>\n\n{keyword_list}\n\n버튼을 눌러 삭제할 수 있습니다.",
                                    parse_mode='HTML',
                                    reply_markup=reply_markup
                                )
                            else:
                                # 대화형 모드: 새 메시지로 전송
                                if result_msg:
                                    await update.message.reply_text(result_msg.strip())
                                
                                await update.message.reply_text(
                                    f"📝 <b>등록된 키워드 목록:</b>\n\n{keyword_list}\n\n버튼을 눌러 삭제할 수 있습니다.",
                                    parse_mode='HTML',
                                    reply_markup=reply_markup
                                )
                        else:
                            if waiting_info['action'] == 'add_from_list':
                                await self.application.bot.edit_message_text(
                                    chat_id=waiting_info['chat_id'],
                                    message_id=waiting_info['list_message_id'],
                                    text="❌ 키워드 추가 실패"
                                )
                            else:
                                await update.message.reply_text("❌ 키워드 추가 실패")
                    except Exception as e:
                        logger.error(f"키워드 목록 업데이트 실패: {e}")
                        await update.message.reply_text("❌ 키워드 추가 중 오류가 발생했습니다.")
    
    async def check_news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """수동으로 뉴스 확인"""
        user_id = update.effective_chat.id
        
        # 사용자 명령어 실행 로그
        logger.info(f"사용자 {user_id} - /check 명령어 실행")
        
        # 키워드가 있는지 먼저 확인
        keywords = self.db.get_keywords(user_id)
        if not keywords:
            await self.send_message_to_user(
                user_id, 
                "⚠️ <b>등록된 키워드가 없습니다.</b>\n\n"
                "➕ 키워드 추가 버튼을 눌러 키워드를 먼저 등록해주세요!"
            )
            return
        
        # 로딩 메시지 전송 및 저장
        loading_msg = await update.message.reply_text("🔍 뉴스를 확인하고 있습니다...")
        
        # 뉴스 확인
        await self.check_news_for_user(user_id, manual_check=True)
        
        # 로딩 메시지 삭제
        try:
            await loading_msg.delete()
        except:
            pass  # 이미 삭제되었거나 삭제 권한이 없는 경우 무시
    
    async def stock_info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """주가 정보 확인"""
        user_id = update.effective_chat.id
        
        # 사용자 명령어 실행 로그
        logger.info(f"사용자 {user_id} - /stock 명령어 실행")
        
        # 로딩 메시지 전송 및 저장
        loading_msg = await update.message.reply_text("📊 주가 정보를 가져오는 중...")
        
        # 나스닥 알림 설정 확인
        nasdaq_alert_enabled = self.db.get_nasdaq_alert_setting(user_id)
        
        # 동기 함수를 별도 스레드에서 실행 (나스닥 알림 상태 전달)
        report = await asyncio.to_thread(
            self.stock_monitor.get_full_report_html, 
            user_id, 
            nasdaq_alert_enabled
        )
        
        # 버튼 생성
        if nasdaq_alert_enabled:
            button_text = "🔕 나스닥 알림 끄기"
            callback_data = "nasdaq_alert:off"
        else:
            button_text = "🔔 나스닥 알림 켜기"
            callback_data = "nasdaq_alert:on"
        
        keyboard = [[InlineKeyboardButton(button_text, callback_data=callback_data)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 결과 전송 (버튼 포함)
        await update.message.reply_text(report, parse_mode='HTML', reply_markup=reply_markup)
        
        # 로딩 메시지 삭제
        try:
            await loading_msg.delete()
        except:
            pass  # 이미 삭제되었거나 삭제 권한이 없는 경우 무시
    
    async def check_news_updates(self):
        """뉴스 업데이트 확인 (스케줄러용 - 키워드 중복 제거 + 캐시 활용)"""
        try:
            logger.info("=== 뉴스 업데이트 체크 시작 ===")
            
            # 7일 이상 오래된 뉴스 기록 삭제
            self.db.cleanup_old_news(days=7)
            
            # 1. 모든 사용자 키워드 수집
            user_keywords = self.db.get_all_user_keywords_except_blocked()
            
            if not user_keywords:
                logger.info("등록된 키워드가 없습니다.")
                return
            
            # 2. 키워드 분해 및 고유 기본 키워드 추출
            unique_base_keywords, keyword_mapping = self.get_unique_base_keywords(user_keywords)
            
            logger.info(f"고유 기본 키워드: {len(unique_base_keywords)}개")
            logger.info(f"기본 키워드: {unique_base_keywords}")
            
            # 3. 기본 키워드에 대해서만 API 호출
            base_news_map = {}
            for base_kw in unique_base_keywords:
                news_list = self.news_crawler.get_latest_news(base_kw, last_check_count=15)
                base_news_map[base_kw] = news_list
                await asyncio.sleep(0.3)  # API 부하 분산
            
            # 4. 사용자별로 그룹화
            from collections import defaultdict
            user_keyword_map = defaultdict(list)  # {user_id: [keyword1, keyword2, ...]}
            for user_id, keyword in user_keywords:
                user_keyword_map[user_id].append(keyword)
            
            logger.info(f"{len(user_keyword_map)}명의 사용자, 총 {len(user_keywords)}개 키워드")
            
            # 5. 사용자별로 처리
            for user_id, keywords in user_keyword_map.items():
                try:
                    # 방해금지 시간 체크
                    if self.is_quiet_time(user_id):
                        logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀")
                        continue
                    
                    # 사용자의 모든 키워드에 대한 뉴스 수집 (복합연산 적용)
                    for keyword in keywords:
                        logger.info(f"사용자 {user_id} - 키워드 '{keyword}' 처리 시작")
                        
                        # 복합연산 적용
                        combined_news = self.apply_operation(keyword, base_news_map)
                        logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 복합연산 결과 {len(combined_news)}개 뉴스")
                        
                        if combined_news:
                            # 각 뉴스에 키워드 정보 추가
                            for news in combined_news:
                                news['_keyword'] = keyword
                            
                            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 뉴스 전송 시작")
                            # 개별 키워드별로 뉴스 전송 (자동 알림)
                            await self._send_news_to_user(user_id, keyword, combined_news, manual_check=False)
                        else:
                            logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 뉴스 없음")
                    
                    logger.info(f"사용자 {user_id} - {len(keywords)}개 키워드 처리 완료")
                    
                except Exception as e:
                    logger.error(f"사용자 {user_id} 처리 중 오류: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            logger.info("=== 뉴스 업데이트 체크 완료 ===")
        except Exception as e:
            logger.error(f"뉴스 업데이트 체크 전체 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _send_batch_news_to_user(self, user_id, news_by_keyword):
        """사용자별로 통합된 뉴스 메시지 전송 (배치 전송) + 메시지 캐시 저장"""
        # 방해금지 시간 체크
        if self.is_quiet_time(user_id):
            logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀")
            return
        
        # 모든 키워드의 새로운 뉴스 수집
        all_new_news = {}  # {keyword: [news_list]}
        total_new_news = 0
        
        for keyword, news_list in news_by_keyword.items():
            # 새로운 뉴스만 필터링
            new_news = []
            for news in news_list:
                if not self.db.is_news_sent(user_id, keyword, news['url']):
                    new_news.append(news)
            
            if new_news:
                # 날짜순으로 정렬 (최신 뉴스가 상단에 오도록)
                new_news = self._sort_news_by_date(new_news)
                all_new_news[keyword] = new_news
                total_new_news += len(new_news)
        
        # 새로운 뉴스가 없으면 전송하지 않음
        if not all_new_news:
            logger.info(f"사용자 {user_id} - 새로운 뉴스 없음")
            return
        
        # 통합 메시지 생성
        message = f"📰 <b>새로운 뉴스 알림</b>\n"
        message += f"총 {total_new_news}건 ({len(all_new_news)}개 키워드)\n"
        message += "═══════════════\n\n"
        
        # 키워드별로 뉴스 추가
        for keyword, news_list in all_new_news.items():
            message += f"🔍 <b>키워드: {keyword}</b> ({len(news_list)}건)\n"
            message += "───────────────\n"
            
            for i, news in enumerate(news_list, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                similar_count = news.get('similar_count', 1)
                
                # 뉴스 아이콘 결정
                icon = self._get_news_icon(news)
                
                # 제목 (아이콘 + 제목)
                message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                
                # 관련뉴스 개수 표시
                if icon == '⭐':
                    if similar_count >= 2:
                        message += f" [관련뉴스: {similar_count}건]"
                elif similar_count > 1:
                    message += f" [관련뉴스: {similar_count}건]"
                
                message += "\n"
                
                # 부가 정보
                message += f"<code>{source}, {date}</code>\n"
                message += "───────────────\n"
            
            message += "\n"
        
        # 메시지 전송 시도
        success = await self.send_message_to_user(user_id, message)
        
        # 전송 성공한 경우에만 DB에 기록 및 메시지 저장
        if success:
            for keyword, news_list in all_new_news.items():
                for news in news_list:
                    self.db.mark_news_sent(user_id, keyword, news['url'], news['title'])
                
                # 개별 키워드별 메시지 생성 및 DB 저장
                keyword_message = f"📰 <b>새로운 뉴스</b> (키워드: {keyword})\n"
                keyword_message += f"총 {len(news_list)}건\n"
                keyword_message += "──────────────\n\n"
                
                for i, news in enumerate(news_list, 1):
                    title = news['title']
                    source = news['source']
                    date = self._format_date_simple(news['date'])
                    url = news['url']
                    similar_count = news.get('similar_count', 1)
                    
                    # 뉴스 아이콘 결정
                    icon = self._get_news_icon(news)
                    
                    # 제목 (아이콘 + 제목)
                    keyword_message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                    
                    # 관련뉴스 개수 표시
                    if icon == '⭐':
                        if similar_count >= 2:
                            keyword_message += f" [관련뉴스: {similar_count}건]"
                    elif similar_count > 1:
                        keyword_message += f" [관련뉴스: {similar_count}건]"
                    
                    keyword_message += "\n\n"
                    
                    # 부가 정보
                    keyword_message += f"<code>{source}, {date}</code>\n"
                    keyword_message += "──────────────\n\n"
                
                # 개별 키워드 메시지 DB 저장
                self.db.save_last_message(user_id, keyword, keyword_message)
            
            logger.info(f"사용자 {user_id} - 배치 뉴스 전송 성공: {total_new_news}건 ({len(all_new_news)}개 키워드)")
        else:
            logger.warning(f"사용자 {user_id} - 배치 뉴스 전송 실패")
    
    def _sort_news_by_date(self, news_list):
        """뉴스를 날짜순으로 정렬 (최신 뉴스가 상단)"""
        try:
            from datetime import datetime
            
            def parse_date(news):
                """뉴스 날짜를 datetime 객체로 변환"""
                try:
                    date_str = news['date']
                    if '+' in date_str or '-' in date_str:
                        dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %z')
                    else:
                        dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S')
                    return dt
                except:
                    return datetime.now()
            
            # 날짜순 정렬 (최신 우선, 내림차순)
            sorted_news = sorted(news_list, key=parse_date, reverse=True)
            return sorted_news
        except Exception as e:
            logger.warning(f"뉴스 정렬 실패: {e}, 원본 순서 유지")
            return news_list
    
    def _get_news_icon(self, news):
        """뉴스 아이콘 결정 (유사 개수 및 특수 키워드 기반)"""
        title = news.get('title', '')
        similar_count = news.get('similar_count', 1)
        
        # 제목에 [단독], [속보], [긴급] 또는 (단독), (속보), (긴급) 포함 시 별표
        special_keywords = ['[단독]', '[속보]', '[긴급]', '(단독)', '(속보)', '(긴급)']
        if any(keyword in title for keyword in special_keywords):
            return '⭐'
        
        # 유사 개수에 따른 아이콘
        if similar_count >= 5:
            return '🔥🔥'
        elif similar_count >= 2:
            return '🔥'
        else:
            return '🔹'  # 1건: 현재와 동일
    
    async def _send_news_to_user(self, user_id, keyword, news_list, manual_check=False):
        """특정 사용자에게 뉴스 전송 (키워드별 최적화용)"""
        logger.info(f"사용자 {user_id} - 키워드 '{keyword}': _send_news_to_user 시작, 입력 뉴스 {len(news_list)}개, 수동확인: {manual_check}")
        
        # 방해금지 시간 체크
        if self.is_quiet_time(user_id):
            logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀 ({keyword})")
            return
        
        # 새로운 뉴스만 필터링
        new_news = []
        for news in news_list:
            if not self.db.is_news_sent(user_id, keyword, news['url']):
                new_news.append(news)
        
        logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 새로운 뉴스 {len(new_news)}개 (전체 {len(news_list)}개 중)")
        
        # 새로운 뉴스가 0개인 경우 추가 정보 로그
        if len(new_news) == 0:
            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 모든 뉴스가 이미 본 뉴스입니다.")
            # 이미 본 뉴스로 채우기 시도
            if len(news_list) > 0:
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스로 15개 채우기 시도")
                base_keywords = self.normalize_keyword(keyword)
                additional_news = self._get_additional_news(user_id, keyword, base_keywords, 15)
                if additional_news:
                    new_news = additional_news
                    logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 {len(additional_news)}개 추가")
                else:
                    logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 추가할 이미 본 뉴스 없음")
        
        # 새 뉴스를 날짜순으로 정렬 (최신 뉴스가 상단에 오도록)
        if new_news:
            new_news = self._sort_news_by_date(new_news)
            
            # 새 뉴스가 15개 미만이면 이미 본 뉴스로 채우기
            if len(new_news) < 15:
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 새로운 뉴스 {len(new_news)}개, 이미 본 뉴스로 {15 - len(new_news)}개 추가")
                base_keywords = self.normalize_keyword(keyword)
                additional_news = self._get_additional_news(user_id, keyword, base_keywords, 15 - len(new_news))
                if additional_news:
                    new_news.extend(additional_news)
                    new_news = self._sort_news_by_date(new_news)
                    logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 총 {len(new_news)}개 뉴스로 채움")
        
        # 새 뉴스가 있으면 전송
        if new_news:
            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 메시지 생성 시작")
            
            # 총 관련 기사 수 계산
            total_similar = sum(news.get('similar_count', 1) for news in new_news)
            
            # 새로운 뉴스와 이미 본 뉴스 구분
            new_count = len([news for news in new_news if not self.db.is_news_sent(user_id, keyword, news['url'])])
            seen_count = len(new_news) - new_count
            
            if seen_count > 0:
                message = f"📰 <b>새로운 뉴스</b> (키워드: {keyword})\n"
                message += f"새로운 뉴스 {new_count}건 + 이미 본 뉴스 {seen_count}건 = 총 {len(new_news)}건\n"
            else:
                message = f"📰 <b>새로운 뉴스</b> (키워드: {keyword})\n"
                message += f"총 {len(new_news)}건\n"
            message += "──────────────\n\n"
            
            for i, news in enumerate(new_news, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                similar_count = news.get('similar_count', 1)
                
                # 뉴스 아이콘 결정
                icon = self._get_news_icon(news)
                
                # 제목 (아이콘 + 제목)
                message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                
                # 관련뉴스 개수 표시
                # ⭐(단독/속보/긴급)는 2건 이상일 때만, 다른 아이콘은 2건 이상일 때 표시
                if icon == '⭐':
                    if similar_count >= 2:
                        message += f" [관련뉴스: {similar_count}건]"
                elif similar_count > 1:
                    message += f" [관련뉴스: {similar_count}건]"
                
                message += "\n\n"
                
                # 부가 정보는 작고 덜 눈에 띄게
                message += f"<code>{source}, {date}</code>\n"
                message += "──────────────\n\n"
            
            # 메시지 전송 시도
            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 텔레그램 메시지 전송 시도")
            success = await self.send_message_to_user(user_id, message)
            
            # 전송 성공한 경우에만 DB에 기록 및 메시지 저장
            if success:
                for news in new_news:
                    self.db.mark_news_sent(user_id, keyword, news['url'], news['title'])
                # 직전 메시지 DB 저장 (수동 확인용)
                self.db.save_last_message(user_id, keyword, message)
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': {len(new_news)}개의 새 뉴스 전송 성공")
            else:
                logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 뉴스 전송 실패")
        else:
            # 새로운 뉴스가 0개일 때
            if manual_check:
                # 수동 확인일 때만 이미 본 뉴스로 채우기 시도
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 새로운 뉴스 0개, 수동확인으로 이미 본 뉴스로 채우기 시도")
                base_keywords = self.normalize_keyword(keyword)
                additional_news = self._get_additional_news(user_id, keyword, base_keywords, 15)
                if additional_news:
                    new_news = additional_news
                    logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 {len(additional_news)}개 추가")
                    
                    # 이미 본 뉴스로 메시지 생성
                    message = f"📰 <b>최신 뉴스</b> (키워드: {keyword})\n"
                    message += f"💡 <i>이미 확인한 뉴스입니다.</i>\n"
                    message += f"총 {len(new_news)}건\n"
                    message += "──────────────\n\n"
                    
                    for i, news in enumerate(new_news, 1):
                        title = news['title']
                        source = news['source']
                        date = self._format_date_simple(news['date'])
                        url = news['url']
                        similar_count = news.get('similar_count', 1)
                        
                        # 뉴스 아이콘 결정
                        icon = self._get_news_icon(news)
                        
                        # 제목 (아이콘 + 제목)
                        message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                        
                        # 관련뉴스 개수 표시
                        if icon == '⭐':
                            if similar_count >= 2:
                                message += f" [관련뉴스: {similar_count}건]"
                        elif similar_count > 1:
                            message += f" [관련뉴스: {similar_count}건]"
                        
                        message += "\n\n"
                        
                        # 부가 정보
                        message += f"<code>{source}, {date}</code>\n"
                        message += "──────────────\n\n"
                    
                    # 메시지 전송 (DB에는 저장하지 않음 - 이미 본 뉴스이므로)
                    success = await self.send_message_to_user(user_id, message)
                    if success:
                        logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 {len(new_news)}개 전송 성공")
                    else:
                        logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 전송 실패")
                else:
                    logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 추가할 이미 본 뉴스 없음")
            else:
                # 자동 알림일 때는 새로운 뉴스가 없으면 아무것도 보내지 않음
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 새로운 뉴스 없음으로 전송하지 않음 (자동알림)")
    
    def _get_additional_news(self, user_id, keyword, base_keywords, needed_count):
        """이미 본 뉴스 중에서 부족한 만큼 추가 뉴스 선택"""
        try:
            # 기본 키워드들의 뉴스 수집
            all_news = []
            for base_kw in base_keywords:
                news_list = self.news_crawler.get_latest_news(base_kw, last_check_count=50)  # 더 많이 가져오기
                all_news.extend(news_list)
            
            if not all_news:
                return []
            
            # 중복 제거
            seen_urls = set()
            unique_news = []
            for news in all_news:
                if news['url'] not in seen_urls:
                    unique_news.append(news)
                    seen_urls.add(news['url'])
            
            # 날짜순으로 정렬 (최신 뉴스가 상단에 오도록)
            unique_news = self._sort_news_by_date(unique_news)
            
            # 이미 본 뉴스만 필터링
            seen_news = []
            for news in unique_news:
                if self.db.is_news_sent(user_id, keyword, news['url']):
                    seen_news.append(news)
            
            # 부족한 만큼만 선택
            additional_news = seen_news[:needed_count]
            
            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 {len(additional_news)}개 추가")
            return additional_news
            
        except Exception as e:
            logger.error(f"추가 뉴스 선택 중 오류: {e}")
            return []
    
    async def _send_latest_news_message(self, user_id, keyword, base_news_map):
        """최신 뉴스 15개로 메시지 생성해서 전송 (이미 본 뉴스 포함)"""
        # 방해금지 시간 체크
        if self.is_quiet_time(user_id):
            logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀 ({keyword})")
            return
        
        # 기본 키워드들 추출
        base_keywords = self.normalize_keyword(keyword)
        
        # 최신 뉴스 수집 (이미 본 뉴스 포함)
        all_news = []
        for base_kw in base_keywords:
            news_list = base_news_map.get(base_kw, [])
            all_news.extend(news_list)
        
        if not all_news:
            await self.send_message_to_user(user_id, f"📰 '{keyword}' 키워드에 대한 뉴스를 찾을 수 없습니다.")
            return
        
        # 중복 제거
        seen_urls = set()
        unique_news = []
        for news in all_news:
            if news['url'] not in seen_urls:
                unique_news.append(news)
                seen_urls.add(news['url'])
        
        # 날짜순으로 정렬 (최신 뉴스가 상단에 오도록)
        unique_news = self._sort_news_by_date(unique_news)
        
        # 15개로 제한
        latest_news = unique_news[:15]
        
        # 메시지 생성
        message = f"📰 <b>최신 뉴스</b> (키워드: {keyword})\n"
        message += f"💡 <i>이미 확인한 뉴스입니다.</i>\n"
        message += f"총 {len(latest_news)}건\n"
        message += "──────────────\n\n"
        
        for i, news in enumerate(latest_news, 1):
            title = news['title']
            source = news['source']
            date = self._format_date_simple(news['date'])
            url = news['url']
            similar_count = news.get('similar_count', 1)
            
            # 뉴스 아이콘 결정
            icon = self._get_news_icon(news)
            
            # 제목 (아이콘 + 제목)
            message += f"<a href='{url}'><b>{icon} {title}</b></a>"
            
            # 관련뉴스 개수 표시
            if icon == '⭐':
                if similar_count >= 2:
                    message += f" [관련뉴스: {similar_count}건]"
            elif similar_count > 1:
                message += f" [관련뉴스: {similar_count}건]"
            
            message += "\n\n"
            
            # 부가 정보
            message += f"<code>{source}, {date}</code>\n"
            message += "──────────────\n\n"
        
        # 메시지 전송 (DB에는 저장하지 않음 - 이미 본 뉴스이므로)
        success = await self.send_message_to_user(user_id, message)
        if success:
            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 최신 뉴스 {len(latest_news)}개 전송 성공")
        else:
            logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 최신 뉴스 전송 실패")
    
    async def _send_seen_news_message(self, user_id, keyword, base_keywords):
        """이미 본 뉴스 15개로 메시지 생성해서 전송"""
        # 방해금지 시간 체크
        if self.is_quiet_time(user_id):
            logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀 ({keyword})")
            return
        
        try:
            # 기본 키워드들의 뉴스 수집
            all_news = []
            for base_kw in base_keywords:
                news_list = self.news_crawler.get_latest_news(base_kw, last_check_count=50)  # 더 많이 가져오기
                all_news.extend(news_list)
                await asyncio.sleep(0.3)  # API 부하 분산
            
            if not all_news:
                await self.send_message_to_user(user_id, f"📰 '{keyword}' 키워드에 대한 뉴스를 찾을 수 없습니다.")
                return
            
            # 중복 제거
            seen_urls = set()
            unique_news = []
            for news in all_news:
                if news['url'] not in seen_urls:
                    unique_news.append(news)
                    seen_urls.add(news['url'])
            
            # 날짜순으로 정렬 (최신 뉴스가 상단에 오도록)
            unique_news = self._sort_news_by_date(unique_news)
            
            # 이미 본 뉴스만 필터링
            seen_news = []
            for news in unique_news:
                if self.db.is_news_sent(user_id, keyword, news['url']):
                    seen_news.append(news)
            
            if not seen_news:
                await self.send_message_to_user(user_id, f"📰 '{keyword}' 키워드에 대한 뉴스를 찾을 수 없습니다.")
                return
            
            # 15개로 제한
            latest_news = seen_news[:15]
            
            # 메시지 생성
            message = f"📰 <b>최신 뉴스</b> (키워드: {keyword})\n"
            message += f"💡 <i>이미 확인한 뉴스입니다.</i>\n"
            message += f"총 {len(latest_news)}건\n"
            message += "──────────────\n\n"
            
            for i, news in enumerate(latest_news, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                similar_count = news.get('similar_count', 1)
                
                # 뉴스 아이콘 결정
                icon = self._get_news_icon(news)
                
                # 제목 (아이콘 + 제목)
                message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                
                # 관련뉴스 개수 표시
                if icon == '⭐':
                    if similar_count >= 2:
                        message += f" [관련뉴스: {similar_count}건]"
                elif similar_count > 1:
                    message += f" [관련뉴스: {similar_count}건]"
                
                message += "\n\n"
                
                # 부가 정보
                message += f"<code>{source}, {date}</code>\n"
                message += "──────────────\n\n"
            
            # 메시지 전송 (DB에는 저장하지 않음 - 이미 본 뉴스이므로)
            success = await self.send_message_to_user(user_id, message)
            if success:
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 {len(latest_news)}개 전송 성공")
            else:
                logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 이미 본 뉴스 전송 실패")
                
        except Exception as e:
            logger.error(f"이미 본 뉴스 메시지 생성 중 오류: {e}")
            await self.send_message_to_user(user_id, f"❌ '{keyword}' 키워드 처리 중 오류가 발생했습니다.")
    
    async def check_news_for_user(self, user_id, manual_check=False):
        """특정 사용자의 뉴스 확인 (수동 확인은 최신 뉴스 또는 직전 메시지 재전송)"""
        keywords = self.db.get_keywords(user_id)
        
        if not keywords:
            logger.info(f"사용자 {user_id} - 등록된 키워드가 없습니다.")
            return
        
        if manual_check:
            # 수동 확인: 최신 뉴스 확인 후, 없으면 직전 메시지 재전송
            for keyword in keywords:
                logger.info(f"사용자 {user_id} - {keyword} 수동 확인")
                
                try:
                    # 1. 기본 키워드들 추출
                    base_keywords = self.normalize_keyword(keyword)
                    
                    # 2. 각 기본 키워드의 뉴스 수집
                    base_news_map = {}
                    for base_kw in base_keywords:
                        news_list = self.news_crawler.get_latest_news(base_kw, last_check_count=15)
                        base_news_map[base_kw] = news_list
                        await asyncio.sleep(0.3)  # API 부하 분산
                    
                    # 3. 복합연산 적용
                    combined_news = self.apply_operation(keyword, base_news_map)
                    logger.info(f"사용자 {user_id} - {keyword} 복합연산 결과: {len(combined_news)}개 뉴스")
                    
                    if combined_news:
                        # 4. 새로운 뉴스가 있으면 전송 + DB 저장
                        logger.info(f"사용자 {user_id} - {keyword} 새로운 뉴스 처리 시작")
                        await self._send_news_to_user(user_id, keyword, combined_news, manual_check=True)
                    else:
                        # 5. 새로운 뉴스가 없으면 이미 본 뉴스 15개로 메시지 생성해서 전송
                        logger.info(f"사용자 {user_id} - {keyword} 새로운 뉴스 없음, 이미 본 뉴스 15개로 메시지 생성")
                        await self._send_seen_news_message(user_id, keyword, base_keywords)
                        
                except Exception as e:
                    logger.error(f"수동 확인 처리 중 오류: {e}")
                    await self.send_message_to_user(user_id, f"❌ '{keyword}' 키워드 처리 중 오류가 발생했습니다.")
        else:
            # 자동 확인: 기존 로직 (새로운 뉴스 없으면 아무것도 안 보냄)
            for keyword in keywords:
                try:
                    await self._check_news_for_keyword(user_id, keyword, manual_check=manual_check)
                    # 키워드 간 딜레이 (수동 확인 시에도 적용)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"사용자 {user_id} - 뉴스 확인 중 오류 ({keyword}): {e}")
    
    async def _check_news_for_keyword(self, user_id, keyword, manual_check=False):
        """특정 사용자의 키워드에 대한 뉴스 확인"""
        # 방해금지 시간 체크 (수동 확인 시에는 무시)
        if not manual_check and self.is_quiet_time(user_id):
            logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀")
            return
        
        # 네이버 최신 뉴스 (15개) 가져오기
        news_list = self.news_crawler.get_latest_news(keyword, last_check_count=15)
        
        if not news_list:
            if manual_check:
                await self.send_message_to_user(
                    user_id,
                    f"⚠️ 키워드 '<b>{keyword}</b>'에 대한 뉴스를 찾을 수 없습니다."
                )
            return
        
        # 새로운 뉴스만 필터링
        new_news = []
        for news in news_list:
            if not self.db.is_news_sent(user_id, keyword, news['url']):
                new_news.append(news)
        
        # 새 뉴스를 날짜순으로 정렬 (최신 뉴스가 상단에 오도록)
        if new_news:
            new_news = self._sort_news_by_date(new_news)
        
        # 새 뉴스가 있으면 하나의 메시지로 전송
        if new_news:
            # 총 관련 기사 수 계산
            total_similar = sum(news.get('similar_count', 1) for news in new_news)
            
            message = f"📰 <b>새로운 뉴스</b> (키워드: {keyword})\n"
            message += f"총 {len(new_news)}건\n"
            message += "──────────────\n\n"
            
            for i, news in enumerate(new_news, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                similar_count = news.get('similar_count', 1)
                
                # 뉴스 아이콘 결정
                icon = self._get_news_icon(news)
                
                # 제목 (아이콘 + 제목)
                message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                
                # 관련뉴스 개수 표시
                # ⭐(단독/속보/긴급)는 2건 이상일 때만, 다른 아이콘은 2건 이상일 때 표시
                if icon == '⭐':
                    if similar_count >= 2:
                        message += f" [관련뉴스: {similar_count}건]"
                elif similar_count > 1:
                    message += f" [관련뉴스: {similar_count}건]"
                
                message += "\n\n"
                
                # 부가 정보는 작고 덜 눈에 띄게
                message += f"<code>{source}, {date}</code>\n"
                message += "──────────────\n\n"
            
            # 메시지 전송 시도
            success = await self.send_message_to_user(user_id, message)
            
            # 전송 성공한 경우에만 DB에 기록
            if success:
                for news in new_news:
                    self.db.mark_news_sent(user_id, keyword, news['url'], news['title'])
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': {len(new_news)}개의 새 뉴스 전송 성공")
            else:
                logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 뉴스 전송 실패, DB 기록 안 함 (다음에 재시도)")
        
        elif manual_check:
            # 수동 확인 시 새 뉴스가 없으면 최신 뉴스 표시 (이미 본 뉴스)
            # 날짜순으로 정렬
            sorted_news_list = self._sort_news_by_date(news_list)
            total_similar = sum(news.get('similar_count', 1) for news in sorted_news_list)
            
            message = f"📰 <b>최신 뉴스</b> (키워드: {keyword})\n"
            message += f"💡 <i>이미 확인한 뉴스입니다.</i>\n"
            message += f"총 {len(sorted_news_list)}건\n"
            message += "──────────────\n\n"
            
            for i, news in enumerate(sorted_news_list, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                similar_count = news.get('similar_count', 1)
                
                # 뉴스 아이콘 결정
                icon = self._get_news_icon(news)
                
                # 제목 (아이콘 + 제목)
                message += f"<a href='{url}'><b>{icon} {title}</b></a>"
                
                # 관련뉴스 개수 표시
                # ⭐(단독/속보/긴급)는 2건 이상일 때만, 다른 아이콘은 2건 이상일 때 표시
                if icon == '⭐':
                    if similar_count >= 2:
                        message += f" [관련뉴스: {similar_count}건]"
                elif similar_count > 1:
                    message += f" [관련뉴스: {similar_count}건]"
                
                message += "\n\n"
                
                # 부가 정보는 작고 덜 눈에 띄게
                message += f"<code>{source}, {date}</code>\n"
                message += "──────────────\n\n"
            
            # 메시지 전송 (DB에는 기록하지 않음 - 이미 기록되어 있음)
            await self.send_message_to_user(user_id, message)
            logger.info(f"사용자 {user_id} - 키워드 '{keyword}': 수동 확인, 기존 뉴스 {len(news_list)}개 표시")
    
    def _format_date_simple(self, date_str):
        """날짜 포맷 변환 (간소화 + 몇 분 전)"""
        try:
            from datetime import datetime, timezone, timedelta
            
            # "Sat, 18 Oct 2025 10:40:00 +0900" 형식 파싱
            if '+' in date_str:
                # +0900 부분 추출
                parts = date_str.rsplit('+', 1)
                dt_str = parts[0].strip()
                tz_str = parts[1].strip()
                
                # 시간대 정보 파싱 (+0900 = KST)
                tz_hours = int(tz_str[:2])
                tz_minutes = int(tz_str[2:]) if len(tz_str) > 2 else 0
                tz = timezone(timedelta(hours=tz_hours, minutes=tz_minutes))
                
                # 날짜 파싱
                dt = datetime.strptime(dt_str, "%a, %d %b %Y %H:%M:%S")
                dt = dt.replace(tzinfo=tz)
            else:
                dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S")
                dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))  # KST
            
            # 현재 시간 (KST)
            now = datetime.now(timezone(timedelta(hours=9)))
            
            # 시간 차이 계산
            diff = now - dt
            minutes_ago = int(diff.total_seconds() / 60)
            
            # 요일 한글 변환
            weekday_kr = ['월', '화', '수', '목', '금', '토', '일']
            weekday = weekday_kr[dt.weekday()]
            
            # 포맷: 10.18(토) 10:50(6분전)
            if minutes_ago < 1:
                time_ago = "방금"
            elif minutes_ago < 60:
                time_ago = f"{minutes_ago}분전"
            elif minutes_ago < 1440:  # 24시간
                hours_ago = minutes_ago // 60
                time_ago = f"{hours_ago}시간전"
            else:
                days_ago = minutes_ago // 1440
                time_ago = f"{days_ago}일전"
            
            return f"{dt.month}.{dt.day}({weekday}) {dt.strftime('%H:%M')}({time_ago})"
            
        except Exception as e:
            print(f"[DEBUG] 날짜 파싱 오류: {e}")
            # 파싱 실패 시 원본 반환
            return date_str.split('+')[0].strip() if '+' in date_str else date_str
    
    async def send_stock_report(self):
        """주가 리포트 전송 (스케줄러용 - 구버전, 사용 안함)"""
        try:
            report = self.stock_monitor.get_full_report_html()
            await self.send_message_html(report)
            logger.info("주가 리포트 전송 완료")
        except Exception as e:
            logger.error(f"주가 리포트 전송 중 오류: {e}")
    
    async def check_stock_drop_alerts(self):
        """주가 하락 알림 체크 (5%부터 1%p 단위로 100%까지)"""
        try:
            logger.info("=== 주가 하락 알림 체크 시작 ===")
            
            # 나스닥 정보 가져오기 (동기 함수를 별도 스레드에서 실행)
            nasdaq_info = await asyncio.to_thread(self.stock_monitor.get_nasdaq_info)
            if not nasdaq_info:
                logger.warning("나스닥 정보를 가져올 수 없습니다. 주가 알림 건너뜀")
                return
            
            current_price = nasdaq_info['current_price']
            ath_price = nasdaq_info['all_time_high']
            ath_date = nasdaq_info['ath_date'].strftime('%Y-%m-%d')
            drop_percentage = nasdaq_info['drop_percentage']
            
            logger.info(f"나스닥 현재가: ${current_price:,.2f}, 전고점 대비: {drop_percentage:.2f}% 하락")
            
            # 하락률에 따른 레벨 계산 (1%p 단위, 5% 이상만)
            # 5.0~5.9%: 레벨 5, 6.0~6.9%: 레벨 6, 7.0~7.9%: 레벨 7, ...
            current_level = int(drop_percentage)
            
            # 모든 사용자에게 알림
            all_users = self.db.get_all_users()
            logger.info(f"{len(all_users)}명의 사용자에게 알림 확인")
            
            for user_id in all_users:
                try:
                    # 나스닥 알림 설정 확인
                    nasdaq_alert_enabled = self.db.get_nasdaq_alert_setting(user_id)
                    if not nasdaq_alert_enabled:
                        logger.info(f"사용자 {user_id} - 나스닥 알림 비활성화, 건너뜀")
                        continue
                    
                    # 마지막 알림 레벨 확인
                    last_alert = self.db.get_last_stock_alert_level(user_id)
                    
                    # 전고점이 변경되었거나, 레벨이 올라갔을 때만 알림 (각 레벨당 최초 1회)
                    should_alert = False
                    if last_alert is None or last_alert['ath_price'] != ath_price:
                        # 새로운 전고점 또는 첫 알림
                        if current_level >= 5:  # 5% 이상 하락 시에만 알림
                            should_alert = True
                    elif current_level > last_alert['last_level'] and current_level >= 5:
                        # 기존 전고점에서 하락 레벨이 증가 (예: 5% → 10%)
                        should_alert = True
                    
                    if not should_alert:
                        continue
                    
                    # 방해금지 시간 체크
                    if self.is_quiet_time(user_id):
                        logger.info(f"사용자 {user_id} - 방해금지 시간, 주가 알림 대기 중 ({current_level}% 하락)")
                        # DB에 pending 상태로 저장 (방해금지 해제 시 전송)
                        self.db.set_pending_stock_alert(user_id, current_level, ath_price, ath_date, nasdaq_info)
                        continue
                    
                    # 알림 전송 및 성공 시에만 DB 업데이트
                    success = await self._send_drop_alert(user_id, current_level, nasdaq_info)
                    if success:
                        self.db.update_stock_alert_level(user_id, current_level, ath_price, ath_date)
                    else:
                        logger.warning(f"사용자 {user_id} - 주가 알림 전송 실패, DB 업데이트 안 함 (다음에 재시도)")
                    
                    # 사용자 간 딜레이 (메시지 전송 간격 확보)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"사용자 {user_id} - 주가 알림 처리 중 오류: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            logger.info("=== 주가 하락 알림 체크 완료 ===")
                
        except Exception as e:
            logger.error(f"주가 하락 알림 체크 전체 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _send_drop_alert(self, user_id, drop_level, nasdaq_info):
        """주가 하락 알림 전송"""
        # TQQQ 정보 가져오기 (동기 함수를 별도 스레드에서 실행)
        tqqq_info = await asyncio.to_thread(self.stock_monitor.get_tqqq_info)
        if not tqqq_info:
            logger.warning(f"사용자 {user_id} - TQQQ 정보를 가져올 수 없어 알림 전송 실패")
            return False
        
        # TQQQ 시나리오 계산
        scenarios = self.stock_monitor.calculate_tqqq_scenarios(
            nasdaq_info['current_price'],
            nasdaq_info['all_time_high'],
            tqqq_info['current_price']
        )
        
        ath_date_str = nasdaq_info['ath_date'].strftime('%Y-%m-%d')
        
        alert_message = f"""🚨 <b>나스닥 100 하락 알림</b> 🚨

<b>⚠️ 전고점 대비 {drop_level}% 하락!</b>

<b>나스닥 100 (^NDX)</b>
• 현재가: ${nasdaq_info['current_price']:,.2f}
• 전고점: ${nasdaq_info['all_time_high']:,.2f} ({ath_date_str})
• 하락률: ▼ {nasdaq_info['drop_percentage']:.2f}%

<b>TQQQ</b>
• 현재가: ${tqqq_info['current_price']:.2f}

<b>📉 나스닥 100 하락 시 (전고점 대비) TQQQ 예상가</b>
<i>(20거래일 가정, 복리 계산)</i>
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
        
        success = await self.send_message_to_user(user_id, alert_message)
        if success:
            logger.info(f"사용자 {user_id} - 주가 하락 알림 전송 성공: {drop_level}% 레벨")
        return success
    
    async def send_message_to_user(self, user_id, text, parse_mode='HTML'):
        """특정 사용자에게 메시지 전송 (강화된 재시도 로직)"""
        max_retries = 3  # 재시도 횟수
        base_delay = 2  # 기본 대기 시간 (초)
        
        for attempt in range(max_retries):
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True
                )
                
                if attempt > 0:
                    logger.info(f"✅ 사용자 {user_id} - 메시지 전송 성공 ({attempt + 1}번째 시도)")
                
                # 성공 시 짧은 딜레이 (텔레그램 API rate limiting 방지)
                await asyncio.sleep(0.5)
                return True
                
            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__
                
                # 사용자가 봇을 차단한 경우 - 재시도 불필요
                if 'bot was blocked' in error_str or 'Forbidden' in error_type:
                    self.db.add_blocked_user(user_id, 'bot_blocked')
                    logger.warning(f"⚠️ 사용자 {user_id} - 봇 차단됨, DB에 차단 상태 저장")
                    return False
                
                # 재시도 가능한 오류인지 확인
                is_retryable_error = any(err in error_str or err in error_type for err in [
                    'ConnectError', 'NetworkError', 'TimedOut', 'TimeoutError',
                    'ConnectionError', 'ReadTimeout', 'ConnectTimeout',
                    'RemoteDisconnected', 'BadGateway', 'ServiceUnavailable'
                ])
                
                if attempt < max_retries - 1:
                    if is_retryable_error:
                        # 지수 백오프: 3초, 6초, 12초, 24초, 48초
                        wait_time = base_delay * (2 ** attempt)
                        logger.warning(f"🔄 사용자 {user_id} - 네트워크 오류, {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})")
                        logger.debug(f"   오류 상세: {error_type}: {error_str[:150]}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # 재시도 불가능한 오류
                        logger.error(f"❌ 사용자 {user_id} - 재시도 불가능한 오류: {error_type}: {error_str[:150]}")
                        return False
                else:
                    # 최종 실패
                    logger.error(f"❌ 사용자 {user_id} - 메시지 전송 최종 실패 ({max_retries}회 시도)")
                    logger.error(f"   최종 오류: {error_type}: {error_str[:150]}")
                    return False
        
        return False
    
    async def send_message_html(self, text):
        """메시지 전송 (HTML 모드) - TELEGRAM_CHAT_ID 사용 (기존 호환성)"""
        try:
            if TELEGRAM_CHAT_ID:
                await self.application.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=text,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
        except Exception as e:
            logger.error(f"메시지 전송 오류: {e}")
    
    def setup_scheduler(self):
        """스케줄러 설정"""
        # 뉴스 체크 - 정각부터 10분 단위로
        self.scheduler.add_job(
            self.check_news_updates,
            'cron',
            minute='*/10',  # 0, 10, 20, 30, 40, 50분에 실행
            id='news_check',
            max_instances=1,  # 동시 실행 방지
            coalesce=True,    # 누락된 작업 병합
            misfire_grace_time=300  # 5분 이내 누락은 허용
        )
        logger.info("뉴스 체크 스케줄러 등록: 정각부터 10분 단위 (0, 10, 20, 30, 40, 50분)")
        
        # 주가 체크 - 정각부터 2시간 단위로 (0시, 2시, 4시, 6시, 8시, 10시, 12시, 14시, 16시, 18시, 20시, 22시)
        self.scheduler.add_job(
            self.check_stock_drop_alerts,
            'cron',
            hour='*/2',  # 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22시에 실행
            minute=0,    # 정각에 실행
            id='stock_drop_check',
            max_instances=1,  # 동시 실행 방지
            coalesce=True,    # 누락된 작업 병합
            misfire_grace_time=600  # 10분 이내 누락은 허용
        )
        logger.info("주가 하락 알림 스케줄러 등록: 정각부터 2시간 단위 (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22시)")
        
        self.scheduler.start()
        logger.info("스케줄러 시작됨")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """에러 핸들러"""
        # 네트워크 오류는 재시도 로직이 처리하므로 간단히 로그만
        error_str = str(context.error)
        if 'ConnectError' in error_str or 'NetworkError' in error_str or 'TimedOut' in error_str:
            # 네트워크 오류는 WARNING 레벨로 (재시도가 자동으로 처리됨)
            logger.warning(f"네트워크 일시 오류 (자동 재시도 중)")
        else:
            # 다른 오류는 ERROR 레벨로
            logger.error(f"업데이트 처리 중 오류 발생: {context.error}")
    
    def run(self):
        """봇 실행"""
        if not TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
            print("❌ .env 파일에 TELEGRAM_BOT_TOKEN을 설정해주세요.")
            return
        
        # Application 생성 (네트워크 안정성 최적화)
        # 커스텀 HTTPXRequest로 연결 안정성 강화
        request = HTTPXRequest(
            connect_timeout=20.0,       # 연결 타임아웃 20초
            read_timeout=20.0,          # 읽기 타임아웃 20초
            write_timeout=20.0,         # 쓰기 타임아웃 20초
            pool_timeout=20.0,          # 풀 타임아웃 20초
            connection_pool_size=8      # 연결 풀 크기 (적절한 크기로 조정)
        )
        
        self.application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .request(request)
            .get_updates_request(request)
            .build()
        )
        
        # 명령어 핸들러 등록
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("add", self.add_keyword_command))
        self.application.add_handler(CommandHandler("remove", self.remove_keyword_command))
        self.application.add_handler(CommandHandler("removeall", self.remove_all_keywords_command))
        self.application.add_handler(CommandHandler("list", self.list_keywords_command))
        self.application.add_handler(CommandHandler("news", self.check_news_command))
        self.application.add_handler(CommandHandler("stock", self.stock_info_command))
        self.application.add_handler(CommandHandler("setquiet", self.set_quiet_command))
        self.application.add_handler(CommandHandler("users", self.users_command))
        
        # 콜백 쿼리 핸들러 (버튼 클릭)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
        # 텍스트 메시지 핸들러 (대화형 키워드 입력)
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        
        # 에러 핸들러
        self.application.add_error_handler(self.error_handler)
        
        # 스케줄러 설정
        self.setup_scheduler()
        
        # 명령어 메뉴 설정 (텔레그램 자동완성용 - 인자가 필요 없는 명령어만)
        async def post_init(application: Application):
            await application.bot.set_my_commands([
                BotCommand("start", "봇 안내"),
                BotCommand("add", "키워드 추가"),
                BotCommand("list", "키워드 목록"),
                BotCommand("news", "즉시 뉴스 확인"),
                BotCommand("stock", "나스닥 정보"),
                BotCommand("setquiet", "방해금지 시간 설정"),
            ])
        
        self.application.post_init = post_init
        
        # 봇 시작 메시지
        logger.info("=" * 50)
        logger.info("TeleNews Bot 시작됨!")
        logger.info("=" * 50)
        print("\n✅ 봇이 시작되었습니다!")
        print("📱 텔레그램에서 봇과 대화를 시작하세요!")
        print("⌨️  Ctrl+C를 눌러 종료할 수 있습니다.\n")
        
        # 봇 실행
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    bot = TeleNewsBot()
    bot.run()

