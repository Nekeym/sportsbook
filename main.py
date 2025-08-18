import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import json
import os
from datetime import datetime, timedelta
from keep_alive import keep_alive
import base64
import requests  # <-- for GitHub API push

# Intents setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Constants
ADMIN_ID = 1085391944240332940
# Token loaded securely from environment variable; set TOKENFORBOTHERE in your Docker or hosting env
TOKEN = os.environ.get("TOKENFORBOTHERE")
PAYOUT_CHANNEL_ID = 1401259843834216528  # <-- Replace with your payout channel ID

USERS_FILE = "users.json"
MATCHUPS_FILE = "matchups.json"

# Ensure data folder and files exist
os.makedirs("data", exist_ok=True)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)
if not os.path.exists(MATCHUPS_FILE):
    with open(MATCHUPS_FILE, "w") as f:
        json.dump({}, f)

# Load and save helpers
def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

# GitHub API push helper
def push_json_to_github_api(file_path, repo_path, commit_message="Auto-update JSON"):
    github_user = "Nekeym"           # your GitHub username
    github_repo = "sportsbook"       # your repo name
    branch = "main"                  # your branch

    # Load the file content
    with open(file_path, "r") as f:
        content = f.read()

    # Encode content in base64
    b64_content = base64.b64encode(content.encode()).decode()

    # Get SHA if file exists
    url_get = f"https://api.github.com/repos/{github_user}/{github_repo}/contents/{repo_path}?ref={branch}"
    headers = {"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"}
    response = requests.get(url_get, headers=headers)

    sha = None
    if response.status_code == 200:
        sha = response.json()["sha"]

    # Push/update file
    url_put = f"https://api.github.com/repos/{github_user}/{github_repo}/contents/{repo_path}"
    data = {
        "message": commit_message,
        "content": b64_content,
        "branch": branch
    }
    if sha:
        data["sha"] = sha

    put_response = requests.put(url_put, headers=headers, data=json.dumps(data))
    if put_response.status_code in [200, 201]:
        print(f"{file_path} successfully pushed to GitHub!")
    else:
        print(f"Failed to push {file_path}: {put_response.text}")

# Push both JSONs
def push_all_jsons():
    try:
        push_json_to_github_api(USERS_FILE, "users.json", "Update users.json")
        push_json_to_github_api(MATCHUPS_FILE, "matchups.json", "Update matchups.json")
    except Exception as e:
        print(f"Failed to push JSONs via API: {e}")

# Updated save_json to call API push
def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    push_all_jsons()  # <-- push to GitHub after saving

# User data helpers
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

# Embed helpers
def create_embed(title, description="", color=discord.Color.blurple()):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Sportsbook Bot • Dollars💵")
    embed.timestamp = datetime.utcnow()
    return embed

def no_permission_embed():
    return create_embed("🟥 YOU DO NOT HAVE PERMISSION TO USE THIS 🟥", color=discord.Color.red())

