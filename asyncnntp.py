"""
asyncnntp.py - An asynchronous NNTP client.
"""
import asyncore
import asynchat
import logging
import nntplib
import socket
import thread
import time

try:
    import ssl
except ImportError:
    _have_ssl = False
else:
    _have_ssl = True

CRLF = '\r\n'

SSL_PORTS = [443, 563]

LONG_RESP_CODES = ('100',      # HELP
                   '101',      # CAPABILITIES
                   '211',      # LISTGROUP (also GROUP, but *not* multi-line)
                   '215',      # LIST
                   '220',      # ARTICLE
                   '221',      # HEAD
                   '222',      # BODY
                   '224',      # OVER
                   '225',      # HDR
                   '230',      # NEWNEWS
                   '231',      # NEWGROUPS
                   '282')      # ???

LONG_RESP_COMMANDS = ('HELP',
                      'CAPABILITIES',
                      'LISTGROUP',
                      'LIST',
                      'ARTICLE',
                      'HEAD',
                      'BODY',
                      'OVER',
                      'HDR',
                      'NEWNEWS',
                      'NEWGROUPS')

COMMANDS = {
    "DATE":         ("111",),
    "HELP":         ("100",),
    "NEWGROUPS":    ("231",),
    "NEWNEWS":      ("230",),
    "LIST":         ("215",),
}


def loop_forever(target=None, *args, **kwargs):
    """
    Runs ``asyncore.loop`` in a separate thread. ``target`` should be a function
    to be called during the loop (can also be None).  ``args`` and ``kwargs``
    should be valid arguments to ``asyncore.loop``.  This function will return
    control to the calling thread.
    """
    def loop():
        while True:
            asyncore.loop(*args, **kwargs)
            if target:
                target()
    thread.start_new_thread(loop, ())

class Request:
    """
    
    """
    def __init__(self, command, *args, **kwargs):
        self.command          = command.upper()
        self.args             = args
        self.response_code    = None
        self.response_message = ""
        self.response_data    = []
        self.multiline        = self.command in LONG_RESP_COMMANDS
        self.lines            = None
        self.logger           = logging.getLogger("NNTP::Request")
        self.callback         = kwargs.get("callback", None)

    def __repr__(self):
        return "<%s>" % str(self)

    def __str__(self):
        return "Request: %s %s" % (self.command, " ".join(self.args))

    def getline(self):
        """
        Returns a fully formatted request, including terminating characters.
        """
        cmd = [self.command]
        for arg in self.args:
            if arg:
                cmd.append(str(arg))
        return " ".join(cmd).strip()+CRLF

    def getterminator(self):
        """
        Returns the appropriate terminator for the given request, depending on
        whether a single-line or multi-line response is expected.
        """
        if self.multiline:
            return "%s.%s" % (CRLF,CRLF)
        return CRLF

    def get_callback(self):
        return self.callback or "on_%s" % self.command.lower()

    def handle_data(self, data):
        """
        Called when data has been received from the socket.
        """
        self.logger.debug("handle_data()")
        self.response_data.append(data)

    def finish(self):
        """
        Called once all data has been received.
        """
        self.logger.debug("%s -> finish()" % self)
        self.lines = ''.join(self.response_data).split(CRLF)

        if len(self.lines) < 1:
            raise nntplib.NNTPDataError("No data received")

        self.response_code, self.response_message = self.lines[0][:3], \
                                                    self.lines[0][3:].strip()

        self.logger.debug("code = %s" % self.response_code)
        self.logger.debug("msg  = %s" % self.response_message)

