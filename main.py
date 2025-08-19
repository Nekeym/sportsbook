import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime, timedelta
import os
import json
from keep_alive import keep_alive  # keep_alive.py in same folder

# -------------------------------
# Load environment variables
# -------------------------------
TOKEN = os.getenv("TOKENFORBOTHERE")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# -------------------------------
# Helper Functions
# -------------------------------
USERS_FILE = "users.json"
MATCHUPS_FILE = "matchups.json"

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

def get_user(user_id):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"money": 100, "bet_history": [], "win_history": [], "last_daily": datetime.min.isoformat()}
        save_json(USERS_FILE, users)
    return users[uid]

def update_user(user_id, data):
    users = load_json(USERS_FILE)
    users[str(user_id)] = data
    save_json(USERS_FILE, users)

def change_user_money(user_id, amount):
    user = get_user(user_id)
    user["money"] += amount
    update_user(user_id, user)

def log_user_bet(user_id, entry):
    user = get_user(user_id)
    if "bet_history" not in user:
        user["bet_history"] = []
    user["bet_history"].append(entry)
    update_user(user_id, user)

def log_user_win(user_id, entry):
    user = get_user(user_id)
    if "win_history" not in user:
        user["win_history"] = []
    user["win_history"].append(entry)
    update_user(user_id, user)

def create_embed(title, description):
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    return embed

def no_permission_embed():
    return create_embed("❌ Permission Denied", "You do not have permission to use this command.")

# -------------------------------
# Bot Setup
# -------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------
# Part 1 & 3: Money, Daily, Matchups, Bet History, Win History, Leaderboard
# -------------------------------
class MoneyButton(Button):
    def __init__(self):
        super().__init__(label="💵 Money", style=discord.ButtonStyle.success)
    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        await interaction.response.send_message(embed=create_embed("💰 Account Balance", f"You currently have 💵{user_data['money']}"), ephemeral=True)

class DailyButton(Button):
    def __init__(self):
        super().__init__(label="🟣 Daily Grab", style=discord.ButtonStyle.primary)
    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        last_claim = datetime.fromisoformat(user_data.get("last_daily", datetime.min.isoformat()))
        if datetime.utcnow() - last_claim >= timedelta(hours=24):
            change_user_money(interaction.user.id, 25)
            user_data["last_daily"] = datetime.utcnow().isoformat()
            update_user(interaction.user.id, user_data)
            await interaction.response.send_message(embed=create_embed("✅ Daily Claimed", "You received 💵25!"), ephemeral=True)
        else:
            next_time = last_claim + timedelta(hours=24)
            remaining = next_time - datetime.utcnow()
            hours, remainder = divmod(remaining.total_seconds(), 3600)
            minutes = remainder // 60
            await interaction.response.send_message(embed=create_embed("⏳ Not Ready Yet", f"Come back in {int(hours)}h {int(minutes)}m"), ephemeral=True)

class MatchupsButton(Button):
    def __init__(self):
        super().__init__(label="🤎 Matchups", style=discord.ButtonStyle.secondary)
    async def callback(self, interaction: discord.Interaction):
        matchups = load_json(MATCHUPS_FILE)
        if not matchups:
            await interaction.response.send_message(embed=create_embed("📭 No Active Bets", "No bets available right now."), ephemeral=True)
            return
        for bid, data in matchups.items():
            embed = create_embed(f"📌 Bet #{bid} ({data['type'].capitalize()})",
                                 f"**{data['home']}** vs **{data['away'] if data['away'] else 'N/A'}**\nSpread: {data['spread']}\nOver/Under: {data['over_under']}\nMoneyline: {data.get('moneyline',{})}")
            view = BetTypeSelectionView(bid)
            try:
                await interaction.user.send(embed=embed, view=view)
            except discord.Forbidden:
                await interaction.response.send_message(embed=create_embed("❌ Cannot DM", "Enable DMs to receive bets."), ephemeral=True)
                return
        await interaction.response.send_message(embed=create_embed("📬 Sent", "All bets sent to your DMs."), ephemeral=True)

