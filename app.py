import discord
from discord.ext import commands, tasks
import requests
import mysql.connector
import asyncio
import os
from dotenv import load_dotenv

# =====================
# ENV + VALIDATION
# =====================
load_dotenv()

def get_env_var(key: str, cast=str, required=True):
    value = os.getenv(key)
    if required and (value is None or value.strip() == ""):
        raise ValueError(f"❌ Missing required environment variable: {key}")
    try:
        return cast(value) if value is not None else None
    except Exception:
        raise ValueError(f"❌ Invalid value for {key}, expected {cast.__name__}")

TOKEN = get_env_var("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")  # Default to "!" if not set
GUILD_ID = get_env_var("GUILD_ID", int)
REQUIRED_ROLE_IDS = [int(x) for x in get_env_var("REQUIRED_ROLE_IDS").split(",")]
ADMIN_ROLE_IDS = [int(x) for x in get_env_var("ADMIN_ROLE_IDS").split(",")]
SYNC_LOG_CHANNEL_ID = get_env_var("SYNC_LOG_CHANNEL_ID", int)

JELLYFIN_URL = get_env_var("JELLYFIN_URL")
JELLYFIN_API_KEY = get_env_var("JELLYFIN_API_KEY")

DB_HOST = get_env_var("DB_HOST")
DB_USER = get_env_var("DB_USER")
DB_PASSWORD = get_env_var("DB_PASSWORD")
DB_NAME = get_env_var("DB_NAME")

