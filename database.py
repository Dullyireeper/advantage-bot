import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, BigInteger, UniqueConstraint, Index
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True); telegram_id=Column(BigInteger,unique=True,nullable=False,index=True)
    username=Column(String(100)); first_name=Column(String(100)); last_name=Column(String(100)); email=Column(String(254),unique=True)
    balance=Column(Float,default=0.0); pending_balance=Column(Float,default=0.0); referred_by=Column(BigInteger,index=True)
    join_date=Column(DateTime,default=datetime.utcnow); last_active=Column(DateTime,default=datetime.utcnow,index=True)
    is_active=Column(Boolean,default=True); is_admin=Column(Boolean,default=False); is_verified=Column(Boolean,default=False)
    total_earned=Column(Float,default=0.0); total_withdrawn=Column(Float,default=0.0); phone_number=Column(String(30)); language=Column(String(10),default='en')
    notifications_enabled=Column(Boolean,default=True); suspicious_score=Column(Integer,default=0); suspended_reason=Column(String(255))

class PaymentMethod(Base):
    __tablename__='payment_methods'
    id=Column(Integer,primary_key=True); name=Column(String(80),unique=True); slug=Column(String(80),unique=True)
    logo=Column(String(20),default='💳'); currency=Column(String(20),default='USD'); account_label=Column(String(100),default='Account')
    receiving_account=Column(String(255)); instructions=Column(Text); min_deposit=Column(Float,default=1); min_withdrawal=Column(Float,default=5)
    enabled=Column(Boolean,default=True); deposit_enabled=Column(Boolean,default=True); withdrawal_enabled=Column(Boolean,default=True)
    account_format=Column(String(255),default='Any valid account or wallet address')

class Deposit(Base):
    __tablename__='deposits'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); amount=Column(Float); method=Column(String(80));
    transaction_id=Column(String(100),unique=True); proof=Column(Text); status=Column(String(30),default='pending',index=True)
    requested_at=Column(DateTime,default=datetime.utcnow); completed_at=Column(DateTime); admin_note=Column(Text)

class Withdrawal(Base):
    __tablename__='withdrawals'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); amount=Column(Float); method=Column(String(80)); account_details=Column(Text)
    transaction_id=Column(String(100),unique=True); status=Column(String(30),default='pending',index=True); requested_at=Column(DateTime,default=datetime.utcnow)
    completed_at=Column(DateTime); admin_note=Column(Text)

class BalanceHistory(Base):
    __tablename__='balance_history'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); amount=Column(Float); type=Column(String(30)); description=Column(String(255))
    created_at=Column(DateTime,default=datetime.utcnow); balance_before=Column(Float); balance_after=Column(Float)

class Ad(Base):
    __tablename__='ads'
    id=Column(Integer,primary_key=True); title=Column(String(200),nullable=False); description=Column(Text); advertiser_name=Column(String(200)); image_url=Column(String(500)); link_url=Column(String(500),nullable=False)
    cost_per_view=Column(Float,default=0.008); user_reward=Column(Float,default=0.002); total_views=Column(Integer,default=0); max_views=Column(Integer,default=1000)
    is_active=Column(Boolean,default=True); created_at=Column(DateTime,default=datetime.utcnow); expires_at=Column(DateTime); budget=Column(Float,default=0.0)

class AdView(Base):
    __tablename__='ad_views'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); ad_id=Column(Integer,index=True); viewed_at=Column(DateTime,default=datetime.utcnow,index=True)
    user_reward=Column(Float); owner_revenue=Column(Float); verified=Column(Boolean,default=False)
    __table_args__=(UniqueConstraint('user_id','ad_id','viewed_at',name='uq_ad_view'),)

class Task(Base):
    __tablename__='tasks'
    id=Column(Integer,primary_key=True); title=Column(String(200)); description=Column(Text); task_type=Column(String(50)); url=Column(String(500)); reward=Column(Float,default=0.0)
    max_completions=Column(Integer,default=100); completions=Column(Integer,default=0); requires_proof=Column(Boolean,default=False); is_active=Column(Boolean,default=True)
    created_at=Column(DateTime,default=datetime.utcnow); expires_at=Column(DateTime)

class TaskCompletion(Base):
    __tablename__='task_completions'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); task_id=Column(Integer,index=True); proof=Column(Text); status=Column(String(30),default='pending')
    reward=Column(Float,default=0.0); created_at=Column(DateTime,default=datetime.utcnow); reviewed_at=Column(DateTime); admin_note=Column(Text)
    __table_args__=(UniqueConstraint('user_id','task_id',name='uq_task_user'),)

