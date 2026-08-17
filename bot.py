import logging
import math
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import Config
from database import (
    init_db,
    User,
    Ad,
    AdView,
    Task,
    TaskCompletion,
    SocialProfile,
    SocialTask,
    SocialTaskCompletion,
    Deposit,
    Withdrawal,
    BalanceHistory,
    DailyStreak,
    Achievement,
    PremiumPackage,
    PremiumOrder,
    PaymentMethod,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("advantage-bot")


EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)


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

        db.add(
            BalanceHistory(
                user_id=user.telegram_id,
                amount=amount,
                type=kind,
                description=description[:200],
                balance_before=before,
                balance_after=user.balance,
            )
        )

    async def start_command(self, update, context):
        db = self.session()
        try:
            tg = update.effective_user

            user = (
                db.query(User)
                .filter_by(telegram_id=tg.id)
                .first()
            )

            if not user:
                user = User(
                    telegram_id=tg.id,
                    username=tg.username,
                    first_name=tg.first_name,
                    last_name=tg.last_name,
                    join_date=now(),
                    last_active=now(),
                    is_admin=self.is_admin(tg.id),
                )
                db.add(user)
                db.flush()

                if context.args and context.args[0].isdigit():
                    referrer_id = int(context.args[0])

                    if referrer_id != tg.id:
                        referrer = (
                            db.query(User)
                            .filter_by(telegram_id=referrer_id)
                            .first()
                        )

                        if referrer:
                            user.referred_by = referrer_id
                            self.log_balance(
                                db,
                                referrer,
                                Config.REFERRAL_BONUS,
                                "referral",
                                f"Referral bonus for {tg.id}",
                            )
                            referrer.total_earned += Config.REFERRAL_BONUS

            user.username = tg.username
            user.first_name = tg.first_name
            user.last_name = tg.last_name
            user.is_admin = self.is_admin(tg.id)
            user.last_active = now()

            db.commit()
            await self.show_main_menu(update, user)

        except Exception:
            db.rollback()
            logger.exception("start_command failed")
            if update.message:
                await update.message.reply_text(
                    "⚠️ Something went wrong. Please try again."
                )
        finally:
            db.close()

    async def show_main_menu(self, update_or_query, user):
        keyboard = [
            [
                InlineKeyboardButton("📺 Watch Ads", callback_data="watch_ads"),
                InlineKeyboardButton("📋 Tasks", callback_data="daily_tasks"),
            ],
            [
                InlineKeyboardButton("📱 Social Tasks", callback_data="social_menu"),
                InlineKeyboardButton("👥 Referrals", callback_data="referral"),
            ],
            [
                InlineKeyboardButton("👛 Wallet", callback_data="wallet"),
                InlineKeyboardButton("👤 Profile", callback_data="profile"),
            ],
            [
                InlineKeyboardButton("📧 My Email", callback_data="email_menu"),
                InlineKeyboardButton("🎮 Games", callback_data="mini_games"),
            ],
        ]

        if user and self.is_admin(user.telegram_id):
            keyboard.append(
                [InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")]
            )

        text = (
            "🎯 <b>WELCOME TO ADVANTAGE</b> 🎯\n\n"
            "Complete legitimate tasks, view sponsored content, "
            "build your social presence and earn rewards.\n\n"
            "💰 Earn rewards\n"
            "📋 Complete tasks\n"
            "📺 View sponsored ads\n"
            "📧 Add your email\n"
            "👥 Refer users\n"
            "📊 Track your activity\n\n"
            "Choose an option below."
        )

        markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await update_or_query.edit_message_text(
                text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )

    async def handle_callback(self, update, context):
        query = update.callback_query
        await query.answer()

        db = self.session()

        try:
            user = (
                db.query(User)
                .filter_by(telegram_id=update.effective_user.id)
                .first()
            )

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
            elif data.startswith("ad_open_"):
                await self.ad_open(query, db, user, data.split("_")[-1])
            elif data == "daily_tasks":
                await self.show_tasks(query, db, user)
            elif data.startswith("taskclaim_"):
                await self.claim_task(query, db, user, data.split("_")[-1])
            elif data.startswith("task_"):
                await self.complete_task(query, db, user, data.split("_")[-1])
            elif data == "social_task_list":
                await self.show_social_menu(query, db, user)
            elif data.startswith("socialclaim_"):
                await self.claim_social_task(query, db, user, data.split("_")[-1])
            elif data.startswith("social_task_"):
                await self.complete_social_task(query, db, user, data.split("_")[-1])
            elif data == "social_menu":
                await self.show_social_menu(query, db, user)
            elif data == "mini_games":
                await self.show_games(query, db, user)
            elif data in {"payment_menu", "wallet"}:
                await self.show_wallet(query, db, user)
            elif data == "deposit_menu":
                await self.show_deposit_methods(query, db, user)
            elif data.startswith("deposit_method_"):
                method = data.replace("deposit_method_", "", 1)
                await self.begin_deposit(query, db, user, method, context)
            elif data == "wallet_history":
                await self.show_wallet_history(query, db, user)
            elif data == "admin_deposits":
                await self.show_pending_deposits(query, db, user)
            elif data == "admin_payment_methods":
                await self.show_admin_payment_methods(query, db, user)
            elif data.startswith("admin_paycfg_"):
                method = data.replace("admin_paycfg_", "", 1)
                await self.begin_payment_config(query, db, user, method, context)
            elif data.startswith("approve_d_"):
                await self.approve_deposit(query, db, user, data.split("_")[-1])
            elif data.startswith("reject_d_"):
                await self.reject_deposit(query, db, user, data.split("_")[-1])
            elif data == "withdraw_menu":
                await self.show_withdrawal_methods(query, db, user)
            elif data.startswith("withdraw_method_"):
                method = data.replace("withdraw_method_", "", 1)
                await self.begin_withdrawal(query, db, user, method, context)
            elif data == "cancel_input":
                context.user_data.pop("awaiting_email", None)
                context.user_data.pop("withdrawal_flow", None)
                context.user_data.pop("deposit_flow", None)
                context.user_data.pop("payment_config_flow", None)
                await self.show_wallet(query, db, user)
            elif data == "deposit_info":
                await query.edit_message_text(
                    "💰 <b>DEPOSIT</b>\n\n"
                    f"M-Pesa Paybill: <b>{Config.MPESA_PAYBILL or 'Not configured'}</b>\n"
                    f"Account/reference: <b>{Config.MPESA_ACCOUNT or 'Not configured'}</b>\n\n"
                    "Use the deposit process configured by the administrator.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Payment Center", callback_data="payment_menu")]
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            elif data == "referral":
                await self.show_referral(query, db, user)
            elif data == "email_menu":
                await self.show_email_menu(query, db, user)
            elif data == "set_email":
                context.user_data["awaiting_email"] = True
                await query.edit_message_text(
                    "📧 <b>EMAIL REQUIRED</b>\n\n"
                    "Your text input is needed only now. Send your email address.\n"
                    "Example: <code>name@example.com</code>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_input")]
                    ]),
                    parse_mode=ParseMode.HTML,
                )
                await query.message.reply_text(
                    "✍️ Enter your email address:",
                    reply_markup=ForceReply(selective=True),
                )
            elif data == "admin_panel":
                await self.show_admin_panel(query, db, user)
            elif data == "admin_withdrawals":
                await self.show_pending_withdrawals(query, db, user)
            elif data == "admin_users":
                await self.admin_users_button(query, db, user)
            elif data == "admin_ads":
                await self.admin_ads_button(query, db, user)
            elif data == "admin_tasks":
                await self.admin_tasks_button(query, db, user)
            elif data == "back_to_menu":
                await self.show_main_menu(query, user)
            elif data.startswith("approve_w_"):
                await self.approve_withdrawal(
                    query, db, user, data.split("_")[-1]
                )
            elif data.startswith("reject_w_"):
                await self.reject_withdrawal(
                    query, db, user, data.split("_")[-1]
                )
            else:
                await query.edit_message_text("❌ Unknown action.")

            db.commit()

        except Exception:
            db.rollback()
            logger.exception("callback failed")
            try:
                await query.edit_message_text(
                    "⚠️ Something went wrong. Please try again."
                )
            except Exception:
                pass
        finally:
            db.close()

    async def show_profile(self, query, db, user):
        streak = (
            db.query(DailyStreak)
            .filter_by(user_id=user.telegram_id)
            .first()
        )

        refs = (
            db.query(User)
            .filter_by(referred_by=user.telegram_id)
            .count()
        )

        email = user.email or "Not added"

        text = (
            "👤 <b>PROFILE</b>\n\n"
            f"📱 Username: @{user.username or 'N/A'}\n"
            f"📧 Email: {email}\n"
            f"📅 Joined: {user.join_date.strftime('%Y-%m-%d')}\n"
            f"💰 Balance: <b>{money(user.balance)}</b>\n"
            f"💵 Total earned: <b>{money(user.total_earned)}</b>\n"
            f"🏦 Withdrawn: <b>{money(user.total_withdrawn)}</b>\n"
            f"👥 Referrals: <b>{refs}</b>\n"
            f"🔥 Streak: {streak.streak_days if streak else 0} days"
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_email_menu(self, query, db, user):
        status = "Verified" if user.email_verified else "Not verified"

        text = (
            "📧 <b>EMAIL</b>\n\n"
            f"Email: <b>{user.email or 'Not added'}</b>\n"
            f"Status: <b>{status}</b>\n\n"
            "Your email can be used for account notifications and "
            "future verification features.\n\n"
            "Only enter an email address you control."
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("➕ Add / Change Email", callback_data="set_email")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
                ]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_ads(self, query, db, user):
        today = now().replace(hour=0, minute=0, second=0, microsecond=0)

        daily_views = (
            db.query(AdView)
            .filter(
                AdView.user_id == user.telegram_id,
                AdView.viewed_at >= today,
            )
            .count()
        )

        if daily_views >= Config.MAX_ADS_PER_DAY:
            await query.edit_message_text(
                f"⚠️ Daily ad limit reached ({Config.MAX_ADS_PER_DAY}).",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
                ),
            )
            return

        ads = (
            db.query(Ad)
            .filter(
                Ad.is_active.is_(True),
                Ad.total_views < Ad.max_views,
            )
            .order_by(Ad.id.asc())
            .all()
        )

        ad = None
        for candidate in ads:
            if candidate.expires_at and candidate.expires_at < now():
                continue
            ad = candidate
            break

        if not ad:
            await query.edit_message_text(
                "📺 No sponsored ads are available right now.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
                ),
            )
            return

        text = (
            f"📺 <b>{ad.title}</b>\n\n"
            f"{ad.description or ''}\n\n"
            f"💰 Reward: <b>{money(ad.user_reward)}</b>\n"
            f"👀 Campaign views: {ad.total_views}/{ad.max_views}\n"
            f"🔢 Your remaining views today: "
            f"{Config.MAX_ADS_PER_DAY - daily_views}\n\n"
            "Open the sponsored page and review it. "
            "Then return here and claim the reward."
        )

        buttons = [
            [InlineKeyboardButton("🔗 Open Sponsored Page", url=ad.link_url)],
            [InlineKeyboardButton("✅ Claim Reward", callback_data=f"ad_watched_{ad.id}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def ad_open(self, query, db, user, ad_id):
        await self.show_ads(query, db, user)

    async def ad_watched(self, query, db, user, ad_id):
        if not str(ad_id).isdigit():
            await query.edit_message_text("❌ Invalid ad.")
            return

        ad = (
            db.query(Ad)
            .filter_by(id=int(ad_id))
            .first()
        )

        if (
            not ad
            or not ad.is_active
            or ad.total_views >= ad.max_views
            or (ad.expires_at and ad.expires_at < now())
        ):
            await query.edit_message_text("❌ This ad is no longer available.")
            return

        today = now().replace(hour=0, minute=0, second=0, microsecond=0)

        daily_views = (
            db.query(AdView)
            .filter(
                AdView.user_id == user.telegram_id,
                AdView.viewed_at >= today,
            )
            .count()
        )

        if daily_views >= Config.MAX_ADS_PER_DAY:
            await query.edit_message_text("⚠️ Daily ad limit reached.")
            return

        already_today = (
            db.query(AdView)
            .filter(
                AdView.user_id == user.telegram_id,
                AdView.ad_id == ad.id,
                AdView.viewed_at >= today,
            )
            .first()
        )

        if already_today:
            await query.edit_message_text(
                "✅ You already claimed this sponsored ad today.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📺 More Ads", callback_data="watch_ads")]]
                ),
            )
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

        self.log_balance(
            db,
            user,
            ad.user_reward,
            "ad",
            f"Sponsored ad reward #{ad.id}",
        )
        user.total_earned += ad.user_reward

        if ad.total_views >= ad.max_views:
            ad.is_active = False

        await query.edit_message_text(
            f"✅ <b>Reward credited</b>\n\n"
            f"💰 Earned: {money(ad.user_reward)}\n"
            f"💵 New balance: {money(user.balance)}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📺 Watch More", callback_data="watch_ads")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
                ]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_tasks(self, query, db, user):
        today = now().replace(hour=0, minute=0, second=0, microsecond=0)

        completed_today = (
            db.query(TaskCompletion)
            .filter(
                TaskCompletion.user_id == user.telegram_id,
                TaskCompletion.completed_at >= today,
            )
            .count()
        )

        tasks = (
            db.query(Task)
            .filter(Task.is_active.is_(True))
            .order_by(Task.id.asc())
            .all()
        )

        buttons = []
        lines = [
            "📋 <b>TASKS</b>",
            "",
            f"Completed today: {completed_today}/{Config.MAX_TASKS_PER_DAY}",
            "",
        ]

        for task in tasks:
            if task.expires_at and task.expires_at < now():
                continue
            if task.completions >= task.max_completions:
                continue

            done = (
                db.query(TaskCompletion)
                .filter_by(
                    user_id=user.telegram_id,
                    task_id=task.id,
                )
                .first()
            )

            if done:
                continue

            lines.append(
                f"• <b>{task.title}</b> — {money(task.reward)}"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"📋 {task.title[:35]}",
                        callback_data=f"task_{task.id}",
                    )
                ]
            )

        if len(lines) == 4:
            lines.append("No new tasks right now.")

        buttons.append(
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
        )

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def complete_task(self, query, db, user, task_id):
        if not str(task_id).isdigit():
            await query.edit_message_text("❌ Invalid task.")
            return

        today = now().replace(hour=0, minute=0, second=0, microsecond=0)

        count_today = (
            db.query(TaskCompletion)
            .filter(
                TaskCompletion.user_id == user.telegram_id,
                TaskCompletion.completed_at >= today,
            )
            .count()
        )

        if count_today >= Config.MAX_TASKS_PER_DAY:
            await query.edit_message_text("⚠️ Daily task limit reached.")
            return

        task = (
            db.query(Task)
            .filter_by(id=int(task_id), is_active=True)
            .first()
        )

        if not task or task.completions >= task.max_completions:
            await query.edit_message_text("❌ Task unavailable.")
            return

        if task.expires_at and task.expires_at < now():
            await query.edit_message_text("❌ Task expired.")
            return

        done = (
            db.query(TaskCompletion)
            .filter_by(
                user_id=user.telegram_id,
                task_id=task.id,
            )
            .first()
        )

        if done:
            await query.edit_message_text("✅ You already completed this task.")
            return

        buttons = []

        if task.target_url and valid_url(task.target_url):
            buttons.append(
                [InlineKeyboardButton("🔗 Open Task", url=task.target_url)]
            )

        buttons.append(
            [InlineKeyboardButton("✅ Mark Completed", callback_data=f"taskclaim_{task.id}")]
        )
        buttons.append(
            [InlineKeyboardButton("🔙 Back", callback_data="daily_tasks")]
        )

        context_text = (
            f"📋 <b>{task.title}</b>\n\n"
            f"{task.description or 'Complete the task as instructed.'}\n\n"
            f"💰 Reward: <b>{money(task.reward)}</b>\n\n"
            "Complete the task, then press Mark Completed."
        )

        # Store a pending task in callback-safe user data isn't available here,
        # so the claim callback is handled separately through taskclaim_.
        await query.edit_message_text(
            context_text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def claim_task(self, query, db, user, task_id):
        if not str(task_id).isdigit():
            await query.edit_message_text("❌ Invalid task.")
            return

        task = (
            db.query(Task)
            .filter_by(id=int(task_id), is_active=True)
            .first()
        )

        if not task or task.completions >= task.max_completions:
            await query.edit_message_text("❌ Task unavailable.")
            return

        done = (
            db.query(TaskCompletion)
            .filter_by(
                user_id=user.telegram_id,
                task_id=task.id,
            )
            .first()
        )

        if done:
            await query.edit_message_text("✅ Already completed.")
            return

        completion = TaskCompletion(
            user_id=user.telegram_id,
            task_id=task.id,
            completed_at=now(),
            reward=task.reward,
        )
        db.add(completion)
        task.completions += 1

        self.log_balance(
            db,
            user,
            task.reward,
            "task",
            f"Task reward #{task.id}",
        )
        user.total_earned += task.reward

        if task.completions >= task.max_completions:
            task.is_active = False

        await query.edit_message_text(
            f"✅ <b>Task completed</b>\n\n"
            f"💰 Earned: {money(task.reward)}\n"
            f"💵 Balance: {money(user.balance)}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📋 More Tasks", callback_data="daily_tasks")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
                ]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_social_menu(self, query, db, user):
        profile = (
            db.query(SocialProfile)
            .filter_by(user_id=user.telegram_id)
            .first()
        )

        if not profile:
            profile = SocialProfile(
                user_id=user.telegram_id,
                username=user.username or f"user_{user.telegram_id}",
            )
            db.add(profile)
            db.flush()

        tasks = (
            db.query(SocialTask)
            .filter_by(is_active=True)
            .all()
        )

        buttons = []

        for task in tasks[:8]:
            done = (
                db.query(SocialTaskCompletion)
                .filter_by(
                    user_id=user.telegram_id,
                    task_id=task.id,
                )
                .first()
            )

            if not done:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f"📱 {task.platform.title()} +{task.points_reward} pts",
                            callback_data=f"social_task_{task.id}",
                        )
                    ]
                )

        buttons.append(
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
        )

        text = (
            "📱 <b>SOCIAL TASKS</b>\n\n"
            f"⭐ Points: <b>{profile.points}</b>\n"
            f"👥 Completed: <b>{profile.followers_gained}</b>\n\n"
            "Only complete genuine actions."
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def complete_social_task(self, query, db, user, task_id):
        if not str(task_id).isdigit():
            await query.edit_message_text("❌ Invalid task.")
            return

        task = (
            db.query(SocialTask)
            .filter_by(id=int(task_id), is_active=True)
            .first()
        )

        if not task:
            await query.edit_message_text("❌ Task unavailable.")
            return

        done = (
            db.query(SocialTaskCompletion)
            .filter_by(
                user_id=user.telegram_id,
                task_id=task.id,
            )
            .first()
        )

        if done:
            await query.edit_message_text("✅ Already completed.")
            return

        buttons = []

        if task.target_url and valid_url(task.target_url):
            buttons.append(
                [InlineKeyboardButton("🔗 Open Social Task", url=task.target_url)]
            )

        buttons.append(
            [InlineKeyboardButton(
                "✅ Submit Completion",
                callback_data=f"socialclaim_{task.id}"
            )]
        )
        buttons.append(
            [InlineKeyboardButton("🔙 Back", callback_data="social_menu")]
        )

        await query.edit_message_text(
            f"📱 <b>{task.platform.title()} task</b>\n\n"
            f"Target: <b>{task.target_username}</b>\n"
            f"Reward: <b>{task.points_reward} points</b>\n\n"
            "Complete the genuine action, then submit it.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def claim_social_task(self, query, db, user, task_id):
        if not str(task_id).isdigit():
            await query.edit_message_text("❌ Invalid task.")
            return

        task = (
            db.query(SocialTask)
            .filter_by(id=int(task_id), is_active=True)
            .first()
        )

        if not task:
            await query.edit_message_text("❌ Task unavailable.")
            return

        done = (
            db.query(SocialTaskCompletion)
            .filter_by(
                user_id=user.telegram_id,
                task_id=task.id,
            )
            .first()
        )

        if done:
            await query.edit_message_text("✅ Already completed.")
            return

        profile = (
            db.query(SocialProfile)
            .filter_by(user_id=user.telegram_id)
            .first()
        )

        if not profile:
            profile = SocialProfile(
                user_id=user.telegram_id,
                username=user.username or f"user_{user.telegram_id}",
            )
            db.add(profile)

        db.add(
            SocialTaskCompletion(
                user_id=user.telegram_id,
                task_id=task.id,
                completed_at=now(),
                points_earned=task.points_reward,
            )
        )

        profile.points += task.points_reward
        profile.followers_gained += 1

        await query.edit_message_text(
            f"✅ <b>Social task recorded</b>\n\n"
            f"⭐ +{task.points_reward} points\n"
            f"Total: <b>{profile.points}</b>",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📱 More Tasks", callback_data="social_menu")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
                ]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_games(self, query, db, user):
        await query.edit_message_text(
            "🎮 <b>MINI GAMES</b>\n\n"
            "The game section is reserved for future games. "
            "No cash game is enabled.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_payment_menu(self, query, db, user):
        await self.show_wallet(query, db, user)

    async def show_wallet(self, query, db, user):
        """Main wallet screen: balance, deposits, withdrawals and history."""
        pending_withdrawals = db.query(Withdrawal).filter_by(
            user_id=user.telegram_id, status="pending"
        ).count()
        pending_deposits = db.query(Deposit).filter_by(
            user_id=user.telegram_id, status="pending"
        ).count()
        text = (
            "👛 <b>MY WALLET</b>\n\n"
            f"💰 Available balance: <b>{money(user.balance)}</b>\n"
            f"📥 Pending deposits: <b>{pending_deposits}</b>\n"
            f"📤 Pending withdrawals: <b>{pending_withdrawals}</b>\n"
            f"💵 Total earned: <b>{money(user.total_earned)}</b>\n"
            f"🏦 Total withdrawn: <b>{money(user.total_withdrawn)}</b>\n\n"
            "Choose an action below."
        )
        buttons = [
            [InlineKeyboardButton("➕ Deposit Funds", callback_data="deposit_menu")],
            [InlineKeyboardButton("💸 Withdraw Funds", callback_data="withdraw_menu")],
            [InlineKeyboardButton("📜 Wallet History", callback_data="wallet_history")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    async def show_wallet_history(self, query, db, user):
        rows = db.query(BalanceHistory).filter_by(user_id=user.telegram_id).order_by(BalanceHistory.created_at.desc()).limit(10).all()
        if not rows:
            text = "📜 <b>WALLET HISTORY</b>\n\nNo transactions yet."
        else:
            lines = ["📜 <b>WALLET HISTORY</b>", ""]
            for r in rows:
                sign = "+" if float(r.amount or 0) >= 0 else ""
                lines.append(f"{r.created_at.strftime('%Y-%m-%d %H:%M')} • {sign}{money(r.amount)} • {r.description}")
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Wallet", callback_data="wallet")]]), parse_mode=ParseMode.HTML)

    async def show_deposit_methods(self, query, db, user):
        methods = db.query(PaymentMethod).filter_by(is_active=True, deposit_enabled=True).order_by(PaymentMethod.id).all()
        buttons = []
        for m in methods:
            buttons.append([InlineKeyboardButton(f"{m.icon} {m.name}", callback_data=f"deposit_method_{m.code}")])
        buttons.append([InlineKeyboardButton("🔙 Wallet", callback_data="wallet")])
        text = "💰 <b>DEPOSIT FUNDS</b>\n\nChoose where you will send the money. The bot will then show the administrator's configured receiving account and ask only for the information needed to create your deposit request."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    async def begin_deposit(self, query, db, user, method, context):
        pm = db.query(PaymentMethod).filter_by(code=method, is_active=True, deposit_enabled=True).first()
        if not pm:
            await query.edit_message_text("❌ This deposit method is not available.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Wallet", callback_data="wallet")]]))
            return
        if not pm.receive_account:
            await query.edit_message_text(
                f"{pm.icon} <b>{pm.name}</b>\n\n⚠️ This method has not been configured by the administrator yet.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Deposit Methods", callback_data="deposit_menu")]]),
                parse_mode=ParseMode.HTML,
            )
            return
        context.user_data["deposit_flow"] = {"method": method, "step": "amount"}
        account = pm.receive_account
        owner = f"\n👤 Account name: <b>{pm.receive_name}</b>" if pm.receive_name else ""
        instructions = f"\n\n📝 {pm.instructions}" if pm.instructions else ""
        await query.edit_message_text(
            f"{pm.icon} <b>{pm.name} DEPOSIT</b>\n\n"
            f"Send your payment to:\n<code>{account}</code>{owner}{instructions}\n\n"
            "After payment, enter the amount and then the payment/reference ID."
            "\n\nType /cancel to stop.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_input")]]),
            parse_mode=ParseMode.HTML,
        )
        await query.message.reply_text("✍️ Enter the amount you paid:", reply_markup=ForceReply(selective=True))

    def validate_deposit_reference(self, method, value):
        value = value.strip()
        if not 3 <= len(value) <= 150:
            return None
        return value

    async def process_deposit_text(self, update, context, db, user, text):
        flow = context.user_data.get("deposit_flow")
        if not flow:
            return False
        if text.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("deposit_flow", None)
            await update.message.reply_text("❌ Deposit cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👛 Wallet", callback_data="wallet")]]))
            return True
        method = flow["method"]
        pm = db.query(PaymentMethod).filter_by(code=method).first()
        if not pm:
            context.user_data.pop("deposit_flow", None)
            return True
        if flow["step"] == "amount":
            try:
                amount = float(text.replace(",", ""))
            except ValueError:
                await update.message.reply_text("❌ Enter a valid amount, for example 10 or 25.50.", reply_markup=ForceReply(selective=True))
                return True
            if not math.isfinite(amount) or amount <= 0:
                await update.message.reply_text("❌ Amount must be greater than zero.", reply_markup=ForceReply(selective=True))
                return True
            flow["amount"] = amount
            flow["step"] = "reference"
            context.user_data["deposit_flow"] = flow
            await update.message.reply_text(
                f"🧾 Enter the payment/reference/transaction ID for your {pm.name} payment.\n\n"
                "This is used by the administrator to verify the deposit.",
                reply_markup=ForceReply(selective=True),
            )
            return True
        if flow["step"] == "reference":
            ref = self.validate_deposit_reference(method, text)
            if not ref:
                await update.message.reply_text("❌ Invalid reference. Enter the payment/transaction ID shown by the payment service.", reply_markup=ForceReply(selective=True))
                return True
            # Keep references unique. If a provider uses duplicate-looking references, admin can reject the request.
            existing = db.query(Deposit).filter_by(transaction_id=ref).first()
            if existing:
                await update.message.reply_text("❌ That transaction/reference ID has already been submitted.", reply_markup=ForceReply(selective=True))
                return True
            dep = Deposit(
                user_id=user.telegram_id,
                amount=float(flow["amount"]),
                method=method,
                transaction_id=ref,
                status="pending",
                requested_at=now(),
            )
            db.add(dep)
            db.flush()
            context.user_data.pop("deposit_flow", None)
            await update.message.reply_text(
                "✅ <b>Deposit submitted</b>\n\n"
                f"💰 Amount: <b>{money(dep.amount)}</b>\n"
                f"💳 Method: <b>{pm.name}</b>\n"
                f"🧾 Reference: <code>{dep.transaction_id}</code>\n\n"
                "Your balance will be credited after an administrator verifies the payment.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👛 Wallet", callback_data="wallet")]]),
                parse_mode=ParseMode.HTML,
            )
            return True
        return False

    async def show_withdrawal_methods(self, query, db, user):
        methods = db.query(PaymentMethod).filter_by(is_active=True, withdrawal_enabled=True).order_by(PaymentMethod.id).all()
        if user.balance < Config.MIN_WITHDRAWAL:
            await query.edit_message_text(
                f"❌ Your balance is {money(user.balance)}.\n\nMinimum withdrawal: {money(Config.MIN_WITHDRAWAL)}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Wallet", callback_data="wallet")]]),
                parse_mode=ParseMode.HTML,
            )
            return
        buttons = [[InlineKeyboardButton(f"{m.icon} {m.name}", callback_data=f"withdraw_method_{m.code}")] for m in methods]
        buttons.append([InlineKeyboardButton("🔙 Wallet", callback_data="wallet")])
        await query.edit_message_text(
            "💸 <b>WITHDRAW FUNDS</b>\n\n"
            f"Available: <b>{money(user.balance)}</b>\n"
            f"Minimum: <b>{money(Config.MIN_WITHDRAWAL)}</b>\n\n"
            "Choose a payout method. You will only be asked for the account information required by that method.",
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML,
        )

    async def begin_withdrawal(self, query, db, user, method, context):
        pm = db.query(PaymentMethod).filter_by(code=method, is_active=True, withdrawal_enabled=True).first()
        if not pm:
            await query.edit_message_text("❌ This withdrawal method is unavailable.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Wallet", callback_data="wallet")]]))
            return
        context.user_data["withdrawal_flow"] = {"method": method, "step": "amount"}
        await query.edit_message_text(
            f"{pm.icon} <b>{pm.name} WITHDRAWAL</b>\n\n"
            f"💰 Available: <b>{money(user.balance)}</b>\n"
            f"Minimum: <b>{money(Config.MIN_WITHDRAWAL)}</b>\n"
            f"Daily limit: <b>{money(Config.MAX_WITHDRAWAL_DAILY)}</b>\n\n"
            "Enter the amount first. I will then ask for the correct payout account/identifier.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_input")]]),
            parse_mode=ParseMode.HTML,
        )
        await query.message.reply_text("✍️ Enter withdrawal amount:", reply_markup=ForceReply(selective=True))

    def normalize_mpesa(self, value):
        value = re.sub(r"[\s-]", "", value)
        if re.fullmatch(r"07\d{8}", value) or re.fullmatch(r"01\d{8}", value): return "254" + value[1:]
        if re.fullmatch(r"254(?:7|1)\d{8}", value): return value
        return None

    def validate_withdrawal_account(self, method, value):
        value = value.strip()
        if method == "mpesa": return self.normalize_mpesa(value)
        if method == "paypal": return value.lower() if EMAIL_RE.match(value) else None
        if method == "binance": return value if re.fullmatch(r"\d{6,20}", value) else None
        if method == "speedwallet": return value if re.fullmatch(r"[A-Za-z0-9._@+-]{4,80}", value) else None
        if method == "faucetpay": return value if re.fullmatch(r"[A-Za-z0-9._@+-]{3,100}", value) else None
        if method == "telegram_wallet": return value if len(value) >= 8 and len(value) <= 120 else None
        if method == "usdt_trc20": return value if re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", value) else None
        if method == "usdt_bep20": return value if re.fullmatch(r"0x[a-fA-F0-9]{40}", value) else None
        if method == "bitcoin": return value if 20 <= len(value) <= 120 and re.fullmatch(r"[A-Za-z0-9]+", value) else None
        if method == "ethereum": return value if re.fullmatch(r"0x[a-fA-F0-9]{40}", value) else None
        return None

    def account_prompt(self, method):
        return {
            "mpesa": "📱 Enter your M-Pesa phone number (07XXXXXXXX or 2547XXXXXXXX):",
            "paypal": "📧 Enter your PayPal email address:",
            "binance": "🟡 Enter your Binance UID:",
            "speedwallet": "⚡ Enter your Speed Wallet account/wallet ID:",
            "faucetpay": "🚰 Enter your FaucetPay email/username:",
            "telegram_wallet": "✈️ Enter your Telegram Wallet username/address as shown by your wallet:",
            "usdt_trc20": "₮ Enter your USDT TRC20 wallet address:",
            "usdt_bep20": "₮ Enter your USDT BEP20 wallet address:",
            "bitcoin": "₿ Enter your Bitcoin wallet address:",
            "ethereum": "♦️ Enter your Ethereum wallet address:",
        }.get(method, "Enter your payout account/identifier:")

    async def process_withdrawal_text(self, update, context, db, user, text):
        flow = context.user_data.get("withdrawal_flow")
        if not flow: return False
        if text.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("withdrawal_flow", None)
            await update.message.reply_text("❌ Withdrawal cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👛 Wallet", callback_data="wallet")]]))
            return True
        method = flow["method"]
        pm = db.query(PaymentMethod).filter_by(code=method).first()
        if not pm: return True
        if flow["step"] == "amount":
            try: amount = float(text.replace(",", ""))
            except ValueError:
                await update.message.reply_text("❌ Enter a valid number.", reply_markup=ForceReply(selective=True)); return True
            if not math.isfinite(amount) or amount <= 0:
                await update.message.reply_text("❌ Amount must be greater than zero.", reply_markup=ForceReply(selective=True)); return True
            if amount < Config.MIN_WITHDRAWAL:
                await update.message.reply_text(f"❌ Minimum withdrawal is {money(Config.MIN_WITHDRAWAL)}.", reply_markup=ForceReply(selective=True)); return True
            if amount > user.balance:
                await update.message.reply_text(f"❌ Insufficient balance. Available: {money(user.balance)}.", reply_markup=ForceReply(selective=True)); return True
            since = now().replace(hour=0, minute=0, second=0, microsecond=0)
            daily = db.query(Withdrawal).filter(Withdrawal.user_id == user.telegram_id, Withdrawal.requested_at >= since, Withdrawal.status.in_(["pending", "completed"])).all()
            daily_total = sum(float(w.amount or 0) for w in daily)
            if daily_total + amount > Config.MAX_WITHDRAWAL_DAILY:
                await update.message.reply_text(f"❌ Daily limit is {money(Config.MAX_WITHDRAWAL_DAILY)}. Remaining: {money(max(0, Config.MAX_WITHDRAWAL_DAILY-daily_total))}."); return True
            flow["amount"] = amount; flow["step"] = "account"; context.user_data["withdrawal_flow"] = flow
            await update.message.reply_text(self.account_prompt(method) + "\n\nType /cancel to stop.", reply_markup=ForceReply(selective=True)); return True
        if flow["step"] == "account":
            account = self.validate_withdrawal_account(method, text)
            if not account:
                await update.message.reply_text("❌ Invalid account format for this payment method. Please enter it again.", reply_markup=ForceReply(selective=True)); return True
            amount = float(flow["amount"])
            self.log_balance(db, user, -amount, "withdrawal", f"Withdrawal reserved via {pm.name}")
            w = Withdrawal(user_id=user.telegram_id, amount=amount, method=method, account_details=account, transaction_id=f"WTH-{uuid.uuid4().hex[:10].upper()}", status="pending", requested_at=now())
            db.add(w); db.flush(); context.user_data.pop("withdrawal_flow", None)
            await update.message.reply_text(
                "✅ <b>Withdrawal request created</b>\n\n"
                f"💰 Amount: <b>{money(amount)}</b>\n💳 Method: <b>{pm.name}</b>\n"
                f"🧾 Reference: <code>{w.transaction_id}</code>\n\nFunds are reserved while an administrator reviews the request.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👛 Wallet", callback_data="wallet")]]), parse_mode=ParseMode.HTML)
            return True
        return False

    async def show_referral(self, query, db, user):
        count = (
            db.query(User)
            .filter_by(referred_by=user.telegram_id)
            .count()
        )

        link = f"https://t.me/{Config.BOT_USERNAME}?start={user.telegram_id}"

        text = (
            "👥 <b>REFERRALS</b>\n\n"
            f"💰 Bonus: <b>{money(Config.REFERRAL_BONUS)}</b>\n"
            f"📊 Referrals: <b>{count}</b>\n\n"
            f"🔗 <code>{link}</code>"
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_admin_panel(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized.")
            return

        users = db.query(User).count()
        active = db.query(User).filter_by(is_active=True).count()
        ads = db.query(Ad).filter_by(is_active=True).count()
        tasks = db.query(Task).filter_by(is_active=True).count()
        pending = db.query(Withdrawal).filter_by(status="pending").count()

        text = (
            "⚙️ <b>ADMIN PANEL</b>\n\n"
            f"👥 Users: {users}\n"
            f"🟢 Active users: {active}\n"
            f"📺 Active ads: {ads}\n"
            f"📋 Active tasks: {tasks}\n"
            f"💸 Pending withdrawals: {pending}\n\n"
            "Commands:\n"
            "<code>/stats</code>\n"
            "<code>/users</code>\n"
            "<code>/addad Title|Description|URL|Reward|MaxViews</code>\n"
            "<code>/addtask Title|Description|URL|Reward|MaxCompletions</code>\n"
            "<code>/pending</code>\n"
            "<code>/approve ID</code>\n"
            "<code>/reject ID</code>\n"
            "<code>/credit USER_ID AMOUNT</code>"
        )

        buttons = [
            [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
            [InlineKeyboardButton("📺 Ads", callback_data="admin_ads")],
            [InlineKeyboardButton("📋 Tasks", callback_data="admin_tasks")],
            [InlineKeyboardButton("💸 Withdrawals", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("💰 Deposits", callback_data="admin_deposits")],
            [InlineKeyboardButton("🏦 Payment Accounts", callback_data="admin_payment_methods")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def admin_users_button(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized.")
            return

        users = db.query(User).order_by(User.join_date.desc()).limit(15).all()

        if not users:
            text = "👥 No users yet."
        else:
            lines = ["👥 <b>RECENT USERS</b>", ""]
            for u in users:
                lines.append(
                    f"#{u.telegram_id} | @{u.username or 'N/A'} | {money(u.balance)}"
                )
            text = "\n".join(lines)

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def admin_ads_button(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized.")
            return

        ads = db.query(Ad).order_by(Ad.id.desc()).limit(15).all()

        if not ads:
            text = "📺 No ads yet.\n\nUse /addad to create one."
        else:
            lines = ["📺 <b>ADS</b>", ""]
            for ad in ads:
                status = "ON" if ad.is_active else "OFF"
                lines.append(
                    f"#{ad.id} {status} | {ad.title[:35]} | "
                    f"{ad.total_views}/{ad.max_views}"
                )
            text = "\n".join(lines)

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def admin_tasks_button(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized.")
            return

        tasks = db.query(Task).order_by(Task.id.desc()).limit(15).all()

        if not tasks:
            text = "📋 No tasks yet.\n\nUse /addtask to create one."
        else:
            lines = ["📋 <b>TASKS</b>", ""]
            for task in tasks:
                status = "ON" if task.is_active else "OFF"
                lines.append(
                    f"#{task.id} {status} | {task.title[:35]} | "
                    f"{task.completions}/{task.max_completions}"
                )
            text = "\n".join(lines)

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]]
            ),
            parse_mode=ParseMode.HTML,
        )

    async def show_admin_payment_methods(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized."); return
        methods = db.query(PaymentMethod).order_by(PaymentMethod.id).all()
        buttons = []
        lines = ["🏦 <b>PAYMENT ACCOUNTS</b>", "", "Configure where user deposits are sent and which methods can be used for withdrawals.", ""]
        for m in methods:
            status = "🟢" if m.is_active else "🔴"
            configured = "configured" if m.receive_account else "not configured"
            lines.append(f"{status} {m.icon} <b>{m.name}</b> — {configured}")
            buttons.append([InlineKeyboardButton(f"⚙️ Configure {m.name}", callback_data=f"admin_paycfg_{m.code}")])
        buttons.append([InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")])
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    async def begin_payment_config(self, query, db, user, method, context):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized."); return
        pm = db.query(PaymentMethod).filter_by(code=method).first()
        if not pm:
            await query.edit_message_text("❌ Payment method not found."); return
        context.user_data["payment_config_flow"] = {"method": method, "step": "account"}
        await query.edit_message_text(
            f"⚙️ <b>CONFIGURE {pm.name.upper()}</b>\n\n"
            "Enter the receiving account/address/number where user deposits for this method should be sent.\n\n"
            "Examples: M-Pesa paybill/till, PayPal email, crypto address, or wallet ID.\n\nType /cancel to stop.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_input")]]), parse_mode=ParseMode.HTML)
        await query.message.reply_text("✍️ Enter receiving account/address:", reply_markup=ForceReply(selective=True))

    async def process_payment_config_text(self, update, context, db, user, text):
        flow = context.user_data.get("payment_config_flow")
        if not flow: return False
        if not self.is_admin(user.telegram_id): return True
        if text.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("payment_config_flow", None)
            await update.message.reply_text("❌ Configuration cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏦 Payment Accounts", callback_data="admin_payment_methods")]])); return True
        pm = db.query(PaymentMethod).filter_by(code=flow["method"]).first()
        if not pm: return True
        if flow["step"] == "account":
            if not 3 <= len(text.strip()) <= 500:
                await update.message.reply_text("❌ Enter a valid account/address.", reply_markup=ForceReply(selective=True)); return True
            pm.receive_account = text.strip(); flow["step"] = "name"; context.user_data["payment_config_flow"] = flow
            await update.message.reply_text("✍️ Enter the account holder/business name (or type NONE):", reply_markup=ForceReply(selective=True)); return True
        if flow["step"] == "name":
            pm.receive_name = None if text.strip().upper() == "NONE" else text.strip()[:200]
            flow["step"] = "instructions"; context.user_data["payment_config_flow"] = flow
            await update.message.reply_text("✍️ Enter payment instructions for users (or type NONE):", reply_markup=ForceReply(selective=True)); return True
        if flow["step"] == "instructions":
            pm.instructions = None if text.strip().upper() == "NONE" else text.strip()[:1000]
            context.user_data.pop("payment_config_flow", None)
            await update.message.reply_text(f"✅ {pm.name} configuration saved.\n\nReceiving account: {pm.receive_account}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏦 Payment Accounts", callback_data="admin_payment_methods")]])); return True
        return False

    async def show_pending_deposits(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized."); return
        items = db.query(Deposit).filter_by(status="pending").order_by(Deposit.requested_at.asc()).limit(15).all()
        if not items:
            await query.edit_message_text("💰 No pending deposits.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]])); return
        lines=["💰 <b>PENDING DEPOSITS</b>",""]; buttons=[]
        for d in items:
            lines.append(f"#{d.id} • User {d.user_id} • {money(d.amount)} • {d.method} • {d.transaction_id}")
            buttons.append([InlineKeyboardButton(f"✅ Approve #{d.id}", callback_data=f"approve_d_{d.id}"), InlineKeyboardButton(f"❌ Reject #{d.id}", callback_data=f"reject_d_{d.id}")])
        buttons.append([InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")])
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    async def approve_deposit(self, query, db, admin, deposit_id):
        if not self.is_admin(admin.telegram_id) or not str(deposit_id).isdigit():
            await query.edit_message_text("❌ Unauthorized."); return
        d=db.query(Deposit).filter_by(id=int(deposit_id)).first()
        if not d or d.status != "pending":
            await query.edit_message_text("❌ Deposit is no longer pending."); return
        target=db.query(User).filter_by(telegram_id=d.user_id).first()
        if not target:
            d.status="rejected"; d.completed_at=now(); return
        self.log_balance(db,target,float(d.amount),"deposit",f"Verified deposit {d.transaction_id}")
        d.status="completed"; d.completed_at=now(); target.total_earned += 0
        await query.edit_message_text(f"✅ Deposit #{d.id} approved and {money(d.amount)} credited to user {d.user_id}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Deposits", callback_data="admin_deposits")]]))
        try:
            await self.application.bot.send_message(d.user_id, f"✅ Your deposit of {money(d.amount)} has been verified and credited to your wallet.\nReference: {d.transaction_id}")
        except Exception: pass

    async def reject_deposit(self, query, db, admin, deposit_id):
        if not self.is_admin(admin.telegram_id) or not str(deposit_id).isdigit():
            await query.edit_message_text("❌ Unauthorized."); return
        d=db.query(Deposit).filter_by(id=int(deposit_id)).first()
        if not d or d.status != "pending":
            await query.edit_message_text("❌ Deposit is no longer pending."); return
        d.status="rejected"; d.completed_at=now()
        await query.edit_message_text(f"❌ Deposit #{d.id} rejected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Deposits", callback_data="admin_deposits")]]))
        try:
            await self.application.bot.send_message(d.user_id, f"❌ Your deposit request {d.transaction_id} was rejected. Contact support if you believe this is incorrect.")
        except Exception: pass

    async def show_pending_withdrawals(self, query, db, user):
        if not self.is_admin(user.telegram_id):
            await query.edit_message_text("❌ Unauthorized.")
            return

        items = (
            db.query(Withdrawal)
            .filter_by(status="pending")
            .order_by(Withdrawal.requested_at.asc())
            .limit(10)
            .all()
        )

        if not items:
            text = "💸 No pending withdrawals."
            buttons = [
                [InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]
            ]
        else:
            lines = ["💸 <b>PENDING WITHDRAWALS</b>", ""]
            buttons = []

            for w in items:
                lines.append(
                    f"#{w.id} • User {w.user_id} • "
                    f"{money(w.amount)} • {w.account_details}"
                )
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f"✅ Approve #{w.id}",
                            callback_data=f"approve_w_{w.id}",
                        ),
                        InlineKeyboardButton(
                            f"❌ Reject #{w.id}",
                            callback_data=f"reject_w_{w.id}",
                        ),
                    ]
                )

            buttons.append(
                [InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]
            )
            text = "\n".join(lines)

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    async def approve_withdrawal(self, query, db, admin, withdrawal_id):
        if (
            not self.is_admin(admin.telegram_id)
            or not str(withdrawal_id).isdigit()
        ):
            await query.edit_message_text("❌ Unauthorized.")
            return

        w = (
            db.query(Withdrawal)
            .filter_by(id=int(withdrawal_id))
            .first()
        )

        if not w or w.status != "pending":
            await query.edit_message_text("❌ Withdrawal is no longer pending.")
            return

        w.status = "completed"
        w.completed_at = now()

        target = (
            db.query(User)
            .filter_by(telegram_id=w.user_id)
            .first()
        )

        if target:
            target.total_withdrawn += w.amount

        await query.edit_message_text(
            f"✅ Withdrawal #{w.id} marked completed."
        )

        try:
            await self.application.bot.send_message(
                w.user_id,
                f"✅ Your withdrawal of {money(w.amount)} has been approved.",
            )
        except Exception:
            logger.warning("Could not notify user %s", w.user_id)

    async def reject_withdrawal(self, query, db, admin, withdrawal_id):
        if (
            not self.is_admin(admin.telegram_id)
            or not str(withdrawal_id).isdigit()
        ):
            await query.edit_message_text("❌ Unauthorized.")
            return

        w = (
            db.query(Withdrawal)
            .filter_by(id=int(withdrawal_id))
            .first()
        )

        if not w or w.status != "pending":
            await query.edit_message_text("❌ Withdrawal is no longer pending.")
            return

        target = (
            db.query(User)
            .filter_by(telegram_id=w.user_id)
            .first()
        )

        if target:
            self.log_balance(
                db,
                target,
                w.amount,
                "refund",
                f"Rejected withdrawal #{w.id}",
            )

        w.status = "rejected"
        w.completed_at = now()

        await query.edit_message_text(
            f"↩️ Withdrawal #{w.id} rejected and funds refunded."
        )

        try:
            await self.application.bot.send_message(
                w.user_id,
                f"↩️ Your withdrawal of {money(w.amount)} was rejected and refunded.",
            )
        except Exception:
            logger.warning("Could not notify user %s", w.user_id)

    async def handle_message(self, update, context):
        db = self.session()

        try:
            user_id = update.effective_user.id
            text = (update.message.text or "").strip()

            user = (
                db.query(User)
                .filter_by(telegram_id=user_id)
                .first()
            )

            if not user:
                await update.message.reply_text("Please send /start first.")
                return

            # Free-text input is accepted only when the current flow requires it.
            if await self.process_payment_config_text(update, context, db, user, text):
                db.commit()
                return
            if await self.process_deposit_text(update, context, db, user, text):
                db.commit()
                return
            if await self.process_withdrawal_text(update, context, db, user, text):
                db.commit()
                return

            # Email entry is handled before normal commands.
            if context.user_data.get("awaiting_email"):
                email = text.strip().lower()

                if not EMAIL_RE.match(email):
                    await update.message.reply_text(
                        "❌ That does not look like a valid email.\n"
                        "Example: name@example.com"
                    )
                    return

                existing = (
                    db.query(User)
                    .filter(
                        User.email == email,
                        User.telegram_id != user_id,
                    )
                    .first()
                )

                if existing:
                    await update.message.reply_text(
                        "❌ That email is already linked to another account."
                    )
                    return

                user.email = email
                user.email_verified = False
                context.user_data["awaiting_email"] = False
                db.commit()

                await update.message.reply_text(
                    f"✅ Email saved: {email}\n\n"
                    "It is currently marked as unverified."
                )
                return

            parts = text.split()
            if not parts:
                return

            command = parts[0].lower().lstrip("/")

            if command == "email":
                if len(parts) != 2:
                    await update.message.reply_text("Usage: /email name@example.com")
                    return

                email = parts[1].strip().lower()

                if not EMAIL_RE.match(email):
                    await update.message.reply_text("❌ Invalid email.")
                    return

                existing = (
                    db.query(User)
                    .filter(
                        User.email == email,
                        User.telegram_id != user_id,
                    )
                    .first()
                )

                if existing:
                    await update.message.reply_text(
                        "❌ That email is already linked to another account."
                    )
                    return

                user.email = email
                user.email_verified = False

                await update.message.reply_text(
                    f"✅ Email saved: {email}\n"
                    "It is currently unverified."
                )

            elif command == "deposit":
                if len(parts) != 2:
                    await update.message.reply_text("Usage: /deposit 100")
                    return

                amount = float(parts[1])

                if not math.isfinite(amount) or amount <= 0:
                    raise ValueError

                dep = Deposit(
                    user_id=user_id,
                    amount=amount,
                    method="mpesa",
                    transaction_id=f"DEP-{uuid.uuid4().hex[:10].upper()}",
                    status="pending",
                    requested_at=now(),
                )
                db.add(dep)

                await update.message.reply_text(
                    f"✅ Deposit request created: {money(amount)}\n"
                    f"Reference: {dep.transaction_id}\n"
                    "An admin must verify it before crediting your balance."
                )

            elif command == "withdraw":
                if len(parts) < 3:
                    await update.message.reply_text(
                        "Usage: /withdraw 5 0712345678"
                    )
                    return

                amount = float(parts[1])
                account = " ".join(parts[2:]).strip()

                if not math.isfinite(amount) or amount <= 0:
                    raise ValueError

                if amount < Config.MIN_WITHDRAWAL:
                    await update.message.reply_text(
                        f"❌ Minimum withdrawal is {money(Config.MIN_WITHDRAWAL)}."
                    )
                    return

                if amount > user.balance:
                    await update.message.reply_text(
                        f"❌ Insufficient balance: {money(user.balance)}."
                    )
                    return

                since = now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

                daily = (
                    db.query(Withdrawal)
                    .filter(
                        Withdrawal.user_id == user_id,
                        Withdrawal.requested_at >= since,
                        Withdrawal.status.in_(["pending", "completed"]),
                    )
                    .all()
                )

                daily_total = sum(w.amount for w in daily)

                if daily_total + amount > Config.MAX_WITHDRAWAL_DAILY:
                    await update.message.reply_text(
                        f"❌ Daily withdrawal limit is "
                        f"{money(Config.MAX_WITHDRAWAL_DAILY)}."
                    )
                    return

                self.log_balance(
                    db,
                    user,
                    -amount,
                    "withdrawal",
                    "Withdrawal reserved",
                )

                w = Withdrawal(
                    user_id=user_id,
                    amount=amount,
                    method="mpesa",
                    account_details=account,
                    transaction_id=f"WTH-{uuid.uuid4().hex[:10].upper()}",
                    status="pending",
                    requested_at=now(),
                )
                db.add(w)

                await update.message.reply_text(
                    f"✅ Withdrawal request created for {money(amount)}.\n"
                    "Funds are reserved while the admin processes it."
                )

            elif command == "setpayment":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized."); return
                raw = text.split(" ", 1)
                fields = [x.strip() for x in raw[1].split("|", 3)] if len(raw) == 2 else []
                if len(fields) != 4:
                    await update.message.reply_text("Usage: /setpayment METHOD|ACCOUNT|NAME|INSTRUCTIONS"); return
                method, account, name, instructions = fields
                pm = db.query(PaymentMethod).filter_by(code=method.lower()).first()
                if not pm:
                    await update.message.reply_text("❌ Unknown method. Open Admin → Payment Accounts to see available methods."); return
                pm.receive_account = account; pm.receive_name = None if name.upper() == "NONE" else name; pm.instructions = None if instructions.upper() == "NONE" else instructions
                await update.message.reply_text(f"✅ {pm.name} payment configuration updated.")

            elif command == "stats":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return
                await self.admin_stats(update, db)

            elif command == "users":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return
                await self.admin_users_command(update, db)

            elif command == "addad":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return
                await self.admin_add_ad(update, db, text)

            elif command == "addtask":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return
                await self.admin_add_task(update, db, text)

            elif command == "pending":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return
                await self.admin_pending(update, db)

            elif command == "approve":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return
                if len(parts) != 2 or not parts[1].isdigit():
                    await update.message.reply_text("Usage: /approve ID")
                    return

                w = (
                    db.query(Withdrawal)
                    .filter_by(id=int(parts[1]))
                    .first()
                )

                if not w or w.status != "pending":
                    await update.message.reply_text(
                        "❌ Withdrawal not pending."
                    )
                    return

                w.status = "completed"
                w.completed_at = now()

                target = (
                    db.query(User)
                    .filter_by(telegram_id=w.user_id)
                    .first()
                )

                if target:
                    target.total_withdrawn += w.amount

                await update.message.reply_text(
                    f"✅ Withdrawal #{w.id} approved."
                )

            elif command == "reject":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return

                if len(parts) != 2 or not parts[1].isdigit():
                    await update.message.reply_text("Usage: /reject ID")
                    return

                w = (
                    db.query(Withdrawal)
                    .filter_by(id=int(parts[1]))
                    .first()
                )

                if not w or w.status != "pending":
                    await update.message.reply_text(
                        "❌ Withdrawal not pending."
                    )
                    return

                target = (
                    db.query(User)
                    .filter_by(telegram_id=w.user_id)
                    .first()
                )

                if target:
                    self.log_balance(
                        db,
                        target,
                        w.amount,
                        "refund",
                        f"Rejected withdrawal #{w.id}",
                    )

                w.status = "rejected"
                w.completed_at = now()

                await update.message.reply_text(
                    f"↩️ Withdrawal #{w.id} rejected and refunded."
                )

            elif command == "credit":
                if not self.is_admin(user_id):
                    await update.message.reply_text("❌ Unauthorized.")
                    return

                if len(parts) != 3 or not parts[1].isdigit():
                    await update.message.reply_text(
                        "Usage: /credit USER_ID AMOUNT"
                    )
                    return

                target = (
                    db.query(User)
                    .filter_by(telegram_id=int(parts[1]))
                    .first()
                )

                amount = float(parts[2])

                if (
                    not target
                    or not math.isfinite(amount)
                    or amount <= 0
                ):
                    await update.message.reply_text(
                        "❌ Invalid user or amount."
                    )
                    return

                self.log_balance(
                    db,
                    target,
                    amount,
                    "admin",
                    "Admin credit",
                )
                target.total_earned += amount

                await update.message.reply_text(
                    f"✅ Credited {money(amount)} to user {target.telegram_id}."
                )

            else:
                await update.message.reply_text(
                    "❓ Use /start to open the menu.\n\n"
                    "Commands:\n"
                    "/email name@example.com\n"
                    "/deposit 100\n"
                    "/withdraw 5 0712345678"
                )

            db.commit()

        except ValueError:
            db.rollback()
            await update.message.reply_text("❌ Invalid amount or value.")
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
        tasks = db.query(Task).count()
        task_completions = db.query(TaskCompletion).count()
        pending = db.query(Withdrawal).filter_by(status="pending").count()

        balance = sum((u.balance or 0) for u in db.query(User).all())

        await update.message.reply_text(
            f"📊 <b>ADMIN STATS</b>\n\n"
            f"👥 Users: {users}\n"
            f"🟢 Active: {active}\n"
            f"📺 Ads: {ads}\n"
            f"👀 Ad claims: {views}\n"
            f"📋 Tasks: {tasks}\n"
            f"✅ Task completions: {task_completions}\n"
            f"💸 Pending withdrawals: {pending}\n"
            f"💰 User balances: {money(balance)}",
            parse_mode=ParseMode.HTML,
        )

    async def admin_users_command(self, update, db):
        users = db.query(User).order_by(User.join_date.desc()).limit(30).all()

        if not users:
            await update.message.reply_text(
                "👥 No users yet. The first user will appear after they send /start."
            )
            return

        lines = ["👥 <b>RECENT USERS</b>", ""]
        for u in users:
            lines.append(
                f"{u.telegram_id} | @{u.username or 'N/A'} | "
                f"{u.email or 'no email'} | {money(u.balance)}"
            )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    async def admin_add_ad(self, update, db, text):
        raw = text.split(" ", 1)

        if len(raw) != 2:
            await update.message.reply_text(
                "Usage:\n"
                "/addad Title|Description|URL|Reward|MaxViews\n\n"
                "Example:\n"
                "/addad My Shop|Visit our shop|https://example.com|0.002|1000"
            )
            return

        fields = [x.strip() for x in raw[1].split("|")]

        if len(fields) != 5:
            await update.message.reply_text(
                "❌ Provide exactly 5 fields separated by |."
            )
            return

        title, description, url, reward, max_views = fields

        try:
            reward = float(reward)
            max_views = int(max_views)
        except ValueError:
            await update.message.reply_text(
                "❌ Reward must be a number and MaxViews a whole number."
            )
            return

        if not valid_url(url) or reward < 0 or max_views <= 0:
            await update.message.reply_text("❌ Invalid URL, reward or max views.")
            return

        ad = Ad(
            title=title[:200],
            description=description,
            link_url=url,
            user_reward=reward,
            cost_per_view=max(reward, Config.AD_REVENUE_PER_VIEW),
            max_views=max_views,
            is_active=True,
        )

        db.add(ad)

        await update.message.reply_text(
            f"✅ Sponsored ad created: {title}\n"
            f"Reward per eligible claim: {money(reward)}\n"
            f"Maximum claims: {max_views}"
        )

    async def admin_add_task(self, update, db, text):
        raw = text.split(" ", 1)

        if len(raw) != 2:
            await update.message.reply_text(
                "Usage:\n"
                "/addtask Title|Description|URL|Reward|MaxCompletions\n\n"
                "Example:\n"
                "/addtask Visit website|Read the page|https://example.com|0.05|100"
            )
            return

        fields = [x.strip() for x in raw[1].split("|")]

        if len(fields) != 5:
            await update.message.reply_text(
                "❌ Provide exactly 5 fields separated by |."
            )
            return

        title, description, url, reward, max_completions = fields

        try:
            reward = float(reward)
            max_completions = int(max_completions)
        except ValueError:
            await update.message.reply_text(
                "❌ Reward must be a number and MaxCompletions a whole number."
            )
            return

        if reward < 0 or max_completions <= 0:
            await update.message.reply_text(
                "❌ Invalid reward or completion limit."
            )
            return

        if url and not valid_url(url):
            await update.message.reply_text("❌ Invalid URL.")
            return

        db.add(
            Task(
                title=title[:200],
                description=description,
                target_url=url or None,
                reward=reward,
                max_completions=max_completions,
                is_active=True,
            )
        )

        await update.message.reply_text(
            f"✅ Task created: {title}\n"
            f"Reward: {money(reward)}\n"
            f"Maximum completions: {max_completions}"
        )

    async def admin_pending(self, update, db):
        items = (
            db.query(Withdrawal)
            .filter_by(status="pending")
            .limit(20)
            .all()
        )

        if not items:
            await update.message.reply_text("No pending withdrawals.")
            return

        text = "\n".join(
            f"#{w.id} | user {w.user_id} | {money(w.amount)} | {w.account_details}"
            for w in items
        )

        await update.message.reply_text(text)

    def run(self):
        self.application = (
            Application.builder()
            .token(Config.BOT_TOKEN)
            .build()
        )

        self.application.add_handler(
            CommandHandler("start", self.start_command)
        )
        self.application.add_handler(
            CommandHandler("help", self.start_command)
        )

        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback)
        )

        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.handle_message,
            )
        )

        self.application.add_handler(
            MessageHandler(
                filters.COMMAND,
                self.handle_message,
            )
        )

        logger.info(
            "🚀 AdVantage Bot v%s starting",
            Config.VERSION,
        )

        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES
        )


if __name__ == "__main__":
    AdVantageBot().run()
