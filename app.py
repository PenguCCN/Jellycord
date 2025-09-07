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
ENABLE_TRIAL_ACCOUNTS = os.getenv("ENABLE_TRIAL_ACCOUNTS", "False").lower() == "true"

JELLYSEERR_ENABLED = os.getenv("JELLYSEERR_ENABLED", "false").lower() == "true"
JELLYSEERR_URL = os.getenv("JELLYSEERR_URL", "").rstrip("/")
JELLYSEERR_API_KEY = os.getenv("JELLYSEERR_API_KEY", "")

DB_HOST = get_env_var("DB_HOST")
DB_USER = get_env_var("DB_USER")
DB_PASSWORD = get_env_var("DB_PASSWORD")
DB_NAME = get_env_var("DB_NAME")

BOT_VERSION = "1.0.3"
VERSION_URL = "https://raw.githubusercontent.com/PenguCCN/Jellycord/main/version.txt"
RELEASES_URL = "https://github.com/PenguCCN/Jellycord/releases"

# =====================
# EVENT LOGGING
# =====================
EVENT_LOGGING = os.getenv("EVENT_LOGGING", "false").lower() == "true"

def log_event(message: str):
    if EVENT_LOGGING:
        print(f"[EVENT] {datetime.datetime.utcnow().isoformat()} | {message}")

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
    log_event(f"Initiating Database...")
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

    # Normal accounts table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            discord_id BIGINT PRIMARY KEY,
            jellyfin_username VARCHAR(255) NOT NULL,
            jellyfin_id VARCHAR(255) NOT NULL,
            jellyseerr_id VARCHAR(255)
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

    # Trial accounts table (persistent history, one-time only)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trial_accounts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            discord_id BIGINT NOT NULL UNIQUE,
            jellyfin_username VARCHAR(255),
            jellyfin_id VARCHAR(255),
            trial_created_at DATETIME NOT NULL,
            expired BOOLEAN DEFAULT 0
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_metadata (
            key_name VARCHAR(255) PRIMARY KEY,
            value VARCHAR(255) NOT NULL
        )
    """)

    # Cleanup logs table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cleanup_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            run_at DATETIME NOT NULL
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

def init_trial_accounts_table():
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    # Persistent trial accounts table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trial_accounts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            discord_id BIGINT NOT NULL UNIQUE,
            jellyfin_username VARCHAR(255) NOT NULL,
            jellyfin_id VARCHAR(255) NOT NULL,
            trial_created_at DATETIME NOT NULL,
            expired BOOLEAN DEFAULT 0
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def get_accounts():
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT discord_id, jellyfin_username, jellyfin_id, jellyseerr_id FROM accounts")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_account_by_jellyfin(username):
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT discord_id, jellyfin_id, jellyseerr_id FROM accounts WHERE jellyfin_username=%s", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # (discord_id, jf_id, js_id)


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
    return row  # (jellyfin_username, jf_id, js_id)


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
    
def get_jellyseerr_id(jf_id: str) -> str | None:
    """Return the Jellyseerr user ID for a given Jellyfin user ID."""
    if not JELLYSEERR_ENABLED:
        return None

    headers = {"X-Api-Key": JELLYSEERR_API_KEY}
    try:
        r = requests.get(f"{JELLYSEERR_URL}/api/v1/user", headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        users = r.json()
        for user in users:
            if "jellyfinUserIds" in user and jf_id in user["jellyfinUserIds"]:
                return user["id"]
        return None
    except Exception as e:
        print(f"[Jellyseerr] Failed to fetch user ID for Jellyfin ID {jf_id}: {e}")
        return None


def delete_jellyseerr_user(js_id: str) -> bool:
    if not JELLYSEERR_ENABLED or not js_id:
        return True
    headers = {"X-Api-Key": JELLYSEERR_API_KEY}
    try:
        dr = requests.delete(f"{JELLYSEERR_URL}/api/v1/user/{js_id}", headers=headers, timeout=10)
        return dr.status_code in (200, 204)
    except Exception as e:
        print(f"[Jellyseerr] Failed to delete user {js_id}: {e}")
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

def create_trial_jellyfin_user(username, password):
    payload = {
        "Name": username,
        "Password": password,
        "Policy": {
            "EnableDownloads": False,
            "EnableSyncTranscoding": False,
            "EnableRemoteControlOfOtherUsers": False,
            "EnableLiveTvAccess": False,
            "IsAdministrator": False,
            "IsHidden": False,
            "IsDisabled": False
        }
    }
    headers = {
        "X-Emby-Token": JELLYFIN_API_KEY,
        "Content-Type": "application/json"
    }
    response = requests.post(f"{JELLYFIN_URL}/Users/New", json=payload, headers=headers)

    if response.status_code == 200:
        return response.json().get("Id")
    else:
        print(f"[Jellyfin] Trial user creation failed. Status: {response.status_code}, Response: {response.text}")
        return None


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

def command_usage(base: str, args: list[str]) -> str:
    """Return usage message for a command."""
    return f"❌ Usage: `{base} {' '.join(args)}`"

def log_event(message: str):
    """Log events to console if enabled in .env."""
    if os.getenv("EVENT_LOGGING", "false").lower() == "true":
        print(f"[EVENT] {message}")

@bot.command()
async def createaccount(ctx, username: str = None, password: str = None):
    log_event(f"createaccount invoked by {ctx.author}")
    if username is None or password is None:
        await ctx.send(command_usage(f"{PREFIX}createaccount", ["<username>", "<password>"]))
        return

    if not isinstance(ctx.channel, discord.DMChannel):
        try: await ctx.message.delete()
        except discord.Forbidden: pass
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

    if create_jellyfin_user(username, password):
        jf_id = get_jellyfin_user(username)
        if not jf_id:
            await ctx.send(f"❌ Failed to fetch Jellyfin ID for **{username}**. Please contact an admin.")
            return

        js_id = None
        if JELLYSEERR_ENABLED:
            js_id = import_jellyseerr_user(jf_id)

        add_account(ctx.author.id, username, jf_id, js_id)

        if JELLYSEERR_ENABLED:
            if js_id:
                await ctx.send(f"✅ Jellyfin account **{username}** created and imported into Jellyseerr!\n🌐 Login here: {JELLYFIN_URL}")
            else:
                await ctx.send(f"⚠️ Jellyfin account **{username}** created, but Jellyseerr import failed.\n🌐 Login here: {JELLYFIN_URL}")
        else:
            await ctx.send(f"✅ Jellyfin account **{username}** created!\n🌐 Login here: {JELLYFIN_URL}")
    else:
        await ctx.send(f"❌ Failed to create Jellyfin account **{username}**. It may already exist.")

@bot.command()
async def trialaccount(ctx, username: str = None, password: str = None):
    """Create a 24-hour trial Jellyfin account. DM-only, one-time per user."""
    log_event(f"trialaccount invoked by {ctx.author}")

    # Ensure trial accounts are enabled
    if not ENABLE_TRIAL_ACCOUNTS:
        await ctx.send("❌ Trial accounts are currently disabled.")
        return

    # Ensure it's a DM
    if not isinstance(ctx.channel, discord.DMChannel):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.send(f"{ctx.author.mention} ❌ Please DM me to create a trial account.")
        return

    # Ensure required arguments
    if username is None or password is None:
        await ctx.send(command_usage(f"{PREFIX}trialaccount", ["<username>", "<password>"]))
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(ctx.author.id) if guild else None

    # Check required server role
    if not member or not has_required_role(member):
        await ctx.send(f"❌ {ctx.author.mention}, you don’t have the required role.")
        return

    # Check if user already has a normal Jellyfin account
    if get_account_by_discord(ctx.author.id):
        await ctx.send(f"❌ {ctx.author.mention}, you already have a Jellyfin account.")
        return

    # Check if user already had a trial account (one-time)
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("SELECT * FROM trial_accounts WHERE discord_id=%s", (ctx.author.id,))
    existing_trial = cur.fetchone()
    if existing_trial:
        cur.close()
        conn.close()
        await ctx.send(f"❌ {ctx.author.mention}, you have already used your trial account. You cannot create another.")
        return

    # Create Jellyfin trial user
    if create_jellyfin_user(username, password):
        jf_id = get_jellyfin_user(username)
        if not jf_id:
            await ctx.send(f"❌ Failed to fetch Jellyfin ID for **{username}**. Please contact an admin.")
            return

        # Store trial account info in separate persistent table
        cur.execute("""
            INSERT INTO trial_accounts (discord_id, jellyfin_username, jellyfin_id, trial_created_at, expired)
            VALUES (%s, %s, %s, NOW(), 0)
        """, (ctx.author.id, username, jf_id))
        conn.commit()
        cur.close()
        conn.close()

        await ctx.send(f"✅ Trial Jellyfin account **{username}** created! It will expire in 24 hours.\n🌐 Login here: {JELLYFIN_URL}")
        log_event(f"Trial account created for {ctx.author} ({username})")
    else:
        cur.close()
        conn.close()
        await ctx.send(f"❌ Failed to create trial account **{username}**. It may already exist.")


@bot.command()
async def recoveraccount(ctx, new_password: str = None):
    log_event(f"recoveraccount invoked by {ctx.author}")
    if new_password is None:
        await ctx.send(command_usage(f"{PREFIX}recoveraccount", ["<newpassword>"]))
        return

    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} Please DM me to reset your password.")
        return

    acc = get_account_by_discord(ctx.author.id)
    if not acc:
        await ctx.send("❌ You do not have a linked Jellyfin account.")
        return

    username = acc[0]
    if reset_jellyfin_password(username, new_password):
        await ctx.send(f"✅ Your Jellyfin password for **{username}** has been reset!\n🌐 Login here: {JELLYFIN_URL}")
    else:
        await ctx.send(f"❌ Failed to reset password for **{username}**. Please contact an admin.")


@bot.command()
async def deleteaccount(ctx, username: str = None):
    log_event(f"deleteaccount invoked by {ctx.author}")
    if username is None:
        await ctx.send(command_usage(f"{PREFIX}deleteaccount", ["<username>"]))
        return

    if not isinstance(ctx.channel, discord.DMChannel):
        try: await ctx.message.delete()
        except discord.Forbidden: pass
        await ctx.send(f"{ctx.author.mention} ❌ Please DM me to delete your Jellyfin account.")
        return

    acc = get_account_by_discord(ctx.author.id)
    if not acc or acc[0].lower() != username.lower():
        await ctx.send(f"❌ {ctx.author.mention}, that Jellyfin account is not linked to you.")
        return

    jf_id, js_id = acc[1], acc[2] if len(acc) > 2 else None

    if delete_jellyfin_user(username):
        delete_account(ctx.author.id)
        if JELLYSEERR_ENABLED and js_id:
            try:
                headers = {"X-Api-Key": JELLYSEERR_API_KEY}
                dr = requests.delete(f"{JELLYSEERR_URL}/api/v1/user/{js_id}", headers=headers, timeout=10)
                if dr.status_code in (200, 204): print(f"[Jellyseerr] User {js_id} removed successfully.")
            except Exception as e:
                print(f"[Jellyseerr] Failed to delete user {js_id}: {e}")
        await ctx.send(f"✅ Jellyfin account **{username}** deleted successfully.")
    else:
        await ctx.send(f"❌ Failed to delete Jellyfin account **{username}**.")


@bot.command()
async def cleanup(ctx):
    log_event(f"cleanup invoked by {ctx.author}")
    guild = bot.get_guild(GUILD_ID)
    removed = []

    for row in get_accounts():
        discord_id = row[0]
        jf_username = row[1]
        jf_id = row[2] if len(row) > 2 else None
        js_id = row[3] if len(row) > 3 else None

        m = guild.get_member(discord_id)
        if m is None or not has_required_role(m):
            if delete_jellyfin_user(jf_username):
                delete_account(discord_id)

                if JELLYSEERR_ENABLED and js_id:
                    try:
                        headers = {"X-Api-Key": JELLYSEERR_API_KEY}
                        dr = requests.delete(f"{JELLYSEERR_URL}/api/v1/user/{js_id}", headers=headers, timeout=10)
                        if dr.status_code in (200, 204):
                            print(f"[Jellyseerr] User {js_id} removed successfully.")
                    except Exception as e:
                        print(f"[Jellyseerr] Failed to delete user {js_id}: {e}")

                removed.append(jf_username)

    log_channel = bot.get_channel(SYNC_LOG_CHANNEL_ID)
    if removed and log_channel:
        await log_channel.send(f"🧹 Removed {len(removed)} Jellyfin accounts: {', '.join(removed)}")

    await ctx.send("✅ Cleanup complete.")


@bot.command()
async def lastcleanup(ctx):
    log_event(f"lastcleanup invoked by {ctx.author}")
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

    await ctx.send(f"🧹 Last cleanup ran at **{last_run_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC**\n⏳ Time until next cleanup: {hours}h {minutes}m {seconds}s")


@bot.command()
async def searchaccount(ctx, username: str = None):
    log_event(f"searchaccount invoked by {ctx.author}")
    if username is None:
        await ctx.send(command_usage(f"{PREFIX}searchaccount", ["<jellyfin_username>"]))
        return

    result = get_account_by_jellyfin(username)
    if result:
        discord_id = result[0]
        user = await bot.fetch_user(discord_id)
        await ctx.send(f"🔍 Jellyfin account **{username}** is linked to Discord user {user.mention}.")
    else:
        await ctx.send("❌ No linked Discord user found for that Jellyfin account.")


@bot.command()
async def searchdiscord(ctx, user: discord.User = None):
    log_event(f"searchdiscord invoked by {ctx.author}")
    if user is None:
        await ctx.send(command_usage(f"{PREFIX}searchdiscord", ["@user"]))
        return

    result = get_account_by_discord(user.id)
    if result:
        await ctx.send(f"🔍 Discord user {user.mention} is linked to Jellyfin account **{result[0]}**.")
    else:
        await ctx.send("❌ That Discord user does not have a linked Jellyfin account.")


@bot.command()
async def scanlibraries(ctx):
    log_event(f"scanlibraries invoked by {ctx.author}")
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    response = requests.post(f"{JELLYFIN_URL}/Library/Refresh", headers={"X-Emby-Token": JELLYFIN_API_KEY})
    if response.status_code in (200, 204):
        await ctx.send("✅ All Jellyfin libraries are being scanned.")
    else:
        await ctx.send(f"❌ Failed to start library scan. Status code: {response.status_code}")


@bot.command()
async def link(ctx, jellyfin_username: str = None, user: discord.User = None, js_id: str = None):
    log_event(f"link invoked by {ctx.author}")
    usage_args = ["<Jellyfin Account>", "<@user>"]
    if JELLYSEERR_ENABLED: usage_args.append("<Jellyseerr ID>")

    if jellyfin_username is None or user is None or (JELLYSEERR_ENABLED and js_id is None):
        await ctx.send(command_usage(f"{PREFIX}link", usage_args))
        return

    existing_acc = get_account_by_discord(user.id)
    if existing_acc:
        await ctx.send(f"❌ Discord user {user.mention} already has a linked account.")
        return

    jf_id = get_jellyfin_user(jellyfin_username)
    if not jf_id:
        await ctx.send(f"❌ Could not find Jellyfin account **{jellyfin_username}**. Make sure it exists.")
        return

    add_account(user.id, jellyfin_username, jf_id, js_id)
    await ctx.send(f"✅ Linked Jellyfin account **{jellyfin_username}** to {user.mention}.")


@bot.command()
async def unlink(ctx, discord_user: discord.User = None):
    log_event(f"unlink invoked by {ctx.author}")
    if discord_user is None:
        await ctx.send(command_usage(f"{PREFIX}unlink", ["@user"]))
        return

    account = get_account_by_discord(discord_user.id)
    if not account:
        await ctx.send(f"❌ Discord user {discord_user.mention} does not have a linked Jellyfin account.")
        return

    delete_account(discord_user.id)
    await ctx.send(f"✅ Unlinked Jellyfin account **{account[0]}** from Discord user {discord_user.mention}.")


@bot.command()
async def setprefix(ctx, new_prefix: str = None):
    log_event(f"setprefix invoked by {ctx.author}")
    if new_prefix is None:
        await ctx.send(command_usage(f"{PREFIX}setprefix", ["<symbol>"]))
        return

    member = ctx.guild.get_member(ctx.author.id)
    if not member or not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    if len(new_prefix) != 1 or new_prefix.isalnum():
        await ctx.send("❌ Prefix must be a single non-alphanumeric symbol (e.g. !, $, %, ?)")
        return

    PREFIX = new_prefix
    bot.command_prefix = PREFIX

    lines = []
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("PREFIX="):
                lines.append(f"PREFIX={new_prefix}\n")
            else:
                lines.append(line)
    with open(".env", "w") as f: f.writelines(lines)

    await ctx.send(f"✅ Command prefix updated to `{new_prefix}`")


@bot.command()
async def updates(ctx):
    log_event(f"updates invoked by {ctx.author}")
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    try:
        response = requests.get(VERSION_URL, timeout=10)
        if response.status_code == 200:
            latest_version = response.text.strip()
            await ctx.send(f"🤖 Bot version: `{BOT_VERSION}`\n🌍 Latest version: `{latest_version}`\n{'✅ Up to date!' if BOT_VERSION == latest_version else f'⚠️ Update available! Get it here: {RELEASES_URL}'}")
        else:
            await ctx.send("❌ Failed to fetch latest version info.")
    except Exception as e:
        await ctx.send(f"❌ Error checking version: {e}")

@bot.command()
async def logging(ctx, state: str):
    """Admin-only: Enable or disable event logging."""
    member = ctx.guild.get_member(ctx.author.id)
    if not member or not has_admin_role(member):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    global EVENT_LOGGING
    if state.lower() in ("on", "true", "1"):
        EVENT_LOGGING = True
        new_value = "true"
    elif state.lower() in ("off", "false", "0"):
        EVENT_LOGGING = False
        new_value = "false"
    else:
        await ctx.send("❌ Invalid value. Use `on` or `off`.")
        return

    # Update .env
    lines = []
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("EVENT_LOGGING="):
                lines.append(f"EVENT_LOGGING={new_value}\n")
            else:
                lines.append(line)
    with open(".env", "w") as f:
        f.writelines(lines)

    await ctx.send(f"✅ Event logging is now {'enabled' if EVENT_LOGGING else 'disabled'}.")
    log_event(f"EVENT_LOGGING toggled to {new_value} by {ctx.author}")


@bot.command(name="help")
async def help_command(ctx):
    log_event(f"Command help invoked by {ctx.author}")
    member = ctx.guild.get_member(ctx.author.id)
    is_admin = has_admin_role(member)

    embed = discord.Embed(
        title=f"📖 Jellyfin Bot Help {BOT_VERSION}",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )

    # User commands
    user_cmds = [
        f"`{PREFIX}createaccount <username> <password>` - Create your Jellyfin account",
        f"`{PREFIX}recoveraccount <newpassword>` - Reset your password",
        f"`{PREFIX}deleteaccount <username>` - Delete your Jellyfin account"
    ]

    # Only show trialaccount if enabled
    if ENABLE_TRIAL_ACCOUNTS:
        user_cmds.append(f"`{PREFIX}trialaccount <username> <password>` - Create a 24-hour trial Jellyfin account")

    embed.add_field(name="User Commands", value="\n".join(user_cmds), inline=False)

    # Admin commands
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
            f"`{PREFIX}setprefix` - Change the bot's command prefix\n"
            f"`{PREFIX}updates` - Manually check for bot updates\n"
            f"`{PREFIX}logging` - Enable/Disable Console Event Logging\n"
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

    # Normal accounts cleanup
    for discord_id, jf_username, jf_id, js_id in get_accounts():
        m = guild.get_member(discord_id)
        if m is None or not has_required_role(m):
            if delete_jellyfin_user(jf_username):
                delete_account(discord_id)
                removed.append(jf_username)

    # Trial accounts cleanup
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM trial_accounts WHERE expired=0")
    trials = cur.fetchall()

    for trial in trials:
        created_at = trial["trial_created_at"]
        if created_at and datetime.datetime.utcnow() > created_at + datetime.timedelta(hours=24):
            # Delete from Jellyfin
            delete_jellyfin_user(trial["jellyfin_username"])
            # Mark trial as expired
            cur.execute("UPDATE trial_accounts SET expired=1 WHERE discord_id=%s", (trial["discord_id"],))
            conn.commit()
            removed.append(f"{trial['jellyfin_username']} (trial)")


    cur.close()
    conn.close()

    # Record cleanup run
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor()
    cur.execute("INSERT INTO cleanup_logs (run_at) VALUES (%s)", (datetime.datetime.utcnow(),))
    conn.commit()
    cur.close()
    conn.close()

    if removed:
        print(f"Cleanup removed {len(removed)} accounts: {removed}")


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
                        f"📌 Current version: `{BOT_VERSION}`\n"
                        f"⬆️ Latest version: `{latest_version}`\n"
                        f"⚠️ **Update available for Jellyfin Bot! Get it here:**\n\n"
                        f"{RELEASES_URL}"
                    )
                    log_event(f"Latest Version:'{latest_version}', Current Version: '{BOT_VERSION}'")
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
