import discord
from discord.ext import commands
from discord import app_commands
import os, json, random, math, asyncio, base64, requests
from datetime import datetime, timedelta
from flask import Flask
import threading
from constants import ADMIN_COMMANDS, USER_COMMANDS

# --- Load Environment Variables ---
TOKEN = os.getenv("TOKENFORBOTHERE")   # Discord bot token
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # Admin Discord ID
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # "username/repo"
GITHUB_BRANCH = "main"

# --- Bot Configuration ---
CURRENCY_SYMBOL = "💵"
DAILY_CLAIM_AMOUNT = 50
STARTING_BALANCE = 500
BET_LOCK_BUFFER_SECONDS = 300
PAYOUT_CHANNEL_ID = None

# --- Discord Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
tree = bot.tree

# --- Flask Keep Alive ---
app = Flask('')
@app.route('/')
def home(): 
    return "Bot is alive!"

def run_keep_alive():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_keep_alive).start()

# --- JSON File Paths ---
USERS_FILE = "users.json"
MATCHUPS_FILE = "matchups.json"
USERS = {}
MATCHUPS = {}

# --- GitHub Push Helper ---
def push_to_github(filename):
    """Push or update a JSON file to GitHub repository."""
    with open(filename, "r") as f:
        content = f.read()
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    # Check for existing file to get SHA
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": f"Update {filename}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(url, headers=headers, data=json.dumps(payload))
    if response.status_code in [200, 201]:
        print(f"✅ {filename} saved to GitHub")
    else:
        print(f"❌ Failed to push {filename} to GitHub: {response.json()}")

# --- Load / Save Functions ---
def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(USERS, f, indent=4)
    push_to_github(USERS_FILE)

