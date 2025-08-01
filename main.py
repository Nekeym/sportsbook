import discord
from discord.ext import commands
import json
import os
from datetime import datetime, timedelta
from keep_alive import keep_alive  # <-- added this line

keep_alive()  # <-- added this line to start the webserver to keep the bot alive

ADMIN_ID = 1085391944240332940
DATA_FILE = "data.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def load_data():
    if not os.path.isfile(DATA_FILE):
        return {"users": {}, "matchups": [], "bets": []}  # <-- changed to list
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
    if isinstance(data.get("matchups"), dict):
        data["matchups"] = []
    if isinstance(data.get("bets"), dict):  # in case old data is dict, convert to list
        data["bets"] = [{"user_id": k, **v} for k, v in data["bets"].items()]
    return data

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def is_admin(ctx):
    return ctx.author.id == ADMIN_ID

def format_odds(odds):
    return f"+{odds}" if odds > 0 else str(odds)

def parse_signed_int(s):
    s = s.strip()
    if s.startswith("+"):
        s = s[1:]
    return int(s)

def get_matchup(data, number):
    if 1 <= number <= len(data["matchups"]):
        return data["matchups"][number - 1]
    return None

def calculate_payout(amount, odds):
    if odds > 0:
        profit = amount * (odds / 100)
    else:
        profit = amount * (100 / abs(odds))
    return int(amount + profit)