class NNTP(asynchat.async_chat):
    """
    
    """
    def __init__(self, host, port=119, user=None, password=None,
                 readermode=None, usenetrc=True, use_ssl=None):

        self.host       = host
        self.port       = port
        self.__username = user
        self.__password = password
        self.logger     = logging.getLogger('NNTP')

        self.use_ssl = use_ssl
        if self.use_ssl is None:
            self.use_ssl = port in SSL_PORTS
        self.established = not self.use_ssl

        self._request = None
        self._fifo    = asynchat.fifo()

        asynchat.async_chat.__init__(self)

        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)

        self.connect((host, port))

        self._connected = False
        self.welcome    = ""

    def reconnect(self):
        self.socket.close()
        del self.socket

        if hasattr(self, "_socket"):
            self._socket.close()
            del self._socket

        self.established = not self.use_ssl
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((self.host, self.port))

    def _handshake(self):
        try:
            self.socket.do_handshake()
        except ssl.SSLError as err:
            self.logger.debug("SSL handshake not complete")
            self.want_read = self.want_write = False
            if err.args[0] == ssl.SSL_ERROR_WANT_READ:
                self.want_read = True
            elif err.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                self.want_write = True
            else:
                raise
        else:
            self.logger.debug("SSL handshake complete")
            self.want_read = self.want_write = True
            self.established = True

    def _do_callback(self, name, *args, **kwargs):
        # Try internal callback first
        _name = "_%s" % name
        if hasattr(self, _name):
            self.logger.debug("Calling %s()" % _name)
            getattr(self, _name)(*args, **kwargs)

        # Then try user-defined callback
        if hasattr(self, name):
            self.logger.debug("Calling %s()" % name)
            getattr(self, name)(*args, **kwargs)

    def handle_connect(self):
        """
        If SSL has been requested, this method will wrap the socket in SSL.  If
        SSL has been requested but is not available a ``ValueError`` will be
        raised.
        """
        self.logger.debug('handle_connect()')

        # Default terminator
        self.set_terminator(CRLF)

        # See if we need to wrap the socket in SSL
        if self.use_ssl:
            if not _have_ssl:
                self.logger.error("SSL requested but not available")
                raise ValueError("SSL not available")

            self.logger.debug('Wrapping in SSL')
            self._socket = self.socket
            self.socket = ssl.wrap_socket(self._socket,
                                          do_handshake_on_connect=False)

    def handle_write(self):
        """
        Overload the default ``handle_read`` method to support SSL handshake.
        """
        if self.established:
            return self.initiate_send()
        self._handshake()

    def recv(self, buffer_size):
        """
        The default ``recv`` function does not support SSL sockets which
        sometimes will fail when they appear readable but in fact aren't ready
        to be read yet.  This get's around that issue by catching the error.  If
        SSL isn't available (or enabled) then this behaves just like the default
        implementation.
        """
        try:
            return asynchat.async_chat.recv(self, buffer_size)
        except Exception as e:
            if _have_ssl:
                if isinstance(e, ssl.SSLWantReadError):
                    return ''
            raise e

    def _handle_read(self):
        """
        We can't use the default ``handle_read`` here because it doesn't support
        SSL sockets.  This fix is from: http://bugs.python.org/issue16976
        """
        try:
            data = self.recv (self.ac_in_buffer_size)
        except socket.error, why:
            self.handle_error()
            return

        if hasattr(self.socket, 'ssl_version'):
        # Fix for SSL wrapped sockets, checks if there is any data pending in
        # the SSL Socket's internal buffer and recv's it before contining.
            ssl_data_remainder = ''
            amount_of_data_left_over = self.socket.pending()
            while amount_of_data_left_over > 0:
                # while the ssl socket still has some data pending
                try:
                    # get the remaining data
                    ssl_data_remainder += self.recv(amount_of_data_left_over)
                except socket.error, why:
                    self.handle_error()
                    return
                # check if there is anymore remaining
                amount_of_data_left_over = self.socket.pending()
            data += ssl_data_remainder  # add the remainder to the data
        self.ac_in_buffer = self.ac_in_buffer + data

        # Continue to search for self.terminator in self.ac_in_buffer,
        # while calling self.collect_incoming_data.  The while loop
        # is necessary because we might read several data+terminator
        # combos with a single recv(4096).

        while self.ac_in_buffer:
            lb = len(self.ac_in_buffer)
            terminator = self.get_terminator()
            if not terminator:
                # no terminator, collect it all
                self.collect_incoming_data (self.ac_in_buffer)
                self.ac_in_buffer = ''
            elif isinstance(terminator, int) or isinstance(terminator, long):
                # numeric terminator
                n = terminator
                if lb < n:
                    self.collect_incoming_data (self.ac_in_buffer)
                    self.ac_in_buffer = ''
                    self.terminator = self.terminator - lb
                else:
                    self.collect_incoming_data (self.ac_in_buffer[:n])
                    self.ac_in_buffer = self.ac_in_buffer[n:]
                    self.terminator = 0
                    self.found_terminator()
            else:
                # 3 cases:
                # 1) end of buffer matches terminator exactly:
                #    collect data, transition
                # 2) end of buffer matches some prefix:
                #    collect data to the prefix
                # 3) end of buffer does not match any prefix:
                #    collect data
                terminator_len = len(terminator)
                index = self.ac_in_buffer.find(terminator)
                if index != -1:
                    # we found the terminator
                    if index > 0:
                        # don't bother reporting the empty string
                        # (source of subtle bugs)
                        self.collect_incoming_data (self.ac_in_buffer[:index])
                    self.ac_in_buffer = self.ac_in_buffer[index+terminator_len:]
                    # This does the Right Thing if the terminator
                    # is changed here.
                    self.found_terminator()
                else:
                    # check for a prefix of the terminator
                    index = asynchat.find_prefix_at_end (self.ac_in_buffer, terminator)
                    if index:
                        if index != lb:
                            # we found a prefix, collect up to the prefix
                            self.collect_incoming_data (self.ac_in_buffer[:-index])
                            self.ac_in_buffer = self.ac_in_buffer[-index:]
                        break
                    else:
                        # no prefix, collect it all
                        self.collect_incoming_data (self.ac_in_buffer)
                        self.ac_in_buffer = ''

    def handle_read(self):
        """
        Overload the default ``handle_read`` method to support SSL handshake
        and also use the custom ``_handle_read`` method.
        """
        if self.established:
            return self._handle_read()
        self._handshake()

    def collect_incoming_data(self, data):
        self.logger.debug('collect_incoming_data() -> (%d)', len(data))

        #print "data =", `data`
        if self._request is None:
            notempty, self._request = self._fifo.pop()

        if self._request is None:
            # If we still don't have a request, then we need to construct one
            self._request = Request("UNKNOWN")

        self._request.handle_data(data)

    def found_terminator(self):
        self.logger.debug('found_terminator()')

        # This should never happen
        if not self._request:
            self.logger.error('No request found')
            return

        # Finish the request
        self._request.finish()

        # Reset request
        request = self._request
        self._request = None

        # Reset terminator
        self.set_terminator(CRLF)

        if request.command == "UNKNOWN":
            # An "UNKNOWN" request means that we received an unsolicited
            # response from the server.  This happens on initial connection
            # to the server.  Some servers also disconnect the client due to
            # idleness
            code = request.response_code
            if code in ("200", "201"):
                self._do_callback("on_connect", request)
            elif code == "400":
                # XXX: Is this general enough?
                self._do_callback("on_disconnect", request)
            else:
                self.logger.warn("UNKNOWN Request; code %s" % request.response_code)

        # Get the name of the callback and try to call it
        callback = request.get_callback()
        self._do_callback(callback, request)

        # Send the next request in the FIFO
        self.sendrequest()

    def addrequest(self, request):
        """
        Adds a :class:`Request` to the request FIFO.  If there isn't a currently
        pending request then this will also initiate the request.
        """
        self._fifo.push(request)
        if self._request is None:
            self.sendrequest()

    def sendrequest(self):
        """
        Gets the next :class:`Request` from the request FIFO and sends the
        command to the server.
        """
        _, request = self._fifo.pop()

        if request:
            self._request = request

            terminator = self._request.getterminator()

            self.logger.debug("terminator = %s" % `terminator`)
            self.set_terminator(terminator)

            line = self._request.getline()
            self.logger.debug("sending command: %s" % line.strip())
            self.push(line)

    def ready(self):
        return self._connected

    ############################################################################
    # Client functions
    ############################################################################
    def username(self, username):
        """
        Send an
        `AUTHINFO USER <https://tools.ietf.org/html/rfc2980#section-3.1.1>`_
        command with the given ``username``.

        :callback: ``on_username``
        """
        self.addrequest(Request("AUTHINFO", "USER", username,
                                callback="on_username"))

    def password(self, password):
        """
        Send an
        `AUTHINFO PASS <https://tools.ietf.org/html/rfc2980#section-3.1.1>`_
        command with the given ``password``.

        :callback: ``on_username``.
        """
        self.addrequest(Request("AUTHINFO", "PASS", password,
                                callback="on_username"))

    def mode_reader(self):
        """
        :callback: ``on_mode_reader``
        """
        self.addrequest(Request("MODE READER", callback="on_mode_reader"))

    def quit(self):
        """
        Send a `QUIT <https://tools.ietf.org/html/rfc3977#section-5.4>`_
        command.

        :callback: ``on_quit``
        """
        self.addrequest(Request("QUIT", callback="on_quit"))

    def group(self, name):
        """
        Send a `GROUP <https://tools.ietf.org/html/rfc3977#section-6.1.1>`_
        command, where ``name`` is a `string` of the desired group.

        :callback: ``do_group``
        """
        self.addrequest(Request("GROUP", name, callback="on_group"))

    def listgroup(self, group=None, range=None):
        """
        Send a `LISTGROUP <https://tools.ietf.org/html/rfc3977#section-6.1.2>`_
        command.  If ``group`` is provided, then that group will be selected,
        otherwise the previously selected group will be used.  See link for 
        format of ``range``.

        :callback: ``on_listgroup``
        """
        self.addrequest(Request("LISTGROUP", group, range,
                                callback="on_listgroup"))

    def last(self):
        """
        Send a `LAST <https://tools.ietf.org/html/rfc3977#section-6.1.3>`_
        command.

        :callback: ``on_last``
        """
        self.addrequest(Request("LAST", callback="on_last"))

    def next(self):
        """
        Send a `NEXT <https://tools.ietf.org/html/rfc3977#section-6.1.4>`_
        command.

        :callback: ``on_next``
        """
        self.addrequest(Request("NEXT", callback="on_next"))

    def article(self, article):
        """
        Send a `ARTICLE <https://tools.ietf.org/html/rfc3977#section-6.2.1>`_
        command.  If a group has been selected (via a prior call to
        :func:`group`), then ``article`` can be an integer.  Alternativley,
        ``article`` can be a unique message-id string of the format
        ``<message-id>``.

        :callback: ``on_article``
        """
        self.addrequest(Request("ARTICLE", article, callback="on_article"))

    def head(self, article):
        """
        Send a `HEAD <https://tools.ietf.org/html/rfc3977#section-6.2.2>`_
        command.  See :func:`article` for a description of allowable forms for
        ``article``.

        :callback: ``on_head``
        """
        self.addrequest(Request("HEAD", article, callback="on_head"))

    def body(self, article):
        """
        Send a `BODY <https://tools.ietf.org/html/rfc3977#section-6.2.3>`_
        command.  See :func:`article` for a description of allowable forms for
        ``article``.

        :callback: ``on_body``
        """
        self.addrequest(Request("BODY", article, callback="on_body"))

    def stat(self, article):
        """
        Send a `STAT <https://tools.ietf.org/html/rfc3977#section-6.2.4>`_
        command.  See :func:`article` for a description of allowable forms for
        ``article``.

        :callback: ``on_stat``
        """
        self.addrequest(Request("STAT", article, callback="on_stat"))

    def date(self):
        """
        Send a `DATE <https://tools.ietf.org/html/rfc3977#section-7.1>`_
        command.

        :callback: ``on_date``
        """
        self.addrequest(Request("DATE", callback="on_date"))

    def list(self):
        """
        Send a `LIST <https://tools.ietf.org/html/rfc3977#section-7.6.1>`_
        command.

        :callback: ``on_list``
        """
        self.addrequest(Request("LIST", callback="on_list"))

    ############################################################################
    # Internal callback functions
    ############################################################################
    def _on_connect(self, request):
        self.welcome = request.response_message

        # If we were given a username, try to authenticate
        if self.__username:
            self.username(self.__username)
        else:
            self._connected = True
            self._do_callback("on_ready")

    def _on_quit(self, request):
        self._connected = False

    def _on_disconnect(self, request):
        self._connected = False

    def _on_username(self, request):
        if request.response_code == "381":
            # Password is required
            if self.__password:
                self.password(self.__password)
            else:
                self.logger.error("Password required but not provided")
        elif request.response_code == "281":
            self._connected = True
            self._do_callback("on_ready")

    def _on_password(self, request):
        if request.response_code == "281":
            self._connected = True
            self._do_callback("on_ready")