def load_matchups():
    try:
        with open(MATCHUPS_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_matchups():
    with open(MATCHUPS_FILE, "w") as f:
        json.dump(MATCHUPS, f, indent=4)
    push_to_github(MATCHUPS_FILE)

# --- Helper Functions ---
def format_currency(amount):
    return f"{CURRENCY_SYMBOL}{amount}"

def gen_id(prefix="id"):
    return f"{prefix}_{random.randint(100000, 999999)}"

def get_user(user_id):
    """Retrieve or create user."""
    if user_id not in USERS:
        USERS[user_id] = {
            "balance": STARTING_BALANCE,
            "bets": {},
            "history": [],
            "stats": {"spent":0,"won":0,"lost":0,"bets_won":0,"bets_lost":0},
            "achievements": [],
            "last_claim": None,
            "weekly": {"week_start": None, "progress": {"bets":0}, "claimed_this_week": False}
        }
        save_users()
    return USERS[user_id]

# --- Load existing data ---
USERS = load_users()
MATCHUPS = load_matchups()

# =============================
# Odds & Payout Logic
# =============================

def implied_decimal_from_moneyline(ml: int):
    """Convert moneyline to decimal odds."""
    return (ml / 100 + 1) if ml > 0 else (100 / abs(ml) + 1)

def moneyline_from_decimal(dec: float):
    """Convert decimal odds to moneyline."""
    return int(round((dec - 1) * 100)) if dec >= 2 else int(round(-100 / (dec - 1)))

def calculate_dynamic_moneylines(matchup):
    """Adjust odds based on current betting volume."""
    home_vol, away_vol = 0, 0
    for bet in matchup.get("bets", {}).values():
        if bet["kind"] == "spread":
            sel = bet["selection"].upper()
            if sel == matchup["home"].upper(): home_vol += bet["amount"]
            if sel == matchup["away"].upper(): away_vol += bet["amount"]
    total = home_vol + away_vol
    if total == 0: return {"home_ml": -110, "away_ml": -110}
    
    home_share = home_vol / total
    away_share = away_vol / total
    home_odds = 1.8 + (away_share - home_share) * 0.5
    away_odds = 1.8 + (home_share - away_share) * 0.5
    return {"home_ml": moneyline_from_decimal(home_odds), "away_ml": moneyline_from_decimal(away_odds)}

def calculate_payout(bet):
    """Calculate payout for single or parlay bets."""
    if bet["kind"] == "parlay":
        combined_odds = 1
        for leg in bet["selection"]:
            combined_odds *= leg["odds"]
        return int(bet["amount"] * combined_odds)
    return int(bet["amount"] * bet["odds"])

# =============================
# Currency & User Commands
# =============================

@bot.command(name="daily")
async def daily(ctx):
    """Claim daily coins."""
    user = get_user(str(ctx.author.id))
    now = datetime.utcnow()
    last_claim = user.get("last_claim")
    
    if last_claim and datetime.fromisoformat(last_claim) > now - timedelta(hours=24):
        return await ctx.send(embed=discord.Embed(
            title="❌ Daily Already Claimed",
            description="Come back in 24 hours to claim again!",
            color=discord.Color.red()
        ))

    user["balance"] += DAILY_CLAIM_AMOUNT
    user["last_claim"] = now.isoformat()
    save_users()

    await ctx.send(embed=discord.Embed(
        title="✅ Daily Claimed",
        description=f"You received {format_currency(DAILY_CLAIM_AMOUNT)}.\nNew balance: {format_currency(user['balance'])}",
        color=discord.Color.green()
    ))

@bot.command(name="balance")
async def balance(ctx, member: discord.Member = None):
    """Check your balance or another user's."""
    member = member or ctx.author
    user = get_user(str(member.id))
    await ctx.send(embed=discord.Embed(
        title=f"{member.display_name}'s Balance",
        description=f"{format_currency(user['balance'])}",
        color=discord.Color.gold()
    ))

@bot.command(name="history")
async def history(ctx, member: discord.Member = None):
    """View betting history (last 10 bets)."""
    member = member or ctx.author
    user = get_user(str(member.id))

    history_text = ""
    for h in user["history"][-10:]:
        outcome = "✅ WIN" if h.get("payout",0) > 0 else "❌ LOSS"
        selection = h["selection"] if isinstance(h["selection"], str) else "Parlay"
        history_text += f"• {h['kind']} on {selection} — {outcome} ({format_currency(h['amount'])})\n"

    if not history_text:
        history_text = "No history yet."

    await ctx.send(embed=discord.Embed(
        title=f"{member.display_name}'s Betting History",
        description=history_text,
        color=discord.Color.blue()
    ))

@bot.command(name="leaderboard")
async def leaderboard(ctx, category: str = "balance"):
    """Show top 10 users by a category (balance/stats)."""
    valid = ["balance", "spent", "won", "lost", "bets_won", "bets_lost"]
    if category not in valid:
        return await ctx.send(embed=discord.Embed(
            title="❌ Invalid Category",
            description=f"Choose from: {', '.join(valid)}",
            color=discord.Color.red()
        ))

    sorted_users = sorted(
        USERS.items(),
        key=lambda x: x[1]["balance"] if category == "balance" else x[1]["stats"][category],
        reverse=True
    )[:10]

    desc = ""
    for i, (uid, data) in enumerate(sorted_users, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        stat = data["balance"] if category == "balance" else data["stats"][category]
        if category in ["balance","spent","won","lost"]:
            desc += f"**{i}. {name}** — {format_currency(stat)}\n"
        else:
            desc += f"**{i}. {name}** — {stat}\n"

    await ctx.send(embed=discord.Embed(
        title=f"🏆 Leaderboard: {category.title()}",
        description=desc,
        color=discord.Color.gold()
    ))

# =============================
# Admin Check Utility
# =============================
def is_admin(ctx):
    """Check if a user is an admin (ID or Discord perms)."""
    return ctx.author.id == ADMIN_ID or ctx.author.guild_permissions.administrator

# =============================
# Admin Commands — Matchups
# =============================

@bot.command(name="addmatchup")
async def add_matchup(ctx, kind: str, title: str, home: str = None, away: str = None, spread: float = 0.0, overunder: float = 0.0):
    """Create a new matchup."""
    if not is_admin(ctx): return await ctx.send("❌ You are not an admin.")

    mid = gen_id("m")
    MATCHUPS[mid] = {
        "id": mid,
        "type": kind,
        "title": title,
        "home": home,
        "away": away,
        "spread": spread,
        "overunder": overunder,
        "bets": {},
        "locked": False,
        "settled": False,
        "result": None,
        "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat()
    }
    save_matchups()

    await ctx.send(embed=discord.Embed(
        title="✅ Matchup Created",
        description=f"**{title}** (type: {kind})",
        color=discord.Color.green()
    ))

@bot.command(name="editmatchup")
async def edit_matchup(ctx, matchup_id: str, field: str, *, value: str):
    """Edit matchup field (title, home, away, spread, overunder, type)."""
    if not is_admin(ctx): return await ctx.send("❌ You are not an admin.")
    matchup = MATCHUPS.get(matchup_id)
    if not matchup: return await ctx.send("❌ Matchup not found.")
    if field not in ["title", "home", "away", "spread", "overunder", "type"]:
        return await ctx.send("❌ Invalid field. Allowed: title, home, away, spread, overunder, type.")
    
    if field in ["spread", "overunder"]:
        try: value = float(value)
        except ValueError: return await ctx.send("❌ Spread/Overunder must be a number.")

    matchup[field] = value
    save_matchups()
    await ctx.send(embed=discord.Embed(
        title="✅ Matchup Updated",
        description=f"{field} set to `{value}` for {matchup['title']}",
        color=discord.Color.green()
    ))

@bot.command(name="removematchup")
async def remove_matchup(ctx, matchup_id: str):
    """Delete a matchup."""
    if not is_admin(ctx): return await ctx.send("❌ You are not an admin.")
    matchup = MATCHUPS.pop(matchup_id, None)
    if not matchup: return await ctx.send("❌ Matchup not found.")
    save_matchups()
    await ctx.send(embed=discord.Embed(
        title="✅ Matchup Removed",
        description=f"Removed matchup: {matchup['title']}",
        color=discord.Color.red()
    ))

@bot.command(name="lockmatchup")
async def lock_matchup(ctx, matchup_id: str):
    """Lock a matchup to prevent further bets."""
    if not is_admin(ctx): return await ctx.send("❌ You are not an admin.")
    matchup = MATCHUPS.get(matchup_id)
    if not matchup: return await ctx.send("❌ Matchup not found.")
    matchup["locked"] = True
    save_matchups()
    await ctx.send(embed=discord.Embed(
        title="🔒 Matchup Locked",
        description=f"Betting is now locked for {matchup['title']}.",
        color=discord.Color.red()
    ))

@bot.command(name="settlematchup")
async def settle_matchup(ctx, matchup_id: str, winning_selection: str):
    """Settle a matchup and pay winners."""
    if not is_admin(ctx): return await ctx.send("❌ You are not an admin.")

    matchup = MATCHUPS.get(matchup_id)
    if not matchup: return await ctx.send("❌ Matchup not found.")
    if matchup["settled"]: return await ctx.send("❌ Already settled.")

    matchup["settled"] = True
    matchup["result"] = {"winner": winning_selection.upper()}

    payout_messages = []
    for bet_id, bet in list(matchup["bets"].items()):
        user = get_user(bet["user_id"])
        if bet["selection"].upper() == winning_selection.upper():
            payout = calculate_payout(bet)
            user["balance"] += payout
            bet["payout"] = payout
            user["stats"]["won"] += payout
            user["stats"]["bets_won"] += 1
            payout_messages.append(f"<@{bet['user_id']}> won {format_currency(payout)} on {matchup['title']}!")
        else:
            user["stats"]["lost"] += bet["amount"]
            user["stats"]["bets_lost"] += 1
            bet["payout"] = 0
        bet["resolved"] = True
        user["history"].append(bet)
        del user["bets"][bet_id]

    save_users()
    save_matchups()

    msg = "\n".join(payout_messages) if payout_messages else "Nobody won this time!"
    embed = discord.Embed(
        title=f"🏁 Matchup Settled: {matchup['title']}",
        description=msg,
        color=discord.Color.green()
    )
    channel = ctx.guild.get_channel(PAYOUT_CHANNEL_ID) if PAYOUT_CHANNEL_ID else ctx.channel
    await channel.send(embed=embed)

# =============================
# User Commands — Betting
# =============================

@bot.command(name="bet")
async def bet(ctx, matchup_id: str, selection: str, amount: int):
    """Place a bet on a matchup."""
    user = get_user(str(ctx.author.id))
    if amount <= 0 or user["balance"] < amount:
        return await ctx.send("❌ Invalid bet amount.")

    matchup = MATCHUPS.get(matchup_id)
    if not matchup: return await ctx.send("❌ Matchup not found.")
    if matchup["locked"]: return await ctx.send("❌ Betting is locked for this matchup.")

    odds_data = calculate_dynamic_moneylines(matchup)
    odds = 1.9  # default
    if selection.upper() == matchup["home"].upper(): odds = implied_decimal_from_moneyline(odds_data["home_ml"])
    elif selection.upper() == matchup["away"].upper(): odds = implied_decimal_from_moneyline(odds_data["away_ml"])

    user["balance"] -= amount
    bet_id = gen_id("b")
    bet_obj = {
        "id": bet_id,
        "user_id": str(ctx.author.id),
        "matchup_id": matchup_id,
        "kind": matchup["type"],
        "selection": selection.upper(),
        "amount": amount,
        "odds": odds,
        "placed_at": datetime.utcnow().isoformat(),
        "resolved": False,
        "payout": None
    }
    user["bets"][bet_id] = bet_obj
    matchup["bets"][bet_id] = bet_obj
    user["stats"]["spent"] += amount

    save_users()
    save_matchups()

    await ctx.send(embed=discord.Embed(
        title="🎟️ Bet Slip",
        description=f"Matchup: {matchup['title']}\nPick: **{selection.upper()}**\nWager: {format_currency(amount)}\nOdds: {odds:.2f}",
        color=discord.Color.blue()
    ))

@bot.command(name="pending")
async def pending(ctx, member: discord.Member = None):
    """View pending bets for a user."""
    member = member or ctx.author
    user = get_user(str(member.id))
    if not user["bets"]:
        return await ctx.send(f"{member.display_name} has no pending bets.")

    desc = ""
    for b in user["bets"].values():
        matchup = MATCHUPS.get(b["matchup_id"])
        matchup_title = matchup["title"] if matchup else "Parlay"
        desc += f"• {b['selection']} on {matchup_title} ({format_currency(b['amount'])})\n"

    await ctx.send(embed=discord.Embed(
        title=f"📋 Pending Bets: {member.display_name}",
        description=desc,
        color=discord.Color.orange()
    ))

# =============================
# User Command — Parlay
# =============================
@bot.command(name="parlay")
async def parlay(ctx):
    """Let users create a parlay bet (2-5 legs)."""
    user = get_user(str(ctx.author.id))

    # Step 1: List open matchups
    open_matchups = [m for m in MATCHUPS.values() if not m["locked"] and not m["settled"]]
    if not open_matchups: return await ctx.send("❌ No open matchups available for parlays.")

    desc = "\n".join([f"{i+1}. {m['home']} vs {m['away']} (Type: {m['type']})" if m.get("home") else f"{i+1}. {m['title']} (Type: {m['type']})" for i, m in enumerate(open_matchups)])
    await ctx.send(embed=discord.Embed(title="📋 Open Matchups", description=desc, color=discord.Color.blurple()))

    # Step 2: Ask for leg numbers
    await ctx.send("Enter the numbers of the matchups you want in your parlay (2-5), separated by commas:")
    try:
        msg = await bot.wait_for("message", check=lambda m: m.author == ctx.author, timeout=60)
        indices = [int(x.strip()) - 1 for x in msg.content.split(",")]
        if not 2 <= len(indices) <= 5: return await ctx.send("❌ Parlays must have 2–5 legs.")
    except Exception:
        return await ctx.send("❌ Invalid input or timed out.")

    selected_matchups = [open_matchups[i] for i in indices]

    # Step 3: Ask selection for each leg
    legs = []
    for m in selected_matchups:
        teams = [m['home'], m['away']] if m.get("home") else ["Option1", "Option2"]
        await ctx.send(f"Select for **{m['title']}**:\n{teams[0]} or {teams[1]}?")
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author == ctx.author, timeout=60)
            sel = msg.content.strip().upper()
            if sel not in [t.upper() for t in teams]: return await ctx.send("❌ Invalid selection.")
            odds_data = calculate_dynamic_moneylines(m)
            odds = implied_decimal_from_moneyline(odds_data["home_ml"]) if sel.upper() == m["home"].upper() else implied_decimal_from_moneyline(odds_data["away_ml"])
            legs.append({"matchup_id": m["id"], "selection": sel, "odds": odds})
        except Exception:
            return await ctx.send("❌ Timed out or error in selection.")

    # Step 4: Ask for total stake
    await ctx.send(f"Enter your total stake (you have {format_currency(user['balance'])}):")
    try:
        msg = await bot.wait_for("message", check=lambda m: m.author == ctx.author, timeout=60)
        amount = int(msg.content.strip())
        if amount <= 0 or amount > user["balance"]: return await ctx.send("❌ Invalid stake amount.")
    except Exception:
        return await ctx.send("❌ Invalid input or timed out.")

    # Step 5: Deduct balance, record bet
    user["balance"] -= amount
    bet_id = gen_id("b")
    parlay_bet = {
        "id": bet_id,
        "user_id": str(ctx.author.id),
        "matchup_id": None,
        "kind": "parlay",
        "selection": legs,
        "amount": amount,
        "odds": None,  # calculated from legs
        "placed_at": datetime.utcnow().isoformat(),
        "resolved": False,
        "payout": None
    }
    user["bets"][bet_id] = parlay_bet
    save_users()

    # Step 6: Calculate combined odds
    combined_odds = math.prod([leg["odds"] for leg in legs])

    # Step 7: Send confirmation
    desc = "\n".join([f"• {leg['selection']} on {MATCHUPS.get(leg['matchup_id'], {}).get('title','Prop Bet')} (Odds: {leg['odds']:.2f})" for leg in legs])
    embed = discord.Embed(title="🎟️ Parlay Bet Slip", description=desc, color=discord.Color.blue())
    embed.add_field(name="Stake", value=format_currency(amount))
    embed.add_field(name="Combined Odds", value=f"{combined_odds:.2f}")
    embed.set_footer(text=f"Bet ID: {bet_id}")
    await ctx.send(embed=embed)

# =============================
# Extras — Achievements / Weekly
# =============================
def check_achievements(user, bet):
    if "First Bet" not in user["achievements"]: user["achievements"].append("First Bet")

WEEKLY_CHALLENGE_PAYOUT = 150

@bot.command(name="weekly")
async def weekly(ctx):
    """Track weekly challenge progress."""
    user = get_user(str(ctx.author.id))
    week_start = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())
    if not user.get("weekly") or datetime.fromisoformat(user.get("weekly", {}).get("week_start","1970-01-01")) < week_start:
        user["weekly"] = {"week_start": week_start.isoformat(), "progress": {"bets": 0}, "claimed_this_week": False}
    save_users()

    progress = user["weekly"]["progress"]["bets"]
    desc = f"Bets Placed: {progress}/5\n"
    if progress >= 5 and not user["weekly"]["claimed_this_week"]:
        user["balance"] += WEEKLY_CHALLENGE_PAYOUT
        user["weekly"]["claimed_this_week"] = True
        desc += f"✅ Challenge Complete! You earned {format_currency(WEEKLY_CHALLENGE_PAYOUT)}"
        save_users()

    await ctx.send(embed=discord.Embed(
        title=f"📅 Weekly Challenge — {ctx.author.display_name}",
        description=desc,
        color=discord.Color.teal()
    ))

