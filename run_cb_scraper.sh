#!/bin/bash

# CB Scraper Launcher
# This script properly sets up the environment and runs the CB scraper

cd "$(dirname "$0")"

# Run CB scraper with the venv Python
python cb_scraper.py "$@"
