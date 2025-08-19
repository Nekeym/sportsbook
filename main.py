# =========================
# PART 1: SETUP & HELPERS
# =========================
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import json
import os
from datetime import datetime, timedelta
from keep_alive import keep_alive
import base64
import requests

# -----------------------
# Bot & Intents
# -----------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -----------------------
# Constants
# -----------------------
ADMIN_ID = 1085391944240332940
TOKEN = os.environ.get("TOKENFORBOTHERE")
PAYOUT_CHANNEL_ID = 1401259843834216528

USERS_FILE = "data/users.json"
MATCHUPS_FILE = "data/matchups.json"

# -----------------------
# Ensure data files exist
# -----------------------
os.makedirs("data", exist_ok=True)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)
if not os.path.exists(MATCHUPS_FILE):
    with open(MATCHUPS_FILE, "w") as f:
        json.dump({}, f)

# -----------------------
# JSON helpers
# -----------------------
def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    push_all_jsons()  # push to GitHub after every save

# -----------------------
# GitHub push helpers
# -----------------------
def push_json_to_github_api(file_path, repo_path, commit_message="Auto-update JSON"):
    github_user = "Nekeym"
    github_repo = "sportsbook"
    branch = "main"

    with open(file_path, "r") as f:
        content = f.read()

    b64_content = base64.b64encode(content.encode()).decode()
    url_get = f"https://api.github.com/repos/{github_user}/{github_repo}/contents/{repo_path}?ref={branch}"
    headers = {"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"}
    response = requests.get(url_get, headers=headers)
    sha = response.json()["sha"] if response.status_code == 200 else None

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

# -----------------------
# User helpers
# -----------------------
def get_user(user_id):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"money": 500, "last_daily": "2000-01-01T00:00:00", "bet_history": [], "win_history": []}
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
    users[uid].setdefault("bet_history", []).append(entry)
    save_json(USERS_FILE, users)

def log_user_result(user_id, entry):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    users[uid].setdefault("win_history", []).append(entry)
    save_json(USERS_FILE, users)

# -----------------------
# Embed helpers
# -----------------------
def create_embed(title, description="", color=discord.Color.blurple()):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Sportsbook Bot • Dollars💵")
    embed.timestamp = datetime.utcnow()
    return embed

def no_permission_embed():
    return create_embed("🟥 YOU DO NOT HAVE PERMISSION TO USE THIS 🟥", color=discord.Color.red())

# =========================
# PART 2: ADMIN BUTTONS & MODALS
# =========================

from discord import ButtonStyle

# -----------------------
# Admin View
# -----------------------
class AdminView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CreateMatchup())
        self.add_item(FinishMatchup())
        self.add_item(AddMoneyToUser())
        self.add_item(AddMoneyToAll())
        self.add_item(RemoveMoneyFromUser())
        self.add_item(DeleteUserBet())
        self.add_item(DeleteMatchup())

# -----------------------
# Button 1: Create Matchup
# -----------------------
class CreateMatchup(Button):
    def __init__(self):
        super().__init__(label="Create Matchup", style=ButtonStyle.primary)

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
                    home_val = float(self.home_spread.value.strip().replace("+",""))
                    away_val = float(self.away_spread.value.strip().replace("+",""))
                    ou_val = float(self.over_under.value.strip())
                except:
                    await interaction.response.send_message(embed=create_embed(
                        "⚠️ Invalid input", "Spreads and O/U must be numeric like -6.5 or 55.5"
                    ), ephemeral=True)
                    return

                matchups = load_json(MATCHUPS_FILE)
                match_id = str(len(matchups) + 1)
                matchups[match_id] = {
                    "home": self.home_team.value.strip(),
                    "away": self.away_team.value.strip(),
                    "spread": {"home": home_val, "away": away_val},
                    "moneyline": {"home": -110, "away": -110},
                    "over_under": ou_val,
                    "bets": []
                }
                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(embed=create_embed(
                    "✅ Matchup Created", f"Matchup ID: `{match_id}`"
                ), ephemeral=True)

        await interaction.response.send_modal(MatchupModal())