@bot.command(name="volume")
async def volume(ctx, matchup_id: str):
    """Show betting volume for a matchup."""
    matchup = MATCHUPS.get(matchup_id)
    if not matchup: return await ctx.send("❌ Matchup not found.")

    total = sum(b["amount"] for b in matchup["bets"].values())
    desc = f"Total Bet Volume: {format_currency(total)}\n"
    by_sel = {}
    for b in matchup["bets"].values(): by_sel[b["selection"]] = by_sel.get(b["selection"], 0) + b["amount"]
    for sel, amt in by_sel.items(): desc += f"• {sel}: {format_currency(amt)}\n"

    await ctx.send(embed=discord.Embed(
        title=f"📊 Bet Volume: {matchup['title']}",
        description=desc,
        color=discord.Color.purple()
    ))

# =============================
# Admin Commands — Money Management
# =============================
@bot.command(name="addmoney")
async def add_money(ctx, member: discord.Member, amount: int):
    """Admin adds coins to a user."""
    if not is_admin(ctx): 
        return await ctx.send("❌ You are not an admin.")
    if amount <= 0: 
        return await ctx.send("❌ Amount must be positive.")
    user = get_user(str(member.id))
    user["balance"] += amount
    save_users()
    await ctx.send(embed=discord.Embed(
        title="✅ Money Added",
        description=f"{format_currency(amount)} added to {member.display_name}. New balance: {format_currency(user['balance'])}",
        color=discord.Color.green()
    ))