class BetHistoryButton(Button):
    def __init__(self):
        super().__init__(label="📜 Bet History", style=discord.ButtonStyle.secondary)
    async def callback(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        history = user.get("bet_history", [])
        text = "\n".join(history[-10:]) if history else "No bets placed yet."
        await interaction.response.send_message(embed=create_embed("📜 Recent Bets", text), ephemeral=True)

class WinHistoryButton(Button):
    def __init__(self):
        super().__init__(label="✅ Win History", style=discord.ButtonStyle.success)
    async def callback(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        wins = user.get("win_history", [])
        text = "\n".join(wins[-10:]) if wins else "No wins yet."
        await interaction.response.send_message(embed=create_embed("🏅 Recent Wins", text), ephemeral=True)

class LeaderboardButton(Button):
    def __init__(self):
        super().__init__(label="🏆 Leaderboard", style=discord.ButtonStyle.primary)
    async def callback(self, interaction: discord.Interaction):
        users = load_json(USERS_FILE)
        sorted_users = sorted(users.items(), key=lambda x: x[1]["money"], reverse=True)
        text = ""
        for i, (uid, data) in enumerate(sorted_users[:10], 1):
            try:
                member = await bot.fetch_user(int(uid))
                wins = sum(1 for h in data.get("bet_history", []) if "WIN" in h)
                losses = sum(1 for h in data.get("bet_history", []) if "LOSS" in h)
                text += f"**{i}. {member.display_name}** - 💵{data['money']} | {wins}W-{losses}L\n"
            except:
                continue
        await interaction.response.send_message(embed=create_embed("🏆 Leaderboard (Top 10)", text), ephemeral=True)

# -------------------------------
# Part 2 & 4: Bet Selection, Spread/O-U, Amount Modal, Dynamic Moneyline
# -------------------------------
class BetTypeSelectionView(View):
    def __init__(self, bet_id):
        super().__init__(timeout=60)
        self.add_item(SpreadButton(bet_id))
        self.add_item(OUButton(bet_id))

class SpreadButton(Button):
    def __init__(self, bet_id):
        super().__init__(label="SPREAD", style=discord.ButtonStyle.primary)
        self.bet_id = bet_id
    async def callback(self, interaction: discord.Interaction):
        await show_team_picker(interaction, self.bet_id, "spread")

class OUButton(Button):
    def __init__(self, bet_id):
        super().__init__(label="O/U", style=discord.ButtonStyle.secondary)
        self.bet_id = bet_id
    async def callback(self, interaction: discord.Interaction):
        await show_team_picker(interaction, self.bet_id, "ou")

async def show_team_picker(interaction, bet_id, bet_type):
    bet_data = load_json(MATCHUPS_FILE).get(bet_id)
    if not bet_data:
        await interaction.response.send_message(embed=create_embed("❌ Bet Not Found"), ephemeral=True)
        return
    view = View(timeout=60)
    if bet_type == "spread" and bet_data.get("home"):
        view.add_item(TeamButton("home", bet_id, bet_data["home"], bet_data["spread"]["home"]))
        if bet_data.get("away"):
            view.add_item(TeamButton("away", bet_id, bet_data["away"], bet_data["spread"]["away"]))
    elif bet_type == "ou" and bet_data.get("over_under"):
        view.add_item(OUChoiceButton("over", bet_id))
        view.add_item(OUChoiceButton("under", bet_id))
    await interaction.response.send_message(embed=create_embed("📊 Choose Option", f"Select for {bet_type.upper()}"), view=view, ephemeral=True)

class TeamButton(Button):
    def __init__(self, key, bet_id, name, spread):
        super().__init__(label=f"{name} ({spread:+})", style=discord.ButtonStyle.success)
        self.key = key
        self.bet_id = bet_id
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AmountModal(self.bet_id, "spread", self.key))

class OUChoiceButton(Button):
    def __init__(self, label_val, bet_id):
        super().__init__(label=label_val.upper(), style=discord.ButtonStyle.success)
        self.label_val = label_val
        self.bet_id = bet_id
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AmountModal(self.bet_id, "ou", self.label_val))

