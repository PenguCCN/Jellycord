# 1.0.6

- Added Progress bar to Active Streams
- Added JFA-Go support for external invites

# 1.0.5

- Added Timezone support in .env
- Added the `what2watch` command. Lists 5 random movie suggestions from the Jellyfin Library
- Added `activestreams` command. Lists all active Jellyfin Streams

# 1.0.4

- Multi-Guild support (As long as a user has a required role or admin role in one server, they are able to use the bot and Jellyfin)
- Fixed link command instructions not updating based on Jellyseerr availability

# 1.0.3

- Fixed: `ValueError: too many values to unpack (expected 2)`
- Cleanup will now delete Jellyseerr accounts as well
- Added Trial Jellyfin account support (enable in .env). Will not create a Jellyseerr account, lasts 24 hours, one time use.

# 1.0.2

- Fixed Jellyseerr support breaking linking, unlinking, and deletion
- Added the ability to link Jellyseerr accounts when linking Jellyfin
- Added event logging support for console (Can be toggled in .env or with commands)
- Reformatted the updates message
- Running a command without any values will now show you the proper command usage

# 1.0.1

- Added Jellyseerr Support

# 1.0.0

- Bot can now track update releases
- Restrict prefixes to non-alphanumeric symbols