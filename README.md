# Jellycord

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/BannerRound.png)

[![Online Members](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdiscordapp.com%2Fapi%2Finvites%2FBkmEarDQxq%3Fwith_counts%3Dtrue&query=approximate_presence_count&style=for-the-badge&logo=discord&logoColor=white&label=ONLINE%20MEMBERS&labelColor=grey&color=239eda)](https://discord.gg/BkmEarDQxq)
![Latest Version:](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FPenguCCN%2FJellycord%2Fmain%2Fversion.json&query=%24.version&style=for-the-badge&logo=python&logoColor=white&color=239eda)

Allow the creation and management of Jellyfin users via Discord

Join my [Discord](https://discord.com/invite/zJMUNCPtPy) for help, and keeping an eye out for updates!

This is a very simple and lightweight Jellyfin Discord bot for managing users. It allows for creation of accounts, password recovery, account deletion, ect.

Fill out values in the .env and you're good to go!

## Features

- Automatic Account Cleanup
- Creating Accounts
- Recovering Passwords
- Searching accounts by Discord User, or Jellyfin User
- Run Library Scanning
- Manual Account Linking (For previously made Jellyfin accounts)
- Change bot prefix live
- Checks for new releases

## Command Overview

**Pinging the bot will show you the necessary commands to create your account.**

**PLEASE NOTE BEFORE USING. THIS BOT IS MEANT TO USE REQUIRED ROLES IN ORDER TO WHITELIST USERS FOR JELLYFIN. TAKING A USERS ROLE AWAY WILL DELETE THEIR JELLYFIN ACCOUNT WHEN THE BOT RUNS ITS CLEANUP (24 Hour Schedule or Admin Forced)**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/ping.png)

**There are protections in place to stop users from creating an account where people can see. If a user sends the account creation or reset in a guild, the bot will delete it.**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/account-deny.png)

**If a user already has a linked Jellyfin account, the bot will not allow them to create another account.**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/account-limit.png)

**In order to create an account, you must have the required roles specified in the .env**

![image](https://cdn.pengucc.com/images/projects/jellycord/readme/role-required.png)

***User Commands***
- `!createaccount` <username> <password> - Create your Jellyfin account
- `!recoveraccount` <username> <newpassword> - Reset your password
- `!deleteaccount` <username> - Delete your Jellyfin account
- `!trialaccount` <username> <password> - Create a 24-hour trial Jellyfin account. Only if ENABLE_TRIAL_ACCOUNTS=True

***Admin Commands***
- `!cleanup` - Remove Jellyfin accounts from users without roles
- `!lastcleanup` - See Last cleanup time, and time remaining before next cleanup
- `!searchaccount` <jellyfin_username> - Find linked Discord user
- `!searchdiscord` @user - Find linked Jellyfin account
- `!scanlibraries` - Scan all Jellyfin libraries
- `!link` <jellyfin_username> @user - Manually link accounts
- `!unlink` @user - Manually unlink accounts

***Admin Bot Commands***
- `!setprefix` - Change the bots command prefix
- `!updates` - Manually check for bot updates
- `!logging` - Enable/Disable Console Event Logging