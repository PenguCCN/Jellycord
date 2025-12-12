# Jellycord

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/BannerRound.png)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Dinstance&style=for-the-badge&logo=nodedotjs&logoColor=white&label=Bot%20Instances&color=9964c5)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Djellyseerr&style=for-the-badge&logo=jellyfin&logoColor=white&label=Jellyseer%20Enabled&color=9964c5)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Dproxmox&style=for-the-badge&logo=proxmox&logoColor=white&label=Proxmox%20Enabled&color=9964c5)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Djfa&style=for-the-badge&logo=go&logoColor=white&label=JFA-GO%20Enabled&color=9964c5)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Dqbittorrent&style=for-the-badge&logo=qbittorrent&logoColor=white&label=qBittorrent%20Enabled&color=9964c5)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Dradarr&style=for-the-badge&logo=radarr&logoColor=white&label=Radarr%20Enabled&color=9964c5)
![Live Player Count](https://img.shields.io/badge/dynamic/json?query=$.data.result[0].value[1]&url=https%3A%2F%2Fprometheus.pengucc.com%2Fapi%2Fv1%2Fquery%3Fquery%3Dsonarr&style=for-the-badge&logo=sonarr&logoColor=white&label=Sonarr%20Enabled&color=9964c5)

[![Online Members](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdiscordapp.com%2Fapi%2Finvites%2FEdPJAhrDq8%3Fwith_counts%3Dtrue&query=approximate_presence_count&style=for-the-badge&logo=discord&logoColor=white&label=ONLINE%20MEMBERS&labelColor=grey&color=239eda)](https://discord.gg/EdPJAhrDq8)
![Latest Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FPenguCCN%2FJellycord%2Fmain%2Fversion.json&query=%24.version&style=for-the-badge&logo=python&logoColor=white&label=Latest%20Version%3A&color=239eda)

Allow the creation and management of Jellyfin users via Discord

Join my [Discord](https://discord.com/invite/zJMUNCPtPy) for help, and keeping an eye out for updates!

This is a very simple and lightweight Jellyfin Discord bot for managing users. It allows for creation of accounts, password recovery, account deletion, ect.

Fill out values in the .env and you're good to go!

# 🛑 Disclaimer (Please Read) 🛑

This bot collects limited amounts of information, it is enabled by default and can be disabled in your environment file. Information Collected is limited to:

- Bot Instances
- Enabled Features

We do **not** and will **never** collect nor store:

- IP Address's.
- System Information.
- Information about Jellyfin or any related services.

## Why do we do this?

Adding these simply allows me to see what features users are interested in, allowing me to focus on improving/fixing highly used features.

# Features

- Automatic Account Cleanup
- Creating Accounts
- Recovering Passwords
- Searching accounts by Discord User, or Jellyfin User
- Run Library Scanning
- Manual Account Linking (For previously made Jellyfin accounts)
- Change bot prefix live
- Checks for new releases

# Command Overview

**Pinging the bot will show you the necessary commands to create your account.**

**PLEASE NOTE BEFORE USING. THIS BOT IS MEANT TO USE REQUIRED ROLES IN ORDER TO WHITELIST USERS FOR JELLYFIN. TAKING A USERS ROLE AWAY WILL DELETE THEIR JELLYFIN ACCOUNT WHEN THE BOT RUNS ITS CLEANUP (24 Hour Schedule or Admin Forced)**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/ping.png)

**There are protections in place to stop users from creating an account where people can see. If a user sends the account creation or reset in a guild, the bot will delete it.**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/account-deny.png)

**If a user already has a linked Jellyfin account, the bot will not allow them to create another account.**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/account-limit.png)

**In order to create an account, you must have the required roles specified in the .env**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/role-required.png)

***🎬 User Commands***

- `!createaccount` <username> <password> - Create your Jellyfin account
- `!recoveraccount` <username> <newpassword> - Reset your password
- `!deleteaccount` <username> - Delete your Jellyfin account
- `!trialaccount` <username> <password> - Create a 24-hour trial Jellyfin account. Only if ENABLE_TRIAL_ACCOUNTS=True
- `!movies2watch` - Lists 5 random movie suggestions from the Jellyfin Library
- `!shows2watch` - Lists 5 random show suggestions from the Jellyfin Library
- `!help` - Displays help command

***🛠️ Admin Commands***

- `!link` @user <jellyfin_username> - Manually link accounts
- `!unlink` @user - Manually unlink accounts
- `!validusers` - Show number of valid and invalid accounts
- `!cleanup` - Remove Jellyfin accounts from users without roles
- `!lastcleanup` - See Last cleanup time, and time remaining before next cleanup
- `!searchaccount` <jellyfin_username> - Find linked Discord user
- `!searchdiscord` @user - Find linked Jellyfin account
- `!scanlibraries` - Scan all Jellyfin libraries
- `!activestreams` - View all Active Jellyfin streams

***💾 qBittorrent Commands***

- `!qbview` - View current qBittorrent downloads

***🗳️ Proxmox Commands***

- `!storage` - Show available storage pools and free space
- `!metrics` - Show Jellyfin container metrics

***🔑 JFA Commands***

- `!createinvite` - Create a new JFA invite link
- `!listinvites` - List all active JFA invite links
- `!deleteinvite <code>` - Delete a specific JFA Invite
- `!refreshjfakey` - Refreshes the JFA API Key Forcefully

***⚙️ Admin Bot Commands***

- `!setprefix` - Change the bots command prefix
- `!stats` - View Local and Global Jellycord Stats
- `!update` - Download latest bot version
- `!backup` - Create a backup of the bot and configurations
- `!backups` - List backups of the bot
- `!restore` - Restore a backup of the bot
- `!version` - Manually check for bot updates
- `!changelog` - View changelog for current bot version
- `!logging` - Enable/Disable Console Event Logging