class AmountModal(Modal):
    def __init__(self, bet_id, bet_type, target):
        super().__init__(title="Enter Bet Amount")
        self.bet_id = bet_id
        self.bet_type = bet_type
        self.target = target
        self.amount = TextInput(label="Amount to Bet", placeholder="e.g. 100", required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        try:
            bet_amount = int(self.amount.value)
            if bet_amount <= 0 or bet_amount > user["money"]:
                raise ValueError
        except:
            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount"), ephemeral=True)
            return

        bets = load_json(MATCHUPS_FILE)
        bet_data = bets.get(self.bet_id)
        if not bet_data:
            await interaction.response.send_message(embed=create_embed("❌ Bet Not Found"), ephemeral=True)
            return

        # Dynamic payout
        total_on_target = sum(b["amount"] for b in bet_data.get("bets", []) if b["type"] == self.bet_type and b["target"] == self.target)
        payout_multiplier = max(1.8 - (total_on_target / 1000), 1.1)
        payout = round(bet_amount * payout_multiplier)

        if "bets" not in bet_data:
            bet_data["bets"] = []
        bet_data["bets"].append({"user": interaction.user.id, "amount": bet_amount, "type": self.bet_type, "target": self.target, "payout": payout})
        save_json(MATCHUPS_FILE, bets)

        change_user_money(interaction.user.id, -bet_amount)
        log_user_bet(interaction.user.id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {self.target.upper()} | {self.bet_type.upper()} | 💵{bet_amount}")

        # Update dynamic moneyline
        await update_moneyline_on_bet(self.bet_id)

        await interaction.response.send_message(embed=create_embed("✅ Bet Placed", f"You bet 💵{bet_amount} on **{self.target.upper()}**\nPotential payout: 💵{payout}"), ephemeral=True)

def calculate_dynamic_moneyline(bet_id):
    bets = load_json(MATCHUPS_FILE)
    matchup = bets.get(bet_id)
    if not matchup:
        return
    home_total = sum(b["amount"] for b in matchup.get("bets", []) if b["target"] == "home")
    away_total = sum(b["amount"] for b in matchup.get("bets", []) if b["target"] == "away")
    total = max(home_total + away_total, 1)
    base_line = 110
    matchup["moneyline"] = {"home": int(base_line * (away_total / total)), "away": int(base_line * (home_total / total))}
    save_json(MATCHUPS_FILE, bets)

async def update_moneyline_on_bet(bet_id):
    calculate_dynamic_moneyline(bet_id)

# -------------------------------
# Part 5 & 6: Admin & Advanced Bets
# -------------------------------
class FinishMatchupModal(Modal):
    def __init__(self):
        super().__init__(title="Finish Matchup")
        self.match_id = TextInput(label="Matchup ID", placeholder="ID of the matchup to finish")
        self.spread_winner = TextInput(label="Spread Winner", placeholder="home/away")
        self.ou_result = TextInput(label="O/U Result", placeholder="over/under")
        self.add_item(self.match_id)
        self.add_item(self.spread_winner)
        self.add_item(self.ou_result)

    async def on_submit(self, interaction: discord.Interaction):
        matchups = load_json(MATCHUPS_FILE)
        uid = self.match_id.value.strip()
        if uid not in matchups:
            await interaction.response.send_message(embed=create_embed("❌ Matchup Not Found"), ephemeral=True)
            return
        matchup = matchups[uid]
        spread_winner = self.spread_winner.value.lower()
        ou_result = self.ou_result.value.lower()
        for bet in matchup.get("bets", []):
            payout = 0
            won = False
            if bet["type"] == "spread" and bet["target"] == spread_winner:
                payout = bet["payout"]
                change_user_money(bet["user"], payout)
                log_user_win(bet["user"], f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {bet['target']} | SPREAD | 💵{payout}")
            elif bet["type"] == "ou" and bet["target"] == ou_result:
                payout = bet["payout"]
                change_user_money(bet["user"], payout)
                log_user_win(bet["user"], f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {bet['target']} | O/U | 💵{payout}")
        del matchups[uid]
        save_json(MATCHUPS_FILE, matchups)
        await interaction.response.send_message(embed=create_embed("✅ Matchup Settled", f"Matchup {uid} has been settled and bets paid."), ephemeral=True)

@bot.command()
async def finishmatchup(ctx):
    if ctx.author.id != ADMIN_ID:
        await ctx.send(embed=no_permission_embed())
        return
    await ctx.send_modal(FinishMatchupModal())

# Parlay, Prop, Futures Modals & Buttons
class ParlayModal(Modal):
    def __init__(self):
        super().__init__(title="Place Parlay Bet")
        self.details = TextInput(label="Parlay Details", placeholder="Format: matchupID-type-target;...", required=True)
        self.amount = TextInput(label="Amount to Bet", placeholder="💵 Amount", required=True)
        self.add_item(self.details)
        self.add_item(self.amount)
    async def on_submit(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        try:
            amount_int = int(self.amount.value.strip())
            if amount_int <=0 or amount_int > user["money"]:
                raise ValueError
        except:
            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount"), ephemeral=True)
            return
        entries = self.details.value.strip().split(";")
        bets_list = []
        try:
            for entry in entries:
                mid, btype, target = entry.strip().split("-")
                bets_list.append({"matchup": mid, "type": btype.lower(), "target": target.lower()})
        except:
            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Format"), ephemeral=True)
            return
        payout_multiplier = 1.5 + 0.1*len(bets_list)
        payout = round(amount_int * payout_multiplier)
        parlay_bets = load_json("parlays.json") if os.path.exists("parlays.json") else {}
        parlay_bets[f"{interaction.user.id}_{datetime.utcnow().timestamp()}"] = {"user":interaction.user.id,"type":"parlay","details":bets_list,"amount":amount_int,"payout":payout}
        save_json("parlays.json", parlay_bets)
        change_user_money(interaction.user.id, -amount_int)
        log_user_bet(interaction.user.id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | PARLAY | 💵{amount_int}")
        await interaction.response.send_message(embed=create_embed("✅ Parlay Placed", f"You bet 💵{amount_int} on {len(bets_list)}-leg parlay. Potential payout: 💵{payout}"), ephemeral=True)

class PropModal(Modal):
    def __init__(self):
        super().__init__(title="Place Prop Bet")
        self.description = TextInput(label="Prop Description", placeholder="Describe prop", required=True)
        self.amount = TextInput(label="Amount to Bet", placeholder="💵 Amount", required=True)
        self.add_item(self.description)
        self.add_item(self.amount)
    async def on_submit(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        try:
            amount_int = int(self.amount.value.strip())
            if amount_int<=0 or amount_int>user["money"]: raise ValueError
        except:
            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount"), ephemeral=True)
            return
        prop_bets = load_json("props.json") if os.path.exists("props.json") else {}
        bet_id = f"{interaction.user.id}_{datetime.utcnow().timestamp()}"
        prop_bets[bet_id] = {"user":interaction.user.id,"description":self.description.value.strip(),"amount":amount_int,"payout":int(amount_int*1.8)}
        save_json("props.json", prop_bets)
        change_user_money(interaction.user.id,-amount_int)
        log_user_bet(interaction.user.id,f"{datetime.utcnow().strftime('%m/%d %H:%M')} | PROP | 💵{amount_int}")
        await interaction.response.send_message(embed=create_embed("✅ Prop Bet Placed", f"You bet 💵{amount_int} on: {self.description.value.strip()}"), ephemeral=True)

class FuturesModal(Modal):
    def __init__(self):
        super().__init__(title="Place Futures Bet")
        self.description = TextInput(label="Futures Description", placeholder="Describe outcome", required=True)
        self.amount = TextInput(label="Amount to Bet", placeholder="💵 Amount", required=True)
        self.add_item(self.description)
        self.add_item(self.amount)
    async def on_submit(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        try:
            amount_int = int(self.amount.value.strip())
            if amount_int<=0 or amount_int>user["money"]: raise ValueError
        except:
            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount"), ephemeral=True)
            return
        futures_bets = load_json("futures.json") if os.path.exists("futures.json") else {}
        bet_id = f"{interaction.user.id}_{datetime.utcnow().timestamp()}"
        futures_bets[bet_id] = {"user":interaction.user.id,"description":self.description.value.strip(),"amount":amount_int,"payout":int(amount_int*2.0)}
        save_json("futures.json", futures_bets)
        change_user_money(interaction.user.id,-amount_int)
        log_user_bet(interaction.user.id,f"{datetime.utcnow().strftime('%m/%d %H:%M')} | FUTURES | 💵{amount_int}")
        await interaction.response.send_message(embed=create_embed("✅ Futures Bet Placed", f"You bet 💵{amount_int} on: {self.description.value.strip()}"), ephemeral=True)

class ParlayButton(Button):
    def __init__(self):
        super().__init__(label="Parlay Bet", style=discord.ButtonStyle.secondary)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ParlayModal())

class PropButton(Button):
    def __init__(self):
        super().__init__(label="Prop Bet", style=discord.ButtonStyle.primary)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PropModal())

class FuturesButton(Button):
    def __init__(self):
        super().__init__(label="Futures Bet", style=discord.ButtonStyle.success)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FuturesModal())

class AdvancedBettingView(View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(MoneyButton())
        self.add_item(DailyButton())
        self.add_item(MatchupsButton())
        self.add_item(BetHistoryButton())
        self.add_item(WinHistoryButton())
        self.add_item(LeaderboardButton())
        self.add_item(ParlayButton())
        self.add_item(PropButton())
        self.add_item(FuturesButton())

# -------------------------------
# Part 7: Settlement Functions
# -------------------------------
def settle_matchup(matchup_id, winning_spread, ou_result):
    matchups = load_json(MATCHUPS_FILE)
    users = load_json(USERS_FILE)
    if matchup_id not in matchups:
        return False, "Matchup not found."
    matchup = matchups[matchup_id]
    for bet in matchup.get("bets", []):
        uid = str(bet["user"])
        if uid not in users: users[uid] = {"money":0,"bet_history":[],"win_history":[]}
        won = False
        if bet["type"]=="spread" and bet["target"]==winning_spread: won=True
        elif bet["type"]=="ou" and bet["target"]==ou_result: won=True
        payout = bet["payout"] if won else 0
        change_user_money(int(uid), payout)
        log_user_bet(int(uid), f"{datetime.utcnow().strftime('%m/%d %H:%M')} | MATCHUP {matchup_id} | {'WIN' if won else 'LOSS'} | 💵{payout}")
    del matchups[matchup_id]
    save_json(MATCHUPS_FILE, matchups)
    save_json(USERS_FILE, users)
    return True, "Matchup settled."

def settle_parlays(results_dict):
    parlays = load_json("parlays.json") if os.path.exists("parlays.json") else {}
    for pid, res in results_dict.items():
        parlay = parlays.get(pid)
        if not parlay: continue
        all_won = all(res)
        payout = parlay["payout"] if all_won else 0
        change_user_money(parlay["user"], payout)
        log_user_bet(parlay["user"], f"{datetime.utcnow().strftime('%m/%d %H:%M')} | PARLAY | {'WIN' if all_won else 'LOSS'} | 💵{payout}")
        del parlays[pid]
    save_json("parlays.json", parlays)

def settle_props(results_dict):
    props = load_json("props.json") if os.path.exists("props.json") else {}
    for pid, won in results_dict.items():
        prop = props.get(pid)
        if not prop: continue
        payout = prop["payout"] if won else 0
        change_user_money(prop["user"], payout)
        log_user_bet(prop["user"], f"{datetime.utcnow().strftime('%m/%d %H:%M')} | PROP | {'WIN' if won else 'LOSS'} | 💵{payout}")
        del props[pid]
    save_json("props.json", props)

def settle_futures(results_dict):
    futures = load_json("futures.json") if os.path.exists("futures.json") else {}
    for fid, won in results_dict.items():
        fut = futures.get(fid)
        if not fut: continue
        payout = fut["payout"] if won else 0
        change_user_money(fut["user"], payout)
        log_user_bet(fut["user"], f"{datetime.utcnow().strftime('%m/%d %H:%M')} | FUTURES | {'WIN' if won else 'LOSS'} | 💵{payout}")
        del futures[fid]
    save_json("futures.json", futures)

# -------------------------------
# Start Bot
# -------------------------------
@bot.event
async def on_ready():
    print(f"🚀 Logged in as {bot.user}")

@bot.command()
async def betting(ctx):
    view = AdvancedBettingView()
    await ctx.send(embed=create_embed("🎲 Betting Menu", "Select an option below:"), view=view)

@bot.command()
async def admincommands(ctx):
    if ctx.author.id != ADMIN_ID:
        await ctx.send(embed=no_permission_embed())
        return
    await ctx.send(embed=create_embed("⚡ Admin Menu", "Use !finishmatchup to settle a matchup."))

keep_alive()
bot.run(TOKEN)
