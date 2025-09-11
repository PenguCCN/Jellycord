import discord
from discord.ext import commands, tasks
import requests
import mysql.connector
import asyncio
import os
from dotenv import load_dotenv
import pytz
import random
import qbittorrentapi

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
GUILD_IDS = [int(x.strip()) for x in get_env_var("GUILD_IDS").split(",")]
REQUIRED_ROLE_IDS = [int(x) for x in get_env_var("REQUIRED_ROLE_IDS").split(",")]
ADMIN_ROLE_IDS = [int(x) for x in get_env_var("ADMIN_ROLE_IDS").split(",")]
SYNC_LOG_CHANNEL_ID = get_env_var("SYNC_LOG_CHANNEL_ID", int)

JELLYFIN_URL = get_env_var("JELLYFIN_URL")
JELLYFIN_API_KEY = get_env_var("JELLYFIN_API_KEY")
ENABLE_TRIAL_ACCOUNTS = os.getenv("ENABLE_TRIAL_ACCOUNTS", "False").lower() == "true"

JELLYSEERR_ENABLED = os.getenv("JELLYSEERR_ENABLED", "false").lower() == "true"
JELLYSEERR_URL = os.getenv("JELLYSEERR_URL", "").rstrip("/")
JELLYSEERR_API_KEY = os.getenv("JELLYSEERR_API_KEY", "")

ENABLE_JFA = os.getenv("ENABLE_JFA", "False").lower() == "true"
JFA_URL = os.getenv("JFA_URL")
JFA_API_KEY = os.getenv("JFA_API_KEY")

ENABLE_QBITTORRENT = os.getenv("ENABLE_QBITTORRENT", "False").lower() == "true"
QBIT_HOST = os.getenv("QBIT_HOST")
QBIT_USERNAME = os.getenv("QBIT_USERNAME")
QBIT_PASSWORD = os.getenv("QBIT_PASSWORD")

DB_HOST = get_env_var("DB_HOST")
DB_USER = get_env_var("DB_USER")
DB_PASSWORD = get_env_var("DB_PASSWORD")
DB_NAME = get_env_var("DB_NAME")

LOCAL_TZ = pytz.timezone(get_env_var("LOCAL_TZ", str, required=False) or "America/Chicago")

BOT_VERSION = "1.0.6"
VERSION_URL = "https://raw.githubusercontent.com/PenguCCN/Jellycord/main/version.txt"
RELEASES_URL = "https://github.com/PenguCCN/Jellycord/releases"

# =====================
# EVENT LOGGING
# =====================
EVENT_LOGGING = os.getenv("EVENT_LOGGING", "false").lower() == "true"

def log_event(message: str):
    """Log events to console if enabled in .env."""
    if EVENT_LOGGING:
        now_local = datetime.datetime.now(LOCAL_TZ)
        print(f"[EVENT] {now_local.isoformat()} | {message}")

# =====================
# DISCORD SETUP
# =====================
intents = discord.Intents.all()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# =====================
# QBITTORRENT SETUP
# =====================

if ENABLE_QBITTORRENT:

    qb = qbittorrentapi.Client(
        host=QBIT_HOST,
        username=QBIT_USERNAME,
        password=QBIT_PASSWORD
    )

    try:
        qb.auth_log_in()
        print("✅ Logged in to qBittorrent")
    except qbittorrentapi.LoginFailed:
        print("❌ Failed to log in to qBittorrent API")
        qb = None 
else:
    qb = None  # qBittorrent disabled


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
# QBITTORRENT HELPERS
# =====================

def progress_bar(progress: float, length: int = 20) -> str:
    """Return a textual progress bar for the embed."""
    filled_length = int(length * progress)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}] {progress*100:.2f}%"

# =====================
# DISCORD HELPERS
# =====================