@bot.command(name="removemoney")
async def remove_money(ctx, member: discord.Member, amount: int):
    """Admin removes coins from a user."""
    if not is_admin(ctx): 
        return await ctx.send("❌ You are not an admin.")
    if amount <= 0: 
        return await ctx.send("❌ Amount must be positive.")
    user = get_user(str(member.id))
    user["balance"] = max(user["balance"] - amount, 0)
    save_users()
    await ctx.send(embed=discord.Embed(
        title="✅ Money Removed",
        description=f"{format_currency(amount)} removed from {member.display_name}. New balance: {format_currency(user['balance'])}",
        color=discord.Color.orange()
    ))

# =============================
# Admin Commands — Props
# =============================
@bot.command(name="addprop")
async def add_prop(ctx, prop_type: str, *, question: str):
    """Admin creates a prop bet."""
    if not is_admin(ctx):
        return await ctx.send("❌ You are not an admin.")

    mid = gen_id("m")
    MATCHUPS[mid] = {
        "id": mid,
        "type": "prop",
        "prop_type": prop_type.lower(),  # numeric or choice
        "title": question,
        "bets": {},
        "locked": False,
        "settled": False,
        "result": None
    }
    save_matchups()

    await ctx.send(embed=discord.Embed(
        title="✅ Prop Bet Created",
        description=f"**{question}** (Type: {prop_type.capitalize()})\nMatchup ID: {mid}",
        color=discord.Color.green()
    ))

