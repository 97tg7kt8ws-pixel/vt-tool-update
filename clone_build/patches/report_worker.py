import random
import time
from PyQt6.QtCore import QThread, pyqtSignal


class ReportWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, api, item, user_id, reason_id=0, message=''):
        super().__init__()
        self.api = api
        self.item = item
        self.user_id = user_id
        self.reason_id = reason_id
        self.message = message

    def run(self):
        try:
            result = self.api.report_item(self.item, self.user_id, self.reason_id, self.message)
            self.finished.emit(bool(result.get('success')), str(result.get('message', '')))
        except Exception as e:
            self.finished.emit(False, f'Worker Error: {e}')


class BatchReportWorker(QThread):
    progress_updated = pyqtSignal(int, int, int, int, str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal(int, int)

    def __init__(self, api, items, user_id, reason_id=376, message=''):
        super().__init__()
        self.api = api
        self.items = list(items or [])
        self.user_id = user_id
        self.reason_id = reason_id
        self.message = message
        self.is_running = True

    def run(self):
        success_count = 0
        fail_count = 0
        consecutive_fails = 0
        total = len(self.items)
        for i, item in enumerate(self.items, 1):
            if not self.is_running or self.isInterruptionRequested():
                break
            try:
                item_id = item.get('id') if isinstance(item, dict) else item
                result = self.api.report_item(item_id, self.user_id, self.reason_id, self.message)
                if result.get('success'):
                    success_count += 1
                    consecutive_fails = 0
                else:
                    fail_count += 1
                    consecutive_fails += 1
                msg = str(result.get('message', ''))
                self.progress_updated.emit(i, total, success_count, fail_count, msg)
                # Matches the original app's modest per-item pacing.
                if i < total and self.is_running:
                    time.sleep(random.uniform(0.5, 1.5))
            except Exception as e:
                fail_count += 1
                consecutive_fails += 1
                self.error_occurred.emit(f'Worker Error: {e}')
                self.progress_updated.emit(i, total, success_count, fail_count, str(e))
            # Avoid endlessly hammering a dead/expired session.
            if consecutive_fails >= 5:
                self.error_occurred.emit('连续多次举报失败，已自动停止，请重新同步登录 Cookie 后再试。')
                break
        self.finished.emit(success_count, fail_count)

    def stop(self):
        self.is_running = False
        self.requestInterruption()