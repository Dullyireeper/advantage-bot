import asyncio, json, logging, math, os, re, uuid, zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import Config
from database import *

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger=logging.getLogger('advantage')

EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE=re.compile(r'^\+?[0-9]{9,15}$')

def now(): return datetime.utcnow()
def money(v): return f'${float(v or 0):.2f}'
def valid_url(v):
    try:
        p=urlparse(v); return p.scheme in {'http','https'} and bool(p.netloc)
    except Exception: return False

def txref(prefix): return f'{prefix}-{uuid.uuid4().hex[:10].upper()}'

def kb(rows): return InlineKeyboardMarkup(rows)

def btn(text,data): return InlineKeyboardButton(text,callback_data=data)

class Bot:
    def __init__(self):
        Config.validate(); self.SessionLocal=init_db(); self.application=None
    def db(self): return self.SessionLocal()
    def admin(self,uid): return uid in Config.ADMIN_IDS
    def log(self,db,uid,action,target='',details=''):
        db.add(AdminLog(admin_id=uid,action=action,target_id=str(target),details=details))
    def balance(self,db,user,amount,kind,desc):
        before=float(user.balance or 0); user.balance=before+amount
        if amount>0: user.total_earned=(user.total_earned or 0)+amount
        db.add(BalanceHistory(user_id=user.telegram_id,amount=amount,type=kind,description=desc[:255],balance_before=before,balance_after=user.balance))
        db.add(Transaction(user_id=user.telegram_id,kind=kind,amount=amount,reference=txref(kind.upper()[:6]),description=desc))
    async def start(self,u,c):
        db=self.db()
        try:
            tg=u.effective_user; user=db.query(User).filter_by(telegram_id=tg.id).first()
            if not user:
                user=User(telegram_id=tg.id,username=tg.username,first_name=tg.first_name,last_name=tg.last_name,is_admin=self.admin(tg.id)); db.add(user); db.flush()
                db.add(DailyStreak(user_id=tg.id))
                if c.args and c.args[0].isdigit() and int(c.args[0])!=tg.id:
                    ref=db.query(User).filter_by(telegram_id=int(c.args[0])).first()
                    if ref and not db.query(Referral).filter_by(referred_id=tg.id).first():
                        user.referred_by=ref.telegram_id; db.add(Referral(referrer_id=ref.telegram_id,referred_id=tg.id,bonus=Config.REFERRAL_BONUS)); self.balance(db,ref,Config.REFERRAL_BONUS,'referral','Referral bonus')
            user.username=tg.username; user.first_name=tg.first_name; user.last_name=tg.last_name; user.last_active=now(); user.is_admin=self.admin(tg.id); db.commit()
            if Config.COMMUNITY_CHANNEL and not await self.member_ok(tg.id):
                await u.message.reply_text('👋 Welcome!\n\nPlease join our official community before using AdVantage.',reply_markup=kb([[InlineKeyboardButton('📢 Join Community',url=Config.COMMUNITY_INVITE or 'https://t.me/'+Config.COMMUNITY_CHANNEL.lstrip('@'))],[btn('✅ I Joined','check_join')]])); return
            await self.menu(u,user)
        except Exception: db.rollback(); logger.exception('start')
        finally: db.close()
    async def member_ok(self,uid):
        try:
            m=await self.application.bot.get_chat_member(Config.COMMUNITY_CHANNEL,uid); return m.status in ('member','administrator','creator')
        except Exception: return False
    async def menu(self,obj,user):
        rows=[[btn('📺 Watch Ads','ads'),btn('📋 Tasks','tasks')],[btn('🎮 Games','games'),btn('💎 Premium','premium')],[btn('📱 Social Tasks','social'),btn('👥 Referrals','ref')],[btn('💰 Wallet','wallet'),btn('👤 Profile','profile')],[btn('🆘 Support','support')]]
        if user and self.admin(user.telegram_id): rows.append([btn('⚙️ Admin Dashboard','admin')])
        text=f'🎯 <b>WELCOME TO ADVANTAGE</b> 🎯\n\n💰 Balance: <b>{money(user.balance)}</b>\n🏆 Lifetime earned: <b>{money(user.total_earned)}</b>\n\nChoose an option below.'
        if hasattr(obj,'message') and obj.message: await obj.message.reply_text(text,reply_markup=kb(rows),parse_mode=ParseMode.HTML)
        else: await obj.edit_message_text(text,reply_markup=kb(rows),parse_mode=ParseMode.HTML)
    async def callback(self,u,c):
        q=u.callback_query; await q.answer(); db=self.db()
        try:
            user=db.query(User).filter_by(telegram_id=u.effective_user.id).first()
            if not user: await q.edit_message_text('Send /start first.'); return
            user.last_active=now(); d=q.data
            if d=='check_join':
                if Config.COMMUNITY_CHANNEL and not await self.member_ok(user.telegram_id):
                    await q.edit_message_text('❌ You have not joined the community yet.',reply_markup=kb([[InlineKeyboardButton('📢 Join Community',url=Config.COMMUNITY_INVITE or 'https://t.me/'+Config.COMMUNITY_CHANNEL.lstrip('@'))],[btn('✅ Check Again','check_join')]])); return
                await self.menu(q,user); return
            routes={'ads':self.ads,'tasks':self.tasks,'games':self.games,'premium':self.premium,'social':self.social,'ref':self.ref,'wallet':self.wallet,'profile':self.profile,'support':self.support,'admin':self.admin_dashboard,'back':self.menu}
            if d in routes:
                if d=='admin' and not self.admin(user.telegram_id): await q.edit_message_text('❌ Unauthorized.'); return
                await routes[d](q,user,db) if d!='back' else await routes[d](q,user)
            elif d=='wallet_deposit': await self.deposit_methods(q,user,db)
            elif d=='wallet_withdraw': await self.withdraw_methods(q,user,db)
            elif d.startswith('dep_'): await self.begin_deposit(q,user,db,d[4:])
            elif d.startswith('wd_'): await self.begin_withdraw(q,user,db,d[3:])
            elif d.startswith('ad_'): await self.claim_ad(q,user,db,int(d.split('_')[1]))
            elif d.startswith('task_'): await self.task_open(q,user,db,int(d.split('_')[1]))
            elif d.startswith('socialtask_'): await self.socialtask(q,user,db,int(d.split('_')[1]))
            elif d.startswith('admin_'): await self.admin_action(q,user,db,d)
            elif d.startswith('pm_'): await self.admin_payment_method(q,user,db,d)
            elif d=='email': c.user_data['state']='email'; await q.edit_message_text('📧 Enter your email address:')
            elif d=='history': await self.history(q,user,db)
            elif d=='community': await self.community(q,user)
            else: await q.edit_message_text('❌ Unknown action.')
            db.commit()
        except Exception: db.rollback(); logger.exception('callback'); await q.edit_message_text('⚠️ Something went wrong.')
        finally: db.close()
    async def profile(self,q,user,db):
        refs=db.query(Referral).filter_by(referrer_id=user.telegram_id).count()
        await q.edit_message_text(f'👤 <b>PROFILE</b>\n\nTelegram ID: <code>{user.telegram_id}</code>\nUsername: @{user.username or "N/A"}\n📧 Email: {user.email or "Not set"}\n\n💰 Balance: <b>{money(user.balance)}</b>\n💵 Earned: <b>{money(user.total_earned)}</b>\n🏦 Withdrawn: <b>{money(user.total_withdrawn)}</b>\n👥 Referrals: <b>{refs}</b>',reply_markup=kb([[btn('📧 Set Email','email')],[btn('📜 Transaction History','history')],[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def wallet(self,q,user,db):
        await q.edit_message_text(f'💰 <b>MY WALLET</b>\n\nAvailable: <b>{money(user.balance)}</b>\nPending: <b>{money(user.pending_balance)}</b>\nLifetime earned: <b>{money(user.total_earned)}</b>\nWithdrawn: <b>{money(user.total_withdrawn)}</b>',reply_markup=kb([[btn('➕ Deposit','wallet_deposit'),btn('➖ Withdraw','wallet_withdraw')],[btn('📜 History','history')],[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def deposit_methods(self,q,user,db):
        ms=db.query(PaymentMethod).filter_by(enabled=True,deposit_enabled=True).all(); rows=[[btn(f'{m.logo} {m.name}','dep_'+m.slug)] for m in ms]; rows.append([btn('🔙 Back','wallet')]); await q.edit_message_text('➕ <b>DEPOSIT</b>\n\nSelect a payment method:',reply_markup=kb(rows),parse_mode=ParseMode.HTML)
    async def withdraw_methods(self,q,user,db):
        ms=db.query(PaymentMethod).filter_by(enabled=True,withdrawal_enabled=True).all(); rows=[[btn(f'{m.logo} {m.name}','wd_'+m.slug)] for m in ms]; rows.append([btn('🔙 Back','wallet')]); await q.edit_message_text('➖ <b>WITHDRAW</b>\n\nSelect a payment method:',reply_markup=kb(rows),parse_mode=ParseMode.HTML)
    async def begin_deposit(self,q,user,db,slug):
        m=db.query(PaymentMethod).filter_by(slug=slug,enabled=True,deposit_enabled=True).first()
        if not m: await q.edit_message_text('❌ Payment method unavailable.'); return
        q.message.chat_id; q._bot._pending_payment if False else None
        # state is stored per-user in bot_data via context on next message
        self.application.bot_data.setdefault('states',{})[user.telegram_id]={'type':'deposit_amount','method':slug}
        text=f'➕ <b>{m.name} DEPOSIT</b>\n\nSend the amount you want to deposit.\nMinimum: {money(m.min_deposit)}\n\n{m.instructions or "Follow the payment instructions provided by the administrator."}'
        if m.receiving_account: text+=f'\n\n📥 Receiving account: <code>{m.receiving_account}</code>'
        await q.edit_message_text(text,parse_mode=ParseMode.HTML)
    async def begin_withdraw(self,q,user,db,slug):
        m=db.query(PaymentMethod).filter_by(slug=slug,enabled=True,withdrawal_enabled=True).first()
        if not m: await q.edit_message_text('❌ Payment method unavailable.'); return
        self.application.bot_data.setdefault('states',{})[user.telegram_id]={'type':'withdraw_amount','method':slug}
        await q.edit_message_text(f'➖ <b>{m.name} WITHDRAWAL</b>\n\nAvailable: {money(user.balance)}\nMinimum: {money(max(Config.MIN_WITHDRAWAL,m.min_withdrawal))}\n\nEnter amount:',parse_mode=ParseMode.HTML)
    async def ads(self,q,user,db):
        day=now().replace(hour=0,minute=0,second=0,microsecond=0); count=db.query(AdView).filter(AdView.user_id==user.telegram_id,AdView.viewed_at>=day).count()
        ad=db.query(Ad).filter(Ad.is_active.is_(True),Ad.total_views<Ad.max_views).first()
        if count>=Config.MAX_ADS_PER_DAY: await q.edit_message_text('⚠️ Daily ad limit reached.',reply_markup=kb([[btn('🔙 Back','back')]])); return
        if not ad: await q.edit_message_text('📺 No ads available.',reply_markup=kb([[btn('🔙 Back','back')]])); return
        self.application.bot_data.setdefault('ad_started',{})[user.telegram_id]=(ad.id,now())
        await q.edit_message_text(f'📺 <b>{ad.title}</b>\n\n{ad.description or ""}\n\n💰 Reward: <b>{money(ad.user_reward)}</b>\n👀 {ad.total_views}/{ad.max_views}\n\nOpen the advertiser link and remain there for at least {Config.AD_MIN_SECONDS} seconds before claiming.',reply_markup=kb([[InlineKeyboardButton('🔗 Open Ad',url=ad.link_url)],[btn('✅ Claim Reward','ad_'+str(ad.id))],[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def claim_ad(self,q,user,db,adid):
        ad=db.query(Ad).filter_by(id=adid,is_active=True).first(); started=self.application.bot_data.get('ad_started',{}).get(user.telegram_id)
        if not ad or not started or started[0]!=adid or (now()-started[1]).total_seconds()<Config.AD_MIN_SECONDS: await q.edit_message_text('⏳ Please open the ad and wait the required time before claiming.'); return
        day=now().replace(hour=0,minute=0,second=0,microsecond=0); count=db.query(AdView).filter(AdView.user_id==user.telegram_id,AdView.viewed_at>=day).count()
        if count>=Config.MAX_ADS_PER_DAY: await q.edit_message_text('⚠️ Daily limit reached.'); return
        db.add(AdView(user_id=user.telegram_id,ad_id=ad.id,user_reward=ad.user_reward,owner_revenue=ad.cost_per_view,verified=True)); ad.total_views+=1; ad.is_active=ad.total_views<ad.max_views; self.balance(db,user,ad.user_reward,'ad',f'Verified ad reward #{ad.id}')
        await q.edit_message_text(f'✅ <b>Reward credited</b>\n\n+{money(ad.user_reward)}\nBalance: <b>{money(user.balance)}</b>',reply_markup=kb([[btn('📺 Watch More','ads')],[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def tasks(self,q,user,db):
        ts=db.query(Task).filter_by(is_active=True).all(); rows=[]
        for t in ts[:15]:
            done=db.query(TaskCompletion).filter_by(user_id=user.telegram_id,task_id=t.id).first()
            if not done and t.completions<t.max_completions: rows.append([btn(f'📋 {t.title} • +{money(t.reward)}',f'task_{t.id}')])
        rows.append([btn('🔙 Back','back')]); await q.edit_message_text('📋 <b>TASK MARKETPLACE</b>\n\nChoose a task:',reply_markup=kb(rows),parse_mode=ParseMode.HTML)
    async def task_open(self,q,user,db,tid):
        t=db.query(Task).filter_by(id=tid,is_active=True).first()
        if not t: await q.edit_message_text('❌ Task unavailable.'); return
        if db.query(TaskCompletion).filter_by(user_id=user.telegram_id,task_id=tid).first(): await q.edit_message_text('✅ Already submitted.'); return
        self.application.bot_data.setdefault('states',{})[user.telegram_id]={'type':'task_proof','task_id':tid}
        await q.edit_message_text(f'📋 <b>{t.title}</b>\n\n{t.description or ""}\n\n💰 Reward: {money(t.reward)}\n\n{("Open the link, complete the task, then send proof." if t.requires_proof else "Complete the task, then send DONE.")}',reply_markup=kb([[InlineKeyboardButton('🔗 Open Task',url=t.url)] ,[btn('🔙 Back','tasks')]]),parse_mode=ParseMode.HTML)
    async def social(self,q,user,db):
        ts=db.query(SocialTask).filter_by(is_active=True).all(); rows=[[btn(f'📱 {t.platform.title()} +{t.points_reward} pts',f'socialtask_{t.id}')] for t in ts[:10]]; rows.append([btn('🔙 Back','back')]); await q.edit_message_text('📱 <b>SOCIAL TASKS</b>\n\nComplete genuine social actions. Rewards are points, not cash.',reply_markup=kb(rows),parse_mode=ParseMode.HTML)
    async def socialtask(self,q,user,db,tid):
        t=db.query(SocialTask).filter_by(id=tid,is_active=True).first()
        if not t: await q.edit_message_text('Unavailable.'); return
        done=db.query(SocialTaskCompletion).filter_by(user_id=user.telegram_id,task_id=tid).first()
        if done: await q.edit_message_text('Already completed.'); return
        db.add(SocialTaskCompletion(user_id=user.telegram_id,task_id=tid,points_earned=t.points_reward)); p=db.query(SocialProfile).filter_by(user_id=user.telegram_id).first() or SocialProfile(user_id=user.telegram_id,username=user.username or str(user.telegram_id)); db.add(p) if not p.id else None; p.points+=t.points_reward; p.followers_gained+=1
        await q.edit_message_text(f'✅ Task recorded. +{t.points_reward} points.',reply_markup=kb([[btn('📱 More','social')],[btn('🔙 Back','back')]]))
    async def games(self,q,user,db): await q.edit_message_text('🎮 <b>MINI GAMES</b>\n\nGames can be enabled by the administrator. No gambling or cash wagering is enabled.',reply_markup=kb([[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def premium(self,q,user,db):
        ps=db.query(PremiumPackage).filter_by(is_active=True).all(); text='💎 <b>PREMIUM</b>\n\n'+('\n'.join(f'• {p.name} — {money(p.price_usd)}' for p in ps) if ps else 'No packages configured yet.'); await q.edit_message_text(text,reply_markup=kb([[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def ref(self,q,user,db):
        link=f'https://t.me/{Config.BOT_USERNAME.lstrip("@")} ?start={user.telegram_id}'.replace(' ',''); n=db.query(Referral).filter_by(referrer_id=user.telegram_id).count(); await q.edit_message_text(f'👥 <b>REFERRALS</b>\n\nReferrals: <b>{n}</b>\nBonus per referral: <b>{money(Config.REFERRAL_BONUS)}</b>\n\n<code>{link}</code>',reply_markup=kb([[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def history(self,q,user,db):
        rows=db.query(BalanceHistory).filter_by(user_id=user.telegram_id).order_by(BalanceHistory.created_at.desc()).limit(12).all(); text='📜 <b>HISTORY</b>\n\n'+('\n'.join(f'{x.created_at:%m-%d %H:%M} • {x.type} • {money(x.amount)}' for x in rows) if rows else 'No transactions yet.'); await q.edit_message_text(text,reply_markup=kb([[btn('🔙 Back','wallet')]]),parse_mode=ParseMode.HTML)
    async def community(self,q,user): await q.edit_message_text('📢 <b>COMMUNITY</b>\n\nJoin our official community for announcements and support.',reply_markup=kb([[InlineKeyboardButton('📢 Join',url=Config.COMMUNITY_INVITE or 'https://t.me/'+Config.COMMUNITY_CHANNEL.lstrip('@'))],[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def support(self,q,user,db):
        await q.edit_message_text(f'🆘 <b>SUPPORT</b>\n\n{("Contact @"+Config.SUPPORT_USERNAME.lstrip("@")) if Config.SUPPORT_USERNAME else "Use the support administrator configured for this bot."}',reply_markup=kb([[btn('🔙 Back','back')]]),parse_mode=ParseMode.HTML)
    async def admin_dashboard(self,q,user,db):
        users=db.query(User).count(); active=db.query(User).filter(User.last_active>=now()-timedelta(days=1)).count(); ads=db.query(Ad).filter_by(is_active=True).count(); views=db.query(AdView).count(); deps=db.query(Deposit).filter_by(status='pending').count(); wds=db.query(Withdrawal).filter_by(status='pending').count(); bal=sum((x.balance or 0) for x in db.query(User).all())
        text=f'⚙️ <b>ADMIN DASHBOARD</b>\n\n💳 Use /pendingdeposits, /approvedep ID, /rejectdep ID\n💸 Use /pendingwithdrawals, /approvewd ID, /rejectwd ID\n\n👥 Users: {users}\n🟢 Active 24h: {active}\n📺 Active ads: {ads}\n👀 Verified views: {views}\n💰 User balances: {money(bal)}\n⏳ Deposits: {deps}\n⏳ Withdrawals: {wds}'
        rows=[[btn('👥 Users','admin_users'),btn('💳 Payments','admin_payments')],[btn('📺 Ads','admin_ads'),btn('📋 Tasks','admin_tasks')],[btn('📊 Analytics','admin_stats'),btn('📢 Broadcast','admin_broadcast')],[btn('⚙️ Settings','admin_settings'),btn('🛡️ Security','admin_security')],[btn('💾 Backup DB','admin_backup')],[btn('🔙 Back','back')]]; await q.edit_message_text(text,reply_markup=kb(rows),parse_mode=ParseMode.HTML)
    async def admin_action(self,q,user,db,d):
        if not self.admin(user.telegram_id): await q.edit_message_text('❌ Unauthorized.'); return
        if d=='admin_users': await q.edit_message_text(f'👥 Users: {db.query(User).count()}\n\nUse /user USER_ID to inspect a user.\nUse /credit USER_ID AMOUNT to credit.\nUse /debit USER_ID AMOUNT to debit.',reply_markup=kb([[btn('🔙 Admin','admin')]]))
        elif d=='admin_stats':
            await q.edit_message_text(f'📊 <b>ANALYTICS</b>\n\nUsers: {db.query(User).count()}\nAds: {db.query(Ad).count()}\nAd views: {db.query(AdView).count()}\nTasks: {db.query(Task).count()}\nTask submissions: {db.query(TaskCompletion).count()}\nDeposits: {db.query(Deposit).count()}\nWithdrawals: {db.query(Withdrawal).count()}',reply_markup=kb([[btn('🔙 Admin','admin')]]),parse_mode=ParseMode.HTML)
        elif d=='admin_payments':
            ms=db.query(PaymentMethod).all(); rows=[[btn(f'{m.logo} {m.name}','pm_'+m.slug)] for m in ms]; rows.append([btn('➕ Add method','admin_addpm'),btn('🔙 Admin','admin')]); await q.edit_message_text('💳 <b>PAYMENT METHODS</b>\n\nSelect one to configure.',reply_markup=kb(rows),parse_mode=ParseMode.HTML)
        elif d.startswith('admin_') and d[6:] in ('ads','tasks'):
            if d=='admin_ads': await q.edit_message_text('📺 Ads management\n\n/addad Title|Description|URL|Reward|MaxViews\n/deletead ID\n/ads',reply_markup=kb([[btn('🔙 Admin','admin')]]))
            else: await q.edit_message_text('📋 Task management\n\n/addtask Title|Description|URL|Reward|MaxCompletions\n/tasks',reply_markup=kb([[btn('🔙 Admin','admin')]]))
        elif d=='admin_broadcast': self.application.bot_data.setdefault('states',{})[user.telegram_id]={'type':'broadcast'}; await q.edit_message_text('📢 Send the broadcast message now:')
        elif d=='admin_security': await q.edit_message_text('🛡️ Security controls enabled: duplicate checks, rate limits, daily limits, pending review, admin authorization and audit logs.',reply_markup=kb([[btn('🔙 Admin','admin')]]))
        elif d=='admin_settings': await q.edit_message_text('⚙️ Settings are controlled by Railway Variables for secrets and Config values. Payment accounts are managed through the payment-method commands.',reply_markup=kb([[btn('🔙 Admin','admin')]]))
        elif d=='admin_backup': await self.backup(q,user,db)
        elif d=='admin_addpm': self.application.bot_data.setdefault('states',{})[user.telegram_id]={'type':'addpm'}; await q.edit_message_text('Enter: slug|name|logo|currency|account label|receiving account|account format|deposit min|withdraw min')
    async def admin_payment_method(self,q,user,db,d):
        if not self.admin(user.telegram_id): return
        slug=d[3:]; m=db.query(PaymentMethod).filter_by(slug=slug).first()
        if not m: await q.edit_message_text('Not found.'); return
        self.application.bot_data.setdefault('states',{})[user.telegram_id]={'type':'editpm','slug':slug}; await q.edit_message_text(f'💳 {m.name}\n\nCurrent receiving account: {m.receiving_account or "not set"}\n\nEnter new receiving account, or type DISABLE to disable deposits/withdrawals.')
    async def backup(self,q,user,db):
        if not Config.DATABASE_URL.startswith('sqlite'): await q.edit_message_text('Automatic file backup is only implemented for SQLite. Use your PostgreSQL provider backups.'); return
        path=Path('bot.db');
        if not path.exists(): await q.edit_message_text('Database file not found.'); return
        out=Path('/tmp')/f'advantage-backup-{now():%Y%m%d-%H%M%S}.db'; out.write_bytes(path.read_bytes()); await q.message.reply_document(document=str(out),caption='AdVantage database backup'); await q.edit_message_text('✅ Backup sent.',reply_markup=kb([[btn('🔙 Admin','admin')]]))
    async def message(self,u,c):
        if not u.message: return
        uid=u.effective_user.id; text=(u.message.text or '').strip(); db=self.db()
        try:
            user=db.query(User).filter_by(telegram_id=uid).first()
            if not user: await u.message.reply_text('Send /start first.'); return
            state=self.application.bot_data.get('states',{}).get(uid)
            if state:
                typ=state['type']
                if typ=='email':
                    if not EMAIL_RE.match(text): await u.message.reply_text('❌ Enter a valid email.'); return
                    user.email=text.lower(); user.is_verified=True; self.application.bot_data['states'].pop(uid,None); await u.message.reply_text('✅ Email saved.');
                elif typ=='deposit_amount': await self.deposit_amount(u,user,db,state,text)
                elif typ=='deposit_tx': await self.deposit_tx(u,user,db,state,text)
                elif typ=='withdraw_amount': await self.withdraw_amount(u,user,db,state,text)
                elif typ=='withdraw_account': await self.withdraw_account(u,user,db,state,text)
                elif typ=='task_proof': await self.task_proof(u,user,db,state,text)
                elif typ=='broadcast': await self.broadcast(u,user,db,text)
                elif typ=='addpm': await self.addpm(u,user,db,text)
                elif typ=='editpm': await self.editpm(u,user,db,state,text)
                db.commit(); return
            cmd=text.split()[0].lstrip('/').lower() if text.startswith('/') else ''
            if cmd=='stats' and self.admin(uid): await self.admin_dashboard(u,user,db)
            elif cmd=='addad' and self.admin(uid): await self.addad(u,db,text)
            elif cmd=='addtask' and self.admin(uid): await self.addtask(u,db,text)
            elif cmd=='ads' and self.admin(uid): await u.message.reply_text('\n'.join(f'#{a.id} {a.title} {a.total_views}/{a.max_views} {"ON" if a.is_active else "OFF"}' for a in db.query(Ad).all()) or 'No ads')
            elif cmd=='tasks' and self.admin(uid): await u.message.reply_text('\n'.join(f'#{t.id} {t.title} {t.completions}/{t.max_completions}' for t in db.query(Task).all()) or 'No tasks')
            elif cmd=='credit' and self.admin(uid): await self.adjust(u,user,db,text,1)
            elif cmd=='debit' and self.admin(uid): await self.adjust(u,user,db,text,-1)
            elif cmd=='user' and self.admin(uid): await self.user_info(u,db,text)
            elif cmd=='pendingdeposits' and self.admin(uid): await self.pending_deposits(u,db)
            elif cmd=='approvedep' and self.admin(uid): await self.approve_deposit(u,db,text)
            elif cmd=='rejectdep' and self.admin(uid): await self.reject_deposit(u,db,text)
            elif cmd=='pendingwithdrawals' and self.admin(uid): await self.pending_withdrawals(u,db)
            elif cmd=='approvewd' and self.admin(uid): await self.approve_withdrawal_cmd(u,db,text)
            elif cmd=='rejectwd' and self.admin(uid): await self.reject_withdrawal_cmd(u,db,text)
            elif cmd=='help': await u.message.reply_text('/start opens the menu.')
            else: await u.message.reply_text('Use /start to open the menu.')
            db.commit()
        except Exception: db.rollback(); logger.exception('message'); await u.message.reply_text('⚠️ Something went wrong.')
        finally: db.close()
    async def deposit_amount(self,u,user,db,s,text):
        try: amount=float(text)
        except: await u.message.reply_text('❌ Enter a valid amount.'); return
        m=db.query(PaymentMethod).filter_by(slug=s['method']).first()
        if amount<m.min_deposit: await u.message.reply_text(f'❌ Minimum deposit is {money(m.min_deposit)}.'); return
        dep=Deposit(user_id=user.telegram_id,amount=amount,method=m.name,transaction_id=txref('DEP')); db.add(dep); s['deposit_id']=dep.id; s['type']='deposit_tx'; await u.message.reply_text(f'💳 Send {money(amount)} to the configured {m.name} account, then enter the transaction/reference ID.\n\nReference: <code>{dep.transaction_id}</code>',parse_mode=ParseMode.HTML)
    async def deposit_tx(self,u,user,db,s,text):
        dep=db.query(Deposit).filter_by(id=s['deposit_id'],user_id=user.telegram_id).first(); dep.proof=text[:500]; self.application.bot_data['states'].pop(user.telegram_id,None); await u.message.reply_text('✅ Deposit submitted for admin verification.')
        await self.notify_admins(f'💳 Deposit #{dep.id}\nUser: {user.telegram_id}\nAmount: {money(dep.amount)}\nMethod: {dep.method}\nTX: {text}')
    async def withdraw_amount(self,u,user,db,s,text):
        try: amount=float(text)
        except: await u.message.reply_text('❌ Enter a valid amount.'); return
        m=db.query(PaymentMethod).filter_by(slug=s['method']).first(); minimum=max(Config.MIN_WITHDRAWAL,m.min_withdrawal)
        if amount<minimum: await u.message.reply_text(f'❌ Minimum is {money(minimum)}.'); return
        if amount>user.balance: await u.message.reply_text('❌ Insufficient balance.'); return
        s['amount']=amount; s['type']='withdraw_account'; await u.message.reply_text(f'Enter your {m.account_label}.\nFormat: {m.account_format}')
    async def withdraw_account(self,u,user,db,s,text):
        m=db.query(PaymentMethod).filter_by(slug=s['method']).first(); amount=float(s['amount'])
        if m.slug=='paypal' and not EMAIL_RE.match(text): await u.message.reply_text('❌ Enter a valid PayPal email.'); return
        if m.slug=='mpesa' and not PHONE_RE.match(text.replace(' ','')): await u.message.reply_text('❌ Enter a valid phone number.'); return
        day=now().replace(hour=0,minute=0,second=0,microsecond=0); total=sum(x.amount for x in db.query(Withdrawal).filter(Withdrawal.user_id==user.telegram_id,Withdrawal.requested_at>=day,Withdrawal.status.in_(['pending','completed'])).all())
        if total+amount>Config.MAX_WITHDRAWAL_DAILY: await u.message.reply_text(f'❌ Daily withdrawal limit is {money(Config.MAX_WITHDRAWAL_DAILY)}.'); return
        self.balance(db,user,-amount,'withdrawal_hold','Withdrawal reserved'); w=Withdrawal(user_id=user.telegram_id,amount=amount,method=m.name,account_details=text[:500],transaction_id=txref('WTH')); db.add(w); self.application.bot_data['states'].pop(user.telegram_id,None); await u.message.reply_text(f'✅ Withdrawal #{w.id} submitted. Funds are reserved until admin approval.'); await self.notify_admins(f'💸 Withdrawal #{w.id}\nUser {user.telegram_id}\n{money(amount)} via {m.name}\nAccount: {text}')
    async def task_proof(self,u,user,db,s,text):
        t=db.query(Task).filter_by(id=s['task_id'],is_active=True).first(); c=TaskCompletion(user_id=user.telegram_id,task_id=t.id,proof=text[:1000],status='approved' if not t.requires_proof and text.upper()=='DONE' else 'pending',reward=t.reward if not t.requires_proof and text.upper()=='DONE' else 0); db.add(c)
        if c.status=='approved': t.completions+=1; self.balance(db,user,t.reward,'task','Task reward'); await u.message.reply_text(f'✅ Task completed. +{money(t.reward)}')
        else: await u.message.reply_text('✅ Task proof submitted for review.')
        self.application.bot_data['states'].pop(user.telegram_id,None); await self.notify_admins(f'📋 Task submission #{c.id} from {user.telegram_id} for task #{t.id}')
    async def addad(self,u,db,text):
        f=text.split(' ',1)[1].split('|') if ' ' in text else []
        if len(f)!=5: await u.message.reply_text('/addad Title|Description|URL|Reward|MaxViews'); return
        title,desc,url,reward,mv=f
        if not valid_url(url): await u.message.reply_text('Invalid URL.'); return
        a=Ad(title=title[:200],description=desc,link_url=url,user_reward=float(reward),cost_per_view=max(float(reward),Config.AD_REVENUE_PER_VIEW),max_views=int(mv)); db.add(a); await u.message.reply_text(f'✅ Ad #{a.id} created.')
    async def addtask(self,u,db,text):
        f=text.split(' ',1)[1].split('|') if ' ' in text else []
        if len(f)!=5: await u.message.reply_text('/addtask Title|Description|URL|Reward|MaxCompletions'); return
        title,desc,url,reward,mx=f
        if not valid_url(url): await u.message.reply_text('Invalid URL.'); return
        t=Task(title=title[:200],description=desc,url=url,reward=float(reward),max_completions=int(mx)); db.add(t); await u.message.reply_text(f'✅ Task #{t.id} created.')
    async def pending_deposits(self,u,db):
        items=db.query(Deposit).filter_by(status='pending').order_by(Deposit.requested_at.asc()).limit(20).all()
        await u.message.reply_text('\n'.join(f'#{x.id} user={x.user_id} amount={money(x.amount)} method={x.method} proof={x.proof or "-"}' for x in items) or 'No pending deposits.')
    async def approve_deposit(self,u,db,text):
        p=text.split();
        if len(p)!=2 or not p[1].isdigit(): await u.message.reply_text('/approvedep ID'); return
        d=db.query(Deposit).filter_by(id=int(p[1]),status='pending').first()
        if not d: await u.message.reply_text('Deposit not found or already processed.'); return
        target=db.query(User).filter_by(telegram_id=d.user_id).first();
        if not target: await u.message.reply_text('User not found.'); return
        d.status='completed'; d.completed_at=now(); self.balance(db,target,d.amount,'deposit',f'Approved deposit #{d.id}'); self.log(db,u.effective_user.id,'approve_deposit',d.id,str(d.amount)); await u.message.reply_text(f'✅ Deposit #{d.id} approved and {money(d.amount)} credited.');
        try: await self.application.bot.send_message(target.telegram_id,f'✅ Your deposit #{d.id} of {money(d.amount)} was approved.')
        except Exception: pass
    async def reject_deposit(self,u,db,text):
        p=text.split();
        if len(p)<2 or not p[1].isdigit(): await u.message.reply_text('/rejectdep ID [reason]'); return
        d=db.query(Deposit).filter_by(id=int(p[1]),status='pending').first();
        if not d: await u.message.reply_text('Deposit not found or already processed.'); return
        d.status='rejected'; d.completed_at=now(); d.admin_note=' '.join(p[2:])[:255]; self.log(db,u.effective_user.id,'reject_deposit',d.id,d.admin_note); await u.message.reply_text(f'↩️ Deposit #{d.id} rejected.')
    async def pending_withdrawals(self,u,db):
        items=db.query(Withdrawal).filter_by(status='pending').order_by(Withdrawal.requested_at.asc()).limit(20).all()
        await u.message.reply_text('\n'.join(f'#{x.id} user={x.user_id} amount={money(x.amount)} method={x.method} account={x.account_details}' for x in items) or 'No pending withdrawals.')
    async def approve_withdrawal_cmd(self,u,db,text):
        p=text.split();
        if len(p)!=2 or not p[1].isdigit(): await u.message.reply_text('/approvewd ID'); return
        w=db.query(Withdrawal).filter_by(id=int(p[1]),status='pending').first();
        if not w: await u.message.reply_text('Withdrawal not found or already processed.'); return
        w.status='completed'; w.completed_at=now(); target=db.query(User).filter_by(telegram_id=w.user_id).first();
        if target: target.total_withdrawn=(target.total_withdrawn or 0)+w.amount
        self.log(db,u.effective_user.id,'approve_withdrawal',w.id,str(w.amount)); await u.message.reply_text(f'✅ Withdrawal #{w.id} approved.');
        try: await self.application.bot.send_message(w.user_id,f'✅ Your withdrawal #{w.id} of {money(w.amount)} was approved.')
        except Exception: pass
    async def reject_withdrawal_cmd(self,u,db,text):
        p=text.split();
        if len(p)<2 or not p[1].isdigit(): await u.message.reply_text('/rejectwd ID [reason]'); return
        w=db.query(Withdrawal).filter_by(id=int(p[1]),status='pending').first();
        if not w: await u.message.reply_text('Withdrawal not found or already processed.'); return
        target=db.query(User).filter_by(telegram_id=w.user_id).first();
        if target: self.balance(db,target,w.amount,'withdrawal_refund',f'Refund rejected withdrawal #{w.id}')
        w.status='rejected'; w.completed_at=now(); w.admin_note=' '.join(p[2:])[:255]; self.log(db,u.effective_user.id,'reject_withdrawal',w.id,w.admin_note); await u.message.reply_text(f'↩️ Withdrawal #{w.id} rejected and refunded.')
        try: await self.application.bot.send_message(w.user_id,f'↩️ Your withdrawal #{w.id} was rejected and refunded.')
        except Exception: pass

    async def adjust(self,u,admin,db,text,mult):
        p=text.split();
        if len(p)!=3 or not p[1].isdigit(): await u.message.reply_text('/credit USER_ID AMOUNT'); return
        target=db.query(User).filter_by(telegram_id=int(p[1])).first(); amount=float(p[2])*mult
        if not target or (mult<0 and target.balance<abs(amount)): await u.message.reply_text('Invalid user or insufficient balance.'); return
        self.balance(db,target,amount,'admin','Admin balance adjustment'); self.log(db,admin.telegram_id,'balance_adjust',target.telegram_id,str(amount)); await u.message.reply_text('✅ Done.')
    async def user_info(self,u,db,text):
        p=text.split(); target=db.query(User).filter_by(telegram_id=int(p[1])).first() if len(p)>1 and p[1].isdigit() else None; await u.message.reply_text(f'User {target.telegram_id}\n@{target.username or "N/A"}\nBalance {money(target.balance)}\nEarned {money(target.total_earned)}\nEmail {target.email or "N/A"}' if target else 'User not found.')
    async def broadcast(self,u,user,db,text):
        if not self.admin(user.telegram_id): return
        self.application.bot_data['states'].pop(user.telegram_id,None); users=db.query(User).filter_by(is_active=True).all(); sent=0
        for x in users:
            try: await self.application.bot.send_message(x.telegram_id,text); sent+=1
            except Exception: pass
            await asyncio.sleep(0.05)
        await u.message.reply_text(f'📢 Broadcast sent to {sent} users.')
    async def addpm(self,u,user,db,text):
        if not self.admin(user.telegram_id): return
        f=text.split('|')
        if len(f)!=9: await u.message.reply_text('Expected 9 fields.'); return
        slug,name,logo,currency,label,account,fmt,mindep,minwd=f; m=PaymentMethod(slug=slug,name=name,logo=logo,currency=currency,account_label=label,receiving_account=account,account_format=fmt,min_deposit=float(mindep),min_withdrawal=float(minwd)); db.add(m); self.application.bot_data['states'].pop(user.telegram_id,None); await u.message.reply_text('✅ Payment method added.')
    async def editpm(self,u,user,db,s,text):
        m=db.query(PaymentMethod).filter_by(slug=s['slug']).first();
        if text.upper()=='DISABLE': m.enabled=False
        else: m.receiving_account=text[:255]
        self.application.bot_data['states'].pop(user.telegram_id,None); await u.message.reply_text('✅ Payment method updated.')
    async def notify_admins(self,text):
        for aid in Config.ADMIN_IDS:
            try: await self.application.bot.send_message(aid,text)
            except Exception: pass
    async def run_async(self):
        self.application=Application.builder().token(Config.BOT_TOKEN).build()
        self.application.add_handler(CommandHandler('start',self.start)); self.application.add_handler(CommandHandler('help',lambda u,c: u.message.reply_text('/start')))
        self.application.add_handler(CallbackQueryHandler(self.callback)); self.application.add_handler(MessageHandler(filters.TEXT,self.message))
        await self.application.initialize(); await self.application.start(); await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info('AdVantage v%s running',Config.VERSION)
        await asyncio.Event().wait()
    def run(self): asyncio.run(self.run_async())

if __name__=='__main__': Bot().run()