# -----------------------
# Button 2: Finish Matchup
# -----------------------
class FinishMatchup(Button):
    def __init__(self):
        super().__init__(label="Finish Matchup", style=ButtonStyle.primary)

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
                    await interaction.response.send_message(embed=create_embed("⚠️ Matchup Not Found"), ephemeral=True)
                    return

                match = matchups[mid]
                winner_key = self.winner.value.strip().lower()
                ou_res = self.ou_result.value.strip().lower()
                if winner_key not in ("home","away") or ou_res not in ("over","under"):
                    await interaction.response.send_message(embed=create_embed("⚠️ Invalid input"), ephemeral=True)
                    return

                payout_msgs = []
                users = load_json(USERS_FILE)
                for bet in match["bets"]:
                    uid = str(bet["user"])
                    result = "LOST"
                    if bet["type"] == "spread" and bet["target"] == winner_key:
                        change_user_money(bet["user"], bet["payout"])
                        result = "WON"
                        payout_msgs.append(f"<@{uid}> won 💵{bet['payout']} on spread ({winner_key.upper()})")
                    elif bet["type"] == "ou" and bet["target"] == ou_res:
                        change_user_money(bet["user"], bet["payout"])
                        result = "WON"
                        payout_msgs.append(f"<@{uid}> won 💵{bet['payout']} on O/U ({ou_res.upper()})")

                    users.setdefault(uid, {"money": 500, "last_daily":"2000-01-01T00:00:00","bet_history":[],"win_history":[]})
                    desc = "Spread bet" if bet["type"]=="spread" else "O/U bet"
                    users[uid].setdefault("win_history", []).append(f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {desc} on {bet['target'].upper()} | {result}")
                save_json(USERS_FILE, users)

                payout_channel = interaction.guild.get_channel(PAYOUT_CHANNEL_ID)
                if payout_channel and payout_msgs:
                    embed = create_embed(f"Payouts for Matchup {mid}", "\n".join(payout_msgs), color=discord.Color.green())
                    await payout_channel.send(embed=embed)

                del matchups[mid]
                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(embed=create_embed("✅ Matchup Settled", "All bets processed."), ephemeral=True)

        await interaction.response.send_modal(FinishModal())
# ========== BUTTON 3: Add Money To User ==========
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
                except:
                    await interaction.response.send_message(
                        embed=create_embed("⚠️ Invalid Input"), ephemeral=True
                    )
                    return

                get_user(user_id_int)
                change_user_money(user_id_int, amount_int)
                await interaction.response.send_message(
                    embed=create_embed("✅ Money Added", f"Added 💵{amount_int} to <@{user_id_int}>."), ephemeral=True
                )

        await interaction.response.send_modal(AddMoneyModal())


# ========== BUTTON 4: Add Money To All ==========
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
                except:
                    await interaction.response.send_message(
                        embed=create_embed("⚠️ Invalid Amount"), ephemeral=True
                    )
                    return

                count = 0
                for member in interaction.guild.members:
                    if not member.bot:
                        get_user(member.id)
                        change_user_money(member.id, amount_int)
                        count += 1

                await interaction.response.send_message(
                    embed=create_embed("✅ Mass Payment", f"Added 💵{amount_int} to {count} users."), ephemeral=True
                )


# ========== BUTTON 5: Remove Money From User ==========
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
                except:
                    await interaction.response.send_message(
                        embed=create_embed("⚠️ Invalid Input"), ephemeral=True
                    )
                    return

                user_data = get_user(user_id_int)
                if user_data["money"] < amount_int:
                    await interaction.response.send_message(
                        embed=create_embed("🛑 Not Enough Money", f"User only has 💵{user_data['money']}."), ephemeral=True
                    )
                    return

                change_user_money(user_id_int, -amount_int)
                await interaction.response.send_message(
                    embed=create_embed("✅ Money Removed", f"Removed 💵{amount_int} from <@{user_id_int}>."), ephemeral=True
                )


# ========== BUTTON 6: Delete User Bet ==========
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
                await interaction.response.send_message(
                    embed=create_embed("✅ Bet Deleted", f"Deleted bet by <@{user_id_int}> on matchup {mid}."), ephemeral=True
                )


# ========== BUTTON 7: Delete Matchup ==========
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
                    await interaction.response.send_message(embed=create_embed("❌ Matchup Not Found"), ephemeral=True)
                    return

                match = matchups[mid]
                # Refund all bets
                for bet in match["bets"]:
                    change_user_money(bet["user"], bet["amount"])
                del matchups[mid]
                save_json(MATCHUPS_FILE, matchups)
                await interaction.response.send_message(
                    embed=create_embed("🗑️ Matchup Deleted", "All bets refunded."), ephemeral=True
                )

# =========================
# BETTING PORTAL BUTTONS / VIEW
# =========================
class BettingView(View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(MoneyButton())
        self.add_item(DailyButton())
        self.add_item(MatchupsButton())
        self.add_item(BetHistoryButton())
        self.add_item(WinHistoryButton())
        self.add_item(LeaderboardButton())


# ---------- BUTTON: Account Balance ----------
class MoneyButton(Button):
    def __init__(self):
        super().__init__(label="Money", style=discord.ButtonStyle.success, emoji="💵")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        await interaction.response.send_message(
            embed=create_embed("💰 Account Balance", f"You currently have 💵{user_data['money']} to bet with."),
            ephemeral=True
        )


# ---------- BUTTON: Daily Grab ----------
class DailyButton(Button):
    def __init__(self):
        super().__init__(label="Daily Grab", style=discord.ButtonStyle.primary, emoji="🟣")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        last_claim = datetime.fromisoformat(user_data["last_daily"])
        now = datetime.utcnow()

        if now - last_claim >= timedelta(hours=24):
            change_user_money(interaction.user.id, 25)
            update_user(interaction.user.id, {"last_daily": now.isoformat()})
            await interaction.response.send_message(
                embed=create_embed("✅ Daily Claimed", "You received 💵25! Come back in 24 hours."),
                ephemeral=True
            )
        else:
            next_time = last_claim + timedelta(hours=24)
            wait_time = next_time - now
            hours, remainder = divmod(wait_time.total_seconds(), 3600)
            minutes = remainder // 60
            await interaction.response.send_message(
                embed=create_embed("⏳ Not Ready Yet", f"Come back in {int(hours)}h {int(minutes)}m to claim again."),
                ephemeral=True
            )


# ---------- BUTTON: Matchups ----------
class MatchupsButton(Button):
    def __init__(self):
        super().__init__(label="Matchups", style=discord.ButtonStyle.secondary, emoji="🤎")

    async def callback(self, interaction: discord.Interaction):
        matchups = load_json(MATCHUPS_FILE)
        if not matchups:
            await interaction.response.send_message(embed=create_embed("📭 No Matchups", "No matchups available right now."), ephemeral=True)
            return

        # Send each matchup to user DM with a betting button
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
                await interaction.response.send_message(
                    embed=create_embed("❌ Cannot send DM", "Please enable DMs to receive matchups."),
                    ephemeral=True
                )
                return

        await interaction.response.send_message(embed=create_embed("📬 Sent", "Matchups sent to your DMs."), ephemeral=True)


# ---------- Matchup Bet Button View ----------
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


# ---------- BUTTON: Bet History ----------
class BetHistoryButton(Button):
    def __init__(self):
        super().__init__(label="Bet History", style=discord.ButtonStyle.danger, emoji="⚫")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        history = user_data.get("bet_history", [])
        if not history:
            await interaction.response.send_message(embed=create_embed("📃 Bet History", "You haven't placed any bets yet."), ephemeral=True)
            return

        text = "\n".join(history[-10:])
        await interaction.response.send_message(embed=create_embed("📃 Bet History (Last 10)", text), ephemeral=True)


# ---------- BUTTON: Win History ----------
class WinHistoryButton(Button):
    def __init__(self):
        super().__init__(label="Win History", style=discord.ButtonStyle.secondary, emoji="🟡")

    async def callback(self, interaction: discord.Interaction):
        user_data = get_user(interaction.user.id)
        history = user_data.get("win_history", [])
        if not history:
            await interaction.response.send_message(embed=create_embed("📈 Win History", "No results yet."), ephemeral=True)
            return

        text = "\n".join(history[-10:])
        await interaction.response.send_message(embed=create_embed("📈 Win History (Last 10)", text), ephemeral=True)


# ---------- BUTTON: Leaderboard ----------
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
            except:
                continue

        await interaction.response.send_message(embed=create_embed("🏆 Leaderboard", text), ephemeral=True)

# =========================
# BET TYPE MENU (SPREAD / O/U)
# =========================
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
        embed=create_embed("📈 Choose Bet Type", "Click one below."),
        view=TypeSelectView(matchup_id),
        ephemeral=True
    )


# =========================
# SPREAD TEAM PICKER
# =========================
class TeamSpreadView(View):
    def __init__(self, matchup_id, matchup):
        super().__init__(timeout=60)
        self.add_item(TeamButton("away", matchup_id, matchup["away"], matchup["spread"]["away"]))
        self.add_item(TeamButton("home", matchup_id, matchup["home"], matchup["spread"]["home"]))


class TeamButton(Button):
    def __init__(self, team_key, matchup_id, name, spread):
        super().__init__(label=f"{name} ({spread:+})", style=discord.ButtonStyle.success)
        self.team_key = team_key
        self.mid = matchup_id

    async def callback(self, interaction: discord.Interaction):
        await get_bet_amount(interaction, self.mid, "spread", self.team_key)


async def show_spread_team_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]
    await interaction.response.send_message(
        embed=create_embed("📊 Choose Team", "Choose which spread to bet."),
        view=TeamSpreadView(matchup_id, matchup),
        ephemeral=True
    )


