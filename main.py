import sys
import os
import time
import threading
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

_server = None
_server_port = None


def _sig_handler(signum, frame):
    global _server
    if _server:
        try:
            _server.shutdown()
        except Exception:
            pass
    sys.exit(0)


def start_server():
    global _server, _server_port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    _server_port = sock.getsockname()[1]
    sock.close()

    from http.server import ThreadingHTTPServer
    from web.app import Handler
    _server = ThreadingHTTPServer(('127.0.0.1', _server_port), Handler)
    try:
        _server.serve_forever()
    except Exception:
        pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    time.sleep(2)

    import webview
    url = f'http://127.0.0.1:{_server_port}'
    window = webview.create_window(
        '票归集',
        url,
        width=1280,
        height=850,
        min_size=(960, 640),
        resizable=True,
        text_select=True,
        confirm_close=True,
    )

    def _on_closed():
        global _server
        if _server:
            try:
                _server.shutdown()
            except Exception:
                pass

    window.events.closed += _on_closed

    webview.start()