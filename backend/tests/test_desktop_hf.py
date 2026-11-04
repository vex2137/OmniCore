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
        self.last_payload = args[0] if args else None
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
callback({'markdown':'# Card\n<p><strong>Readable</strong></p>\n<script>alert(1)</script>\n![x](file:///etc/passwd)'})
assert 'Card' in window.hf_readme.toPlainText()
assert 'Readable' in window.hf_readme.toPlainText()
assert '<strong>' not in window.hf_readme.toPlainText()
assert 'alert(1)' not in window.hf_readme.toPlainText()
assert window.hf_readme.loadResource(0,QUrl('file:///etc/passwd')) is None
window.downloads=[{'id':'one','percent':50,'speed_bytes_per_second':1024,'eta_seconds':10,'state':'running'}]
window.download_list.addItem('one','one'); window._show_download_progress()
assert window.download_progress.value()==50 and '10 s' in window.download_status.text()
assert not window.cancel_download_button.isHidden() and window.resume_download_button.isHidden()
window.downloads[0]['state']='failed'; window._show_download_progress()
assert window.cancel_download_button.isHidden() and not window.resume_download_button.isHidden()
window.downloads[0]['state']='completed'; window.downloads[0]['model_id']='ready'
window._show_download_progress(); assert window.import_download_button.isHidden()
window.hf_quant_filter.clear()
files([{'filename':'large-00001-of-00002.gguf','size_bytes':10},
       {'filename':'small-Q4.gguf','size_bytes':100},
       {'filename':'large-Q8.gguf','size_bytes':10000}])
assert window.hf_files.currentData()['filename']=='small-Q4.gguf'
window.hf_files.setCurrentIndex(window.hf_files.count()-1)
assert not window.download_button.isEnabled()
models=[{'id':'m1','name':'One','backend':'llama.cpp','metadata':{}},
        {'id':'m2','name':'Two','backend':'ollama','metadata':{}}]
window.models=models
window.model_combo.blockSignals(True)
window.model_combo.addItem('One','m1'); window.model_combo.addItem('Two','m2')
window.model_combo.setCurrentIndex(0); window.model_combo.blockSignals(False)
window.model_selected()
window.context_mode.setCurrentIndex(1); window.context_tokens.setValue(8192)
window.save_model_context()
assert api.last_payload=={'mode':'manual','manual_tokens':8192}
saved=api.requests[-1][1]
models[0]['metadata']['desktop_context']={'mode':'manual','manual_tokens':8192}
saved(models[0])
assert window.request_parameters()['context_size']==8192
window.model_combo.setCurrentIndex(1)
assert window.request_parameters()['context_size']==2048
window.model_combo.setCurrentIndex(0)
assert window.request_parameters()['context_size']==8192
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
