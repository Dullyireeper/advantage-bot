import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

from config import Config
from database import (
    init_db, User, Ad, AdView, SocialProfile, SocialTask,
    SocialTaskCompletion, Deposit, Withdrawal, BalanceHistory,
    DailyStreak, Achievement, PremiumPackage, PremiumOrder
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("advantage-bot")


def now():
    return datetime.utcnow()


def money(value):
    return f"${float(value or 0):.2f}"


def valid_url(value):
    try:
        p = urlparse(value)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


class AdVantageBot:
    def __init__(self):
        Config.validate()
        self.SessionLocal = init_db()
        self.application = None

    def session(self):
        return self.SessionLocal()

    def is_admin(self, telegram_id):
        return telegram_id in Config.ADMIN_IDS

    def log_balance(self, db, user, amount, kind, description):
        before = float(user.balance or 0)
        user.balance = before + amount
        db.add(BalanceHistory(
            user_id=user.telegram_id,
            amount=amount,
            type=kind,
            description=description[:200],
            balance_before=before,
            balance_after=user.balance,
        ))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = self.session()
        try:
            tg = update.effective_user
            user = db.query(User).filter_by(telegram_id=tg.id).first()

            if not user:
                user = User(
                    telegram_id=tg.id,
                    username=tg.username,
                    first_name=tg.first_name,
                    last_name=tg.last_name,
                    join_date=now(),
                    is_admin=self.is_admin(tg.id),
                )
                db.add(user)
                db.flush()

                if context.args and context.args[0].isdigit():
                    referrer_id = int(context.args[0])
                    if referrer_id != tg.id:
                        referrer = db.query(User).filter_by(telegram_id=referrer_id).first()
                        if referrer:
                            user.referred_by = referrer_id
                            self.log_balance(
                                db, referrer, Config.REFERRAL_BONUS,
                                "referral", f"Referral bonus for {tg.id}"
                            )
                            referrer.total_earned += Config.REFERRAL_BONUS

            user.is_admin = self.is_admin(tg.id)
            user.last_active = now()
            db.commit()

            await self.show_main_menu(update, user)
        except Exception:
            db.rollback()
            logger.exception("start_command failed")
            if update.message:
                await update.message.reply_text("⚠️ Something went wrong. Please try again.")
        finally:
            db.close()

        async def show_main_menu(self, update_or_query, user):
        keyboard = [
            [InlineKeyboardButton("📺 Watch Ads", callback_data="watch_ads"),
             InlineKeyboardButton("📋 Daily Tasks", callback_data="daily_tasks")],
            [InlineKeyboardButton("🎮 Mini Games", callback_data="mini_games"),
             InlineKeyboardButton("💎 Premium Growth", callback_data="premium_menu")],
            [InlineKeyboardButton("📱 Social Tasks", callback_data="social_menu"),
             InlineKeyboardButton("👥 Referrals", callback_data="referral")],
            [InlineKeyboardButton("💳 Payments", callback_data="payment_menu"),
             InlineKeyboardButton("👤 My Profile", callback_data="profile")],
        ]

        if user and self.is_admin(user.telegram_id):
            keyboard.append([
                InlineKeyboardButton(
                    "⚙️ Admin Panel",
                    callback_data="admin_panel"
                )
            ])

        text = (
            "🎯 <b>WELCOME TO ADVANTAGE</b> 🎯\n\n"
            "<b>Turn your time into opportunities. 🚀</b>\n\n"
            "Advantage is a digital rewards and growth platform where you can "
            "complete tasks, discover opportunities, earn rewards, grow your "
            "social presence, and benefit from our referral program.\n\n"
            "💰 <b>Earn Rewards</b>\n"
            "📋 <b>Complete Tasks</b>\n"
            "📱 <b>Social Growth</b>\n"
            "👥 <b>Refer & Earn</b>\n"
            "💎 <b>Premium Growth</b>\n"
            "🏆 <b>Track Your Progress</b>\n\n"
            "🌍 <b>Built for everyone. Growing globally.</b>\n\n"
            "Choose a service below to get started! 🚀"
        )

        markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await update_or_query.edit_message_text(
                text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        db = self.session()
        try:
            user = db.query(User).filter_by(telegram_id=update.effective_user.id).first()
            if not user:
                await query.edit_message_text("Please send /start first.")
                return
            user.last_active = now()
            data = query.data

            if data == "profile":
                await self.show_profile(query, db, user)
            elif data == "watch_ads":
                await self.show_ads(query, db, user)
            elif data.startswith("ad_watched_"):
                await self.ad_watched(query, db, user, data.split("_")[-1])
            elif data == "daily_tasks":
                await self.show_tasks(query, db, user)
            elif data.startswith("social_task_"):
                await self.complete_social_task(query, db, user, data.split("_")[-1])
            elif data == "social_menu":
                await self.show_social_menu(query, db, user)
            elif data == "mini_games":
                await self.show_games(query, db, user)
            elif data == "premium_menu":
                await self.show_premium(query, db, user)
            elif data == "payment_menu":
                await self.show_payment_menu(query, db, user)
            elif data == "referral":
                await self.show_referral(query, db, user)
            elif data == "admin_panel":
                await self.show_admin_panel(query, db, user)
            elif data == "admin_withdrawals":
                await self.show_pending_withdrawals(query, db, user)
            elif data == "back_to_menu":
                await self.show_main_menu(query, user)
            elif data.startswith("approve_w_"):
                await self.approve_withdrawal(query, db, user, data.split("_")[-1])
            elif data.startswith("reject_w_"):
                await self.reject_withdrawal(query, db, user, data.split("_")[-1])
            else:
                await query.edit_message_text("❌ Unknown action.")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("callback failed")
            try:
                await query.edit_message_text("⚠️ Something went wrong. Please try again.")
            except Exception:
                pass
        finally:
            db.close()

    async def show_profile(self, query, db, user):
        streak = db.query(DailyStreak).filter_by(user_id=user.telegram_id).first()
        refs = db.query(User).filter_by(referred_by=user.telegram_id).count()
        text = (
            "👤 <b>PROFILE</b>\n\n"
            "📱 Username: @{}\n"
            "📅 Joined: {}\n"
            "💰 Balance: <b>{}</b>\n"
            "💵 Total earned: <b>{}</b>\n"
            "🏦 Withdrawn: <b>{}</b>\n"
            "👥 Referrals: <b>{}</b>\n"
            "🔥 Streak: {} days"
        ).format(
            user.username or "N/A",
            user.join_date.strftime("%Y-%m-%d"),
            money(user.balance), money(user.total_earned),
            money(user.total_withdrawn), refs,
            streak.streak_days if streak else 0,
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]),
            parse_mode=ParseMode.HTML,
        )

    async def show_ads(self, query, db, user):
        today = now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_views = db.query(AdView).filter(
            AdView.user_id == user.telegram_id,
            AdView.viewed_at >= today,
        ).count()

        ad = db.query(Ad).filter(
            Ad.is_active.is_(True),
            Ad.total_views < Ad.max_views,
        ).order_by(Ad.id).first()

        if daily_views >= Config.MAX_ADS_PER_DAY:
            text = f"⚠️ Daily ad limit reached ({Config.MAX_ADS_PER_DAY}). Come back tomorrow."
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]])
        elif not ad:
            text = "📺 No ads are available right now."
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]])
        else:
            remaining = Config.MAX_ADS_PER_DAY - daily_views
            text = (
                f"📺 <b>{ad.title}</b>\n\n"
                f"{ad.description or ''}\n\n"
                f"💰 Reward: <b>{money(ad.user_reward)}</b>\n"
                f"👀 Views: {ad.total_views}/{ad.max_views}\n"
                f"🔢 Remaining today: {remaining}\n\n"
                "Open the advertiser link, then press the claim button."
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Open Ad", url=ad.link_url)],
                [InlineKeyboardButton("✅ Claim Reward", callback_data=f"ad_watched_{ad.id}")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ])
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    async def ad_watched(self, query, db, user, ad_id):
        if not str(ad_id).isdigit():
            await query.edit_message_text("❌ Invalid ad.")
            return
        ad = db.query(Ad).filter_by(id=int(ad_id)).first()
        if not ad or not ad.is_active or ad.total_views >= ad.max_views:
            await query.edit_message_text("❌ This ad is no longer available.")
            return

        today = now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_views = db.query(AdView).filter(
            AdView.user_id == user.telegram_id,
            AdView.viewed_at >= today,
        ).count()
        if daily_views >= Config.MAX_ADS_PER_DAY:
            await query.edit_message_text("⚠️ Daily ad limit reached.")
            return

        # A claim is not proof of an external ad view. Keep the reward model conservative.
        duplicate_recent = db.query(AdView).filter(
            AdView.user_id == user.telegram_id,
            AdView.ad_id == ad.id,
            AdView.viewed_at >= now() - timedelta(minutes=10),
        ).first()
        if duplicate_recent:
            await query.edit_message_text("⏳ Please wait before claiming this ad again.")
            return

        view = AdView(
            user_id=user.telegram_id,
            ad_id=ad.id,
            viewed_at=now(),
            user_reward=ad.user_reward,
            owner_revenue=ad.cost_per_view,
        )
        db.add(view)
        ad.total_views += 1
        self.log_balance(db, user, ad.user_reward, "ad", f"Ad reward #{ad.id}")
        user.total_earned += ad.user_reward
        if ad.total_views >= ad.max_views:
            ad.is_active = False

        await query.edit_message_text(
            f"✅ <b>Reward credited</b>\n\n"
            f"💰 Earned: {money(ad.user_reward)}\n"
            f"💵 New balance: {money(user.balance)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📺 Watch More", callback_data="watch_ads")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]),
            parse_mode=ParseMode.HTML,
        )

    async def show_social_menu(self, query, db, user):
        profile = db.query(SocialProfile).filter_by(user_id=user.telegram_id).first()
        if not profile:
            profile = SocialProfile(
                user_id=user.telegram_id,
                username=user.username or f"user_{user.telegram_id}",
            )
            db.add(profile)
            db.flush()

        tasks = db.query(SocialTask).filter(
            SocialTask.is_active.is_(True)
        ).all()
        buttons = []
        for task in tasks[:8]:
            done = db.query(SocialTaskCompletion).filter_by(
                user_id=user.telegram_id, task_id=task.id
            ).first()
            if not done:
                buttons.append([InlineKeyboardButton(
                    f"📱 {task.platform.title()} • +{task.points_reward} pts",
                    callback_data=f"social_task_{task.id}"
                )])

        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")])
        text = (
            "📱 <b>SOCIAL TASKS</b>\n\n"
            f"⭐ Points: <b>{profile.points}</b>\n"
            f"👥 Tasks completed: <b>{profile.followers_gained}</b>\n\n"
            "Complete genuine social actions and submit the task in the bot."
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
        )

    async def complete_social_task(self, query, db, user, task_id):
        if not str(task_id).isdigit():
            await query.edit_message_text("❌ Invalid task.")
            return
        task = db.query(SocialTask).filter_by(id=int(task_id), is_active=True).first()
        if not task:
            await query.edit_message_text("❌ Task unavailable.")
            return
        done = db.query(SocialTaskCompletion).filter_by(
            user_id=user.telegram_id, task_id=task.id
        ).first()
        if done:
            await query.edit_message_text("✅ You already completed this task.")
            return

        profile = db.query(SocialProfile).filter_by(user_id=user.telegram_id).first()
        if not profile:
            profile = SocialProfile(user_id=user.telegram_id, username=user.username or f"user_{user.telegram_id}")
            db.add(profile)

        completion = SocialTaskCompletion(
            user_id=user.telegram_id, task_id=task.id,
            completed_at=now(), points_earned=task.points_reward
        )
        db.add(completion)
        profile.points += task.points_reward
        profile.followers_gained += 1

        await query.edit_message_text(
            f"✅ <b>Task recorded</b>\n\n"
            f"⭐ +{task.points_reward} points\n"
            f"Total: <b>{profile.points}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 More Tasks", callback_data="social_menu")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]),
            parse_mode=ParseMode.HTML,
        )

    async def show_tasks(self, query, db, user):
        text = (
            "📋 <b>DAILY TASKS</b>\n\n"
            "Use Social Tasks to earn points.\n"
            "Daily money-making tasks can be added by an administrator."
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Social Tasks", callback_data="social_menu")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]), parse_mode=ParseMode.HTML
        )

    async def show_games(self, query, db, user):
        text = (
            "🎮 <b>MINI GAMES</b>\n\n"
            "Game engine is ready for expansion.\n"
            "For now, no cash game is enabled."
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
            ]), parse_mode=ParseMode.HTML
        )

    async def show_premium(self, query, db, user):
        packages = db.query(PremiumPackage).filter_by(is_active=True).all()
        if not packages:
            text = "💎 <b>PREMIUM</b>\n\nNo packages are available yet."
            buttons = []
        else:
            lines = ["💎 <b>PREMIUM PACKAGES</b>\n"]
            buttons = []
            for p in packages[:10]:
                lines.append(f"• {p.name} — {money(p.price_usd)}")
            text = "\n".join(lines)
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    async def show_payment_menu(self, query, db, user):
        paybill = Config.MPESA_PAYBILL or "Not configured"
        text = (
            "💳 <b>PAYMENT CENTER</b>\n\n"
            f"💰 Balance: <b>{money(user.balance)}</b>\n"
            f"📱 M-Pesa Paybill: <b>{paybill}</b>\n\n"
            "Commands:\n"
            "<code>/deposit 100</code>\n"
            "<code>/withdraw 5 0712345678</code>\n\n"
            "Deposits remain pending until an administrator verifies payment."
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
            ]), parse_mode=ParseMode.HTML
        )

    async def show_referral(self, query, db, user):
        count = db.query(User).filter_by(referred_by=user.telegram_id).count()
        link = f"https://t.me/{Config.BOT_USERNAME}?start={user.telegram_id}"
        text = (
            "👥 <b>REFERRAL PROGRAM</b>\n\n"
            f"💰 Bonus: <b>{money(Config.REFERRAL_BONUS)}</b>\n"
            f"📊 Referrals: <b>{count}</b>\n\n"
            f"🔗 <code>{link}</code>"
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
            ]), parse_mode=ParseMode.HTML
        )

    async def show_admin_panel(self, query, db, user):
        if not user.is_admin:
            await query.edit_message_text("❌ Unauthorized.")
            return
        users = db.query(User).count()
        ads = db.query(Ad).filter_by(is_active=True).count()
        pending = db.query(Withdrawal).filter_by(status="pending").count()
        text = (
            "⚙️ <b>ADMIN PANEL</b>\n\n"
            f"👥 Users: {users}\n"
            f"📺 Active ads: {ads}\n"
            f"💸 Pending withdrawals: {pending}\n"
            f"🤖 Version: {Config.VERSION}\n\n"
            "Admin commands:\n"
            "<code>/stats</code>\n"
            "<code>/addad Title|Description|URL|Reward|MaxViews</code>\n"
            "<code>/pending</code>\n"
            "<code>/approve ID</code>\n"
            "<code>/reject ID</code>\n"
            "<code>/credit USER_ID AMOUNT</code>"
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_withdrawals")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]), parse_mode=ParseMode.HTML
        )

    async def show_pending_withdrawals(self, query, db, user):
        if not user.is_admin:
            await query.edit_message_text("❌ Unauthorized.")
            return
        items = db.query(Withdrawal).filter_by(status="pending").order_by(Withdrawal.requested_at.asc()).limit(10).all()
        if not items:
            text = "💸 No pending withdrawals."
            buttons = [[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]
        else:
            lines = ["💸 <b>PENDING WITHDRAWALS</b>\n"]
            buttons = []
            for w in items:
                lines.append(f"#{w.id} • User {w.user_id} • {money(w.amount)} • {w.account_details}")
                buttons.append([
                    InlineKeyboardButton(f"✅ Approve #{w.id}", callback_data=f"approve_w_{w.id}"),
                    InlineKeyboardButton(f"❌ Reject #{w.id}", callback_data=f"reject_w_{w.id}")
                ])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel")])
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    async def approve_withdrawal(self, query, db, admin, withdrawal_id):
        if not admin.is_admin or not str(withdrawal_id).isdigit():
            await query.edit_message_text("❌ Unauthorized.")
            return
        w = db.query(Withdrawal).filter_by(id=int(withdrawal_id)).first()
        if not w or w.status != "pending":
            await query.edit_message_text("❌ Withdrawal is no longer pending.")
            return
        w.status = "completed"
        w.completed_at = now()
        target = db.query(User).filter_by(telegram_id=w.user_id).first()
        if target:
            target.total_withdrawn += w.amount
        await query.edit_message_text(f"✅ Withdrawal #{w.id} marked completed.")

        try:
            await self.application.bot.send_message(
                w.user_id, f"✅ Your withdrawal of {money(w.amount)} has been approved."
            )
        except Exception:
            logger.warning("Could not notify user %s", w.user_id)

    async def reject_withdrawal(self, query, db, admin, withdrawal_id):
        if not admin.is_admin or not str(withdrawal_id).isdigit():
            await query.edit_message_text("❌ Unauthorized.")
            return
        w = db.query(Withdrawal).filter_by(id=int(withdrawal_id)).first()
        if not w or w.status != "pending":
            await query.edit_message_text("❌ Withdrawal is no longer pending.")
            return
        target = db.query(User).filter_by(telegram_id=w.user_id).first()
        if target:
            self.log_balance(db, target, w.amount, "refund", f"Rejected withdrawal #{w.id}")
        w.status = "rejected"
        w.completed_at = now()
        await query.edit_message_text(f"↩️ Withdrawal #{w.id} rejected and funds refunded.")

        try:
            await self.application.bot.send_message(
                w.user_id, f"↩️ Your withdrawal of {money(w.amount)} was rejected and refunded."
            )
        except Exception:
            logger.warning("Could not notify user %s", w.user_id)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = self.session()
        try:
            user_id = update.effective_user.id
            text = (update.message.text or "").strip()
            user = db.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await update.message.reply_text("Please send /start first.")
                return

            parts = text.split()
            command = parts[0].lower() if parts else ""

            if command == "deposit":
                if len(parts) != 2:
                    await update.message.reply_text("Usage: /deposit 100")
                    return
                amount = float(parts[1])
                if not math.isfinite(amount) or amount <= 0:
                    raise ValueError
                dep = Deposit(
                    user_id=user_id, amount=amount, method="mpesa",
                    transaction_id=f"DEP-{uuid.uuid4().hex[:10].upper()}",
                    status="pending", requested_at=now()
                )
                db.add(dep)
                await update.message.reply_text(
                    f"✅ Deposit request created: {money(amount)}\n"
                    f"Reference: {dep.transaction_id}\n"
                    "An admin must verify it before crediting your balance."
                )

            elif command == "withdraw":
                if len(parts) < 3:
                    await update.message.reply_text("Usage: /withdraw 5 0712345678")
                    return
                amount = float(parts[1])
                account = " ".join(parts[2:]).strip()
                if not math.isfinite(amount) or amount <= 0:
                    raise ValueError
                if amount < Config.MIN_WITHDRAWAL:
                    await update.message.reply_text(f"❌ Minimum withdrawal is {money(Config.MIN_WITHDRAWAL)}.")
                    return
                if amount > user.balance:
                    await update.message.reply_text(f"❌ Insufficient balance: {money(user.balance)}.")
                    return

                since = now().replace(hour=0, minute=0, second=0, microsecond=0)
                daily = db.query(Withdrawal).filter(
                    Withdrawal.user_id == user_id,
                    Withdrawal.requested_at >= since,
                    Withdrawal.status.in_(["pending", "completed"])
                ).all()
                daily_total = sum(w.amount for w in daily)
                if daily_total + amount > Config.MAX_WITHDRAWAL_DAILY:
                    await update.message.reply_text(
                        f"❌ Daily withdrawal limit is {money(Config.MAX_WITHDRAWAL_DAILY)}."
                    )
                    return

                self.log_balance(db, user, -amount, "withdrawal", "Withdrawal reserved")
                w = Withdrawal(
                    user_id=user_id, amount=amount, method="mpesa",
                    account_details=account,
                    transaction_id=f"WTH-{uuid.uuid4().hex[:10].upper()}",
                    status="pending", requested_at=now()
                )
                db.add(w)
                await update.message.reply_text(
                    f"✅ Withdrawal request #{w.id if w.id else 'pending'} created for {money(amount)}.\n"
                    "Funds are reserved while the admin processes it."
                )

            elif command == "stats" and user.is_admin:
                await self.admin_stats(update, db)

            elif command == "addad" and user.is_admin:
                await self.admin_add_ad(update, db, text)

            elif command == "pending" and user.is_admin:
                await self.admin_pending(update, db)

            elif command in {"/approve", "approve"} and user.is_admin:
                if len(parts) != 2 or not parts[1].isdigit():
                    await update.message.reply_text("Usage: /approve ID")
                    return
                w = db.query(Withdrawal).filter_by(id=int(parts[1])).first()
                if not w or w.status != "pending":
                    await update.message.reply_text("❌ Withdrawal not pending.")
                    return
                w.status = "completed"
                w.completed_at = now()
                target = db.query(User).filter_by(telegram_id=w.user_id).first()
                if target:
                    target.total_withdrawn += w.amount
                await update.message.reply_text(f"✅ Withdrawal #{w.id} approved.")

            elif command in {"/reject", "reject"} and user.is_admin:
                if len(parts) != 2 or not parts[1].isdigit():
                    await update.message.reply_text("Usage: /reject ID")
                    return
                w = db.query(Withdrawal).filter_by(id=int(parts[1])).first()
                if not w or w.status != "pending":
                    await update.message.reply_text("❌ Withdrawal not pending.")
                    return
                target = db.query(User).filter_by(telegram_id=w.user_id).first()
                if target:
                    self.log_balance(db, target, w.amount, "refund", f"Rejected withdrawal #{w.id}")
                w.status = "rejected"
                w.completed_at = now()
                await update.message.reply_text(f"↩️ Withdrawal #{w.id} rejected and refunded.")

            elif command == "credit" and user.is_admin:
                if len(parts) != 3 or not parts[1].isdigit():
                    await update.message.reply_text("Usage: /credit USER_ID AMOUNT")
                    return
                target = db.query(User).filter_by(telegram_id=int(parts[1])).first()
                amount = float(parts[2])
                if not target or not math.isfinite(amount) or amount <= 0:
                    await update.message.reply_text("❌ Invalid user or amount.")
                    return
                self.log_balance(db, target, amount, "admin", "Admin credit")
                target.total_earned += amount
                await update.message.reply_text(f"✅ Credited {money(amount)} to user {target.telegram_id}.")

            else:
                await update.message.reply_text(
                    "❓ Use /start to open the menu.\n"
                    "Commands: /deposit, /withdraw"
                )
            db.commit()
        except ValueError:
            db.rollback()
            await update.message.reply_text("❌ Invalid amount.")
        except Exception:
            db.rollback()
            logger.exception("message handler failed")
            await update.message.reply_text("⚠️ Something went wrong.")
        finally:
            db.close()

    async def admin_stats(self, update, db):
        users = db.query(User).count()
        active = db.query(User).filter_by(is_active=True).count()
        ads = db.query(Ad).count()
        views = db.query(AdView).count()
        pending = db.query(Withdrawal).filter_by(status="pending").count()
        balance = sum((u.balance or 0) for u in db.query(User).all())
        await update.message.reply_text(
            f"📊 USERS: {users}\n"
            f"🟢 Active: {active}\n"
            f"📺 Ads: {ads}\n"
            f"👀 Views: {views}\n"
            f"💸 Pending withdrawals: {pending}\n"
            f"💰 User balances: {money(balance)}"
        )

    async def admin_add_ad(self, update, db, text):
        raw = text.split(" ", 1)
        if len(raw) != 2:
            await update.message.reply_text(
                "Usage:\n/addad Title|Description|URL|Reward|MaxViews"
            )
            return
        fields = [x.strip() for x in raw[1].split("|")]
        if len(fields) != 5:
            await update.message.reply_text("❌ Provide exactly 5 fields separated by |.")
            return
        title, description, url, reward, max_views = fields
        reward = float(reward)
        max_views = int(max_views)
        if not valid_url(url) or reward < 0 or max_views <= 0:
            await update.message.reply_text("❌ Invalid URL, reward, or max views.")
            return
        ad = Ad(
            title=title[:200], description=description,
            link_url=url, user_reward=reward,
            cost_per_view=max(reward, Config.AD_REVENUE_PER_VIEW),
            max_views=max_views, is_active=True
        )
        db.add(ad)
        await update.message.reply_text(f"✅ Ad created: {title}")

    async def admin_pending(self, update, db):
        items = db.query(Withdrawal).filter_by(status="pending").limit(20).all()
        if not items:
            await update.message.reply_text("No pending withdrawals.")
            return
        text = "\n".join(
            f"#{w.id} | user {w.user_id} | {money(w.amount)} | {w.account_details}"
            for w in items
        )
        await update.message.reply_text(text)

    def run(self):
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.start_command))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT, self.handle_message))
        logger.info("🚀 AdVantage Kenya Bot v%s starting", Config.VERSION)
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    AdVantageBot().run()
