import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput, Select
import json
import os
from datetime import datetime, timedelta
from keep_alive import keep_alive
import base64
import requests  # for GitHub API push

# -------------------------------
# Bot Setup
# -------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------
# Constants
# -------------------------------
ADMIN_ID = 1085391944240332940
TOKEN = os.environ.get("TOKENFORBOTHERE")
PAYOUT_CHANNEL_ID = 1401259843834216528  # Replace with your channel ID

USERS_FILE = "data/users.json"
MATCHUPS_FILE = "data/matchups.json"

# Ensure data folder and files exist
os.makedirs("data", exist_ok=True)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)
if not os.path.exists(MATCHUPS_FILE):
    with open(MATCHUPS_FILE, "w") as f:
        json.dump({}, f)

# -------------------------------
# JSON Helpers
# -------------------------------
def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    push_all_jsons()

# GitHub push (optional)
def push_json_to_github_api(file_path, repo_path, commit_message="Auto-update JSON"):
    github_user = "Nekeym"
    github_repo = "sportsbook"
    branch = "main"

    with open(file_path, "r") as f:
        content = f.read()

    b64_content = base64.b64encode(content.encode()).decode()
    headers = {"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"}
    url_get = f"https://api.github.com/repos/{github_user}/{github_repo}/contents/{repo_path}?ref={branch}"
    response = requests.get(url_get, headers=headers)

    sha = None
    if response.status_code == 200:
        sha = response.json()["sha"]

    url_put = f"https://api.github.com/repos/{github_user}/{github_repo}/contents/{repo_path}"
    data = {"message": commit_message, "content": b64_content, "branch": branch}
    if sha:
        data["sha"] = sha

    put_response = requests.put(url_put, headers=headers, data=json.dumps(data))
    if put_response.status_code not in [200, 201]:
        print(f"Failed to push {file_path}: {put_response.text}")

def push_all_jsons():
    try:
        push_json_to_github_api(USERS_FILE, "users.json", "Update users.json")
        push_json_to_github_api(MATCHUPS_FILE, "matchups.json", "Update matchups.json")
    except Exception as e:
        print(f"Failed to push JSONs via API: {e}")

# -------------------------------
# User Helpers
# -------------------------------
def get_user(user_id):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "money": 500,
            "last_daily": "2000-01-01T00:00:00",
            "bet_history": [],
            "win_history": []
        }
        save_json(USERS_FILE, users)
    return users[uid]

def update_user(user_id, data):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    users[uid].update(data)
    save_json(USERS_FILE, users)

def change_user_money(user_id, amount):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        get_user(user_id)
    users[uid]["money"] += amount
    save_json(USERS_FILE, users)
    return users[uid]["money"]

def log_user_bet(user_id, entry):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    users[uid]["bet_history"].append(entry)
    save_json(USERS_FILE, users)

def log_user_result(user_id, entry):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    users[uid]["win_history"].append(entry)
    save_json(USERS_FILE, users)

# -------------------------------
# Embed Helpers
# -------------------------------
def create_embed(title, description="", color=discord.Color.blurple()):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Sportsbook Bot • Dollars💵")
    embed.timestamp = datetime.utcnow()
    return embed

def no_permission_embed():
    return create_embed("🟥 YOU DO NOT HAVE PERMISSION TO USE THIS 🟥", color=discord.Color.red())

print("Part 1 loaded: Setup, JSON, User & Embed helpers.")

# =========================
# ========== ADMIN VIEW ==========
# =========================
class AdminView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CreateMatchupButton())
        self.add_item(FinishMatchupButton())
        self.add_item(AddMoneyToUserButton())
        self.add_item(AddMoneyToAllButton())
        self.add_item(RemoveMoneyFromUserButton())
        self.add_item(DeleteUserBetButton())
        self.add_item(DeleteMatchupButton())

