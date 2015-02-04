"""
An example NZB verification utility using ``asyncnntp``.
"""
import sys
sys.path.append("../")

import asyncnntp
import asyncore
import os
import time
import logging

try:
    from xml.etree import cElementTree as ET
except:
    from xml.etree import ElementTree as ET

HOST = "news.newshost.com"
PORT = 119
USER = "username"
PASS = "password"
CONN = 20

segments    = []
available   = []
missing     = []
unknown     = []
connections = []

class NNTP(asyncnntp.NNTP):
    def stat_next_article(self):
        """
        Grabs the next message-id from the queue and runs a STAT command.
        """
        if len(segments) > 0:
            message_id = "<%s>" % segments.pop()

            # Call the actual stat method
            self.stat(message_id)

    def on_ready(self):
        """
        Callback after the connection has been established and any
        authentication has been completed.  We use this as an entry point to
        begin checking message-ids.
        """
        # Start checking segments
        self.stat_next_article()

    def on_stat(self, request):
        """
        Callback after a STAT command has completed.
        
        According to the spec (https://tools.ietf.org/html/rfc3977)
        the following codes are possible:

            223 - Article exists
            430 - No article with that message-id
        """
        # A stat command looks like "STAT <message-id>".  In the ``request``
        # object ``command`` is "STAT" and ``args`` is ``('<message-id>',)``,
        # so the first argument is the requested message-id.
        message_id = request.args[0]
        
        if request.response_code == "223":
            # This segment is available
            available.append(message_id)
        elif request.response_code == "430":
            # This segment is not available
            missing.append(message_id)
        else:
            # Could be a different 4xx error or a 5xx error.  A better
            # implementation should check, but here we just mark it unknown.
            unknown.append(message_id)
        
        # Check the next message-id
        self.stat_next_article()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print "Usage: %s <nzb>" % sys.argv[0]
        sys.exit(1)
    
    # Uncomment to enable logging
    #logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    path = os.path.abspath(os.path.expanduser(sys.argv[1]))
    try:
        nzb = ET.parse(path)
    except:
        print "Couldn't parse NZB: %s" % path
        sys.exit(2)

    # Get all the segments from the NZB
    for segment in nzb.findall(".//{http://www.newzbin.com/DTD/2003/nzb}segment"):
        segments.append(segment.text)

    num_segments = len(segments)
    print "Found %d segments" % num_segments

    # Start the async loop - this runs in a separate thread
    asyncnntp.loop_forever(timeout=1, count=2)

    # Create the NNTP connections
    for i in range(CONN):
        connections.append(NNTP(HOST, PORT, USER, PASS))

    try:
        count = 0
        while count < num_segments:
            count = len(available) + len(missing) + len(unknown)
            
            # Print out the progress
            sys.stdout.write("\r%d/%d" % (count, num_segments))
            sys.stdout.flush()
            
            # Sleep for a bit to avoid looping too fast
            time.sleep(0.2)

        sys.stdout.write("...Done\n")

        print "Available = %s" % len(available)
        print "Missing   = %s" % len(missing)
        print "Unknown   = %s" % len(unknown)
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print "Exception = %s" % str(e)
    finally:
        # Disconnect all connections
        for conn in connections:
            conn.quit()