def has_required_role(user: discord.User | discord.Member) -> bool:
    """Check if the user has any of the required roles across all configured guilds."""
    for gid in GUILD_IDS:
        guild = bot.get_guild(gid)
        if not guild:
            continue
        member = guild.get_member(user.id)
        if member and any(role.id in REQUIRED_ROLE_IDS for role in member.roles):
            return True
    return False


def has_admin_role(user: discord.User | discord.Member) -> bool:
    """Check if the user has any of the admin roles across all configured guilds."""
    for gid in GUILD_IDS:
        guild = bot.get_guild(gid)
        if not guild:
            continue
        member = guild.get_member(user.id)
        if member and any(role.id in ADMIN_ROLE_IDS for role in member.roles):
            return True
    return False


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

    member = None
    for gid in GUILD_IDS:
        guild = bot.get_guild(gid)
        if guild:
            member = guild.get_member(ctx.author.id)
            if member and has_required_role(member):
                break

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
async def createinvite(ctx):
    """Admin-only: Create a new JFA-Go invite link (create -> fetch latest invite)."""
    if not ENABLE_JFA:
        await ctx.send("❌ JFA support is not enabled in the bot configuration.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    try:
        payload = {"days": 7, "max_uses": 1}
        base = JFA_URL.rstrip("/")

        # Try Bearer, fallback to X-Api-Key
        headers = {"Authorization": f"Bearer {JFA_API_KEY}"}
        r = requests.post(f"{base}/invites", headers=headers, json=payload, timeout=10)
        if r.status_code == 401:
            headers = {"X-Api-Key": JFA_API_KEY}
            r = requests.post(f"{base}/invites", headers=headers, json=payload, timeout=10)

        if r.status_code not in (200, 201):
            await ctx.send(f"❌ Failed to create invite. Status code: {r.status_code}\nResponse: {r.text}")
            return

        # Fetch invites list (some JFA builds only return success on POST)
        r2 = requests.get(f"{base}/invites", headers=headers, timeout=10)
        if r2.status_code not in (200, 201):
            await ctx.send(f"❌ Failed to fetch invite list. Status code: {r2.status_code}\nResponse: {r2.text}")
            return

        invites_resp = r2.json()
        # Normalize different shapes: either {'invites': [...]} or a list
        if isinstance(invites_resp, dict) and "invites" in invites_resp:
            invites_list = invites_resp["invites"]
        elif isinstance(invites_resp, list):
            invites_list = invites_resp
        else:
            # unexpected shape
            print(f"[createinvite] Unexpected invites response shape: {invites_resp}")
            await ctx.send("❌ Unexpected response from JFA when fetching invites. Check bot logs.")
            return

        if not invites_list:
            await ctx.send("❌ No invites found after creation.")
            return

        latest = invites_list[-1]  # assume newest is last; adjust if your JFA sorts differently
        print(f"[createinvite] Latest invite object: {latest}")  # debug log

        code = latest.get("code") or latest.get("id") or latest.get("token")
        url = latest.get("url") or latest.get("link")
        if not url and code:
            # Common invite URL pattern; adjust if your instance is different
            url = f"{base}/invite/{code}"

        # created: JFA gives epoch seconds in 'created'
        created_local_str = None
        created_ts = latest.get("created")
        if created_ts:
            try:
                created_dt = datetime.datetime.utcfromtimestamp(int(created_ts)).replace(tzinfo=datetime.timezone.utc)
                created_local = created_dt.astimezone(LOCAL_TZ)
                created_local_str = created_local.strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                created_local_str = None

        remaining = latest.get("remaining-uses", "N/A")

        embed = discord.Embed(
            title="🎟️ New Jellyfin Invite Created",
            color=discord.Color.blue()
        )
        embed.add_field(name="Code", value=f"`{code}`" if code else "N/A", inline=True)
        embed.add_field(name="Link", value=f"[Click here]({url})" if url else "N/A", inline=True)

        footer_parts = []
        if created_local_str:
            footer_parts.append(f"Created: {created_local_str}")
        footer_parts.append(f"Remaining uses: {remaining}")
        embed.set_footer(text=" • ".join(footer_parts))
        embed.set_author(name=f"Created by {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error creating invite: {e}")
        print(f"[createinvite] Error: {e}", exc_info=True)


@bot.command()
async def listinvites(ctx):
    """Admin-only: List all active JFA-Go invites."""
    if not ENABLE_JFA:
        await ctx.send("❌ JFA support is not enabled in the bot configuration.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    try:
        base = JFA_URL.rstrip("/")
        headers = {"Authorization": f"Bearer {JFA_API_KEY}"}
        r = requests.get(f"{base}/invites", headers=headers, timeout=10)

        if r.status_code == 401:
            headers = {"X-Api-Key": JFA_API_KEY}
            r = requests.get(f"{base}/invites", headers=headers, timeout=10)

        if r.status_code not in (200, 201):
            await ctx.send(f"❌ Failed to fetch invites. Status code: {r.status_code}\nResponse: {r.text}")
            return

        invites_resp = r.json()
        print(f"[listinvites] Raw response: {invites_resp}")  # Debug

        # Normalize to a list of invite dicts
        if isinstance(invites_resp, dict) and "invites" in invites_resp:
            invites_list = invites_resp["invites"]
        elif isinstance(invites_resp, list):
            invites_list = invites_resp
        else:
            await ctx.send("❌ Unexpected invite response format. Check logs.")
            return

        if not invites_list:
            await ctx.send("ℹ️ No active invites found.")
            return

        embed = discord.Embed(
            title="📋 Active Jellyfin Invites",
            color=discord.Color.green()
        )

        for invite in invites_list:
            code = invite.get("code")
            url = f"{base}/invite/{code}" if code else None
            remaining = invite.get("remaining-uses", "N/A")

            created_str = None
            created_ts = invite.get("created")
            if created_ts:
                try:
                    created_dt = datetime.datetime.utcfromtimestamp(int(created_ts)).replace(tzinfo=datetime.timezone.utc)
                    created_local = created_dt.astimezone(LOCAL_TZ)
                    created_str = created_local.strftime("%Y-%m-%d %H:%M:%S %Z")
                except Exception:
                    created_str = None

            value = f"Uses left: {remaining}"
            if url:
                value += f"\n[Invite Link]({url})"
            if created_str:
                value += f"\nCreated: {created_str}"

            embed.add_field(
                name=f"🔑 {code}",
                value=value,
                inline=False
            )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error fetching invites: {e}")
        print(f"[listinvites] Error: {e}", exc_info=True)

@bot.command()
async def deleteinvite(ctx, code: str):
    """Admin-only: Delete a specific JFA-Go invite by code."""
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    try:
        base = JFA_URL.rstrip("/")
        headers = {"Authorization": f"Bearer {JFA_API_KEY}"}

        # Try DELETE with body (legacy API)
        r = requests.delete(f"{base}/invites", headers=headers, json={"code": code}, timeout=10)
        if r.status_code == 401:
            headers = {"X-Api-Key": JFA_API_KEY}
            r = requests.delete(f"{base}/invites", headers=headers, json={"code": code}, timeout=10)

        if r.status_code in (200, 204):
            await ctx.send(f"✅ Invite `{code}` has been deleted.")
        else:
            await ctx.send(f"❌ Failed to delete invite `{code}`. Status code: {r.status_code}\nResponse: {r.text}")

    except Exception as e:
        await ctx.send(f"❌ Error deleting invite: {e}")
        print(f"[deleteinvite] Error: {e}", exc_info=True)


@bot.command()
async def clearinvites(ctx):
    """Admin-only: Delete ALL JFA-Go invites (use with caution!)."""
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    try:
        base = JFA_URL.rstrip("/")
        headers = {"Authorization": f"Bearer {JFA_API_KEY}"}
        r = requests.get(f"{base}/invites", headers=headers, timeout=10)
        if r.status_code == 401:
            headers = {"X-Api-Key": JFA_API_KEY}
            r = requests.get(f"{base}/invites", headers=headers, timeout=10)

        if r.status_code not in (200, 201):
            await ctx.send(f"❌ Failed to fetch invites. Status code: {r.status_code}\nResponse: {r.text}")
            return

        invites_resp = r.json()
        invites_list = invites_resp["invites"] if isinstance(invites_resp, dict) and "invites" in invites_resp else invites_resp
        if not invites_list:
            await ctx.send("ℹ️ No invites to delete.")
            return

        deleted = 0
        for invite in invites_list:
            code = invite.get("code")
            if not code:
                continue
            dr = requests.delete(f"{base}/invites", headers=headers, json={"code": code}, timeout=10)
            if dr.status_code in (200, 204):
                deleted += 1

        await ctx.send(f"✅ Deleted {deleted} invites.")

    except Exception as e:
        await ctx.send(f"❌ Error clearing invites: {e}")
        print(f"[clearinvites] Error: {e}", exc_info=True)


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

    member = None
    for gid in GUILD_IDS:
        guild = bot.get_guild(gid)
        if guild:
            member = guild.get_member(ctx.author.id)
            if member and has_required_role(member):
                break

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
async def what2watch(ctx):
    """Pick 5 random movies from the Jellyfin library with embeds and posters."""
    member = ctx.guild.get_member(ctx.author.id) if ctx.guild else None
    if not member or not has_required_role(member):
        await ctx.send(f"❌ {ctx.author.mention}, you don’t have the required role to use this command.")
        return

    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    try:
        # Fetch all movies
        r = requests.get(f"{JELLYFIN_URL}/Items?IncludeItemTypes=Movie&Recursive=true", headers=headers, timeout=10)
        if r.status_code != 200:
            await ctx.send(f"❌ Failed to fetch movies. Status code: {r.status_code}")
            return

        movies = r.json().get("Items", [])
        if not movies:
            await ctx.send("⚠️ No movies found in the library.")
            return

        # Pick 5 random movies
        selection = random.sample(movies, min(5, len(movies)))

        embed = discord.Embed(
            title="🎬 What to Watch",
            description="Here are 5 random movie suggestions from the library:",
            color=discord.Color.blue()
        )

        for movie in selection:
            name = movie.get("Name")
            year = movie.get("ProductionYear", "N/A")
            runtime = movie.get("RunTimeTicks", None)
            runtime_min = int(runtime / 10_000_000 / 60) if runtime else "N/A"
            
            # Poster URL if available
            poster_url = None
            if "PrimaryImageTag" in movie and movie["PrimaryImageTag"]:
                poster_url = f"{JELLYFIN_URL}/Items/{movie['Id']}/Images/Primary?tag={movie['PrimaryImageTag']}&quality=90"

            field_value = f"Year: {year}\nRuntime: {runtime_min} min"
            embed.add_field(name=name, value=field_value, inline=False)
            
            if poster_url:
                embed.set_image(url=poster_url)  # Only last movie's poster will appear as main embed image

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error fetching movies: {e}")
        print(f"[what2watch] Error: {e}")


@bot.command()
async def cleanup(ctx):
    log_event(f"cleanup invoked by {ctx.author}")
    removed = []

    for discord_id, jf_username, jf_id, js_id in get_accounts():
        member = None
        for gid in GUILD_IDS:
            guild = bot.get_guild(gid)
            if guild:
                member = guild.get_member(discord_id)
                if member:
                    break

        if member is None or not has_required_role(member):
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
async def listvalidusers(ctx):
    """Admin-only: List how many registered users have a valid role."""
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    accounts = get_accounts()
    valid_users = []
    invalid_users = []

    for discord_id, jf_username, jf_id, js_id in accounts:
        user = await bot.fetch_user(discord_id)
        if has_required_role(user):
            valid_users.append(user)
        else:
            invalid_users.append(user)

    embed = discord.Embed(
        title="📊 Registered User Role Status",
        color=discord.Color.green()
    )
    embed.add_field(
        name="✅ Valid Users",
        value=f"{len(valid_users)} users",
        inline=True
    )
    embed.add_field(
        name="❌ Invalid Users",
        value=f"{len(invalid_users)} users",
        inline=True
    )
    if len(valid_users) > 0:
        embed.add_field(
            name="Valid Users List",
            value="\n".join([u.mention for u in valid_users[:20]]) + ("..." if len(valid_users) > 20 else ""),
            inline=False
        )
    if len(invalid_users) > 0:
        embed.add_field(
            name="Invalid Users List",
            value="\n".join([u.mention for u in invalid_users[:20]]) + ("..." if len(invalid_users) > 20 else ""),
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command()
async def lastcleanup(ctx):
    log_event(f"lastcleanup invoked by {ctx.author}")
    member = ctx.guild.get_member(ctx.author.id)
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to view the last cleanup.")
        return

    last_run = get_metadata("last_cleanup")
    if not last_run:
        await ctx.send("ℹ️ No cleanup has been run yet.")
        return

    last_run_dt_utc = datetime.datetime.fromisoformat(last_run)
    if last_run_dt_utc.tzinfo is None:
        last_run_dt_utc = pytz.utc.localize(last_run_dt_utc)
    last_run_local = last_run_dt_utc.astimezone(LOCAL_TZ)
    now_local = datetime.datetime.now(LOCAL_TZ)
    next_run_local = last_run_local + datetime.timedelta(hours=24)
    time_remaining = next_run_local - now_local

    hours, remainder = divmod(int(time_remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    await ctx.send(
        f"🧹 Last cleanup ran at **{last_run_local.strftime('%Y-%m-%d %H:%M:%S %Z')}**\n"
        f"⏳ Time until next cleanup: {hours}h {minutes}m {seconds}s"
    )


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
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    response = requests.post(f"{JELLYFIN_URL}/Library/Refresh", headers={"X-Emby-Token": JELLYFIN_API_KEY})
    if response.status_code in (200, 204):
        await ctx.send("✅ All Jellyfin libraries are being scanned.")
    else:
        await ctx.send(f"❌ Failed to start library scan. Status code: {response.status_code}")


@bot.command()
async def activestreams(ctx):
    """Admin-only: Show currently active Jellyfin user streams (movies/episodes only) with progress bar."""
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return

    headers = {"X-Emby-Token": JELLYFIN_API_KEY}
    try:
        r = requests.get(f"{JELLYFIN_URL}/Sessions", headers=headers, timeout=10)
        if r.status_code != 200:
            await ctx.send(f"❌ Failed to fetch active streams. Status code: {r.status_code}")
            return

        sessions = r.json()
        # Only keep sessions that are actively playing a Movie or Episode
        active_streams = [
            s for s in sessions
            if s.get("NowPlayingItem") and s["NowPlayingItem"].get("Type") in ("Movie", "Episode")
        ]

        if not active_streams:
            await ctx.send("ℹ️ No active movie or episode streams at the moment.")
            return

        embed = discord.Embed(
            title="📺 Active Jellyfin Streams",
            description=f"Currently {len(active_streams)} active stream(s):",
            color=discord.Color.green()
        )

        for session in active_streams:
            user_name = session.get("UserName", "Unknown User")
            device = session.get("DeviceName", "Unknown Device")
            media = session.get("NowPlayingItem", {})
            media_type = media.get("Type", "Unknown")
            media_name = media.get("Name", "Unknown Title")

            # Get progress
            try:
                position_ticks = session.get("PlayState", {}).get("PositionTicks", 0)
                runtime_ticks = media.get("RunTimeTicks", 1)  # avoid div by zero
                position_seconds = position_ticks / 10_000_000
                runtime_seconds = runtime_ticks / 10_000_000

                position_str = str(datetime.timedelta(seconds=int(position_seconds)))
                runtime_str = str(datetime.timedelta(seconds=int(runtime_seconds)))

                # Progress bar
                percent = position_seconds / runtime_seconds if runtime_seconds > 0 else 0
                bar_length = 10
                filled_length = int(round(bar_length * percent))
                bar = "■" * filled_length + "□" * (bar_length - filled_length)

                progress_str = f"{bar} {int(percent*100)}%\n[{position_str} / {runtime_str}]"
            except Exception:
                progress_str = "Unknown"

            embed.add_field(
                name=f"{media_name} ({media_type})",
                value=f"👤 {user_name}\n📱 {device}\n⏱ Progress: {progress_str}",
                inline=False
            )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error fetching active streams: {e}")
        print(f"[activestreams] Error: {e}")

@bot.command()
async def qbview(ctx):
    """Admin-only: View current qBittorrent downloads."""
    if not ENABLE_QBITTORRENT:
        await ctx.send("❌ qBittorrent support is not enabled in the bot configuration.")
        return
    
    if not has_admin_role(ctx.author):
        await ctx.send("❌ You don’t have permission to use this command.")
        return
    
    torrents = qb.torrents_info()
    embed = discord.Embed(title="qBittorrent Downloads", color=0x00ff00)

    if not torrents:
        embed.description = "No torrents found."
        await ctx.send(embed=embed)
        return

    # Group torrents by state
    state_groups = {
        "Downloading / Uploading": [],
        "Finished": [],
        "Stalled": [],
        "Checking / Metadata": [],
        "Other": []
    }

    for t in torrents:
        if t.state in ("downloading", "uploading"):
            state_groups["Downloading / Uploading"].append(t)
        elif t.state in ("completed", "pausedUP", "pausedDL"):
            state_groups["Finished"].append(t)
        elif t.state in ("stalledUP", "stalledDL"):
            state_groups["Stalled"].append(t)
        elif t.state in ("checkingUP", "checkingDL", "checking", "metaDL"):
            state_groups["Checking / Metadata"].append(t)
        else:
            state_groups["Other"].append(t)

    # Add torrents to embed
    for group_name, torrents_list in state_groups.items():
        if torrents_list:
            value_text = ""
            for torrent in torrents_list:
                value_text += (
                    f"{torrent.name}\n"
                    f"{progress_bar(torrent.progress)}\n"
                    f"Peers: {torrent.num_leechs} | Seeders: {torrent.num_seeds}\n"
                    f"Status: {torrent.state}\n\n"
                )
            embed.add_field(name=group_name, value=value_text, inline=False)

    await ctx.send(embed=embed)


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
    if not has_admin_role(ctx.author):
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
    if not has_admin_role(ctx.author):
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
    if not has_admin_role(ctx.author):
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
    is_admin = has_admin_role(ctx.author)

    embed = discord.Embed(
        title=f"📖 Jellyfin Bot Help {BOT_VERSION}",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )

    # --- Jellyfin User Commands ---
    user_cmds = [
        f"`{PREFIX}createaccount <username> <password>` - Create your Jellyfin account",
        f"`{PREFIX}recoveraccount <newpassword>` - Reset your password",
        f"`{PREFIX}deleteaccount <username>` - Delete your Jellyfin account",
        f"`{PREFIX}what2watch` - Lists 5 random movie suggestions from the Jellyfin Library"
    ]
    if ENABLE_TRIAL_ACCOUNTS:
        user_cmds.append(f"`{PREFIX}trialaccount <username> <password>` - Create a 24-hour trial Jellyfin account")
    
    embed.add_field(name="🎬 Jellyfin Commands", value="\n".join(user_cmds), inline=False)

    # --- Bot Commands ---
    bot_cmds = [
        f"`{PREFIX}help` - Show this help message"
    ]
    embed.add_field(name="🤖 Bot Commands", value="\n".join(bot_cmds), inline=False)

    # --- Admin Commands ---
    if is_admin:
        # Admin Jellyfin commands
        link_command = f"`{PREFIX}link <jellyfin_username> @user` - Manually link accounts"
        if JELLYSEERR_ENABLED:
            link_command = f"`{PREFIX}link <jellyfin_username> @user <Jellyseerr ID>` - Link accounts with Jellyseerr"

        admin_cmds = [
            link_command,
            f"`{PREFIX}unlink @user` - Manually unlink accounts",
            f"`{PREFIX}listvalidusers` - Show number of valid and invalid accounts",
            f"`{PREFIX}cleanup` - Remove Jellyfin accounts from users without roles",
            f"`{PREFIX}lastcleanup` - See last cleanup time and time remaining",
            f"`{PREFIX}searchaccount <jellyfin_username>` - Find linked Discord user",
            f"`{PREFIX}searchdiscord @user` - Find linked Jellyfin account",
            f"`{PREFIX}scanlibraries` - Scan all Jellyfin libraries",
            f"`{PREFIX}activestreams` - View all active Jellyfin streams"
        ]
        embed.add_field(name="🛠️ Admin Commands", value="\n".join(admin_cmds), inline=False)

    # --- qBittorrent Commands ---
    if ENABLE_QBITTORRENT:
        qb_cmds = [
            f"`{PREFIX}qbview` - Show current qBittorrent downloads with progress, peers, and seeders",
        ]
        embed.add_field(name="💾 qBittorrent Commands", value="\n".join(qb_cmds), inline=False)

    # --- JFA Commands ---
    if ENABLE_JFA:
        jfa_cmds = [
            f"`{PREFIX}createinvite` - Create a new JFA invite link",
            f"`{PREFIX}listinvites` - List all active JFA invite links",
            f"`{PREFIX}deleteinvite <code>` - Delete a specific JFA invite"
        ]
        embed.add_field(name="🔑 JFA Commands", value="\n".join(jfa_cmds), inline=False)

        # Admin Bot commands
        admin_bot_cmds = [
            f"`{PREFIX}setprefix` - Change the bot's command prefix",
            f"`{PREFIX}updates` - Manually check for bot updates",
            f"`{PREFIX}logging` - Enable/disable console event logging"
        ]
        embed.add_field(name="⚙️ Admin Bot Commands", value="\n".join(admin_bot_cmds), inline=False)

    await ctx.send(embed=embed)


# =====================
# TASKS
# =====================
import datetime
import pytz

import datetime
import pytz
import mysql.connector

LOCAL_TZ = pytz.timezone(os.getenv("LOCAL_TZ", "America/Chicago"))

@tasks.loop(hours=24)
async def cleanup_task():
    log_event("🧹 Running daily account cleanup check...")
    removed = []

    # =======================
    # Normal accounts cleanup
    # =======================
    for discord_id, jf_username, jf_id, js_id in get_accounts():
        member = None
        for gid in GUILD_IDS:
            guild = bot.get_guild(gid)
            if guild:
                member = guild.get_member(discord_id)
                if member:
                    break

        if member is None or not has_required_role(member):
            if jf_username:
                try:
                    if delete_jellyfin_user(jf_username):
                        log_event(f"Deleted Jellyfin user {jf_username} for Discord ID {discord_id}")
                    else:
                        log_event(f"Failed to delete Jellyfin user {jf_username} for Discord ID {discord_id}")
                except Exception as e:
                    print(f"[Cleanup] Error deleting Jellyfin user {jf_username}: {e}")

            # remove DB entry for normal account
            try:
                delete_account(discord_id)
            except Exception as e:
                print(f"[Cleanup] Error removing DB entry for Discord ID {discord_id}: {e}")

            # remove from Jellyseerr if applicable
            if JELLYSEERR_ENABLED and js_id:
                try:
                    if delete_jellyseerr_user(js_id):
                        log_event(f"Deleted Jellyseerr user {js_id} for Discord ID {discord_id}")
                    else:
                        log_event(f"Failed to delete Jellyseerr user {js_id} for Discord ID {discord_id}")
                except Exception as e:
                    print(f"[Cleanup] Failed to delete Jellyseerr user {js_id}: {e}")

            removed.append(jf_username or f"{discord_id}")

    # ======================
    # Trial accounts cleanup
    # ======================
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
        )
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM trial_accounts WHERE expired=0")
        trials = cur.fetchall()
        now_local = datetime.datetime.now(LOCAL_TZ)

        for trial in trials:
            created_at_utc = trial.get("trial_created_at") or trial.get("created_at")
            if not created_at_utc:
                continue

            # Convert DB UTC time to local TZ
            if created_at_utc.tzinfo is None:
                created_at_local = pytz.utc.localize(created_at_utc).astimezone(LOCAL_TZ)
            else:
                created_at_local = created_at_utc.astimezone(LOCAL_TZ)

            if now_local > created_at_local + datetime.timedelta(hours=24):
                # Delete trial Jellyfin user
                try:
                    delete_jellyfin_user(trial.get("jellyfin_username"))
                except Exception as e:
                    print(f"[Trial Cleanup] Error deleting trial Jellyfin user {trial.get('jellyfin_username')}: {e}")

                # Mark trial as expired
                try:
                    cur.execute("UPDATE trial_accounts SET expired=1 WHERE discord_id=%s", (trial["discord_id"],))
                    conn.commit()
                except Exception as e:
                    print(f"[Trial Cleanup] Error marking trial expired for {trial['discord_id']}: {e}")

                removed.append(f"{trial.get('jellyfin_username')} (trial)")
    except Exception as e:
        print(f"[Trial Cleanup] Error reading trial accounts: {e}")
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    # ======================
    # Update metadata & logs
    # ======================
    try:
        set_metadata("last_cleanup", datetime.datetime.now(LOCAL_TZ).isoformat())
    except Exception as e:
        print(f"[Cleanup] Failed to set last_cleanup metadata: {e}")

    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
        )
        cur = conn.cursor()
        cur.execute("INSERT INTO cleanup_logs (run_at) VALUES (%s)", (datetime.datetime.now(LOCAL_TZ),))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Cleanup] Failed to insert cleanup_logs: {e}")

    # ============================
    # Post results to sync channel
    # ============================
    if removed:
        msg = f"🧹 Removed {len(removed)} Jellyfin accounts: {', '.join(removed)}"
        print(msg)
        try:
            log_channel = bot.get_channel(SYNC_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(msg)
        except Exception as e:
            print(f"[Cleanup] Failed to send removed message to sync channel: {e}")


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
        # parse UTC timestamp from DB
        last_run_dt_utc = datetime.datetime.fromisoformat(last_run)
        # convert to local timezone
        if last_run_dt_utc.tzinfo is None:
            last_run_dt_utc = pytz.utc.localize(last_run_dt_utc)
        last_run_local = last_run_dt_utc.astimezone(LOCAL_TZ)
        now_local = datetime.datetime.now(LOCAL_TZ)
        delta = now_local - last_run_local
        if delta.total_seconds() >= 24 * 3600:
            print("Running missed daily cleanup...")
            await cleanup_task()  # run immediately if overdue

    # Start scheduled tasks
    if not cleanup_task.is_running():
        cleanup_task.start()

    if not check_for_updates.is_running():
        check_for_updates.start()

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name=f"{PREFIX}help")
    )

    log_event(f"✅ Bot ready. Current time: {datetime.datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}")

bot.run(TOKEN)
