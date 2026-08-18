import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')
    ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
    BOT_USERNAME = os.getenv('BOT_USERNAME', 'AdVantageBot')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
    VERSION = '8.0.0'

    EXCHANGE_RATE = float(os.getenv('EXCHANGE_RATE', '125'))
    AD_REVENUE_PER_VIEW = float(os.getenv('AD_REVENUE_PER_VIEW', '0.008'))
    USER_REWARD_PER_VIEW = float(os.getenv('USER_REWARD_PER_VIEW', '0.002'))
    REFERRAL_BONUS = float(os.getenv('REFERRAL_BONUS', '0.25'))
    MIN_WITHDRAWAL = float(os.getenv('MIN_WITHDRAWAL', '5'))
    MAX_WITHDRAWAL_DAILY = float(os.getenv('MAX_WITHDRAWAL_DAILY', '20'))
    MAX_ADS_PER_DAY = int(os.getenv('MAX_ADS_PER_DAY', '5'))
    MAX_TASKS_PER_DAY = int(os.getenv('MAX_TASKS_PER_DAY', '10'))
    MAX_GAMES_PER_DAY = int(os.getenv('MAX_GAMES_PER_DAY', '5'))
    AD_MIN_SECONDS = int(os.getenv('AD_MIN_SECONDS', '10'))

    COMMUNITY_CHANNEL = os.getenv('COMMUNITY_CHANNEL', '')
    COMMUNITY_INVITE = os.getenv('COMMUNITY_INVITE', '')
    SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', '')
    MAINTENANCE_MODE = os.getenv('MAINTENANCE_MODE', 'false').lower() == 'true'

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise RuntimeError('BOT_TOKEN is missing. Add it to Railway Variables.')
        if not cls.ADMIN_IDS:
            raise RuntimeError('ADMIN_IDS is missing. Example: ADMIN_IDS=123456789')
        if cls.USER_REWARD_PER_VIEW < 0 or cls.AD_REVENUE_PER_VIEW < cls.USER_REWARD_PER_VIEW:
            raise RuntimeError('Invalid ad reward configuration.')
