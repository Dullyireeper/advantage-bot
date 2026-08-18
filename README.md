# AdVantage Bot v8

Replace the old `bot.py`, `database.py`, and `config.py` with these files. Keep your real secrets in Railway Variables; do not commit them.

## Railway variables
Set at minimum:
- BOT_TOKEN
- ADMIN_IDS
- DATABASE_URL (PostgreSQL recommended for production)
- BOT_USERNAME

Optional:
- COMMUNITY_CHANNEL
- COMMUNITY_INVITE
- SUPPORT_USERNAME
- payment/earning limits from `.env.example`

## Admin commands
- `/stats`
- `/addad Title|Description|URL|Reward|MaxViews`
- `/ads`
- `/addtask Title|Description|URL|Reward|MaxCompletions`
- `/tasks`
- `/credit USER_ID AMOUNT`
- `/debit USER_ID AMOUNT`
- `/user USER_ID`

The bot has wallet, deposits, withdrawals, configurable payment methods, task submissions, ads, referrals, email collection, community gate, admin dashboard, broadcast, analytics, security controls and database backup for SQLite.

Important: the ad module records verified in-bot reward events; it does not create real advertiser revenue. You need an actual advertiser/campaign or ad network contract/API to get paid.