# -------------------------------
# ========== ADMIN BUTTONS ==========
# -------------------------------
# 1. Create Matchup
class CreateMatchupButton(Button):
    def __init__(self):
        super().__init__(label="Create Matchup", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class MatchupModal(Modal, title="Create Matchup"):
            home_team = TextInput(label="Home Team", placeholder="e.g. Oklahoma")
            away_team = TextInput(label="Away Team", placeholder="e.g. Michigan")
            home_spread = TextInput(label="Home Spread", placeholder="e.g. -6.5")
            away_spread = TextInput(label="Away Spread", placeholder="e.g. +6.5")
            over_under = TextInput(label="Over/Under", placeholder="e.g. 55.5")

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    home_spread_val = float(self.home_spread.value.strip().replace("+",""))
                    away_spread_val = float(self.away_spread.value.strip().replace("+",""))
                    ou_val = float(self.over_under.value.strip().replace("+",""))
                except:
                    await interaction.response.send_message(
                        embed=create_embed("⚠️ Invalid input", "Spreads and O/U must be numbers like -6.5 or 55.5"),
                        ephemeral=True
                    )
                    return

                matchups = load_json(MATCHUPS_FILE)
                match_id = str(len(matchups)+1)
                matchups[match_id] = {
                    "home": self.home_team.value.strip(),
                    "away": self.away_team.value.strip(),
                    "spread": {"home": home_spread_val, "away": away_spread_val},
                    "moneyline": {"home": -110, "away": -110},  # Will dynamically adjust as users bet
                    "over_under": ou_val,
                    "bets": [],
                }
                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(
                    embed=create_embed("✅ Matchup Created", f"Matchup ID: `{match_id}`"),
                    ephemeral=True
                )

        await interaction.response.send_modal(MatchupModal())

# 2. Finish Matchup
class FinishMatchupButton(Button):
    def __init__(self):
        super().__init__(label="Finish Matchup", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class FinishModal(Modal, title="Finish Matchup"):
            match_id = TextInput(label="Matchup ID")
            winner = TextInput(label="Winning Spread (home/away)")
            ou_result = TextInput(label="O/U Result (over/under)")

            async def on_submit(self, interaction: discord.Interaction):
                matchups = load_json(MATCHUPS_FILE)
                mid = self.match_id.value.strip()
                if mid not in matchups:
                    await interaction.response.send_message(embed=create_embed("❌ Matchup Not Found"), ephemeral=True)
                    return

                match = matchups[mid]
                winner_key = self.winner.value.strip().lower()
                ou_res = self.ou_result.value.strip().lower()

                if winner_key not in ("home","away"):
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid Winner"), ephemeral=True)
                    return
                if ou_res not in ("over","under"):
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid O/U Result"), ephemeral=True)
                    return

                payout_messages = []
                for bet in match["bets"]:
                    user_id = bet["user"]
                    bet_type = bet["type"]
                    target = bet["target"]
                    amount = bet["amount"]
                    payout = bet["payout"]
                    result_text = "LOST"

                    if bet_type == "spread" and target == winner_key:
                        change_user_money(user_id, payout)
                        log_user_result(user_id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | Spread {target.upper()} WON | 💵{payout}")
                        payout_messages.append(f"<@{user_id}> won 💵{payout} on SPREAD ({target.upper()})")
                        result_text = "WON"

                    elif bet_type == "ou" and target == ou_res:
                        change_user_money(user_id, payout)
                        log_user_result(user_id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | O/U {target.upper()} WON | 💵{payout}")
                        payout_messages.append(f"<@{user_id}> won 💵{payout} on O/U ({target.upper()})")
                        result_text = "WON"

                    else:
                        log_user_result(user_id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {bet_type.upper()} {target.upper()} LOST | 💵{amount}")

                # Send payouts to payout channel
                payout_channel = interaction.guild.get_channel(PAYOUT_CHANNEL_ID)
                if payout_channel and payout_messages:
                    embed = create_embed(f"Payouts for Matchup {mid}", "\n".join(payout_messages), color=discord.Color.green())
                    await payout_channel.send(embed=embed)

                # Delete matchup
                del matchups[mid]
                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(embed=create_embed("✅ Matchup Settled", "All bets processed."), ephemeral=True)

print("Part 2 loaded: Admin buttons and matchup management.")

# -------------------------------
# 3. Add Money to User
# -------------------------------
class AddMoneyToUserButton(Button):
    def __init__(self):
        super().__init__(label="Add Money To User", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class AddMoneyModal(Modal, title="Add Money To User"):
            user_id_input = TextInput(label="User ID", placeholder="Discord User ID")
            amount = TextInput(label="Amount", placeholder="e.g. 100")

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_id_int = int(self.user_id_input.value.strip())
                    amount_int = int(self.amount.value.strip())
                    if amount_int <= 0:
                        raise ValueError
                except:
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid Input"), ephemeral=True)
                    return

                get_user(user_id_int)
                change_user_money(user_id_int, amount_int)
                await interaction.response.send_message(
                    embed=create_embed("✅ Money Added", f"Added 💵{amount_int} to <@{user_id_int}>."),
                    ephemeral=True
                )

# -------------------------------
# 4. Add Money to All Users
# -------------------------------
class AddMoneyToAllButton(Button):
    def __init__(self):
        super().__init__(label="Add Money To All", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class AddAllModal(Modal, title="Add Money To All Users"):
            amount = TextInput(label="Amount", placeholder="e.g. 50")

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    amount_int = int(self.amount.value.strip())
                    if amount_int <= 0:
                        raise ValueError
                except:
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount"), ephemeral=True)
                    return

                count = 0
                for member in interaction.guild.members:
                    if not member.bot:
                        get_user(member.id)
                        change_user_money(member.id, amount_int)
                        count += 1
                await interaction.response.send_message(embed=create_embed("✅ Mass Payment", f"Added 💵{amount_int} to {count} users."), ephemeral=True)

# -------------------------------
# 5. Remove Money From User
# -------------------------------
class RemoveMoneyFromUserButton(Button):
    def __init__(self):
        super().__init__(label="Remove Money From User", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class RemoveMoneyModal(Modal, title="Remove Money From User"):
            user_id_input = TextInput(label="User ID", placeholder="Discord User ID")
            amount = TextInput(label="Amount to Remove", placeholder="e.g. 100")

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_id_int = int(self.user_id_input.value.strip())
                    amount_int = int(self.amount.value.strip())
                    if amount_int <= 0:
                        raise ValueError
                except:
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid Input"), ephemeral=True)
                    return

                user_data = get_user(user_id_int)
                if user_data["money"] < amount_int:
                    await interaction.response.send_message(
                        embed=create_embed("🛑 Not Enough Money", f"User only has 💵{user_data['money']}."),
                        ephemeral=True
                    )
                    return

                change_user_money(user_id_int, -amount_int)
                await interaction.response.send_message(
                    embed=create_embed("✅ Money Removed", f"Removed 💵{amount_int} from <@{user_id_int}>."),
                    ephemeral=True
                )

# -------------------------------
# 6. Delete User Bet
# -------------------------------
class DeleteUserBetButton(Button):
    def __init__(self):
        super().__init__(label="Delete User Bet", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class DeleteBetModal(Modal, title="Delete User Bet"):
            match_id = TextInput(label="Matchup ID")
            user_id_input = TextInput(label="User ID")

            async def on_submit(self, interaction: discord.Interaction):
                matchups = load_json(MATCHUPS_FILE)
                mid = self.match_id.value.strip()
                try:
                    user_id_int = int(self.user_id_input.value.strip())
                except:
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid User ID"), ephemeral=True)
                    return

                if mid not in matchups:
                    await interaction.response.send_message(embed=create_embed("❌ Matchup Not Found"), ephemeral=True)
                    return

                match = matchups[mid]
                original_len = len(match["bets"])
                match["bets"] = [b for b in match["bets"] if b["user"] != user_id_int]
                if len(match["bets"]) == original_len:
                    await interaction.response.send_message(embed=create_embed("ℹ️ Bet Not Found"), ephemeral=True)
                    return

                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(embed=create_embed("✅ Bet Deleted", f"Deleted bet by <@{user_id_int}> on matchup {mid}."), ephemeral=True)

print("Part 3 loaded: Money management and deletion buttons.")

# -------------------------------
# 7. Delete Matchup Button
# -------------------------------
class DeleteMatchupButton(Button):
    def __init__(self):
        super().__init__(label="Delete Matchup", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
            return

        class DeleteModal(Modal, title="Delete Matchup"):
            match_id = TextInput(label="Matchup ID")

            async def on_submit(self, interaction: discord.Interaction):
                matchups = load_json(MATCHUPS_FILE)
                mid = self.match_id.value.strip()
                if mid not in matchups:
                    await interaction.response.send_message(embed=create_embed("❌ Matchup Not Found"), ephemeral=True)
                    return

                match = matchups[mid]
                for bet in match["bets"]:
                    change_user_money(bet["user"], bet["amount"])
                del matchups[mid]
                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(embed=create_embed("🗑️ Matchup Deleted", "All bets refunded."), ephemeral=True)

# -------------------------------
# 8. Admin Commands Portal
# -------------------------------
@bot.command()
async def admincommands(ctx):
    if ctx.author.id != ADMIN_ID:
        await ctx.send(embed=no_permission_embed())
        return

    embed = create_embed("🔒 Admin Portal", f"Welcome, {ctx.author.mention}. Select an action below:")
    view = AdminView()  # Add all admin buttons here
    await ctx.send(embed=embed, view=view)

# -------------------------------
# 9. Betting Portal Buttons/View
# -------------------------------
class BettingView(View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(MoneyButton())
        self.add_item(DailyButton())
        self.add_item(MatchupsButton())
        self.add_item(BetHistoryButton())
        self.add_item(WinHistoryButton())
        self.add_item(LeaderboardButton())

# 9a. Money button
class MoneyButton(Button):
    def __init__(self):
        super().__init__(label="Money", style=discord.ButtonStyle.success, emoji="💵")
    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        await interaction.response.send_message(
            embed=create_embed("💰 Account Balance", f"You currently have 💵{user_data['money']} to bet with."),
            ephemeral=True
        )

# 9b. Daily claim
class DailyButton(Button):
    def __init__(self):
        super().__init__(label="Daily Grab", style=discord.ButtonStyle.primary, emoji="🟣")
    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        last_claim = datetime.fromisoformat(user_data["last_daily"])
        if datetime.utcnow() - last_claim >= timedelta(hours=24):
            change_user_money(interaction.user.id, 25)
            update_user(interaction.user.id, {"last_daily": datetime.utcnow().isoformat()})
            await interaction.response.send_message(embed=create_embed("✅ Daily Claimed", "You received 💵25! Come back in 24 hours."), ephemeral=True)
        else:
            next_time = last_claim + timedelta(hours=24)
            wait_time = next_time - datetime.utcnow()
            hours, remainder = divmod(wait_time.total_seconds(), 3600)
            minutes = remainder // 60
            await interaction.response.send_message(embed=create_embed("⏳ Not Ready Yet", f"Come back in {int(hours)}h {int(minutes)}m to claim again."), ephemeral=True)

# 9c. Matchups button
class MatchupsButton(Button):
    def __init__(self):
        super().__init__(label="Matchups", style=discord.ButtonStyle.secondary, emoji="🤎")
    async def callback(self, interaction: discord.Interaction):
        matchups = load_json(MATCHUPS_FILE)
        if not matchups:
            await interaction.response.send_message(embed=create_embed("📭 No Matchups", "No matchups available right now."), ephemeral=True)
            return

        for mid, data in matchups.items():
            embed = create_embed(
                f"📌 Matchup #{mid}",
                f"**{data['away']}** @ **{data['home']}**\n"
                f"Spread: {data['away']} ({data['spread']['away']:+}), {data['home']} ({data['spread']['home']:+})\n"
                f"Moneyline: {data['away']} ({data['moneyline']['away']}), {data['home']} ({data['moneyline']['home']})\n"
                f"O/U: {data['over_under']}"
            )
            view = MatchupBetButtonView(mid)
            try:
                await interaction.user.send(embed=embed, view=view)
            except discord.Forbidden:
                await interaction.response.send_message(embed=create_embed("❌ Cannot send DM", "Please enable DMs to receive matchups."), ephemeral=True)
                return
        await interaction.response.send_message(embed=create_embed("📬 Sent", "Matchups sent to your DMs."), ephemeral=True)

# -------------------------------
# 10. Bet Type Menu
# -------------------------------
class TypeSelectView(View):
    def __init__(self, matchup_id):
        super().__init__(timeout=60)
        self.add_item(SpreadButton(matchup_id))
        self.add_item(OUButton(matchup_id))

class SpreadButton(Button):
    def __init__(self, matchup_id):
        super().__init__(label="SPREAD", style=discord.ButtonStyle.primary)
        self.mid = matchup_id
    async def callback(self, interaction: discord.Interaction):
        await show_spread_team_picker(interaction, self.mid)

class OUButton(Button):
    def __init__(self, matchup_id):
        super().__init__(label="O/U", style=discord.ButtonStyle.secondary)
        self.mid = matchup_id
    async def callback(self, interaction: discord.Interaction):
        await show_ou_picker(interaction, self.mid)

async def show_bet_type_menu(interaction: discord.Interaction, matchup_id: str):
    await interaction.response.send_message(
        embed=create_embed("📈 Choose Bet Type", "Click one below to continue."),
        view=TypeSelectView(matchup_id),
        ephemeral=True
    )

# -------------------------------
# 11. Spread Team Picker
# -------------------------------
class TeamSpreadView(View):
    def __init__(self, matchup_id, matchup):
        super().__init__(timeout=60)
        self.add_item(TeamButton("away", matchup_id, matchup["away"], matchup["spread"]["away"]))
        self.add_item(TeamButton("home", matchup_id, matchup["home"], matchup["spread"]["home"]))

class TeamButton(Button):
    def __init__(self, team_key, matchup_id, name, spread):
        label = f"{name} ({spread:+})"
        super().__init__(label=label, style=discord.ButtonStyle.success)
        self.team_key = team_key
        self.mid = matchup_id
    async def callback(self, interaction: discord.Interaction):
        await get_bet_amount(interaction, self.mid, "spread", self.team_key)

async def show_spread_team_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]
    await interaction.response.send_message(
        embed=create_embed("📊 Choose Team", "Select the team to bet on the spread."),
        view=TeamSpreadView(matchup_id, matchup),
        ephemeral=True
    )

# -------------------------------
# 12. Over/Under Picker
# -------------------------------
class OUView(View):
    def __init__(self, matchup_id):
        super().__init__(timeout=60)
        self.add_item(OUChoiceButton("over", matchup_id))
        self.add_item(OUChoiceButton("under", matchup_id))

class OUChoiceButton(Button):
    def __init__(self, label_val, matchup_id):
        super().__init__(label=label_val.upper(), style=discord.ButtonStyle.success)
        self.label_val = label_val
        self.mid = matchup_id
    async def callback(self, interaction: discord.Interaction):
        await get_bet_amount(interaction, self.mid, "ou", self.label_val)

async def show_ou_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]
    await interaction.response.send_message(
        embed=create_embed("📈 Bet Over/Under", f"Match O/U: {matchup['over_under']}"),
        view=OUView(matchup_id),
        ephemeral=True
    )

# -------------------------------
# 13. Bet Amount Modal
# -------------------------------
class AmountModal(Modal):
    def __init__(self, matchup_id, bet_type, target):
        super().__init__(title="Enter Bet Amount")
        self.matchup_id = matchup_id
        self.bet_type = bet_type
        self.target = target
        self.amount = TextInput(label="Amount to Bet", placeholder="e.g. 100", required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        user = get_user(interaction.user.id)
        try:
            bet_amount = int(self.amount.value)
            if bet_amount <= 0:
                raise ValueError
        except:
            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount", "Please enter a positive number."), ephemeral=True)
            return

        if bet_amount > user["money"]:
            missing = bet_amount - user["money"]
            await interaction.response.send_message(embed=create_embed("🛑 Insufficient Funds", f"You are missing 💸{missing} to place this bet."), ephemeral=True)
            return

        matchups = load_json(MATCHUPS_FILE)
        if self.matchup_id not in matchups:
            await interaction.response.send_message(embed=create_embed("❌ Matchup not found."), ephemeral=True)
            return

        matchup = matchups[self.matchup_id]
        bets_on_target = [b for b in matchup.get("bets", []) if b["type"] == self.bet_type and b["target"] == self.target]
        total_on_target = sum(b["amount"] for b in bets_on_target)
        payout_multiplier = max(1.8 - (total_on_target / 1000), 1.1)
        payout = round(bet_amount * payout_multiplier)

        # Record bet
        if "bets" not in matchup:
            matchup["bets"] = []
        bet = {"user": interaction.user.id, "amount": bet_amount, "type": self.bet_type, "target": self.target, "payout": payout}
        matchup["bets"].append(bet)
        save_json(MATCHUPS_FILE, matchups)

        change_user_money(interaction.user.id, -bet_amount)
        log_user_bet(interaction.user.id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {self.target.upper()} | {self.bet_type.upper()} | 💵{bet_amount}")

        await interaction.response.send_message(
            embed=create_embed("✅ Bet Placed", f"You bet 💵{bet_amount} on **{self.target.upper()}** ({self.bet_type.upper()})\nPotential payout: 💵{payout}"),
            ephemeral=True
        )

async def get_bet_amount(interaction: discord.Interaction, matchup_id, bet_type, target):
    await interaction.response.send_modal(AmountModal(matchup_id, bet_type, target))

# -------------------------------
# 14. Parlay Bets (Simplified)
# -------------------------------
class ParlayButton(Button):
    def __init__(self):
        super().__init__(label="Parlay Bet", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=create_embed("🃏 Parlays Coming Soon", "This feature will allow multiple bets in one parlay for higher payouts."),
            ephemeral=True
        )

# -------------------------------
# 15. Prop Bets & Futures (Simplified)
# -------------------------------
class PropButton(Button):
    def __init__(self):
        super().__init__(label="Prop Bet", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=create_embed("🎯 Prop Bets Coming Soon", "Prop bets let you bet on player stats or events."),
            ephemeral=True
        )

class FuturesButton(Button):
    def __init__(self):
        super().__init__(label="Futures Bet", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=create_embed("🔮 Futures Coming Soon", "Futures bets allow betting on long-term outcomes (e.g., season champion)."),
            ephemeral=True
        )

# -------------------------------
# 16. Enhanced Leaderboard
# -------------------------------
class LeaderboardButton(Button):
    def __init__(self):
        super().__init__(label="Leaderboard", style=discord.ButtonStyle.primary, emoji="🏆")

    async def callback(self, interaction: discord.Interaction):
        users = load_json(USERS_FILE)
        sorted_users = sorted(users.items(), key=lambda x: x[1]["money"], reverse=True)
        text = ""
        for i, (uid, data) in enumerate(sorted_users[:10], 1):
            try:
                member = await bot.fetch_user(int(uid))
                wins = len(data.get("win_history", []))
                losses = len(data.get("bet_history", [])) - wins
                text += f"**{i}. {member.display_name}** - 💵{data['money']} | {wins}W-{losses}L\n"
            except Exception:
                continue
        await interaction.response.send_message(embed=create_embed("🏆 Leaderboard (Top 10)", text), ephemeral=True)

# -------------------------------
# 17. Dynamic Moneylines
# -------------------------------
def calculate_dynamic_moneyline(matchup_id):
    matchups = load_json(MATCHUPS_FILE)
    matchup = matchups[matchup_id]
    home_bets = sum(b["amount"] for b in matchup.get("bets", []) if b["target"] == "home")
    away_bets = sum(b["amount"] for b in matchup.get("bets", []) if b["target"] == "away")
    base_line = 110
    total = max(home_bets + away_bets, 1)
    matchup["moneyline"]["home"] = int(base_line * (away_bets / total))
    matchup["moneyline"]["away"] = int(base_line * (home_bets / total))
    save_json(MATCHUPS_FILE, matchups)

@bot.command()
async def betting(ctx):
    embed = create_embed(
        "📊 Sportsbook Portal",
        "Payouts adjust based on how many people bet towards one team.\n\nSelect an option below:"
    )
    await ctx.send(embed=embed, view=BettingView())
    
# -------------------------------
# 18. Bot Launch & Run
# -------------------------------
print("🚀 Bot Starting...")
keep_alive()  # if using Flask/uptime method
bot.run(TOKEN)