# =====================
# DISCORD SETUP
# =====================
intents = discord.Intents.all()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# =====================
# DATABASE SETUP
# =====================
def init_db():
    # Existing DB creation
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD
    )
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
    conn.commit()
    cur.close()
    conn.close()

    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            discord_id BIGINT PRIMARY KEY,
            jellyfin_username VARCHAR(255) NOT NULL
        )
    """)
    # New table for metadata
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_metadata (
            key_name VARCHAR(255) PRIMARY KEY,
            value VARCHAR(255) NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def add_account(discord_id, jellyfin_username):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("REPLACE INTO accounts (discord_id, jellyfin_username) VALUES (%s, %s)",
                (discord_id, jellyfin_username))
    conn.commit()
    cur.close()
    conn.close()

def get_accounts():
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT discord_id, jellyfin_username FROM accounts")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_account_by_jellyfin(username):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT discord_id FROM accounts WHERE jellyfin_username=%s", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def get_account_by_discord(discord_id):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT jellyfin_username FROM accounts WHERE discord_id=%s", (discord_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def delete_account(discord_id):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("DELETE FROM accounts WHERE discord_id=%s", (discord_id,))
    conn.commit()
    cur.close()
    conn.close()

# =====================
# JELLYFIN HELPERS
# =====================
def create_jellyfin_user(username, password):
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    data = {"Name": username, "Password": password}
    r = requests.post(f"{JELLYFIN_URL}/Users/New", json=data, headers=headers)
    return r.status_code == 200

def get_jellyfin_user(username):
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    r = requests.get(f"{JELLYFIN_URL}/Users", headers=headers)
    if r.status_code == 200:
        for u in r.json():
            if u["Name"].lower() == username.lower():
                return u["Id"]
    return None

def delete_jellyfin_user(username):
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    user_id = get_jellyfin_user(username)
    if user_id:
        r = requests.delete(f"{JELLYFIN_URL}/Users/{user_id}", headers=headers)
        return r.status_code in (200, 204)
    return True

def reset_jellyfin_password(username: str, new_password: str) -> bool:
    user_id = get_jellyfin_user(username)
    if not user_id:
        return False
    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    data = {"Password": new_password}
    response = requests.post(f"{JELLYFIN_URL}/Users/{user_id}/Password", headers=headers, json=data)
    return response.status_code in (200, 204)

# =====================
# DISCORD HELPERS
# =====================
def has_required_role(member):
    return any(role.id in REQUIRED_ROLE_IDS for role in member.roles)

def has_admin_role(member):
    return any(role.id in ADMIN_ROLE_IDS for role in member.roles)

# =====================
# BOT HELPERS
# =====================

def set_metadata(key, value):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("""
        REPLACE INTO bot_metadata (key_name, value) VALUES (%s, %s)
    """, (key, str(value)))
    conn.commit()
    cur.close()
    conn.close()

def get_metadata(key):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_metadata WHERE key_name=%s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

# =====================
# EVENTS
# =====================
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        instructions = (
            f"👋 Hi {message.author.mention}!\n\n"
            "To create a Jellyfin account, please DM me the following command:\n"
            f"`{PREFIX}createaccount <username> <password>`\n\n"
            "To reset your password, DM me:\n"
            f"`{PREFIX}recoveraccount <username> <newpassword>`\n\n"
            f"Make sure you have the required server role(s) to create an account."
        )
        await message.channel.send(instructions)

    await bot.process_commands(message)

# =====================
# COMMANDS
# =====================
@bot.command()
async def createaccount(ctx, username: str, password: str):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} Please DM me to create your Jellyfin account.")
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(ctx.author.id)

    if not member or not has_required_role(member):
        await ctx.send("❌ You don’t have the required role to create an account.")
        return

    if get_account_by_discord(ctx.author.id):
        await ctx.send("❌ You already have a Jellyfin account.")
        return

    if create_jellyfin_user(username, password):
        add_account(ctx.author.id, username)
        await ctx.send(f"✅ Account created! You can log in at {JELLYFIN_URL}")
    else:
        await ctx.send("❌ Failed to create account. Username may already exist.")

@bot.command()
async def recoveraccount(ctx, new_password: str):
    """DM-only: reset your Jellyfin password"""
    # Ensure it's a DM
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} Please DM me to reset your password.")
        return

    # Fetch the Jellyfin account linked to this Discord user
    acc = get_account_by_discord(ctx.author.id)
    if not acc:
        await ctx.send("❌ You do not have a linked Jellyfin account.")
        return

    username = acc[0]  # the Jellyfin username

    # Reset the password
    if reset_jellyfin_password(username, new_password):
        await ctx.send(
            f"✅ Your Jellyfin password for **{username}** has been reset!\n"
            f"🌐 Login here: {JELLYFIN_URL}"
        )
    else:
        await ctx.send(f"❌ Failed to reset password for **{username}**. Please contact an admin.")

@bot.command()
async def deleteaccount(ctx, username: str):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} Please DM me to delete your Jellyfin account.")
        return

    acc = get_account_by_discord(ctx.author.id)
    if not acc or acc[0].lower() != username.lower():
        await ctx.send("❌ That Jellyfin account is not linked to your Discord user.")
        return

    if delete_jellyfin_user(username):
        delete_account(ctx.author.id)
        await ctx.send("✅ Account deleted.")
    else:
        await ctx.send("❌ Failed to delete account.")

@bot.command()
async def cleanup(ctx):
    guild = bot.get_guild(GUILD_ID)
    removed = []
    for discord_id, jf_username in get_accounts():
        m = guild.get_member(discord_id)
        if m is None or not has_required_role(m):
            if delete_jellyfin_user(jf_username):
                delete_account(discord_id)
                removed.append(jf_username)

    log_channel = bot.get_channel(SYNC_LOG_CHANNEL_ID)
    if removed and log_channel:
        await log_channel.send(f"🧹 Removed {len(removed)} Jellyfin accounts: {', '.join(removed)}")

    await ctx.send("✅ Cleanup complete.")

@bot.command()
async def lastcleanup(ctx):
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to view the last cleanup.")
        return

    last_run = get_metadata("last_cleanup")
    if not last_run:
        await ctx.send("ℹ️ No cleanup has been run yet.")
        return

    last_run_dt = datetime.datetime.fromisoformat(last_run)
    now = datetime.datetime.utcnow()
    next_run_dt = last_run_dt + datetime.timedelta(hours=24)
    time_remaining = next_run_dt - now

    hours, remainder = divmod(int(time_remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    await ctx.send(
        f"🧹 Last cleanup ran at **{last_run_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC**\n"
        f"⏳ Time until next cleanup: {hours}h {minutes}m {seconds}s"
    )


@bot.command()
async def searchaccount(ctx, username: str):
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    result = get_account_by_jellyfin(username)
    if result:
        discord_id = result[0]
        user = await bot.fetch_user(discord_id)
        await ctx.send(f"🔍 Jellyfin account **{username}** is linked to Discord user {user.mention}.")
    else:
        await ctx.send("❌ No linked Discord user found for that Jellyfin account.")

@bot.command()
async def searchdiscord(ctx, user: discord.User):
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    result = get_account_by_discord(user.id)
    if result:
        await ctx.send(f"🔍 Discord user {user.mention} is linked to Jellyfin account **{result[0]}**.")
    else:
        await ctx.send("❌ That Discord user does not have a linked Jellyfin account.")

@bot.command()
async def scanlibraries(ctx):
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    response = requests.post(f"{JELLYFIN_URL}/Library/Refresh", headers=headers)
    if response.status_code in (200, 204):
        await ctx.send("✅ All Jellyfin libraries are being scanned.")
    else:
        await ctx.send(f"❌ Failed to start library scan. Status code: {response.status_code}")

@bot.command()
async def link(ctx, jellyfin_username: str, user: discord.User):
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    add_account(user.id, jellyfin_username)
    await ctx.send(f"✅ Linked Jellyfin account **{jellyfin_username}** to {user.mention}.")

@bot.command()
async def unlink(ctx, discord_user: discord.User):
    """Admin-only: unlink a Jellyfin account from a Discord user (without deleting the account)"""
    guild = ctx.guild
    member = guild.get_member(ctx.author.id) if guild else None

    if not member or not has_admin_role(member):
        await ctx.send(f"❌ {ctx.author.mention}, you don’t have permission to use this command.")
        return

    # Check if the Discord user has a linked Jellyfin account
    account = get_account_by_discord(discord_user.id)
    if not account:
        await ctx.send(f"❌ Discord user {discord_user.mention} does not have a linked Jellyfin account.")
        return

    # Remove the database entry
    delete_account(discord_user.id)
    await ctx.send(f"✅ Unlinked Jellyfin account **{account[0]}** from Discord user {discord_user.mention}.")

@bot.command()
async def setprefix(ctx, new_prefix: str):
    """Admin-only: change the bot command prefix"""
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    global PREFIX
    PREFIX = new_prefix
    bot.command_prefix = PREFIX  # Update bot prefix dynamically

    # Update .env file
    env_file = ".env"
    lines = []
    with open(env_file, "r") as f:
        for line in f:
            if line.startswith("PREFIX="):
                lines.append(f"PREFIX={PREFIX}\n")
            else:
                lines.append(line)
    with open(env_file, "w") as f:
        f.writelines(lines)

    await ctx.send(f"✅ Command prefix has been updated to `{PREFIX}`")

@bot.command(name="help")
async def help_command(ctx):
    member = ctx.guild.get_member(ctx.author.id)
    is_admin = has_admin_role(member)

    embed = discord.Embed(
        title="📖 Jellyfin Bot Help",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )

    embed.add_field(name="User Commands", value=(
        f"`{PREFIX}createaccount <username> <password>` - Create your Jellyfin account\n"
        f"`{PREFIX}recoveraccount <newpassword>` - Reset your password\n"
        f"`{PREFIX}deleteaccount <username>` - Delete your Jellyfin account\n"
    ), inline=False)

    if is_admin:
        embed.add_field(name="Admin Commands", value=(
            f"`{PREFIX}cleanup` - Remove Jellyfin accounts from users without roles\n"
            f"`{PREFIX}lastcleanup` - See Last cleanup time, and time remaining before next cleanup\n"
            f"`{PREFIX}searchaccount <jellyfin_username>` - Find linked Discord user\n"
            f"`{PREFIX}searchdiscord @user` - Find linked Jellyfin account\n"
            f"`{PREFIX}scanlibraries` - Scan all Jellyfin libraries\n"
            f"`{PREFIX}link <jellyfin_username> @user` - Manually link accounts\n"
            f"`{PREFIX}unlink @user` - Manually unlink accounts\n"
        ), inline=False)
        embed.add_field(name="Admin Bot Commands", value=(
            f"`{PREFIX}setprefix` - Change the bots command prefix\n"
        ), inline=False)

    await ctx.send(embed=embed)

# =====================
# TASKS
# =====================
import datetime

@tasks.loop(hours=24)
async def daily_check():
    guild = bot.get_guild(GUILD_ID)
    removed = []

    for discord_id, jf_username in get_accounts():
        m = guild.get_member(discord_id)
        if m is None or not has_required_role(m):
            if delete_jellyfin_user(jf_username):
                delete_account(discord_id)
                removed.append(jf_username)

    if removed:
        print(f"Daily cleanup: removed {len(removed)} accounts: {removed}")

    # Log last run timestamp
    set_metadata("last_cleanup", datetime.datetime.utcnow().isoformat())


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    init_db()

    # Check last cleanup
    last_run = get_metadata("last_cleanup")
    if last_run:
        last_run_dt = datetime.datetime.fromisoformat(last_run)
        now = datetime.datetime.utcnow()
        delta = now - last_run_dt
        if delta.total_seconds() >= 24 * 3600:
            print("Running missed daily cleanup...")
            await daily_check()  # Run immediately if overdue

    daily_check.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{PREFIX}help"))

bot.run(TOKEN)