@bot.command(name="betprop")
async def bet_prop(ctx, matchup_id: str, value, amount: int):
    """Place a bet on a prop matchup."""
    user = get_user(str(ctx.author.id))
    if amount <= 0 or user["balance"] < amount:
        return await ctx.send("❌ Invalid bet amount.")

    matchup = MATCHUPS.get(matchup_id)
    if not matchup:
        return await ctx.send("❌ Matchup not found.")
    if matchup["locked"] or matchup["settled"]:
        return await ctx.send("❌ Betting is locked or this prop has been settled.")

    # numeric prop
    if matchup.get("prop_type") == "numeric":
        try: value = float(value)
        except ValueError: return await ctx.send("❌ You must enter a number for this prop.")

    user["balance"] -= amount
    bet_id = gen_id("b")
    bet_obj = {
        "id": bet_id,
        "user_id": str(ctx.author.id),
        "matchup_id": matchup_id,
        "kind": "prop",
        "prop_type": matchup.get("prop_type"),
        "selection": value,
        "amount": amount,
        "odds": 1.0,
        "placed_at": datetime.utcnow().isoformat(),
        "resolved": False,
        "payout": None
    }
    user["bets"][bet_id] = bet_obj
    matchup["bets"][bet_id] = bet_obj
    save_users(); save_matchups()

    await ctx.send(embed=discord.Embed(
        title="🎟️ Prop Bet Placed",
        description=f"Question: {matchup['title']}\nYour Pick: **{value}**\nWager: {format_currency(amount)}",
        color=discord.Color.blue()
    ))

