"""Exercise the actual widgets in an isolated offscreen Qt application."""

import os
import subprocess
import sys


def test_model_browser_filters_card_and_download_progress():
    code = r"""
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtWidgets import QApplication
from omnicore.desktop.window import MainWindow
from omnicore.desktop.config import DesktopConfig
class API(QObject):
    error=Signal(str); snapshot=Signal(dict); stream_closed=Signal()
    def __init__(self): super().__init__(); self.requests=[]
    def request(self, method, url, *args, **kwargs):
        self.requests.append((url,kwargs.get('success')))
class Session(QObject):
    ready=Signal(); failed=Signal(str); log=Signal(str); stopped=Signal()
    owned=False
app=QApplication([])
api=API(); window=MainWindow(api,Session(),DesktopConfig(locale='en-US'))
window.popular_hf(); url, callback=api.requests.pop(); assert 'sort=downloads' in url
callback([{'repository':'author/model','license':'mit'}])
assert len(api.requests)==2
files=next(callback for url,callback in api.requests if '/files?' in url)
details=next(callback for url,callback in api.requests if '/details?' in url)
api.requests.clear()
files([{'filename':'model-Q4.gguf','size_bytes':1024},
       {'filename':'model-Q8.gguf','size_bytes':2048}])
window.hf_quant_filter.setText('Q8'); assert window.hf_files.count()==1
assert window.hf_files.currentData()['filename']=='model-Q8.gguf'
details({'author':'author','license':'mit','revision':'a'*40,'tags':[]})
assert 'Author: author' in window.hf_detail.text()
url, callback=api.requests.pop(); assert '/readme?' in url
callback({'markdown':'# Card\n<script>alert(1)</script>\n![x](file:///etc/passwd)'})
assert 'Card' in window.hf_readme.toPlainText()
assert window.hf_readme.loadResource(0,QUrl('file:///etc/passwd')) is None
window.downloads=[{'id':'one','percent':50,'speed_bytes_per_second':1024,'eta_seconds':10,'state':'running'}]
window.download_list.addItem('one','one'); window._show_download_progress()
assert window.download_progress.value()==50 and '10 s' in window.download_status.text()
window._poll.stop()
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(  # noqa: S603 - fixed local test program
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
