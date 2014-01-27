#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
import json
from scrimbot.bot import ScrimBot
from scrimbot.util import default_logging, setup_logging

logger = logging.getLogger("scrimbot")


def get_parser():
    parser = argparse.ArgumentParser(description="Hawken chat bot for facilitating scrims and competitive play.")
    parser.add_argument("-c", "--config", default="config.json", help="filename of the config to use")
    return parser


def bootstrap_logging(config):
    # Load in the logging config
    try:
        config_file = open(config)
        try:
            config_data = json.load(config_file)
        finally:
            config_file.close()
    except IOError:
        log_config = default_logging()
    except ValueError:
        log_config = default_logging()
    else:
        try:
            log_config = config_data["bot"]["logging"]
        except KeyError:
            log_config = default_logging()

    # Setup the logging
    setup_logging(log_config)


def run(config):
    # Bootstrap logging
    bootstrap_logging(config)

    # Init the bot
    logger.info("Initializing the bot...")
    hawkenbot = ScrimBot(config)

    # Connect to chat and process data
    logger.info("Connecting to chat...")
    if hawkenbot.connect():
        hawkenbot.process(block=True)
    else:
        logger.critical("Unable to connect.")


if __name__ == "__main__":
    # Parse the args
    args = get_parser().parse_args()

    # Start the bot
    run(args.config)
