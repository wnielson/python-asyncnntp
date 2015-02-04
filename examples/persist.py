"""
An example of a persistent NNTP client using ``asyncnntp``.  It detects an
"idle" disconnect and then reconnects
"""
import sys
sys.path.append("../")

import asyncnntp
import logging
import time

HOST = "news.newhost.com"
PORT = 119
USER = "username"
PASS = "password"

class NNTP(asyncnntp.NNTP):
    def on_disconnect(self, request):
        """
        Callback when the server disconnects us.
        
        This will ensure that if we're disconnected due to idleness that we
        reconnect.
        """
        if "idle" in request.response_message.lower():
            self.logger.info("Reconnecting...")
            self.reconnect()

        def on_ready(self, request):
            """
            Once this is called we are fully connected and authenticated.
            """
            self.logger.info("Connected!")

if __name__ == "__main__":
    # Enable logging
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    # Start networking loop in a separate thread
    asyncnntp.loop_forever(timeout=1, count=2)

    # Create a NNTP connection
    conn = NNTP(HOST, PORT, USER, PASS)

    # Just loop until killed
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, Exception):
        pass
    finally:
        # Manually close the connection, note this will fire the
        # ``on_quit`` callback and not the ``on_disconnect`` callback
        conn.quit()
