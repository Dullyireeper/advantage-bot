# AdVantage Bot v3

## What was fixed
- Explicit Railway start command.
- Valid Procfile format.
- Railway config no longer hidden by .gitignore.
- BOT_TOKEN moved to environment variables.
- DATABASE_URL is respected (PostgreSQL on Railway or SQLite locally).
- SQLAlchemy session handling fixed.
- Admin IDs automatically grant admin access.
- Added balance history.
- Added safer withdrawal limits and refund-on-rejection.
- Added admin statistics, ad creation, pending withdrawal review, approve/reject, and manual credit.
- Added social task completion flow.
- Added active-ad/max-view checks.
- Added duplicate recent ad-claim protection.
- Added input validation and URL validation.
- Added restart policy for Railway.

## Railway variables
Set:
- BOT_TOKEN = your NEW Telegram bot token
- ADMIN_IDS = your Telegram numeric ID(s), comma separated
- DATABASE_URL = Railway PostgreSQL connection string
- BOT_USERNAME = your bot username without @
- MPESA_PAYBILL = your real Paybill, if used
- MPESA_ACCOUNT = optional

Do not commit BOT_TOKEN or .env.

## Important
The token in the original uploaded config.py was exposed in source code. Revoke it in BotFather and create a new token before deploying this version.

## Run locally
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
