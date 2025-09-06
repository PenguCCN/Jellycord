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

JELLYSEERR_ENABLED = os.getenv("JELLYSEERR_ENABLED", "false").lower() == "true"
JELLYSEERR_URL = os.getenv("JELLYSEERR_URL", "").rstrip("/")
JELLYSEERR_API_KEY = os.getenv("JELLYSEERR_API_KEY", "")

DB_HOST = get_env_var("DB_HOST")
DB_USER = get_env_var("DB_USER")
DB_PASSWORD = get_env_var("DB_PASSWORD")
DB_NAME = get_env_var("DB_NAME")

BOT_VERSION = "1.0.1"
VERSION_URL = "https://raw.githubusercontent.com/PenguCCN/Jellyfin-Discord/main/version.txt"
RELEASES_URL = "https://github.com/PenguCCN/Jellyfin-Discord/releases"

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
    # Create database if it doesn't exist
    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
    conn.commit()
    cur.close()
    conn.close()

    # Connect to the database
    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
    cur = conn.cursor()

    # Create accounts table if it doesn't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            discord_id BIGINT PRIMARY KEY,
            jellyfin_username VARCHAR(255) NOT NULL,
            jellyfin_id VARCHAR(255) NOT NULL,
            jellyseerr_id VARCHAR(255) DEFAULT NULL
        )
    """)

    # Ensure jellyfin_id exists
    cur.execute("SHOW COLUMNS FROM accounts LIKE 'jellyfin_id'")
    if cur.fetchone() is None:
        cur.execute("ALTER TABLE accounts ADD COLUMN jellyfin_id VARCHAR(255) NOT NULL")
        print("[DB] Added missing column 'jellyfin_id' to accounts table.")

    # Ensure jellyseerr_id exists
    cur.execute("SHOW COLUMNS FROM accounts LIKE 'jellyseerr_id'")
    if cur.fetchone() is None:
        cur.execute("ALTER TABLE accounts ADD COLUMN jellyseerr_id VARCHAR(255) DEFAULT NULL")
        print("[DB] Added missing column 'jellyseerr_id' to accounts table.")

    # Create bot_metadata table if it doesn't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_metadata (
            key_name VARCHAR(255) PRIMARY KEY,
            value VARCHAR(255) NOT NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


def add_account(discord_id, username, jf_id, js_id=None):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute(
        "REPLACE INTO accounts (discord_id, jellyfin_username, jellyfin_id, jellyseerr_id) VALUES (%s, %s, %s, %s)",
        (discord_id, username, jf_id, js_id)
    )
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
    cur.execute(
        "SELECT jellyfin_username, jellyfin_id, jellyseerr_id FROM accounts WHERE discord_id=%s",
        (discord_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # (jellyfin_username, jellyfin_id, jellyseerr_id)


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
# JELLYSEERR HELPERS
# =====================

def import_jellyseerr_user(jellyfin_user_id: str) -> str:
    """Import user into Jellyseerr. Returns the Jellyseerr user ID if successful, else None."""
    if not JELLYSEERR_ENABLED:
        return None
    headers = {"X-Api-Key": JELLYSEERR_API_KEY, "Content-Type": "application/json"}
    data = {"jellyfinUserIds": [jellyfin_user_id]}
    try:
        url = f"{JELLYSEERR_URL}/api/v1/user/import-from-jellyfin"
        r = requests.post(url, headers=headers, json=data, timeout=15)
        if r.status_code in (200, 201):
            js_user = r.json()
            if isinstance(js_user, list) and len(js_user) > 0 and "id" in js_user[0]:
                js_id = js_user[0]["id"]
                print(f"[Jellyseerr] User {jellyfin_user_id} imported successfully with Jellyseerr ID {js_id}.")
                return js_id
        print(f"[Jellyseerr] Import failed. Status: {r.status_code}, Response: {r.text}")
        return None
    except Exception as e:
        print(f"[Jellyseerr] Failed to import user: {e}")
        return None



def delete_jellyseerr_user(username: str) -> bool:
    if not JELLYSEERR_ENABLED:
        return True
    headers = {"X-Api-Key": JELLYSEERR_API_KEY}
    try:
        # First fetch users to find matching ID
        r = requests.get(f"{JELLYSEERR_URL}/api/v1/user", headers=headers, timeout=10)
        if r.status_code != 200:
            return False
        users = r.json()
        for u in users:
            if u.get("username", "").lower() == username.lower():
                user_id = u["id"]
                dr = requests.delete(f"{JELLYSEERR_URL}/api/v1/user/{user_id}", headers=headers, timeout=10)
                return dr.status_code in (200, 204)
        return True  # no user found, nothing to delete
    except Exception as e:
        print(f"[Jellyseerr] Failed to delete user {username}: {e}")
        return False

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
    # DM-only
    if not isinstance(ctx.channel, discord.DMChannel):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.send(f"{ctx.author.mention} ❌ Please DM me to create your Jellyfin account.")
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(ctx.author.id) if guild else None

    if not member or not has_required_role(member):
        await ctx.send(f"❌ {ctx.author.mention}, you don’t have the required role.")
        return

    if get_account_by_discord(ctx.author.id):
        await ctx.send(f"❌ {ctx.author.mention}, you already have a Jellyfin account.")
        return

    # Create Jellyfin user
    if create_jellyfin_user(username, password):
        jf_id = get_jellyfin_user(username)
        if not jf_id:
            await ctx.send(f"❌ Failed to fetch Jellyfin ID for **{username}**. Please contact an admin.")
            return

        js_id = None
        # Import to Jellyseerr if enabled
        if JELLYSEERR_ENABLED:
            js_id = import_jellyseerr_user(jf_id)

        # Store account in DB
        add_account(ctx.author.id, username, jf_id, js_id)

        if JELLYSEERR_ENABLED:
            if js_id:
                await ctx.send(
                    f"✅ Jellyfin account **{username}** created and imported into Jellyseerr!\n"
                    f"🌐 Login here: {JELLYFIN_URL}"
                )
            else:
                await ctx.send(
                    f"⚠️ Jellyfin account **{username}** created, but Jellyseerr import failed.\n"
                    f"🌐 Login here: {JELLYFIN_URL}"
                )
        else:
            await ctx.send(f"✅ Jellyfin account **{username}** created!\n🌐 Login here: {JELLYFIN_URL}")
    else:
        await ctx.send(f"❌ Failed to create Jellyfin account **{username}**. It may already exist.")


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
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.send(f"{ctx.author.mention} ❌ Please DM me to delete your Jellyfin account.")
        return

    # Fetch account linked to this Discord user
    acc = get_account_by_discord(ctx.author.id)
    if not acc or acc[0].lower() != username.lower():
        await ctx.send(f"❌ {ctx.author.mention}, that Jellyfin account is not linked to you.")
        return

    jf_id = acc[1]        # Jellyfin ID
    js_id = acc[2] if len(acc) > 2 else None  # Jellyseerr ID

    # Delete Jellyfin account
    if delete_jellyfin_user(username):
        delete_account(ctx.author.id)

        # Delete Jellyseerr user if enabled
        if JELLYSEERR_ENABLED and js_id:
            try:
                headers = {"X-Api-Key": JELLYSEERR_API_KEY}
                dr = requests.delete(f"{JELLYSEERR_URL}/api/v1/user/{js_id}", headers=headers, timeout=10)
                if dr.status_code in (200, 204):
                    print(f"[Jellyseerr] User {js_id} removed successfully.")
            except Exception as e:
                print(f"[Jellyseerr] Failed to delete user {js_id}: {e}")

        await ctx.send(f"✅ Jellyfin account **{username}** deleted successfully.")
    else:
        await ctx.send(f"❌ Failed to delete Jellyfin account **{username}**.")


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
    member = ctx.guild.get_member(ctx.author.id)
    if not member or not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    if len(new_prefix) != 1 or new_prefix.isalnum():
        await ctx.send("❌ Prefix must be a single non-alphanumeric symbol (e.g. !, $, %, ?)")
        return

    # Update prefix
    global PREFIX
    PREFIX = new_prefix
    bot.command_prefix = PREFIX

    # Write to .env
    lines = []
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("PREFIX="):
                lines.append(f"PREFIX={new_prefix}\n")
            else:
                lines.append(line)
    with open(".env", "w") as f:
        f.writelines(lines)

    await ctx.send(f"✅ Command prefix updated to `{new_prefix}`")

@bot.command()
async def updates(ctx):
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    try:
        response = requests.get(VERSION_URL, timeout=10)
        if response.status_code == 200:
            latest_version = response.text.strip()
            await ctx.send(
                f"🤖 Bot version: `{BOT_VERSION}`\n"
                f"🌍 Latest version: `{latest_version}`\n"
                f"{'✅ Up to date!' if BOT_VERSION == latest_version else f'⚠️ Update available! Get it here: {RELEASES_URL}'}"
            )
        else:
            await ctx.send("❌ Failed to fetch latest version info.")
    except Exception as e:
        await ctx.send(f"❌ Error checking version: {e}")



@bot.command(name="help")
async def help_command(ctx):
    member = ctx.guild.get_member(ctx.author.id)
    is_admin = has_admin_role(member)

    embed = discord.Embed(
        title=f"📖 Jellyfin Bot Help {BOT_VERSION}",
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
            f"`{PREFIX}updates` - Manually check for bot updates\n"
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

@tasks.loop(hours=1)
async def check_for_updates():
    try:
        response = requests.get(VERSION_URL, timeout=10)
        if response.status_code == 200:
            latest_version = response.text.strip()
            if latest_version != BOT_VERSION:
                log_channel = bot.get_channel(SYNC_LOG_CHANNEL_ID)
                if log_channel:
                    await log_channel.send(
                        f"⚠️ **Update available for Jellyfin Bot!**\n"
                        f"📌 Current version: `{BOT_VERSION}`\n"
                        f"⬆️ Latest version: `{latest_version}`\n\n"
                        f"🔗 Download/update here: {RELEASES_URL}"
                    )
    except Exception as e:
        print(f"[Update Check] Failed: {e}")




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
    check_for_updates.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{PREFIX}help"))

bot.run(TOKEN)
