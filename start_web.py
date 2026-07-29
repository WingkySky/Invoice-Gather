#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动Web服务器(不启动桌面窗口)"""

import sys
import os
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from http.server import ThreadingHTTPServer
from web.app import Handler

_server = None

def _sig_handler(signum, frame):
    global _server
    if _server:
        try:
            _server.shutdown()
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

_server = ThreadingHTTPServer(('127.0.0.1', 8000), Handler)
print('服务器已启动: http://127.0.0.1:8000')
try:
    _server.serve_forever()
except Exception:
    pass