@bot.command(name="settleprop")
async def settle_prop(ctx, matchup_id: str, *, result):
    """Admin settles a prop matchup."""
    if not is_admin(ctx):
        return await ctx.send("❌ You are not an admin.")

    matchup = MATCHUPS.get(matchup_id)
    if not matchup:
        return await ctx.send("❌ Matchup not found.")
    if matchup["settled"]:
        return await ctx.send("❌ Already settled.")

    matchup["settled"] = True
    matchup["result"] = result
    payout_messages = []

    for bet_id, bet in matchup["bets"].items():
        user = get_user(bet["user_id"])
        payout = 0

        if matchup.get("prop_type") == "numeric":
            actual = float(result)
            predicted = float(bet["selection"])
            distance = max(1, abs(actual - predicted))
            payout = int(bet["amount"] * (1 + 100 / distance))
        else:
            if str(bet["selection"]).lower() == str(result).lower():
                payout = bet["amount"] * 2

        bet["payout"] = payout
        user["balance"] += payout
        bet["resolved"] = True
        user["history"].append(bet)
        del user["bets"][bet_id]
        payout_messages.append(f"<@{bet['user_id']}> won {format_currency(payout)}!")

    save_users(); save_matchups()

    msg = "\n".join(payout_messages) if payout_messages else "Nobody won this prop."
    await ctx.send(embed=discord.Embed(
        title=f"🏁 Prop Bet Settled: {matchup['title']}",
        description=msg,
        color=discord.Color.green()
    ))