# === Admin Commands ===
@bot.command()
async def admincommands(ctx):
    if ctx.author.id != ADMIN_ID:
        await ctx.send(embed=no_permission_embed())
        return

    embed = create_embed("🔒 Admin Portal", f"Welcome to the admin portal, {ctx.author.mention}.")

    class AdminView(View):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(self.CreateMatchup())
            self.add_item(self.FinishMatchup())
            self.add_item(self.AddMoneyToUser())
            self.add_item(self.AddMoneyToAll())
            self.add_item(self.RemoveMoneyFromUser())
            self.add_item(self.DeleteUserBet())
            self.add_item(self.DeleteMatchup())

        # Button 1: Create Matchup
        class CreateMatchup(Button):
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
                            home_spread_val = float(self.home_spread.value.strip().replace("+", ""))
                            away_spread_val = float(self.away_spread.value.strip().replace("+", ""))
                            ou_val = float(self.over_under.value.strip().replace("+", ""))
                        except Exception:
                            await interaction.response.send_message(
                                embed=create_embed("⚠️ Invalid input", "Spreads and O/U must be numbers like -6.5 or 55.5"),
                                ephemeral=True
                            )
                            return

                        matchups = load_json(MATCHUPS_FILE)
                        match_id = str(len(matchups) + 1)
                        matchups[match_id] = {
                            "home": self.home_team.value.strip(),
                            "away": self.away_team.value.strip(),
                            "spread": {
                                "home": home_spread_val,
                                "away": away_spread_val
                            },
                            "moneyline": {
                                "home": -110,
                                "away": -110
                            },
                            "over_under": ou_val,
                            "bets": []
                        }
                        save_json(MATCHUPS_FILE, matchups)
                        await interaction.response.send_message(embed=create_embed("✅ Matchup Created", f"Matchup ID: `{match_id}`"), ephemeral=True)

                await interaction.response.send_modal(MatchupModal())

        # Button 2: Finish Matchup
        class FinishMatchup(Button):
            def __init__(self):
                super().__init__(label="Finish Matchup", style=discord.ButtonStyle.primary)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user.id != ADMIN_ID:
                    await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
                    return

                class FinishModal(Modal, title="Finish Matchup"):
                    match_id = TextInput(label="Matchup ID")
                    winner = TextInput(label="Winning Spread (home or away)")
                    ou_result = TextInput(label="O/U Result (over or under)")

                    async def on_submit(self, interaction: discord.Interaction):
                        matchups = load_json(MATCHUPS_FILE)
                        mid = self.match_id.value.strip()
                        if mid not in matchups:
                            await interaction.response.send_message(embed=create_embed("⚠️ Matchup Not Found", color=discord.Color.red()), ephemeral=True)
                            return
                        match = matchups[mid]
                        winner_key = self.winner.value.strip().lower()
                        if winner_key not in ("home", "away"):
                            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Winner", "Winner must be 'home' or 'away'."), ephemeral=True)
                            return
                        ou_res = self.ou_result.value.strip().lower()
                        if ou_res not in ("over", "under"):
                            await interaction.response.send_message(embed=create_embed("⚠️ Invalid O/U Result", "O/U result must be 'over' or 'under'."), ephemeral=True)
                            return

                        # Prepare payout summary list
                        payout_messages = []

                        for bet in match["bets"]:
                            user = bet["user"]
                            bet_type = bet["type"]
                            target = bet["target"]
                            amount = bet["amount"]
                            result = "LOST"

                            if bet_type == "spread" and target == winner_key:
                                change_user_money(user, bet["payout"])
                                result = "WON"
                                payout_messages.append(f"<@{user}> won 💵{bet['payout']} on spread bet ({target.upper()})")
                            elif bet_type == "ou" and target.lower() == ou_res:
                                change_user_money(user, bet["payout"])
                                result = "WON"
                                payout_messages.append(f"<@{user}> won 💵{bet['payout']} on O/U bet ({target.upper()})")

                            users = load_json(USERS_FILE)
                            uid = str(user)
                            if uid not in users:
                                users[uid] = {
                                    "money": 500,
                                    "last_daily": "2000-01-01T00:00:00",
                                    "bet_history": [],
                                    "win_history": []
                                }

                            if bet_type == "spread":
                                desc = f"Spread bet on {target.upper()}"
                            else:
                                desc = f"O/U bet on {target.upper()}"

                            entry = f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {desc} | {result}"
                            users[uid].setdefault("win_history", []).append(entry)
                            save_json(USERS_FILE, users)

                        # Send payout summary to payout channel
                        payout_channel = interaction.guild.get_channel(PAYOUT_CHANNEL_ID)
                        if payout_channel and payout_messages:
                            embed = discord.Embed(title=f"Payouts for Matchup {mid}", color=discord.Color.green())
                            embed.description = "\n".join(payout_messages)
                            await payout_channel.send(embed=embed)

                        # Finally delete the matchup and save
                        del matchups[mid]
                        save_json(MATCHUPS_FILE, matchups)
                        await interaction.response.send_message(embed=create_embed("✅ Matchup Settled", "All bets processed."), ephemeral=True)

                await interaction.response.send_modal(FinishModal())

        # Button 3: Add Money To User
        class AddMoneyToUser(Button):
            def __init__(self):
                super().__init__(label="Add Money To User", style=discord.ButtonStyle.success)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user.id != ADMIN_ID:
                    await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
                    return

                class AddMoneyModal(Modal, title="Add Money To User"):
                    user_id_input = TextInput(label="User ID", placeholder="Discord User ID")
                    amount = TextInput(label="Amount to Add", placeholder="e.g. 100")

                    async def on_submit(self, interaction: discord.Interaction):
                        try:
                            user_id_int = int(self.user_id_input.value.strip())
                            amount_int = int(self.amount.value.strip())
                            if amount_int <= 0:
                                raise ValueError
                        except Exception:
                            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Input", "Please enter valid User ID and positive amount."), ephemeral=True)
                            return

                        get_user(user_id_int)
                        change_user_money(user_id_int, amount_int)
                        await interaction.response.send_message(embed=create_embed("✅ Money Added", f"Added 💵{amount_int} to <@{user_id_int}>."), ephemeral=True)

                await interaction.response.send_modal(AddMoneyModal())

        # Button 4: Add Money To All
        class AddMoneyToAll(Button):
            def __init__(self):
                super().__init__(label="Add Money To All", style=discord.ButtonStyle.success)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user.id != ADMIN_ID:
                    await interaction.response.send_message(embed=no_permission_embed(), ephemeral=True)
                    return

                class AddAllModal(Modal, title="Add Money To All"):
                    amount = TextInput(label="Amount to Add", placeholder="e.g. 50")

                    async def on_submit(self, interaction: discord.Interaction):
                        try:
                            amount_int = int(self.amount.value.strip())
                            if amount_int <= 0:
                                raise ValueError
                        except Exception:
                            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount", "Please enter a positive number."), ephemeral=True)
                            return

                        count = 0
                        for member in interaction.guild.members:
                            if not member.bot:
                                get_user(member.id)
                                change_user_money(member.id, amount_int)
                                count += 1
                        await interaction.response.send_message(embed=create_embed("✅ Mass Payment", f"Added 💵{amount_int} to {count} users."), ephemeral=True)

                await interaction.response.send_modal(AddAllModal())

        # Button 5: Remove Money From User
        class RemoveMoneyFromUser(Button):
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
                        except Exception:
                            await interaction.response.send_message(embed=create_embed("⚠️ Invalid Input", "Please enter valid User ID and positive amount."), ephemeral=True)
                            return

                        user_data = get_user(user_id_int)
                        if user_data["money"] < amount_int:
                            await interaction.response.send_message(embed=create_embed("🛑 Not Enough Money", f"User only has 💵{user_data['money']}."), ephemeral=True)
                            return

                        change_user_money(user_id_int, -amount_int)
                        await interaction.response.send_message(embed=create_embed("✅ Money Removed", f"Removed 💵{amount_int} from <@{user_id_int}>."), ephemeral=True)

                await interaction.response.send_modal(RemoveMoneyModal())

        # Button 6: Delete User Bet
        class DeleteUserBet(Button):
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
                        user_id_int = None
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
                            await interaction.response.send_message(embed=create_embed("ℹ️ Bet Not Found", f"No bet by <@{user_id_int}> found on matchup {mid}."), ephemeral=True)
                            return

                        save_json(MATCHUPS_FILE, matchups)
                        await interaction.response.send_message(embed=create_embed("✅ Bet Deleted", f"Deleted bet by <@{user_id_int}> on matchup {mid}."), ephemeral=True)

                await interaction.response.send_modal(DeleteBetModal())

        # Button 7: Delete Matchup
        class DeleteMatchup(Button):
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
                            await interaction.response.send_message(embed=create_embed("❌ Matchup Not Found", color=discord.Color.red()), ephemeral=True)
                            return
                        match = matchups[mid]
                        # Refund all bets
                        for bet in match["bets"]:
                            change_user_money(bet["user"], bet["amount"])
                        del matchups[mid]
                        save_json(MATCHUPS_FILE, matchups)
                        await interaction.response.send_message(embed=create_embed("🗑️ Matchup Deleted", "All bets refunded."), ephemeral=True)

                await interaction.response.send_modal(DeleteModal())

    await ctx.send(embed=embed, view=AdminView())

