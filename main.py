# main.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction
import json
import os
from datetime import datetime, timedelta
import asyncio

# -----------------------------
# CONFIGURATION & CONSTANTS
# -----------------------------
TOKEN = os.getenv("TOKENFORBOTHERE")
PREFIX = "!"
COOLDOWN_HOURS = 24
DAILY_CLAIM_AMOUNT = 25

DATA_FOLDER = "data"
USERS_FILE = os.path.join(DATA_FOLDER, "users.json")
MATCHUPS_FILE = os.path.join(DATA_FOLDER, "matchups.json")

# Bet types
BET_TYPES = ["Spread", "Over/Under", "Special", "Parlay"]

# Emojis & formatting for professional look
COIN_EMOJI = "💲"
WIN_EMOJI = "🏆"
LOSS_EMOJI = "❌"
PARLAY_EMOJI = "🎯"

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def load_json(file_path):
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            json.dump({}, f)
    with open(file_path, "r") as f:
        return json.load(f)

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

def get_user_data(user_id):
    users = load_json(USERS_FILE)
    if str(user_id) not in users:
        users[str(user_id)] = {
            "coins": 100,  # Starting coins
            "daily_claim": None,
            "bets": [],
            "wins": 0,
            "losses": 0
        }
        save_json(USERS_FILE, users)
    return users[str(user_id)]

def update_user_data(user_id, data):
    users = load_json(USERS_FILE)
    users[str(user_id)] = data
    save_json(USERS_FILE, users)

def get_matchups():
    return load_json(MATCHUPS_FILE)

def update_matchups(data):
    save_json(MATCHUPS_FILE, data)

# -----------------------------
# BOT SETUP
# -----------------------------
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# -----------------------------
# CHECK IF ADMIN
# -----------------------------
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

# -----------------------------
# BOT EVENTS
# -----------------------------
@bot.event
async def on_ready():
    print(f"{bot.user} is online!")
    await bot.tree.sync()
    print("Slash commands synced!")

# -----------------------------
# USER COMMAND: !betting
# -----------------------------
@bot.command()
async def betting(ctx):
    """Main betting menu"""
    embed = discord.Embed(
        title="📊 Betting Menu",
        description="Select an option below to place a bet or view information.",
        color=0x1abc9c
    )
    embed.add_field(name="💰 Claim Daily Coins", value="Use `/claim` to claim your daily 25 coins.", inline=False)
    embed.add_field(name="🎯 Place a Bet", value="Use `/place_bet` to bet on a matchup, O/U, Special, or Parlay.", inline=False)
    embed.add_field(name="📜 Betting History", value="View your history or someone else's with `/history`.", inline=False)
    embed.add_field(name="🏆 Leaderboard", value="View the top users by wins or coins with `/leaderboard`.", inline=False)
    
    await ctx.send(embed=embed)

# -----------------------------
# ADMIN COMMAND: !admincommands
# -----------------------------
@bot.command()
@is_admin()
async def admincommands(ctx):
    """Admin menu"""
    embed = discord.Embed(
        title="🛠 Admin Commands",
        description="Manage matchups, odds, and user accounts.",
        color=0xe74c3c
    )
    embed.add_field(name="➕ Create Matchup", value="`/create_matchup`", inline=False)
    embed.add_field(name="✅ Finish Matchup", value="`/finish_matchup`", inline=False)
    embed.add_field(name="❌ Delete Matchup", value="`/delete_matchup`", inline=False)
    embed.add_field(name="💰 Add/Remove Coins", value="`/modify_coins`", inline=False)
    embed.add_field(name="🗑 Delete User Bet", value="`/delete_bet`", inline=False)
    embed.add_field(name="🎯 Adjust Special Odds", value="`/adjust_odds`", inline=False)
    
    await ctx.send(embed=embed)

from discord.ui import View, Select, Button