# =========================
# OVER/UNDER PICKER
# =========================
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


# =========================
# BET AMOUNT MODAL
# =========================
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
            await interaction.response.send_message(
                embed=create_embed("⚠️ Invalid Amount", "Please enter a positive number."),
                ephemeral=True
            )
            return

        if bet_amount > user["money"]:
            missing = bet_amount - user["money"]
            await interaction.response.send_message(
                embed=create_embed("🛑 Insufficient Funds", f"You are missing 💸{missing} to place this bet."),
                ephemeral=True
            )
            return

        matchups = load_json(MATCHUPS_FILE)
        if self.matchup_id not in matchups:
            await interaction.response.send_message(
                embed=create_embed("❌ Matchup not found."),
                ephemeral=True
            )
            return

        matchup = matchups[self.matchup_id]
        bets_on_target = [b for b in matchup.get("bets", []) if b["type"] == self.bet_type and b["target"] == self.target]
        total_on_target = sum(b["amount"] for b in bets_on_target)
        payout_multiplier = max(1.8 - (total_on_target / 1000), 1.1)
        payout = round(bet_amount * payout_multiplier)

        bet = {"user": interaction.user.id, "amount": bet_amount, "type": self.bet_type, "target": self.target, "payout": payout}
        matchup.setdefault("bets", []).append(bet)
        save_json(MATCHUPS_FILE, matchups)

        change_user_money(interaction.user.id, -bet_amount)
        log_user_bet(interaction.user.id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {self.target.upper()} | {self.bet_type.upper()} | 💵{bet_amount}")

        await interaction.response.send_message(
            embed=create_embed("✅ Bet Placed", f"You bet 💵{bet_amount} on **{self.target.upper()}** ({self.bet_type.upper()})\nPotential payout: 💵{payout}"),
            ephemeral=True
        )


async def get_bet_amount(interaction: discord.Interaction, matchup_id, bet_type, target):
    await interaction.response.send_modal(AmountModal(matchup_id, bet_type, target))