# =============================
# User Command — View Active Props
# =============================
@bot.command(name="props")
async def props(ctx):
    """List all currently active prop bets."""
    active_props = [m for m in MATCHUPS.values() if m["type"] == "prop" and not m["locked"] and not m["settled"]]
    if not active_props:
        return await ctx.send(embed=discord.Embed(
            title="📋 Active Prop Bets",
            description="No active prop bets at the moment.",
            color=discord.Color.orange()
        ))

    desc = ""
    for m in active_props:
        desc += f"• {m['id']} — {m['title']} ({m.get('prop_type', 'Choice')})\n"

    await ctx.send(embed=discord.Embed(
        title="📋 Active Prop Bets",
        description=desc,
        color=discord.Color.blurple()
    ))

# =============================
# Help Commands
# =============================
@bot.command(name="help")
async def user_help(ctx):
    desc = "\n".join([f"• **{cmd}** — {desc}" for cmd, desc in USER_COMMANDS.items()])
    await ctx.send(embed=discord.Embed(title="📖 User Commands", description=desc, color=discord.Color.blue))

@bot.command(name="adminhelp")
async def admin_help(ctx):
    if not is_admin(ctx): return await ctx.send("❌ You are not an admin.")
    desc = "\n".join([f"• **{cmd}** — {desc}" for cmd, desc in ADMIN_COMMANDS.items()])
    await ctx.send(embed=discord.Embed(title="⚡ Admin Commands", description=desc, color=discord.Color.red))

# =============================
# Run the Bot
# =============================
bot.run(TOKEN)
