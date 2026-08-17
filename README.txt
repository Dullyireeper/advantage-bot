# AdVantageBot v5

## Wallet/payment system
The bot now has a dedicated Wallet section. Users can:
- View available balance and wallet history.
- Deposit by selecting a configured payment method.
- See the administrator-configured receiving account before paying.
- Submit the amount and payment/transaction reference for verification.
- Withdraw by selecting a payout method and then entering only the required account/identifier.

Supported seeded methods:
- M-Pesa
- PayPal
- Binance
- Speed Wallet
- FaucetPay
- Telegram Wallet / TON
- USDT TRC20
- USDT BEP20
- Bitcoin
- Ethereum

These are payment-method records, not automatic integrations. Actual deposits/withdrawals are manually verified/paid by the administrator unless an official provider API is integrated. Never claim that a provider will automatically pay the bot merely because a method is listed.

## Admin wallet interface
Admin Panel contains:
- Pending Deposits: approve/reject deposits. Approval credits the user's wallet.
- Withdrawals: approve/reject withdrawals.
- Payment Accounts: configure the account/address/name/instructions users should use when depositing.

The admin can configure a payment method through the buttons, or use:
`/setpayment METHOD|ACCOUNT|NAME|INSTRUCTIONS`

Example:
`/setpayment mpesa|123456|MY BUSINESS|Send using the reference shown after payment.`

For safety, only configure accounts that you control or are authorized to receive payments for.

## Environment
Set at least:
- BOT_TOKEN
- ADMIN_IDS
- DATABASE_URL (optional; SQLite is the default)

## Run
`pip install -r requirements.txt`
`python bot.py`

For Railway, set the environment variables in Variables and deploy.