@bot.command()
async def commands(ctx):
    embed = discord.Embed(title="Commands List", color=discord.Color.green())
    embed.add_field(name="User Commands", value=(
        "`!matchups` - Lists all active matchups\n"
        "`!bet (team) (amount)` - Place bet on a team\n"
        "`!bet (over/under) (matchup #) (amount)` - Place over/under bet on a matchup\n"
        "`!payouts` - How payouts work\n"
        "`!daily` - Claim 15 free coins every 24h\n"
        "`!bethistory @user` - View user bet history"
        "`!coins` - View your coin balance"
    ), inline=False)
    embed.add_field(name="Admin Commands", value=(
        "`!creatematchup (aTeam) (hTeam) (aTeam Odds) (hTeam Odds) (O/U)` - Create a matchup\n"
        "`!settlematchup (matchup #) (winner) (over/under)` - Settle team and O/U bets\n"
        "`!addcoins @user (amount)` - Add coins to user\n"
        "`!addcoinsall (amount)` - Add coins to all users\n"
        "`!removecoins @user (amount)` - Remove coins from user"
    ), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def creatematchup(ctx, *, argstring):
    if not is_admin(ctx):
        return await ctx.send("⛔ You are not authorized to use this command.")
    try:
        args = argstring.split()
        if len(args) < 5:
            return await ctx.send("❌ Usage: !creatematchup (aTeam) (hTeam) (aTeam Odds) (hTeam Odds) (O/U)")

        aOdds_str = args[-3]
        hOdds_str = args[-2]
        overunder_str = args[-1]

        teams = args[:-3]
        if len(teams) < 2:
            return await ctx.send("❌ You must provide both teams.")

        aTeam = teams[0]
        hTeam = " ".join(teams[1:])

        aOdds = parse_signed_int(aOdds_str)
        hOdds = parse_signed_int(hOdds_str)
        overunder = float(overunder_str)

        data = load_data()
        data["matchups"].append({
            "ateam": aTeam,
            "hteam": hTeam,
            "aodds": aOdds,
            "hodds": hOdds,
            "overunder": overunder,
            "enabled": True
        })
        save_data(data)
        await ctx.send(f"✅ Matchup created: {aTeam} at {hTeam} | {format_odds(aOdds)} / {format_odds(hOdds)} | O/U {overunder}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command()
async def matchups(ctx):
    data = load_data()
    if not data["matchups"]:
        return await ctx.send("⚠️ No active matchups currently.")
    for i, m in enumerate(data["matchups"], start=1):
        if not m.get("enabled", True):
            continue
        embed = discord.Embed(title=f"Matchup #{i}: {m['ateam']} at {m['hteam']}", color=discord.Color.blue())
        embed.add_field(name=f"{m['ateam']} Odds", value=format_odds(m["aodds"]), inline=True)
        embed.add_field(name=f"{m['hteam']} Odds", value=format_odds(m["hodds"]), inline=True)
        embed.add_field(name="Over/Under", value=str(m["overunder"]), inline=False)

        a_bets = []
        h_bets = []
        ou_bets = []
        for bet in data.get("bets", []):
            if bet.get("matchup_num") == i:
                user_str = f"<@{bet['user_id']}>"
                if bet["type"] == "team":
                    if bet["team"].lower() == m["ateam"].lower():
                        a_bets.append(f"{user_str} ({bet['amount']})")
                    elif bet["team"].lower() == m["hteam"].lower():
                        h_bets.append(f"{user_str} ({bet['amount']})")
                elif bet["type"] == "overunder":
                    ou_bets.append(f"{user_str} ({bet['choice'].capitalize()} {bet['amount']})")

        embed.add_field(name=f"{m['ateam']} Bets", value="\n".join(a_bets) if a_bets else "No bets", inline=False)
        embed.add_field(name=f"{m['hteam']} Bets", value="\n".join(h_bets) if h_bets else "No bets", inline=False)
        embed.add_field(name="Over/Under Bets", value="\n".join(ou_bets) if ou_bets else "No bets", inline=False)
        await ctx.send(embed=embed)

@bot.command()
async def bet(ctx, *, args):
    data = load_data()
    uid = str(ctx.author.id)
    user = data["users"].setdefault(uid, {"coins": 100, "history": [], "last_daily": None})

    try:
        parts = args.split()
        if len(parts) < 2:
            raise ValueError

        if parts[0].lower() in ("over", "under"):
            # over/under bet: !bet over 1 50
            if len(parts) != 3:
                raise ValueError
            choice = parts[0].lower()
            matchup_num = int(parts[1])
            amount = int(parts[2])

            matchup = get_matchup(data, matchup_num)
            if not matchup or not matchup.get("enabled", True):
                return await ctx.send("⚠️ Invalid or disabled matchup number.")

            if amount > user["coins"]:
                return await ctx.send(f"⚠️ You only have {user['coins']} coins.")

            # Remove previous over/under bet by this user on this matchup
            data["bets"] = [bet for bet in data["bets"] if not (bet["type"] == "overunder" and bet["matchup_num"] == matchup_num and bet["user_id"] == uid)]

            data["bets"].append({
                "user_id": uid,
                "type": "overunder",
                "choice": choice,
                "matchup_num": matchup_num,
                "amount": amount
            })
            user["coins"] -= amount
            user["history"].append({"type":"overunder","matchup":matchup_num,"choice":choice,"amount":amount,"result":None,"payout":None})
            save_data(data)
            return await ctx.send(f"✅ Bet placed on **{choice.capitalize()}** for matchup #{matchup_num} for {amount} coins.")

        else:
            # team bet: !bet Clemson 50 (team can be multiple words)
            amount = int(parts[-1])
            team_name = " ".join(parts[:-1])

            # find matchup where this team plays and is enabled
            matchup_num = None
            for i, m in enumerate(data["matchups"], start=1):
                if not m.get("enabled", True):
                    continue
                if team_name.lower() == m["ateam"].lower() or team_name.lower() == m["hteam"].lower():
                    matchup_num = i
                    break
            if not matchup_num:
                return await ctx.send("⚠️ Team not found in any active matchup.")

            if amount > user["coins"]:
                return await ctx.send(f"⚠️ You only have {user['coins']} coins.")

            # Remove any previous team bet on this matchup by this user
            data["bets"] = [bet for bet in data["bets"] if not (bet["type"] == "team" and bet["matchup_num"] == matchup_num and bet["user_id"] == uid)]

            data["bets"].append({
                "user_id": uid,
                "type": "team",
                "team": team_name,
                "matchup_num": matchup_num,
                "amount": amount
            })
            user["coins"] -= amount
            user["history"].append({"type":"team","matchup":matchup_num,"choice":team_name,"amount":amount,"result":None,"payout":None})
            save_data(data)
            return await ctx.send(f"✅ Bet placed on **{team_name}** for {amount} coins.")

    except Exception:
        await ctx.send("❌ Invalid command usage.\nUse `!bet (team) (amount)` or `!bet (over/under) (matchup #) (amount)`")

@bot.command()
async def settlematchup(ctx, matchup_num: int, winner: str, overunder_result: str):
    if not is_admin(ctx):
        return await ctx.send("⛔ Not authorized.")
    data = load_data()
    matchup = get_matchup(data, matchup_num)
    if not matchup or not matchup.get("enabled", True):
        return await ctx.send("⚠️ Invalid or disabled matchup.")

    winner = winner.lower()
    ou_result = overunder_result.lower()
    valid_ou = ("over", "under")
    if winner != matchup["ateam"].lower() and winner != matchup["hteam"].lower():
        return await ctx.send("⚠️ Winner must be one of the matchup teams.")
    if ou_result not in valid_ou:
        return await ctx.send("⚠️ Over/Under result must be 'over' or 'under'.")

    winners = []
    ou_winners = []

    # Settle team bets
    # Iterate over a copy of the list since we will modify it
    for bet in data["bets"][:]:
        if bet.get("matchup_num") == matchup_num and bet.get("type") == "team":
            uid = bet["user_id"]
            user = data["users"].setdefault(uid, {"coins":100, "history":[]})
            if bet["team"].lower() == winner:
                odds = matchup["aodds"] if bet["team"].lower() == matchup["ateam"].lower() else matchup["hodds"]
                payout = calculate_payout(bet["amount"], odds)
                user["coins"] += payout
                winners.append(f"<@{uid}> won {payout} coins")
                # Update history
                for h in user["history"]:
                    if h["matchup"] == matchup_num and h["choice"].lower() == bet["team"].lower() and h["result"] is None:
                        h["result"] = "Win"
                        h["payout"] = payout
            else:
                # lost
                for h in user["history"]:
                    if h["matchup"] == matchup_num and h["choice"].lower() == bet["team"].lower() and h["result"] is None:
                        h["result"] = "Lose"
                        h["payout"] = 0
            # Remove bet after settlement
            data["bets"].remove(bet)

    # Settle over/under bets
    for bet in data["bets"][:]:
        if bet.get("matchup_num") == matchup_num and bet.get("type") == "overunder":
            uid = bet["user_id"]
            user = data["users"].setdefault(uid, {"coins":100, "history":[]})
            if bet["choice"].lower() == ou_result:
                payout = bet["amount"] * 2  # over/under pays 2x
                user["coins"] += payout
                ou_winners.append(f"<@{uid}> won {payout} coins (O/U)")
                # Update history
                for h in user["history"]:
                    if h["matchup"] == matchup_num and h["choice"].lower() == bet["choice"].lower() and h["result"] is None:
                        h["result"] = "Win"
                        h["payout"] = payout
            else:
                for h in user["history"]:
                    if h["matchup"] == matchup_num and h["choice"].lower() == bet["choice"].lower() and h["result"] is None:
                        h["result"] = "Lose"
                        h["payout"] = 0
            data["bets"].remove(bet)

    matchup["enabled"] = False
    save_data(data)

    msg = f"🏆 **{winner.capitalize()} has won!**\n\n**Winners:**\n"
    msg += "\n".join(winners) if winners else "No winning team bets."
    msg += "\n\n**Over/Under Winners:**\n"
    msg += "\n".join(ou_winners) if ou_winners else "No winning O/U bets."

    await ctx.send(msg)

@bot.command()
async def addcoins(ctx, user: discord.Member, amount: int):
    if not is_admin(ctx):
        return await ctx.send("⛔ Not authorized.")
    if amount <= 0:
        return await ctx.send("⚠️ Amount must be positive.")
    data = load_data()
    uid = str(user.id)
    user_data = data["users"].setdefault(uid, {"coins": 100, "history": []})
    user_data["coins"] += amount
    save_data(data)
    await ctx.send(f"✅ Added {amount} coins to {user.display_name}. Total: {user_data['coins']}")

@bot.command()
async def addcoinsall(ctx, amount: int):
    if not is_admin(ctx):
        return await ctx.send("⛔ Not authorized.")
    if amount <= 0:
        return await ctx.send("⚠️ Amount must be positive.")
    data = load_data()
    for uid, user_data in data["users"].items():
        coins = user_data.get("coins")
        if not isinstance(coins, int):
            coins = 0
        user_data["coins"] = coins + amount
    save_data(data)
    await ctx.send(f"✅ Added {amount} coins to all users.")

@bot.command()
async def removecoins(ctx, user: discord.Member, amount: int):
    if not is_admin(ctx):
        return await ctx.send("⛔ Not authorized.")
    if amount <= 0:
        return await ctx.send("⚠️ Amount must be positive.")
    data = load_data()
    uid = str(user.id)
    user_data = data["users"].setdefault(uid, {"coins": 100, "history": []})
    if user_data["coins"] < amount:
        return await ctx.send(f"⚠️ {user.display_name} only has {user_data['coins']} coins.")
    user_data["coins"] -= amount
    save_data(data)
    await ctx.send(f"✅ Removed {amount} coins from {user.display_name}. Remaining: {user_data['coins']}")

@bot.command()
async def daily(ctx):
    data = load_data()
    uid = str(ctx.author.id)
    user = data["users"].setdefault(uid, {"coins": 0, "history": [], "last_daily": None})

    now = datetime.utcnow()
    last = user.get("last_daily")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt < timedelta(hours=24):
                remain = timedelta(hours=24) - (now - last_dt)
                hrs, rem = divmod(remain.seconds, 3600)
                mins, _ = divmod(rem, 60)
                return await ctx.send(f"⏳ You can claim your next daily in {hrs}h {mins}m.")
        except Exception:
            user["last_daily"] = None  # Reset if malformed

    coins = user.get("coins")
    if not isinstance(coins, int):
        coins = 0
    user["coins"] = coins + 15
    user["last_daily"] = now.isoformat()
    save_data(data)
    await ctx.send("✅ You claimed your daily 15 coins!")

@bot.command()
async def coins(ctx):
    data = load_data()
    uid = str(ctx.author.id)
    user = data["users"].get(uid)
    if not user:
        return await ctx.send("ℹ️ You don't have any coins yet. Use `!daily` to claim some!")
    await ctx.send(f"💰 You have {user.get('coins', 0)} coins.")

@bot.command()
async def bethistory(ctx, user: discord.Member = None):
    user = user or ctx.author
    data = load_data()
    uid = str(user.id)
    user_data = data["users"].get(uid)
    if not user_data or not user_data.get("history"):
        return await ctx.send(f"ℹ️ {user.display_name} has no betting history.")

    history = user_data["history"][-10:]
    lines = []
    for h in history:
        result = h["result"] or "Pending"
        payout = h.get("payout")
        payout_str = f", Payout: {payout}" if payout is not None else ""
        if h["type"] == "team":
            lines.append(f"Matchup #{h['matchup']}: Bet {h['amount']} on {h['choice']} - {result}{payout_str}")
        else:
            lines.append(f"Matchup #{h['matchup']} Over/Under {h['choice']} - Bet {h['amount']} - {result}{payout_str}")

    embed = discord.Embed(title=f"{user.display_name}'s Bet History (last 10)", description="\n".join(lines), color=discord.Color.purple())
    await ctx.send(embed=embed)

@bot.command()
async def payouts(ctx):
    text = (
        "💵 **Payouts Explained:**\n"
        "- Team bets pay according to odds (positive or negative).\n"
        "- Over/Under bets pay 2x the bet amount.\n"
        "- Example: Bet 100 coins on +150 odds -> win 250 coins total (your bet + 150 profit).\n"
        "- Bet 100 coins on -200 odds -> win 150 coins total (your bet + 50 profit).\n"
    )
    await ctx.send(text)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

bot.run(os.getenv("DISCORD_TOKEN"))