# -----------------------------
# DAILY COIN CLAIM
# -----------------------------
@bot.tree.command(name="claim", description="Claim your daily coins!")
async def claim(interaction: Interaction):
    user_data = get_user_data(interaction.user.id)
    now = datetime.utcnow()

    if user_data["daily_claim"]:
        last_claim = datetime.fromisoformat(user_data["daily_claim"])
        if now - last_claim < timedelta(hours=COOLDOWN_HOURS):
            next_claim = last_claim + timedelta(hours=COOLDOWN_HOURS)
            embed = discord.Embed(
                title="⏳ Daily Claim",
                description=f"You've already claimed today! Next claim available at <t:{int(next_claim.timestamp())}:F>",
                color=0xe67e22
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    user_data["coins"] += DAILY_CLAIM_AMOUNT
    user_data["daily_claim"] = now.isoformat()
    update_user_data(interaction.user.id, user_data)

    embed = discord.Embed(
        title="💰 Daily Claim",
        description=f"You claimed {COIN_EMOJI}{DAILY_CLAIM_AMOUNT}! You now have {COIN_EMOJI}{user_data['coins']}.",
        color=0x1abc9c
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# -----------------------------
# PLACE BET COMMAND
# -----------------------------
@bot.tree.command(name="place_bet", description="Place a bet on a matchup, O/U, Special, or Parlay")
async def place_bet(interaction: Interaction):
    matchups = get_matchups()
    if not matchups:
        await interaction.response.send_message("No active matchups currently.", ephemeral=True)
        return

    # Dropdown options for active matchups
    options = []
    for mid, matchup in matchups.items():
        label = f"{matchup['team1']} vs {matchup['team2']}"
        description = f"Spread: {matchup['spread']} | O/U: {matchup['over_under']}"
        options.append(discord.SelectOption(label=label, description=description, value=mid))

    class MatchupSelect(View):
        def __init__(self):
            super().__init__(timeout=120)
            self.add_item(Select(
                placeholder="Select a matchup...",
                options=options,
                min_values=1,
                max_values=5  # Allow multiple selections for parlay
            ))

        @discord.ui.select()
        async def select_callback(self, select: Select, select_interaction: Interaction):
            selected_ids = select.values
            if len(selected_ids) > 1:
                bet_type = "Parlay"
            else:
                bet_type = "Single"
            # Store the selection for the next step
            await select_interaction.response.send_message(
                f"You selected {len(selected_ids)} matchup(s) for a {bet_type} bet. Next, select bet type (Spread/O/U/Special).",
                ephemeral=True
            )

    await interaction.response.send_message("Select matchup(s) for your bet:", view=MatchupSelect(), ephemeral=True)

# -----------------------------
# DYNAMIC MONEYLINE FUNCTION
# -----------------------------
def calculate_moneyline(matchup_id, team=None):
    """Adjust payout based on bet volume for spread or OU"""
    matchups = get_matchups()
    matchup = matchups[matchup_id]
    
    # Example: simple dynamic odds calculation
    total_bets = matchup.get("total_bets", {"team1": 0, "team2": 0, "over": 0, "under": 0})
    
    if team == "team1":
        if total_bets["team1"] == 0:
            return 2.0  # Base payout
        return max(1.1, (total_bets["team2"]+1)/ (total_bets["team1"]+1) + 1)
    elif team == "team2":
        if total_bets["team2"] == 0:
            return 2.0
        return max(1.1, (total_bets["team1"]+1)/ (total_bets["team2"]+1) + 1)
    else:  # Over/Under
        return 1.9  # placeholder

from discord.ui import Modal, TextInput

# -----------------------------
# BET TYPE SELECTION VIEW
# -----------------------------
class BetTypeSelect(View):
    def __init__(self, matchup_ids):
        super().__init__(timeout=120)
        self.matchup_ids = matchup_ids
        self.add_item(Select(
            placeholder="Select bet type...",
            options=[discord.SelectOption(label=bt) for bt in BET_TYPES if bt != "Parlay"],
            min_values=1,
            max_values=1
        ))

    @discord.ui.select()
    async def select_callback(self, select: Select, interaction: Interaction):
        bet_type = select.values[0]
        # Proceed to amount input modal
        await interaction.response.send_modal(BetAmountModal(self.matchup_ids, bet_type))


# -----------------------------
# BET AMOUNT MODAL
# -----------------------------
class BetAmountModal(Modal):
    def __init__(self, matchup_ids, bet_type):
        super().__init__(title="Enter Bet Amount")
        self.matchup_ids = matchup_ids
        self.bet_type = bet_type
        self.add_item(TextInput(label="Bet Amount", placeholder="Enter number of coins...", required=True))

    async def on_submit(self, interaction: Interaction):
        try:
            amount = int(self.children[0].value)
        except ValueError:
            await interaction.response.send_message("Invalid number entered.", ephemeral=True)
            return

        user_data = get_user_data(interaction.user.id)
        if amount > user_data["coins"]:
            await interaction.response.send_message("You do not have enough coins!", ephemeral=True)
            return

        # Deduct coins
        user_data["coins"] -= amount

        # Determine moneyline/payout for each selected matchup
        payouts = []
        for mid in self.matchup_ids:
            if len(self.matchup_ids) > 1:
                # Parlay calculation
                payouts.append(calculate_moneyline(mid))
            else:
                payouts.append(calculate_moneyline(mid))

        if len(self.matchup_ids) > 1:
            bet_type_final = "Parlay"
            combined_payout = 1
            for p in payouts:
                combined_payout *= p
            payout_text = f"{combined_payout:.2f}x"
        else:
            bet_type_final = self.bet_type
            payout_text = f"{payouts[0]:.2f}x"

        # Store bet in user data
        user_data["bets"].append({
            "matchups": self.matchup_ids,
            "bet_type": bet_type_final,
            "amount": amount,
            "payout": payout_text,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "active"
        })
        update_user_data(interaction.user.id, user_data)

        # Confirmation embed
        embed = discord.Embed(
            title=f"{PARLAY_EMOJI if bet_type_final=='Parlay' else ''} Bet Placed!",
            color=0x1abc9c
        )
        embed.add_field(name="User", value=interaction.user.mention, inline=False)
        embed.add_field(name="Bet Type", value=bet_type_final, inline=False)
        embed.add_field(name="Matchups", value=", ".join(self.matchup_ids), inline=False)
        embed.add_field(name="Amount", value=f"{COIN_EMOJI}{amount}", inline=True)
        embed.add_field(name="Potential Payout", value=payout_text, inline=True)
        embed.set_footer(text="Good luck!")

        await interaction.response.send_message(embed=embed, ephemeral=True)

# -----------------------------
# VIEW ALL MATCHUPS
# -----------------------------
@bot.tree.command(name="view_matchups", description="View all active matchups")
async def view_matchups(interaction: Interaction):
    matchups = get_matchups()
    if not matchups:
        await interaction.response.send_message("No active matchups currently.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 Active Matchups",
        color=0x3498db
    )
    for mid, matchup in matchups.items():
        spread = matchup.get("spread", "N/A")
        over_under = matchup.get("over_under", "N/A")
        embed.add_field(
            name=f"{matchup['team1']} vs {matchup['team2']} (ID: {mid})",
            value=f"Spread: {spread} | O/U: {over_under}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# -----------------------------
# VIEW USER BETTING HISTORY
# -----------------------------
@bot.tree.command(name="history", description="View your betting history or someone else's")
@app_commands.describe(user="Optional: User to view history for")
async def history(interaction: Interaction, user: discord.User = None):
    target = user or interaction.user
    user_data = get_user_data(target.id)
    bets = user_data.get("bets", [])
    
    if not bets:
        await interaction.response.send_message(f"No betting history for {target.mention}.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📜 Betting History - {target.display_name}",
        color=0x9b59b6
    )
    for b in bets[-10:]:  # Show last 10 bets
        status = b.get("status", "active")
        matchups_text = ", ".join(b["matchups"])
        embed.add_field(
            name=f"{b['bet_type']} - {COIN_EMOJI}{b['amount']} ({status})",
            value=f"Matchups: {matchups_text} | Potential Payout: {b['payout']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# -----------------------------
# VIEW LEADERBOARD
# -----------------------------
@bot.tree.command(name="leaderboard", description="View top users by wins or coins")
@app_commands.describe(sort_by="Sort leaderboard by 'coins' or 'wins'")
async def leaderboard(interaction: Interaction, sort_by: str = "wins"):
    users = load_json(USERS_FILE)
    if sort_by not in ["wins", "coins"]:
        sort_by = "wins"
    
    sorted_users = sorted(users.items(), key=lambda x: x[1].get(sort_by, 0), reverse=True)
    embed = discord.Embed(
        title=f"🏆 Leaderboard ({sort_by.capitalize()})",
        color=0xf1c40f
    )

    for i, (uid, data) in enumerate(sorted_users[:10], start=1):
        user_obj = interaction.guild.get_member(int(uid))
        name = user_obj.display_name if user_obj else f"User ID: {uid}"
        embed.add_field(
            name=f"{i}. {name}",
            value=f"{COIN_EMOJI}{data.get('coins',0)} | Wins: {data.get('wins',0)} | Losses: {data.get('losses',0)}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# -----------------------------
# CREATE MATCHUP
# -----------------------------
@bot.tree.command(name="create_matchup", description="Admin: Create a new matchup")
@is_admin()
@app_commands.describe(team1="Home team", team2="Away team", spread="Point spread for team1", over_under="Over/Under total points")
async def create_matchup(interaction: Interaction, team1: str, team2: str, spread: float, over_under: float):
    matchups = get_matchups()
    matchup_id = str(len(matchups) + 1)
    matchups[matchup_id] = {
        "team1": team1,
        "team2": team2,
        "spread": spread,
        "over_under": over_under,
        "specials": {},
        "total_bets": {"team1": 0, "team2": 0, "over": 0, "under": 0},
        "status": "active"
    }
    update_matchups(matchups)
    await interaction.response.send_message(f"✅ Matchup created: {team1} vs {team2} (ID: {matchup_id})", ephemeral=True)


# -----------------------------
# FINISH MATCHUP (Resolve Bets)
# -----------------------------
@bot.tree.command(name="finish_matchup", description="Admin: Finish a matchup and resolve bets")
@is_admin()
@app_commands.describe(matchup_id="ID of the matchup", score1="Final score for team1", score2="Final score for team2")
async def finish_matchup(interaction: Interaction, matchup_id: str, score1: int, score2: int):
    matchups = get_matchups()
    if matchup_id not in matchups:
        await interaction.response.send_message("Matchup ID not found.", ephemeral=True)
        return

    matchup = matchups[matchup_id]
    matchup["status"] = "finished"
    update_matchups(matchups)

    # Resolve user bets
    users = load_json(USERS_FILE)
    for uid, data in users.items():
        for bet in data.get("bets", []):
            if bet["status"] != "active":
                continue
            if matchup_id not in bet["matchups"]:
                continue

            # Example: resolve Spread bet
            team1_spread = matchup["spread"]
            if bet["bet_type"] in ["Spread", "Parlay"]:
                if score1 - score2 > team1_spread:
                    win = True
                else:
                    win = False
            else:
                win = False  # TODO: add O/U and Special resolution

            if win:
                multiplier = float(bet["payout"].replace("x", ""))
                winnings = int(bet["amount"] * multiplier)
                data["coins"] += winnings
                data["wins"] += 1
                bet["status"] = "won"
            else:
                data["losses"] += 1
                bet["status"] = "lost"

        users[uid] = data
    save_json(USERS_FILE, users)

    await interaction.response.send_message(f"✅ Matchup {matchup['team1']} vs {matchup['team2']} finished and bets resolved.", ephemeral=True)


# -----------------------------
# DELETE MATCHUP
# -----------------------------
@bot.tree.command(name="delete_matchup", description="Admin: Delete a matchup")
@is_admin()
@app_commands.describe(matchup_id="ID of the matchup to delete")
async def delete_matchup(interaction: Interaction, matchup_id: str):
    matchups = get_matchups()
    if matchup_id in matchups:
        del matchups[matchup_id]
        update_matchups(matchups)
        await interaction.response.send_message(f"✅ Matchup {matchup_id} deleted.", ephemeral=True)
    else:
        await interaction.response.send_message("Matchup ID not found.", ephemeral=True)


# -----------------------------
# MODIFY USER COINS
# -----------------------------
@bot.tree.command(name="modify_coins", description="Admin: Add or remove coins from a user")
@is_admin()
@app_commands.describe(user="User to modify", amount="Amount of coins to add or remove (+/-)")
async def modify_coins(interaction: Interaction, user: discord.User, amount: int):
    data = get_user_data(user.id)
    data["coins"] += amount
    if data["coins"] < 0:
        data["coins"] = 0
    update_user_data(user.id, data)
    await interaction.response.send_message(f"✅ {user.mention} now has {COIN_EMOJI}{data['coins']} coins.", ephemeral=True)


# -----------------------------
# DELETE USER BET
# -----------------------------
@bot.tree.command(name="delete_bet", description="Admin: Delete a user's active bet")
@is_admin()
@app_commands.describe(user="User", bet_index="Index of bet to delete (from /history)")
async def delete_bet(interaction: Interaction, user: discord.User, bet_index: int):
    data = get_user_data(user.id)
    if bet_index < 1 or bet_index > len(data.get("bets", [])):
        await interaction.response.send_message("Invalid bet index.", ephemeral=True)
        return
    deleted_bet = data["bets"].pop(bet_index - 1)
    update_user_data(user.id, data)
    await interaction.response.send_message(f"✅ Deleted bet: {deleted_bet['bet_type']} for {user.mention}.", ephemeral=True)


# -----------------------------
# ADJUST SPECIAL ODDS
# -----------------------------
@bot.tree.command(name="adjust_odds", description="Admin: Adjust odds for special bets")
@is_admin()
@app_commands.describe(matchup_id="ID of the matchup", special_name="Name of the special", new_odds="New payout multiplier")
async def adjust_odds(interaction: Interaction, matchup_id: str, special_name: str, new_odds: float):
    matchups = get_matchups()
    if matchup_id not in matchups:
        await interaction.response.send_message("Matchup ID not found.", ephemeral=True)
        return

    matchups[matchup_id]["specials"][special_name] = new_odds
    update_matchups(matchups)
    await interaction.response.send_message(f"✅ Special odds for {special_name} updated to {new_odds}x.", ephemeral=True)

# -----------------------------
# CALCULATE WINNER FOR A BET
# -----------------------------
def resolve_single_bet(bet, matchup):
    """Determine if a single bet is won or lost"""
    score1 = matchup.get("final_score1")
    score2 = matchup.get("final_score2")
    spread = matchup.get("spread")
    over_under = matchup.get("over_under")
    special_odds = matchup.get("specials", {})

    bet_type = bet["bet_type"]
    result = False

    if bet_type == "Spread":
        if "team1" in bet.get("team_choice", ""):
            result = (score1 - score2) > spread
        else:
            result = (score2 - score1) > -spread

    elif bet_type == "Over/Under":
        total = score1 + score2
        if bet.get("team_choice") == "over":
            result = total > over_under
        else:
            result = total < over_under

    elif bet_type == "Special":
        special = bet.get("special_name")
        result = bet.get("team_choice") == matchup.get("specials_results", {}).get(special)

    return result


# -----------------------------
# FINISH MATCHUP (Updated for All Bets)
# -----------------------------
async def finish_matchup_full(interaction: Interaction, matchup_id: str, score1: int, score2: int):
    matchups = get_matchups()
    if matchup_id not in matchups:
        await interaction.response.send_message("Matchup ID not found.", ephemeral=True)
        return

    matchup = matchups[matchup_id]
    matchup["status"] = "finished"
    matchup["final_score1"] = score1
    matchup["final_score2"] = score2
    update_matchups(matchups)

    users = load_json(USERS_FILE)
    for uid, data in users.items():
        for bet in data.get("bets", []):
            if bet["status"] != "active":
                continue
            if matchup_id not in bet["matchups"]:
                continue

            # Multi-leg Parlay handling
            if bet["bet_type"] == "Parlay":
                parlay_win = True
                combined_multiplier = 1
                for mid in bet["matchups"]:
                    m = matchups.get(mid)
                    if not m:
                        continue
                    win = resolve_single_bet(bet, m)
                    if not win:
                        parlay_win = False
                        break
                    combined_multiplier *= float(bet["payout"].replace("x",""))
                if parlay_win:
                    winnings = int(bet["amount"] * combined_multiplier)
                    data["coins"] += winnings
                    data["wins"] += 1
                    bet["status"] = "won"
                else:
                    data["losses"] += 1
                    bet["status"] = "lost"

            else:
                win = resolve_single_bet(bet, matchup)
                if win:
                    multiplier = float(bet["payout"].replace("x",""))
                    winnings = int(bet["amount"] * multiplier)
                    data["coins"] += winnings
                    data["wins"] += 1
                    bet["status"] = "won"
                else:
                    data["losses"] += 1
                    bet["status"] = "lost"

        users[uid] = data
    save_json(USERS_FILE, users)

    await interaction.response.send_message(f"✅ Matchup {matchup['team1']} vs {matchup['team2']} resolved. All bets updated.", ephemeral=True)


# -----------------------------
# DYNAMIC MONEYLINE UPDATE (Based on Bet Volume)
# -----------------------------
def update_moneyline(matchup_id):
    matchups = get_matchups()
    matchup = matchups.get(matchup_id)
    if not matchup:
        return

    total_bets = matchup.get("total_bets", {"team1": 0, "team2": 0, "over": 0, "under": 0})
    team1_bets = total_bets["team1"] + 1
    team2_bets = total_bets["team2"] + 1
    matchup["moneyline"] = {
        "team1": max(1.1, (team2_bets / team1_bets) + 1),
        "team2": max(1.1, (team1_bets / team2_bets) + 1)
    }
    matchups[matchup_id] = matchup
    update_matchups(matchups)

# -----------------------------
# BET CONFIRMATION EMBED POLISH
# -----------------------------
def create_bet_embed(user, bet):
    embed = discord.Embed(
        title=f"{PARLAY_EMOJI if bet['bet_type']=='Parlay' else '🎯'} Bet Placed!",
        color=0x1abc9c,
        timestamp=datetime.utcnow()
    )
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.add_field(name="Bet Type", value=bet['bet_type'], inline=False)
    embed.add_field(name="Matchups", value=", ".join(bet['matchups']), inline=False)
    embed.add_field(name="Amount", value=f"{COIN_EMOJI}{bet['amount']}", inline=True)
    embed.add_field(name="Potential Payout", value=bet['payout'], inline=True)
    embed.set_footer(text="Good luck!")
    return embed


# -----------------------------
# SPECIAL BETS EXAMPLE: HEISMAN & FIRST TD
# -----------------------------
@bot.tree.command(name="place_special", description="Place a special bet (Heisman, First TD, etc.)")
async def place_special(interaction: Interaction, matchup_id: str, special_name: str, player_name: str, amount: int):
    user_data = get_user_data(interaction.user.id)
    matchups = get_matchups()

    if matchup_id not in matchups:
        await interaction.response.send_message("Matchup not found.", ephemeral=True)
        return

    if amount > user_data["coins"]:
        await interaction.response.send_message("You do not have enough coins.", ephemeral=True)
        return

    user_data["coins"] -= amount
    payout = matchups[matchup_id]["specials"].get(special_name, 2.0)

    user_data["bets"].append({
        "matchups": [matchup_id],
        "bet_type": "Special",
        "amount": amount,
        "payout": f"{payout}x",
        "team_choice": player_name,
        "special_name": special_name,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "active"
    })
    update_user_data(interaction.user.id, user_data)

    embed = discord.Embed(
        title=f"🎖 Special Bet Placed!",
        description=f"{interaction.user.mention} bet {COIN_EMOJI}{amount} on {player_name} for {special_name} (Payout: {payout}x)",
        color=0x9b59b6,
        timestamp=datetime.utcnow()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# -----------------------------
# COOLDOWNS & ERROR HANDLING
# -----------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You do not have permission to use this command.", ephemeral=True)
    else:
        await ctx.send(f"⚠ Error: {str(error)}", ephemeral=True)


# -----------------------------
# INTERACTIVE LEADERBOARD (OPTIONAL POLISH)
# -----------------------------
class LeaderboardSelect(View):
    def __init__(self):
        super().__init__()
        self.add_item(Select(
            placeholder="Sort leaderboard by...",
            options=[
                discord.SelectOption(label="Wins", value="wins"),
                discord.SelectOption(label="Coins", value="coins")
            ],
            min_values=1,
            max_values=1
        ))

    @discord.ui.select()
    async def select_callback(self, select: Select, interaction: Interaction):
        sort_by = select.values[0]
        users = load_json(USERS_FILE)
        sorted_users = sorted(users.items(), key=lambda x: x[1].get(sort_by,0), reverse=True)
        embed = discord.Embed(title=f"🏆 Leaderboard ({sort_by.capitalize()})", color=0xf1c40f)
        for i, (uid, data) in enumerate(sorted_users[:10], start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User ID: {uid}"
            embed.add_field(
                name=f"{i}. {name}",
                value=f"{COIN_EMOJI}{data.get('coins',0)} | Wins: {data.get('wins',0)} | Losses: {data.get('losses',0)}",
                inline=False
            )
        await interaction.response.edit_message(embed=embed, view=self)


@bot.tree.command(name="interactive_leaderboard", description="View leaderboard with interactive sorting")
async def interactive_leaderboard(interaction: Interaction):
    view = LeaderboardSelect()
    await interaction.response.send_message("Select sorting method for leaderboard:", view=view, ephemeral=True)

bot.run(TOKEN)
