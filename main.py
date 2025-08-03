import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import json
import os
from datetime import datetime, timedelta
from keep_alive import keep_alive

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

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

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
@bot.command()
async def betting(ctx):
    user = get_user(ctx.author.id)
    embed = create_embed(
        "📊 Sportsbook Portal",
        "Payouts adjust based on how many people bet towards one team.\n\nSelect an option below:"
    )

    class BettingView(View):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(self.Money())
            self.add_item(self.Daily())
            self.add_item(self.Matchups())
            self.add_item(self.BetHistory())
            self.add_item(self.WinHistory())
            self.add_item(self.Leaderboard())

        class Money(Button):
            def __init__(self):
                super().__init__(label="Money", style=discord.ButtonStyle.success, emoji="💵")

            async def callback(self, interaction: discord.Interaction):
                user_data = get_user(interaction.user.id)
                await interaction.response.send_message(
                    embed=create_embed("💰 Account Balance", f"You currently have 💵{user_data['money']} to bet with."),
                    ephemeral=True
                )

        class Daily(Button):
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

        class Matchups(Button):
            def __init__(self):
                super().__init__(label="Matchups", style=discord.ButtonStyle.secondary, emoji="🤎")

            async def callback(self, interaction: discord.Interaction):
                matchups = load_json(MATCHUPS_FILE)
                if not matchups:
                    await interaction.response.send_message(
                        embed=create_embed("📭 No Matchups", "No matchups available right now."),
                        ephemeral=True
                    )
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

                    class BetButton(Button):
                        def __init__(self, mid):
                            super().__init__(label="BET", style=discord.ButtonStyle.danger)
                            self.mid = mid

                        async def callback(self, interaction: discord.Interaction):
                            if interaction.user.bot:
                                return
                            await show_bet_type_menu(interaction, self.mid)

                    view = View(timeout=180)
                    view.add_item(BetButton(mid))
                    try:
                        await interaction.user.send(embed=embed, view=view)
                    except discord.Forbidden:
                        await interaction.response.send_message(
                            embed=create_embed("❌ Cannot send DM", "Please enable DMs to receive matchups."),
                            ephemeral=True
                        )
                        return
                await interaction.response.send_message(
                    embed=create_embed("📬 Sent", "Matchups sent to your DMs."),
                    ephemeral=True
                )

        class BetHistory(Button):
            def __init__(self):
                super().__init__(label="Bet History", style=discord.ButtonStyle.danger, emoji="⚫")

            async def callback(self, interaction: discord.Interaction):
                user_data = get_user(interaction.user.id)
                history = user_data["bet_history"]
                if not history:
                    await interaction.response.send_message(
                        embed=create_embed("📃 Bet History", "You haven't placed any bets yet."),
                        ephemeral=True
                    )
                    return
                text = "\n".join(history[-10:])
                await interaction.response.send_message(embed=create_embed("📃 Bet History (Last 10)", text), ephemeral=True)

        class WinHistory(Button):
            def __init__(self):
                super().__init__(label="Win History", style=discord.ButtonStyle.secondary, emoji="🟡")

            async def callback(self, interaction: discord.Interaction):
                user_data = get_user(interaction.user.id)
                history = user_data["win_history"]
                if not history:
                    await interaction.response.send_message(
                        embed=create_embed("📈 Win History", "No results yet."),
                        ephemeral=True
                    )
                    return
                text = "\n".join(history[-10:])
                await interaction.response.send_message(embed=create_embed("📈 Win History (Last 10)", text), ephemeral=True)

        class Leaderboard(Button):
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

    await ctx.send(embed=embed, view=BettingView())

async def show_bet_type_menu(interaction: discord.Interaction, matchup_id: str):
    matchups = load_json(MATCHUPS_FILE)
    if matchup_id not in matchups:
        await interaction.response.send_message(embed=create_embed("❌ Matchup not found."), ephemeral=True)
        return

    class TypeSelect(View):
        def __init__(self):
            super().__init__(timeout=60)
            self.add_item(self.SpreadButton())
            self.add_item(self.OUButton())

        class SpreadButton(Button):
            def __init__(self):
                super().__init__(label="SPREAD", style=discord.ButtonStyle.primary)

            async def callback(self, interaction2: discord.Interaction):
                await show_spread_team_picker(interaction2, matchup_id)

        class OUButton(Button):
            def __init__(self):
                super().__init__(label="O/U", style=discord.ButtonStyle.secondary)

            async def callback(self, interaction2: discord.Interaction):
                await show_ou_picker(interaction2, matchup_id)

    await interaction.response.send_message(embed=create_embed("📈 Choose Bet Type", "Click one below."), view=TypeSelect(), ephemeral=True)