# === Betting Commands ===
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from datetime import datetime, timedelta

# -------------------------------
# MAIN BETTING MENU BUTTONS/VIEW
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

class MoneyButton(Button):
    def __init__(self):
        super().__init__(label="Money", style=discord.ButtonStyle.success, emoji="💵")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        await interaction.response.send_message(
            embed=create_embed("💰 Account Balance", f"You currently have 💵{user_data['money']} to bet with."),
            ephemeral=True
        )

class DailyButton(Button):
    def __init__(self):
        super().__init__(label="Daily Grab", style=discord.ButtonStyle.primary, emoji="🟣")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        last_claim = datetime.fromisoformat(user_data["last_daily"])
        if datetime.utcnow() - last_claim >= timedelta(hours=24):
            change_user_money(interaction.user.id, 25)
            update_user(interaction.user.id, {"last_daily": datetime.utcnow().isoformat()})
            await interaction.response.send_message(
                embed=create_embed("✅ Daily Claimed", "You received 💵25! Come back in 24 hours."),
                ephemeral=True
            )
        else:
            next_time = last_claim + timedelta(hours=24)
            wait_time = next_time - datetime.utcnow()
            hours, remainder = divmod(wait_time.total_seconds(), 3600)
            minutes = remainder // 60
            await interaction.response.send_message(
                embed=create_embed("⏳ Not Ready Yet", f"Come back in {int(hours)}h {int(minutes)}m to claim again."),
                ephemeral=True
            )

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
                f"**{data['away']}** @ **{data['home']}**\n\n"
                f"Spread:\n• {data['away']}: {data['spread']['away']:+}\n"
                f"• {data['home']}: {data['spread']['home']:+}\n\n"
                f"Moneyline:\n• {data['away']}: {data['moneyline']['away']}\n"
                f"• {data['home']}: {data['moneyline']['home']}\n\n"
                f"O/U: {data['over_under']}"
            )
            view = MatchupBetButtonView(mid)
            try:
                await interaction.user.send(embed=embed, view=view)
            except discord.Forbidden:
                await interaction.response.send_message(embed=create_embed("❌ Cannot send DM", "Please enable DMs to receive matchups."), ephemeral=True)
                return

        await interaction.response.send_message(embed=create_embed("📬 Sent", "Matchups sent to your DMs."), ephemeral=True)