class Referral(Base):
    __tablename__='referrals'
    id=Column(Integer,primary_key=True); referrer_id=Column(BigInteger,index=True); referred_id=Column(BigInteger,unique=True); bonus=Column(Float,default=0.0); created_at=Column(DateTime,default=datetime.utcnow)

class SocialProfile(Base):
    __tablename__='social_profiles'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,unique=True); platform=Column(String(50),default='tiktok'); username=Column(String(100)); profile_url=Column(String(500)); points=Column(Integer,default=0); followers_gained=Column(Integer,default=0); people_followed=Column(Integer,default=0); is_active=Column(Boolean,default=True); created_at=Column(DateTime,default=datetime.utcnow)

class SocialTask(Base):
    __tablename__='social_tasks'
    id=Column(Integer,primary_key=True); platform=Column(String(50)); task_type=Column(String(50)); target_username=Column(String(100)); target_url=Column(String(500)); points_reward=Column(Integer); is_active=Column(Boolean,default=True); created_at=Column(DateTime,default=datetime.utcnow); expires_at=Column(DateTime)

class SocialTaskCompletion(Base):
    __tablename__='social_task_completions'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger); task_id=Column(Integer); completed_at=Column(DateTime,default=datetime.utcnow); points_earned=Column(Integer)

class PremiumPackage(Base):
    __tablename__='premium_packages'
    id=Column(Integer,primary_key=True); name=Column(String(100)); platform=Column(String(50)); quantity=Column(Integer); price_usd=Column(Float); price_kes=Column(Float); is_active=Column(Boolean,default=True)

class PremiumOrder(Base):
    __tablename__='premium_orders'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger); package_id=Column(Integer); platform=Column(String(50)); quantity=Column(Integer); price_paid=Column(Float); order_status=Column(String(50),default='pending'); ordered_at=Column(DateTime,default=datetime.utcnow)

class Transaction(Base):
    __tablename__='transactions'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); kind=Column(String(40)); amount=Column(Float); currency=Column(String(20),default='USD'); reference=Column(String(100),unique=True); status=Column(String(30),default='completed'); description=Column(String(255)); created_at=Column(DateTime,default=datetime.utcnow)

class DailyStreak(Base):
    __tablename__='daily_streaks'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,unique=True); streak_days=Column(Integer,default=0); last_completed=Column(DateTime); total_bonus_earned=Column(Float,default=0.0)

class Achievement(Base):
    __tablename__='achievements'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger); achievement_type=Column(String(50)); achieved_at=Column(DateTime,default=datetime.utcnow); reward_earned=Column(Float)

class SupportTicket(Base):
    __tablename__='support_tickets'
    id=Column(Integer,primary_key=True); user_id=Column(BigInteger,index=True); subject=Column(String(200)); message=Column(Text); status=Column(String(30),default='open'); created_at=Column(DateTime,default=datetime.utcnow); closed_at=Column(DateTime)

class AdminLog(Base):
    __tablename__='admin_logs'
    id=Column(Integer,primary_key=True); admin_id=Column(BigInteger); action=Column(String(100)); target_id=Column(String(100)); details=Column(Text); created_at=Column(DateTime,default=datetime.utcnow)

class Setting(Base):
    __tablename__='settings'
    id=Column(Integer,primary_key=True); key=Column(String(100),unique=True); value=Column(Text); updated_at=Column(DateTime,default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(engine)
    db=SessionLocal()
    defaults=[
      ('mpesa','M-Pesa','📱','KES','Paybill/Till/Phone','M-Pesa receiving account','Enter a valid Kenyan phone number or account reference.'),
      ('paypal','PayPal','🅿️','USD','PayPal email','', 'Enter a valid PayPal email address.'),
      ('binance','Binance Pay','🟡','USDT','Binance ID/email','', 'Enter your Binance Pay identifier.'),
      ('faucetpay','FaucetPay','🚰','USD','FaucetPay email','', 'Enter your FaucetPay account email.'),
      ('telegram_wallet','Telegram Wallet','💎','USDT','Wallet address/username','', 'Enter the receiving wallet address or supported identifier.'),
      ('usdt_trc20','USDT TRC20','₮','USDT','TRC20 address','', 'Enter a valid TRC20 wallet address.'),
      ('bank','Bank Transfer','🏦','KES','Bank account','', 'Enter bank name and account number.'),
    ]
    for slug,name,logo,currency,label,account,fmt in defaults:
        if not db.query(PaymentMethod).filter_by(slug=slug).first():
            db.add(PaymentMethod(name=name,slug=slug,logo=logo,currency=currency,account_label=label,receiving_account=account,account_format=fmt))
    db.commit(); db.close(); return SessionLocal
