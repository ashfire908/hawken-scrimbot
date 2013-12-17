#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from scrimbot import ScrimBot

if __name__ == "__main__":
    # Config logging
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)-15s %(levelname)-8s %(name)s %(message)s")

    # Run the bot
    hawkenbot = ScrimBot()
    logging.info("Starting the bot...")
    if hawkenbot.connect():
        hawkenbot.process(block=True)
    else:
        logging.critical("Unable to connect.")
