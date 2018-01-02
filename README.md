# Hawken Scrimbot

Hawken Scrimbot is a chat bot that integrates into [Hawken's](https://www.playhawken.com/) XMPP chat server (which backs the friends list functionality of [Hawken](https://www.playhawken.com/)), and provides various miscellaneous functions. It is made in Python 3.x, and built on top of the [Hawken Python API library](https://github.com/ashfire908/hawken-api "Currently closed-source") and [a fork](https://github.com/ashfire908/SleekXMPP/tree/hwk) of the [SleekXMPP library](http://sleekxmpp.com/).

## History

Scrimbot was originally designed as a project to facilitate PUG (or Pick Up Games) as part of the IRC channel #hawkenscrim on QuakeNet. It began life as a proof of concept after the "Ascension Update" added cross-match parties and the ability to deploy groups of players directly into matches. However, due to a bug in the player reservation system for game servers, it was impossible to bring two parties directly into a server (via proxy user). Thus, the bot was converted over into just a project for various other minor tasks. It ran from 2013 until late 2017 when it was shut down. In January 2018, after the PC version of Hawken was shut down, the code is now being made open source, as it no longer can operate (as the console versions of the game do not operate an XMPP server).

## Features

Scrimbot was designed as a plugin-based system, inspired by [Supybot](https://github.com/Supybot/Supybot)/[Limnoria](https://github.com/ProgVal/Limnoria). It has a number of core features, and then user functionality is provided via various plugins that can be loaded or unloaded.

Core features:
- Central config management (backed by JSON file)
- Command parsing (with aliasing and permission integration)
- Hawken API library integration (for XMPP authentication and various other calls)
- Support for Hawken parties and player reservations
- Group-based permission system
- Logging system
- Basic in-memory cache (backed by JSON file)

Plugins:
- Admin - Various bot management commands
- Info - A plugin providing information and help for the bot
- Pager - Internal plugin used for paging specific people IRL directly from the bot
- Party Rank - Provides MMR information for players in a party
- Player Rank - Provides MMR information for a single player
- Quality - A reimplementation of the match quality system in Hawken, fed using the same parameters
- Scrim - A plugin implementing a bot driven party, intended for use with organized matches
- Server Rank - Provides MMR information for a server
- Spectator - Player reservation placing framework to facilitate spectating a server
- Test - Various testing commands for the bot
- Tracker - Integration with the incomplete [Hawken "Tracker" project](https://github.com/ashfire908/hawken-tracker), allowing users to opt out

## License

Scrimbot is released under the [MIT LICENSE](LICENSE).