class MatchupBetButtonView(View):
    def __init__(self, matchup_id):
        super().__init__(timeout=180)
        self.add_item(BetButton(matchup_id))

class BetButton(Button):
    def __init__(self, matchup_id):
        super().__init__(label="BET", style=discord.ButtonStyle.danger)
        self.mid = matchup_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.bot:
            return
        await show_bet_type_menu(interaction, self.mid)

class BetHistoryButton(Button):
    def __init__(self):
        super().__init__(label="Bet History", style=discord.ButtonStyle.danger, emoji="⚫")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        history = user_data["bet_history"]
        if not history:
            await interaction.response.send_message(embed=create_embed("📃 Bet History", "You haven't placed any bets yet."), ephemeral=True)
            return
        text = "\n".join(history[-10:])
        await interaction.response.send_message(embed=create_embed("📃 Bet History (Last 10)", text), ephemeral=True)

class WinHistoryButton(Button):
    def __init__(self):
        super().__init__(label="Win History", style=discord.ButtonStyle.secondary, emoji="🟡")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        history = user_data["win_history"]
        if not history:
            await interaction.response.send_message(embed=create_embed("📈 Win History", "No results yet."), ephemeral=True)
            return
        text = "\n".join(history[-10:])
        await interaction.response.send_message(embed=create_embed("📈 Win History (Last 10)", text), ephemeral=True)

class LeaderboardButton(Button):
    def __init__(self):
        super().__init__(label="Leaderboard", style=discord.ButtonStyle.primary, emoji="🔵")

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
        await interaction.response.send_message(embed=create_embed("🏆 Leaderboard", text), ephemeral=True)

# -------------------------------
# BET TYPE MENU
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
    async def callback(self, interaction):
        await show_spread_team_picker(interaction, self.mid)

class OUButton(Button):
    def __init__(self, matchup_id):
        super().__init__(label="O/U", style=discord.ButtonStyle.secondary)
        self.mid = matchup_id
    async def callback(self, interaction):
        await show_ou_picker(interaction, self.mid)

async def show_bet_type_menu(interaction: discord.Interaction, matchup_id: str):
    await interaction.response.send_message(
        embed=create_embed("📈 Choose Bet Type", "Click one below."),
        view=TypeSelectView(matchup_id),
        ephemeral=True
    )

# -------------------------------
# SPREAD TEAM PICKER
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
    async def callback(self, interaction):
        await get_bet_amount(interaction, self.mid, "spread", self.team_key)

async def show_spread_team_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]
    await interaction.response.send_message(
        embed=create_embed("📊 Choose Team", "Choose which spread to bet."),
        view=TeamSpreadView(matchup_id, matchup),
        ephemeral=True
    )

# -------------------------------
# OVER/UNDER PICKER
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
    async def callback(self, interaction):
        await get_bet_amount(interaction, self.mid, "ou", self.label_val)

async def show_ou_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]
    await interaction.response.send_message(
        embed=create_embed("📈 Bet Over/Under", f"Match O/U: {matchup['over_under']}"),
        view=OUView(matchup_id),
        ephemeral=True
    )

# -------------------------------
# BET AMOUNT MODAL
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
# COMMAND
# -------------------------------
@bot.command()
async def betting(ctx):
    embed = create_embed(
        "📊 Sportsbook Portal",
        "Payouts adjust based on how many people bet towards one team.\n\nSelect an option below:"
    )
    await ctx.send(embed=embed, view=BettingView())


print("Starting bot...")
keep_alive()
bot.run(TOKEN)