async def show_spread_team_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]

    class TeamSpread(View):
        def __init__(self):
            super().__init__(timeout=60)
            self.add_item(self.TeamButton("away", matchup["away"], matchup["spread"]["away"]))
            self.add_item(self.TeamButton("home", matchup["home"], matchup["spread"]["home"]))

        class TeamButton(Button):
            def __init__(self, team_key, name, spread):
                label = f"{name} ({spread:+})"
                super().__init__(label=label, style=discord.ButtonStyle.success)
                self.team_key = team_key

            async def callback(self, i: discord.Interaction):
                await get_bet_amount(i, matchup_id, "spread", self.team_key)

    await interaction.response.send_message(embed=create_embed("📊 Choose Team", "Choose which spread to bet."), view=TeamSpread(), ephemeral=True)


async def show_ou_picker(interaction: discord.Interaction, matchup_id: str):
    matchup = load_json(MATCHUPS_FILE)[matchup_id]

    class OUButtons(View):
        def __init__(self):
            super().__init__(timeout=60)
            self.add_item(self.OUButton("over"))
            self.add_item(self.OUButton("under"))

        class OUButton(Button):
            def __init__(self, label):
                super().__init__(label=label.upper(), style=discord.ButtonStyle.success)
                self.label_val = label.lower()

            async def callback(self, i: discord.Interaction):
                await get_bet_amount(i, matchup_id, "ou", self.label_val)

    await interaction.response.send_message(embed=create_embed("📈 Bet Over/Under", f"Match O/U: {matchup['over_under']}"), view=OUButtons(), ephemeral=True)


async def get_bet_amount(interaction: discord.Interaction, matchup_id: str, bet_type: str, target: str):
    class AmountModal(Modal, title="Enter Bet Amount"):
        amount = TextInput(label="Amount to Bet", placeholder="e.g. 100", required=True)

        async def on_submit(self, modal_interaction: discord.Interaction):
            user = get_user(modal_interaction.user.id)
            try:
                bet_amount = int(self.amount.value)
                if bet_amount <= 0:
                    raise ValueError
            except:
                await modal_interaction.response.send_message(embed=create_embed("⚠️ Invalid Amount", "Please enter a positive number."), ephemeral=True)
                return

            if bet_amount > user["money"]:
                missing = bet_amount - user["money"]
                await modal_interaction.response.send_message(
                    embed=create_embed("🛑 Insufficient Funds", f"You are missing 💸{missing} to place this bet."),
                    ephemeral=True
                )
                return

            matchups = load_json(MATCHUPS_FILE)
            if matchup_id not in matchups:
                await modal_interaction.response.send_message(embed=create_embed("❌ Matchup not found."), ephemeral=True)
                return

            matchup = matchups[matchup_id]

            # Calculate dynamic payout multiplier based on total bet volume on the selected target
            bets_on_target = [b for b in matchup["bets"] if b["type"] == bet_type and b["target"] == target]
            total_on_target = sum(b["amount"] for b in bets_on_target)
            payout_multiplier = max(1.8 - (total_on_target / 1000), 1.1)  # Adjust odds based on bet volume

            payout = round(bet_amount * payout_multiplier)

            # Record the bet
            bet = {
                "user": modal_interaction.user.id,
                "amount": bet_amount,
                "type": bet_type,
                "target": target,
                "payout": payout
            }
            matchup["bets"].append(bet)
            save_json(MATCHUPS_FILE, matchups)

            # Deduct bet amount from user balance
            change_user_money(modal_interaction.user.id, -bet_amount)
            log_user_bet(modal_interaction.user.id, f"{datetime.utcnow().strftime('%m/%d %H:%M')} | {target.upper()} | {bet_type.upper()} | 💵{bet_amount}")

            await modal_interaction.response.send_message(
                embed=create_embed("✅ Bet Placed", f"You bet 💵{bet_amount} on **{target.upper()}** ({bet_type.upper()})\nPotential payout: 💵{payout}"),
                ephemeral=True
            )

    await interaction.response.send_modal(AmountModal())

print("Starting bot...")
keep_alive()
bot.run(TOKEN)
