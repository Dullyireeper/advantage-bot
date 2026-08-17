# AdVantage Bot v4

Replace your existing `config.py`, `database.py`, and `bot.py` with the files in this folder.

## 1. Railway variables

Set:

BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_IDS=YOUR_TELEGRAM_NUMERIC_ID
BOT_USERNAME=YourBotUsername

DATABASE_URL=sqlite:///bot.db

EXCHANGE_RATE=125
AD_REVENUE_PER_VIEW=0.008
USER_REWARD_PER_VIEW=0.002
REFERRAL_BONUS=0.25

MIN_WITHDRAWAL=5
MAX_WITHDRAWAL_DAILY=20
MAX_ADS_PER_DAY=5
MAX_TASKS_PER_DAY=10
MAX_GAMES_PER_DAY=5

MPESA_PAYBILL=
MPESA_ACCOUNT=

## 2. Install dependencies

pip install -r requirements.txt

## 3. Start

python bot.py

## 4. First user

You currently have zero active users. That is normal.

Open the bot in Telegram and send:

/start

The bot will create your user record automatically.

## 5. Add email

The user can press My Email -> Add / Change Email.

Or send:

/email name@example.com

The database stores the email and marks it unverified.

## 6. Add a sponsored ad as admin

Example:

/addad My Shop|Visit our shop|https://example.com|0.002|1000

This creates a direct-sponsored campaign in your database.

IMPORTANT:
`AD_REVENUE_PER_VIEW` is only your internal accounting value. It does NOT automatically make money from Telegram or an external ad network. To actually get advertiser revenue, you need advertisers or a legitimate ad platform/network that allows Telegram traffic and pays you.

## 7. Add a task as admin

Example:

/addtask Visit Website|Open and review the website|https://example.com|0.05|100

Users will see it under Tasks.

## 8. Admin commands

/stats
/users
/addad ...
/addtask ...
/pending
/approve ID
/reject ID
/credit USER_ID AMOUNT

The Admin Panel also provides buttons for users, ads, tasks and withdrawals.

## 9. Database

The SQLite database is created automatically as `bot.db`.

For Railway production, PostgreSQL is recommended. If DATABASE_URL is set to a PostgreSQL URL, SQLAlchemy will use it, provided the required PostgreSQL driver is installed.

## Important

Do not advertise guaranteed earnings.

Do not pay users for fake clicks, fake engagement, spam or fraudulent ad activity.

The current "claim" buttons record user claims in your own database; they do not prove that an external website was actually viewed. If you later connect an external ad network, use that network's approved tracking/verification method.
