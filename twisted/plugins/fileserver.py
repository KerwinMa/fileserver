# -*- coding: utf-8 -*-
"""twistd plugin for Dropbox fileserver."""
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


import demjson

from zope.interface import implements

from twisted.python import usage
from twisted.plugin import IPlugin
from twisted.application.service import IServiceMaker, MultiService

from kontalk.fileserver import log


class Options(usage.Options):
    optParameters = [["config", "c", "fileserver.conf", "Configuration file."]]


class KontalkFileserverServiceMaker(object):
    implements(IServiceMaker, IPlugin)
    tapname = "kontalk-fileserver"
    description = "Kontalk Dropbox Fileserver."
    options = Options

    def makeService(self, options):
        from kontalk.fileserver.fileserver import Fileserver

        # load configuration
        fp = open(options['config'], 'r')
        config = demjson.decode(fp.read(), allow_comments=True)
        fp.close()

        log.init(config)

        appl = MultiService()
        comp = Fileserver(config)
        comp.setServiceParent(appl)
        comp.setup().setServiceParent(appl)

        return appl

serviceMaker = KontalkFileserverServiceMaker()
