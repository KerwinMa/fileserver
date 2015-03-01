# -*- coding: utf-8 -*-
"""HTTP auth utilities."""
"""
  Kontalk Fileserver
  Copyright (C) 2015 Kontalk Devteam <devteam@kontalk.org>

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""


from OpenSSL import SSL

from zope.interface import implements

from twisted.web.resource import IResource, ErrorPage
from twisted.web import util as webutil
from twisted.cred import error
from twisted.cred.credentials import Anonymous
from twisted.python.components import proxyForInterface

import log


class UnauthorizedResource(object):
    """
    Simple IResource to escape Resource dispatch
    """
    implements(IResource)
    isLeaf = True


    def render(self, request):
        request.setResponseCode(401)
        if request.method == 'HEAD':
            return ''
        return 'Unauthorized'


    def getChildWithDefault(self, path, request):
        """
        Disable resource dispatch
        """
        return self


class HTTPSAuthSessionWrapper(object):
    """
    Wrap a portal, enforcing SSL client certificate authentication.

    @ivar _portal: The L{Portal} which will be used to retrieve L{IResource}
        avatars.
    @ivar _credential: Credential class that will be passed the peer certificate.
    """
    implements(IResource)
    isLeaf = False

    def __init__(self, portal, credential):
        """
        Initialize a session wrapper

        @type portal: C{Portal}
        @param portal: The portal that will authenticate the remote client

        @type credential: C{ICredentials}
        @param credential: Credential class to be instanciated with the peer certificate
        """
        self._portal = portal
        self._credential = credential


    def _authorizedResource(self, request):
        """
        Get the L{IResource} which the given request is authorized to receive.
        If the proper authorization headers are present, the resource will be
        requested from the portal.  If not, an anonymous login attempt will be
        made.
        """
        cert = request.channel.transport.getPeerCertificate()

        # Anonymous access if no certificate
        if not cert:
            return webutil.DeferredResource(self._login(Anonymous()))

        # TODO hard-coded to Kontalk usage
        return webutil.DeferredResource(self._login(self._credential(cert)))


    def render(self, request):
        """
        Find the L{IResource} avatar suitable for the given request, if
        possible, and render it.  Otherwise, perhaps render an error page
        requiring authorization or describing an internal server failure.
        """
        return self._authorizedResource(request).render(request)


    def getChildWithDefault(self, path, request):
        """
        Inspect the Authorization HTTP header, and return a deferred which,
        when fired after successful authentication, will return an authorized
        C{Avatar}. On authentication failure, an C{UnauthorizedResource} will
        be returned, essentially halting further dispatch on the wrapped
        resource and all children
        """
        # Don't consume any segments of the request - this class should be
        # transparent!
        request.postpath.insert(0, request.prepath.pop())
        return self._authorizedResource(request)


    def _login(self, credentials):
        """
        Get the L{IResource} avatar for the given credentials.

        @return: A L{Deferred} which will be called back with an L{IResource}
            avatar or which will errback if authentication fails.
        """
        d = self._portal.login(credentials, None, IResource)
        d.addCallbacks(self._loginSucceeded, self._loginFailed)
        return d


    def _loginSucceeded(self, (interface, avatar, logout)):
        """
        Handle login success by wrapping the resulting L{IResource} avatar
        so that the C{logout} callback will be invoked when rendering is
        complete.
        """
        class ResourceWrapper(proxyForInterface(IResource, 'resource')):
            """
            Wrap an L{IResource} so that whenever it or a child of it
            completes rendering, the cred logout hook will be invoked.

            An assumption is made here that exactly one L{IResource} from
            among C{avatar} and all of its children will be rendered.  If
            more than one is rendered, C{logout} will be invoked multiple
            times and probably earlier than desired.
            """
            def getChildWithDefault(self, name, request):
                """
                Pass through the lookup to the wrapped resource, wrapping
                the result in L{ResourceWrapper} to ensure C{logout} is
                called when rendering of the child is complete.
                """
                return ResourceWrapper(self.resource.getChildWithDefault(name, request))

            def render(self, request):
                """
                Hook into response generation so that when rendering has
                finished completely (with or without error), C{logout} is
                called.
                """
                request.notifyFinish().addBoth(lambda ign: logout())
                return super(ResourceWrapper, self).render(request)

        return ResourceWrapper(avatar)


    def _loginFailed(self, result):
        """
        Handle login failure by presenting either another challenge (for
        expected authentication/authorization-related failures) or a server
        error page (for anything else).
        """
        if result.check(error.Unauthorized, error.LoginFailed):
            return UnauthorizedResource()
        else:
            log.error(
                "HTTPAuthSessionWrapper.getChildWithDefault encountered "
                "unexpected error (%s)" % (result, ))
            return ErrorPage(500, None, None)


    def _selectParseHeader(self, header):
        """
        Choose an C{ICredentialFactory} from C{_credentialFactories}
        suitable to use to decode the given I{Authenticate} header.

        @return: A two-tuple of a factory and the remaining portion of the
            header value to be decoded or a two-tuple of C{None} if no
            factory can decode the header value.
        """
        elements = header.split(' ')
        scheme = elements[0].lower()
        for fact in self._credentialFactories:
            if fact.scheme == scheme:
                return (fact, ' '.join(elements[1:]))
        return (None, None)

class MyOpenSSLCertificateOptions(object):

    _context = None
    # Older versions of PyOpenSSL didn't provide OP_ALL.  Fudge it here, just in case.
    _OP_ALL = getattr(SSL, 'OP_ALL', 0x0000FFFF)
    method = SSL.SSLv23_METHOD
    options = SSL.OP_NO_SSLv3 | SSL.OP_NO_SSLv2

    def __init__(self, privateKeyFile=None, certificateFile=None, verifyCallback=None, enableSingleUseKeys=True):
        self.privateKeyFile = privateKeyFile
        self.certificateFile = certificateFile
        self._verifyCallback = verifyCallback
        self.enableSingleUseKeys = enableSingleUseKeys

    def getContext(self):
        """Return a SSL.Context object.
        """
        if self._context is None:
            self._context = self._makeContext()
        return self._context


    def _makeContext(self):
        ctx = SSL.Context(self.method)
        ctx.set_options(self.options)

        if self.certificateFile is not None and self.privateKeyFile is not None:
            ctx.use_certificate_chain_file(self.certificateFile)
            ctx.use_privatekey_file(self.privateKeyFile)
            # Sanity check
            ctx.check_privatekey()

        verifyFlags = SSL.VERIFY_NONE
        if self._verifyCallback:
            verifyFlags = SSL.VERIFY_PEER

            ctx.set_verify(verifyFlags, self._verifyCallback)

        if self.enableSingleUseKeys:
            ctx.set_options(SSL.OP_SINGLE_DH_USE)

        return ctx
