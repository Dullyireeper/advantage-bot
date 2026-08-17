import os
from datetime import datetime, timedelta

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    Text,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))

    email = Column(String(254), unique=True, nullable=True)
    email_verified = Column(Boolean, default=False)

    balance = Column(Float, default=0.0)
    referred_by = Column(BigInteger, nullable=True)

    join_date = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    total_earned = Column(Float, default=0.0)
    total_withdrawn = Column(Float, default=0.0)

    phone_number = Column(String(20), nullable=True)
    language = Column(String(10), default="en")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    icon = Column(String(10), default="💳")
    receive_account = Column(String(500), nullable=True)
    receive_name = Column(String(200), nullable=True)
    instructions = Column(Text, nullable=True)
    withdrawal_enabled = Column(Boolean, default=True)
    deposit_enabled = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Ad(Base):
    __tablename__ = "ads"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    advertiser_name = Column(String(200))
    image_url = Column(String(500))
    link_url = Column(String(500), nullable=False)

    cost_per_view = Column(Float, default=0.008)
    user_reward = Column(Float, default=0.002)

    total_views = Column(Integer, default=0)
    max_views = Column(Integer, default=1000)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class AdView(Base):
    __tablename__ = "ad_views"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    ad_id = Column(Integer, nullable=False)
    viewed_at = Column(DateTime, default=datetime.utcnow)

    user_reward = Column(Float)
    owner_revenue = Column(Float)

    # One user can claim an ad once per day.
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "ad_id",
            "viewed_at",
            name="uq_ad_view",
        ),
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    task_type = Column(String(50), default="general")
    target_url = Column(String(500))
    reward = Column(Float, default=0.0)
    max_completions = Column(Integer, default=1000)
    completions = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class TaskCompletion(Base):
    __tablename__ = "task_completions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    task_id = Column(Integer, nullable=False)
    completed_at = Column(DateTime, default=datetime.utcnow)
    reward = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "task_id",
            name="uq_task_user",
        ),
    )


class SocialProfile(Base):
    __tablename__ = "social_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True)
    platform = Column(String(50), default="tiktok")
    username = Column(String(100))
    profile_url = Column(String(500))
    points = Column(Integer, default=0)
    followers_gained = Column(Integer, default=0)
    people_followed = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SocialTask(Base):
    __tablename__ = "social_tasks"

    id = Column(Integer, primary_key=True)
    platform = Column(String(50))
    task_type = Column(String(50))
    target_username = Column(String(100))
    target_url = Column(String(500))
    points_reward = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class SocialTaskCompletion(Base):
    __tablename__ = "social_task_completions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    task_id = Column(Integer)
    completed_at = Column(DateTime, default=datetime.utcnow)
    points_earned = Column(Integer)


class PremiumPackage(Base):
    __tablename__ = "premium_packages"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    platform = Column(String(50))
    quantity = Column(Integer)
    price_usd = Column(Float)
    price_kes = Column(Float)
    is_active = Column(Boolean, default=True)


class PremiumOrder(Base):
    __tablename__ = "premium_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    package_id = Column(Integer)
    platform = Column(String(50))
    quantity = Column(Integer)
    price_paid = Column(Float)
    order_status = Column(String(50), default="pending")
    ordered_at = Column(DateTime, default=datetime.utcnow)


class Deposit(Base):
    __tablename__ = "deposits"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    amount = Column(Float)
    method = Column(String(50))
    transaction_id = Column(String(100), unique=True)
    status = Column(String(50), default="pending")
    requested_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    amount = Column(Float)
    method = Column(String(50))
    account_details = Column(Text)
    transaction_id = Column(String(100), unique=True)
    status = Column(String(50), default="pending")
    requested_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class BalanceHistory(Base):
    __tablename__ = "balance_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    amount = Column(Float)
    type = Column(String(20))
    description = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    balance_before = Column(Float)
    balance_after = Column(Float)


class DailyStreak(Base):
    __tablename__ = "daily_streaks"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True)
    streak_days = Column(Integer, default=0)
    last_completed = Column(DateTime)
    total_bonus_earned = Column(Float, default=0.0)


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    achievement_type = Column(String(50))
    achieved_at = Column(DateTime, default=datetime.utcnow)
    reward_earned = Column(Float)


def init_db():
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        # Seed a few social tasks only when none exist.
        if session.query(SocialTask).count() == 0:
            tasks = [
                (
                    "tiktok",
                    "follow",
                    "@example",
                    50,
                    "https://www.tiktok.com/",
                ),
                (
                    "instagram",
                    "follow",
                    "@example",
                    50,
                    "https://www.instagram.com/",
                ),
                (
                    "youtube",
                    "subscribe",
                    "example",
                    100,
                    "https://www.youtube.com/",
                ),
            ]

            for platform, task_type, username, points, url in tasks:
                session.add(
                    SocialTask(
                        platform=platform,
                        task_type=task_type,
                        target_username=username,
                        points_reward=points,
                        target_url=url,
                        expires_at=datetime.utcnow() + timedelta(days=30),
                    )
                )

        session.commit()
    finally:
        session.close()

    return SessionLocal
