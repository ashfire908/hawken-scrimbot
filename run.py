#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from scrimbot import ScrimBot

if __name__ == "__main__":
    # Config logging
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)-15s %(levelname)-8s %(message)s")

    # Run the bot
    hawkenbot = ScrimBot()
    logging.info("Starting the bot...")
    if hawkenbot.connect():
        try:
            hawkenbot.process(block=True)
        except KeyboardInterrupt:
            hawkenbot.disconnect(wait=True)
        logging.info("Bot shutting down.")
    else:
        logging.critical("Unable to connect.")
