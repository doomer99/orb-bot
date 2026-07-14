# ORB Signal Bot — Set It and Forget It

Trades the 5-minute opening range breakout on MES futures
automatically every day. You leave for work at 7 AM,
bot fires at 9:35 AM, trade closes by 10:05 AM.
Check results on your phone when you get home.

## What it does

- **9:34:55 AM ET** — Bot reads the 5-min SPY range
- **9:35:00 AM ET** — Places buy or sell stop on MES via TradersPost
- **~10:05 AM ET** — Trade closes (stop, target, or 30-min timer)
- **Dashboard** — Shows signal live, check from any phone

## One-time setup (20 minutes)

### Step 1 — GitHub
Push these files to a new GitHub repo (free)

### Step 2 — Railway
1. Go to railway.app — sign up free
2. New Project → Deploy from GitHub repo
3. Select your repo
4. Under Variables, add these (from your .env.example):
   - TRADERSPOST_WEBHOOK_URL
   - TRADERSPOST_PASSWORD
   - CONTRACTS=1
   - STOP_POINTS=8.0
   - TARGET_POINTS=20.0
   - SIM_MODE=true  ← keep true until ready
   - DAILY_LOSS_LIMIT=1000
   - DAILY_LOSS_BUFFER=200
5. Railway gives you a public URL — that's your dashboard

### Step 3 — TradersPost
1. Sign up at traderspost.io (free tier)
2. Connect your Topstep account
3. Create a new strategy webhook
4. Set stop loss = 8 points, target = 20 points
5. Copy the webhook URL → paste into Railway Variables

### Step 4 — Go live
1. Change SIM_MODE to false in Railway Variables
2. Done. Bot runs 24/7 without your computer.

## Check from your phone
Open your Railway URL any time to see:
- Current signal (LONG / SHORT / WAITING / DONE)
- Range high and low
- Entry, stop, target if in a trade
- Live P&L
- Activity log

## Trading rules hard-coded into the bot
- One trade per day maximum
- 8-point stop loss
- 20-point profit target
- 30-minute timed exit
- 12:00 PM hard close
- Daily loss limit guard

## Files
- main.py — bot logic + TradersPost integration
- dashboard.py — Streamlit signal display
- requirements.txt — Python dependencies
- Procfile — tells Railway how to start
- .env.example — environment variables template
