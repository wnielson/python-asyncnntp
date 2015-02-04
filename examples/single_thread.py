"""
An example that runs everything in a single thread.
"""
import sys
sys.path.append("../")

import asyncnntp
import asyncore
import logging
import time

HOST = "news.newhost.com"
PORT = 119
USER = "username"
PASS = "passwor"

if __name__ == "__main__":
    # Enable logging
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    # Create a NNTP connection
    conn = asyncnntp.NNTP(HOST, PORT, USER, PASS)

    while not conn.ready():
        # Pump the asyncore loop manually
        asyncore.loop(timeout=1, count=1)

    # Not we're connected, let's issue a "DATE" command
    conn.date()

   	# Wait till we're killed
    while True:
        # Pump the asyncore loop manually
        asyncore.loop(timeout=1, count=1)

    conn.quit()
