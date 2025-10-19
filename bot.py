import asyncio
import logging
from datetime import datetime
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.request import HTTPXRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NEWS_CHECK_INTERVAL, STOCK_ALERT_TIMES
from database import Database
from news_crawler import NaverNewsCrawler
from stock_monitor import StockMonitor

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
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
    
    def is_quiet_time(self, user_id):
        """현재 시간이 사용자의 방해금지 시간인지 확인"""
        quiet_hours = self.db.get_quiet_hours(user_id)
        if not quiet_hours or not quiet_hours['enabled']:
            return False
        
        from datetime import datetime
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        
        start = quiet_hours['start_time']
        end = quiet_hours['end_time']
        
        # 시간 비교 (자정을 넘는 경우도 고려)
        if start <= end:
            # 예: 23:00 ~ 07:00이 아닌 경우 (09:00 ~ 18:00)
            return start <= current_time <= end
        else:
            # 예: 23:00 ~ 07:00 (자정을 넘는 경우)
            return current_time >= start or current_time <= end
    
    async def safe_reply(self, message, text, parse_mode='HTML', reply_markup=None):
        """안전한 메시지 응답 (강화된 재시도 포함)"""
        max_retries = 5  # 재시도 횟수 증가
        base_delay = 3  # 기본 대기 시간 증가
        
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
        """키워드 추가"""
        user_id = update.effective_chat.id
        
        # 인자가 있으면 바로 추가 (예: /add 삼성전자)
        if context.args:
            keyword = ' '.join(context.args)
            if self.db.add_keyword(user_id, keyword):
                await self.safe_reply(update.message, f"✅ 키워드 '{keyword}' 추가되었습니다!")
                logger.info(f"사용자 {user_id} - 키워드 추가됨: {keyword}")
            else:
                await self.safe_reply(update.message, f"⚠️ 키워드 '{keyword}' 이미 등록되어 있습니다.")
        else:
            # 인자가 없으면 대화형 모드 시작
            self.waiting_for_keyword[user_id] = 'add'
            await self.safe_reply(update.message, "📝 추가할 키워드를 입력해주세요:\n\n예시: 삼성전자, AI, 나스닥")
    
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
        keywords = self.db.get_keywords(user_id)
        
        if not keywords:
            await update.message.reply_text("📝 등록된 키워드가 없습니다.\n/add 명령으로 키워드를 추가하세요.")
        else:
            # 키워드 목록 텍스트
            keyword_list = '\n'.join([f"• {kw}" for kw in keywords])
            
            # 각 키워드마다 삭제 버튼 생성
            keyboard = []
            for keyword in keywords:
                keyboard.append([InlineKeyboardButton(f"🗑️ {keyword} 삭제", callback_data=f"remove:{keyword}")])
            
            # 모두 삭제 및 키워드 추가 버튼
            keyboard.append([InlineKeyboardButton("🗑️ 모두 삭제", callback_data="removeall")])
            keyboard.append([InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📝 <b>등록된 키워드 목록:</b>\n\n{keyword_list}\n\n버튼을 눌러 관리할 수 있습니다:", 
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
        
        # 현재 설정 정보
        if quiet_hours:
            status = "🔕 활성화" if quiet_hours['enabled'] else "🔔 비활성화"
            current_info = f"\n\n📌 현재 설정: {quiet_hours['start_time']} ~ {quiet_hours['end_time']} ({status})"
        else:
            current_info = "\n\n📌 현재 설정 없음"
        
        # 시작 시간 선택 버튼
        keyboard = [
            [InlineKeyboardButton("⏰ 시작 시간 선택", callback_data="quiet:select_start")]
        ]
        
        # 해제 버튼 (이미 설정이 있을 때만)
        if quiet_hours and quiet_hours['enabled']:
            keyboard.append([InlineKeyboardButton("🔔 방해금지 해제", callback_data="quiet:off")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔕 <b>방해금지 시간 설정</b>{current_info}\n\n"
            "시작 시간과 종료 시간을 각각 선택할 수 있습니다.\n\n"
            "💡 설정한 시간대에는 자동 알림이 전송되지 않습니다.",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """인라인 버튼 클릭 처리"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data == "removeall":
            # 모두 삭제
            deleted_count = self.db.remove_all_keywords(user_id)
            if deleted_count > 0:
                await query.edit_message_text(f"✅ 모든 키워드가 제거되었습니다. (총 {deleted_count}개)")
                logger.info(f"사용자 {user_id} - 모든 키워드 제거됨 ({deleted_count}개)")
            else:
                await query.edit_message_text("📝 제거할 키워드가 없습니다.")
        
        elif data.startswith("remove:"):
            # 개별 키워드 삭제
            keyword = data.split(":", 1)[1]
            if self.db.remove_keyword(user_id, keyword):
                # 키워드 제거 후 남은 키워드 목록 다시 표시
                keywords = self.db.get_keywords(user_id)
                
                if keywords:
                    keyword_list = '\n'.join([f"• {kw}" for kw in keywords])
                    keyboard = []
                    for kw in keywords:
                        keyboard.append([InlineKeyboardButton(f"🗑️ {kw} 삭제", callback_data=f"remove:{kw}")])
                    keyboard.append([InlineKeyboardButton("🗑️ 모두 삭제", callback_data="removeall")])
                    keyboard.append([InlineKeyboardButton("➕ 키워드 추가", callback_data="add_keyword")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        f"✅ '{keyword}' 제거됨!\n\n📝 <b>남은 키워드:</b>\n\n{keyword_list}\n\n버튼을 눌러 관리할 수 있습니다:",
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                else:
                    await query.edit_message_text("✅ 모든 키워드가 제거되었습니다!")
                
                logger.info(f"사용자 {user_id} - 키워드 제거됨: {keyword}")
            else:
                await query.edit_message_text(f"❌ 키워드 '{keyword}'를 찾을 수 없습니다.")
        
        elif data.startswith("quiet:") or data.startswith("quiet-"):
            # 방해금지 시간 설정
            if data == "quiet:off":
                # 방해금지 해제
                if self.db.disable_quiet_hours(user_id):
                    await query.edit_message_text("🔔 방해금지 시간이 해제되었습니다!")
                    logger.info(f"사용자 {user_id} - 방해금지 시간 해제")
                    
                    # 대기 중인 주가 알림 확인 및 전송
                    pending = self.db.get_pending_stock_alert(user_id)
                    if pending:
                        logger.info(f"사용자 {user_id} - 대기 중인 주가 알림 전송: {pending['alert_level']}% 하락")
                        # 나스닥 정보 재구성
                        nasdaq_info_dict = pending['nasdaq_info']
                        from datetime import datetime
                        nasdaq_info_dict['ath_date'] = datetime.strptime(nasdaq_info_dict['ath_date'], '%Y-%m-%d')
                        
                        # 알림 전송
                        success = await self._send_drop_alert(user_id, pending['alert_level'], nasdaq_info_dict)
                        if success:
                            self.db.update_stock_alert_level(user_id, pending['alert_level'], pending['ath_price'], pending['ath_date'])
                            self.db.clear_pending_stock_alert(user_id)
                else:
                    await query.edit_message_text("⚠️ 설정된 방해금지 시간이 없습니다.")
            
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
                    "알림을 받지 않을 시작 시간을 선택하세요:",
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
                    f"알림을 다시 받을 종료 시간을 선택하세요:",
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
                await query.edit_message_text(
                    f"✅ 방해금지 시간이 설정되었습니다!\n\n"
                    f"🔕 {start_time} ~ {end_time}\n\n"
                    f"이 시간대에는 자동 알림이 전송되지 않습니다.\n"
                    f"(수동 명령어는 사용 가능합니다)"
                )
                logger.info(f"사용자 {user_id} - 방해금지 시간 설정: {start_time} ~ {end_time}")
        
        elif data == "add_keyword":
            # 키워드 추가 버튼
            self.waiting_for_keyword[user_id] = 'add'
            await query.edit_message_text(
                "📝 <b>키워드 추가</b>\n\n"
                "추가할 키워드를 입력해주세요:\n\n"
                "예시: 삼성전자, AI, 나스닥, 경제",
                parse_mode='HTML'
            )
            logger.info(f"사용자 {user_id} - 키워드 추가 대기 모드 진입")
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """일반 텍스트 메시지 처리 (대화형 키워드 입력 + 버튼 클릭)"""
        user_id = update.effective_chat.id
        text = update.message.text
        
        # 메인 메뉴 버튼 처리
        if text == "📋 키워드 목록":
            await self.list_keywords_command(update, None)
            return
        elif text == "📰 즉시 뉴스 확인":
            await self.check_news_command(update, None)
            return
        elif text == "📊 주가 정보":
            await self.stock_info_command(update, None)
            return
        elif text == "🔕 방해금지 설정":
            await self.set_quiet_command(update, None)
            return
        
        # 사용자가 키워드 입력 대기 중인지 확인
        if user_id in self.waiting_for_keyword:
            action = self.waiting_for_keyword[user_id]
            del self.waiting_for_keyword[user_id]
            
            if action == 'add':
                keyword = text.strip()
                if self.db.add_keyword(user_id, keyword):
                    await update.message.reply_text(f"✅ 키워드 '{keyword}'가 추가되었습니다!")
                    logger.info(f"사용자 {user_id} - 키워드 추가됨: {keyword}")
                else:
                    await update.message.reply_text(f"⚠️ 키워드 '{keyword}'는 이미 등록되어 있습니다.")
    
    async def check_news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """수동으로 뉴스 확인"""
        user_id = update.effective_chat.id
        
        # 키워드가 있는지 먼저 확인
        keywords = self.db.get_keywords(user_id)
        if not keywords:
            await self.send_message_to_user(
                user_id, 
                "⚠️ <b>등록된 키워드가 없습니다.</b>\n\n"
                "➕ 키워드 추가 버튼을 눌러 키워드를 먼저 등록해주세요!"
            )
            return
        
        await update.message.reply_text("🔍 뉴스를 확인하고 있습니다...")
        await self.check_news_for_user(user_id, manual_check=True)
    
    async def stock_info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """주가 정보 확인"""
        await update.message.reply_text("📊 주가 정보를 가져오는 중...")
        # 동기 함수를 별도 스레드에서 실행
        report = await asyncio.to_thread(self.stock_monitor.get_full_report_html)
        await update.message.reply_text(report, parse_mode='HTML')
    
    async def check_news_updates(self):
        """뉴스 업데이트 확인 (스케줄러용 - 모든 사용자, 키워드별 최적화)"""
        try:
            logger.info("=== 뉴스 업데이트 체크 시작 ===")
            
            # 30일 이상 오래된 뉴스 기록 삭제
            self.db.cleanup_old_news(days=30)
            
            user_keywords = self.db.get_all_user_keywords()
            
            if not user_keywords:
                logger.info("등록된 키워드가 없습니다.")
                return
            
            # 키워드별로 그룹화 (최적화!) ⭐
            from collections import defaultdict
            keyword_users = defaultdict(list)  # {keyword: [user_id1, user_id2, ...]}
            for user_id, keyword in user_keywords:
                keyword_users[keyword].append(user_id)
            
            logger.info(f"중복 제거: 총 {len(user_keywords)}개 → {len(keyword_users)}개 고유 키워드")
            logger.info(f"{len(set(uid for uid, _ in user_keywords))}명의 사용자")
            
            # 키워드별로 한 번씩만 크롤링 (최적화!)
            for keyword, user_ids in keyword_users.items():
                try:
                    # 키워드 1번 크롤링
                    news_list = self.news_crawler.get_latest_news(keyword, last_check_count=10)
                    
                    if not news_list:
                        logger.info(f"키워드 '{keyword}': 뉴스 없음")
                        continue
                    
                    logger.info(f"키워드 '{keyword}': {len(news_list)}개 뉴스 수집, {len(user_ids)}명에게 전송")
                    
                    # 같은 키워드를 등록한 모든 사용자에게 전송
                    for user_id in user_ids:
                        try:
                            await self._send_news_to_user(user_id, keyword, news_list)
                        except Exception as e:
                            logger.error(f"사용자 {user_id} - 뉴스 전송 중 오류 ({keyword}): {e}")
                    
                    # 키워드 간 딜레이 (API 부하 분산)
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"키워드 '{keyword}' 처리 중 오류: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            logger.info("=== 뉴스 업데이트 체크 완료 ===")
        except Exception as e:
            logger.error(f"뉴스 업데이트 체크 전체 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _send_news_to_user(self, user_id, keyword, news_list):
        """특정 사용자에게 뉴스 전송 (키워드별 최적화용)"""
        # 방해금지 시간 체크
        if self.is_quiet_time(user_id):
            logger.info(f"사용자 {user_id} - 방해금지 시간, 뉴스 알림 건너뜀 ({keyword})")
            return
        
        # 새로운 뉴스만 필터링
        new_news = []
        for news in news_list:
            if not self.db.is_news_sent(user_id, keyword, news['url']):
                new_news.append(news)
        
        # 새 뉴스가 있으면 전송
        if new_news:
            message = f"📰 <b>새로운 뉴스</b> (키워드: {keyword})\n"
            message += f"총 {len(new_news)}개\n"
            message += f"<i>💡 네이버에 방금 등록된 뉴스입니다</i>\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for i, news in enumerate(new_news, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                
                # 제목을 크고 강조
                message += f"<a href='{url}'><b>🔹 {title}</b></a>\n\n"
                
                # 부가 정보는 작고 덜 눈에 띄게
                message += f"<code>{source}, {date}</code>\n"
                message += "────────────────────\n\n"
            
            # 메시지 전송 시도
            success = await self.send_message_to_user(user_id, message)
            
            # 전송 성공한 경우에만 DB에 기록
            if success:
                for news in new_news:
                    self.db.mark_news_sent(user_id, keyword, news['url'], news['title'])
                logger.info(f"사용자 {user_id} - 키워드 '{keyword}': {len(new_news)}개의 새 뉴스 전송 성공")
            else:
                logger.warning(f"사용자 {user_id} - 키워드 '{keyword}': 뉴스 전송 실패")
    
    async def check_news_for_user(self, user_id, manual_check=False):
        """특정 사용자의 뉴스 확인 (내부 함수, 메시지 없음)"""
        keywords = self.db.get_keywords(user_id)
        
        if not keywords:
            logger.info(f"사용자 {user_id} - 등록된 키워드가 없습니다.")
            return
        
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
        
        # 네이버 첫 페이지 분량 (10개) 가져오기
        news_list = self.news_crawler.get_latest_news(keyword, last_check_count=10)
        
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
        
        # 새 뉴스가 있으면 하나의 메시지로 전송
        if new_news:
            message = f"📰 <b>새로운 뉴스</b> (키워드: {keyword})\n"
            message += f"총 {len(new_news)}개\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for i, news in enumerate(new_news, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                
                # 제목을 크고 강조
                message += f"<a href='{url}'><b>🔹 {title}</b></a>\n\n"
                
                # 부가 정보는 작고 덜 눈에 띄게 (코드 블록 스타일)
                message += f"<code>{source}, {date}</code>\n"
                message += "────────────────────\n\n"
            
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
            message = f"📰 <b>최신 뉴스</b> (키워드: {keyword})\n"
            message += f"💡 <i>이미 확인한 뉴스입니다</i>\n"
            message += f"총 {len(news_list)}개\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for i, news in enumerate(news_list, 1):
                title = news['title']
                source = news['source']
                date = self._format_date_simple(news['date'])
                url = news['url']
                
                # 제목을 크고 강조
                message += f"<a href='{url}'><b>🔹 {title}</b></a>\n\n"
                
                # 부가 정보는 작고 덜 눈에 띄게 (코드 블록 스타일)
                message += f"<code>{source}, {date}</code>\n"
                message += "────────────────────\n\n"
            
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
            
            # 포맷: 10.18(토) 18:26 🆕 (발행 시간 + 새 뉴스 표시)
            # 현재 시간과 비교하여 최근성 표시
            if minutes_ago < 15:
                time_badge = " 🔥"  # 15분 이내: 초속보
            elif minutes_ago < 60:
                time_badge = " 🆕"  # 1시간 이내: 새 뉴스
            else:
                time_badge = " (방금 발견)"  # 1시간 이상: 네이버 늦은 등록
            
            return f"{dt.month}.{dt.day}({weekday}) {dt.strftime('%H:%M')}{time_badge}"
            
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

<b>📉 추가 하락 시 TQQQ 예상가</b>
<i>(20거래일 가정, 복리 계산)</i>
• 전고점 대비 20% 하락 시: ${scenarios['20%']:.2f}
• 전고점 대비 30% 하락 시: ${scenarios['30%']:.2f}
• 전고점 대비 40% 하락 시: ${scenarios['40%']:.2f}
"""
        
        success = await self.send_message_to_user(user_id, alert_message)
        if success:
            logger.info(f"사용자 {user_id} - 주가 하락 알림 전송 성공: {drop_level}% 레벨")
        return success
    
    async def send_message_to_user(self, user_id, text, parse_mode='HTML'):
        """특정 사용자에게 메시지 전송 (강화된 재시도 로직)"""
        max_retries = 5  # 재시도 횟수 증가
        base_delay = 3  # 기본 대기 시간 증가 (초)
        
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
                    logger.warning(f"⚠️ 사용자 {user_id} - 봇 차단됨, 재시도 안 함")
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
    
    async def heartbeat(self):
        """스케줄러 상태 확인 (heartbeat)"""
        logger.info("💓 봇 정상 작동 중...")
    
    def setup_scheduler(self):
        """스케줄러 설정"""
        # Heartbeat - 15분마다 (봇이 살아있음을 확인)
        self.scheduler.add_job(
            self.heartbeat,
            'interval',
            minutes=15,
            id='heartbeat'
        )
        logger.info("Heartbeat 스케줄러 등록: 15분 간격")
        
        # 뉴스 체크 - 주기적으로
        self.scheduler.add_job(
            self.check_news_updates,
            'interval',
            minutes=NEWS_CHECK_INTERVAL,
            id='news_check',
            max_instances=1,  # 동시 실행 방지
            coalesce=True,    # 누락된 작업 병합
            misfire_grace_time=300  # 5분 이내 누락은 허용
        )
        logger.info(f"뉴스 체크 스케줄러 등록: {NEWS_CHECK_INTERVAL}분 간격")
        
        # 주가 체크 - 2시간마다 (하락률 기반 알림)
        self.scheduler.add_job(
            self.check_stock_drop_alerts,
            'interval',
            hours=2,
            id='stock_drop_check',
            max_instances=1,  # 동시 실행 방지
            coalesce=True,    # 누락된 작업 병합
            misfire_grace_time=600  # 10분 이내 누락은 허용
        )
        logger.info("주가 하락 알림 스케줄러 등록: 2시간 간격 (5%부터 1%p 단위로 최초 1회 알림)")
        
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

