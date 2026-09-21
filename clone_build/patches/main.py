import os, sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QMessageBox, QDialog
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtCore import QTimer

from ui.styles import STYLESHEET, SEARCH_BTN_LOADING_STYLE
from ui.sidebar import Sidebar
from ui.product_grid import ProductGrid
from ui.product_card import ProductCard
from ui.history_panel import HistoryPanel
from ui.toast import ToastNotification
from ui.dialog import CustomConfirmDialog, ReportDialog
from ui.login import LoginDialog
from api.client import VintedAPI
from utils.image_loader import ImageLoader
from core.history_manager import HistoryManager
from core.cookie_server import CookieServer
from core.constants import COUNTRY_NAMES, DOMAINS
from workers.search_worker import SearchWorker
from workers.user_worker import UserInfoWorker
from workers.report_worker import ReportWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Vinted 助手')
        self.resize(1280, 800)
        icon_path=os.path.join(os.path.dirname(__file__),'assets','Dragonflycap.png')
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))

        self.api=VintedAPI(); self.image_loader=ImageLoader(); self.history_manager=HistoryManager()
        self.current_user_id=None; self.current_country_code=None; self.accumulated_items=[]; self.current_search_params={}; self.worker=None; self.user_worker=None; self.report_worker=None; self._report_queue=[]; self._report_queue_meta=None

        self.cookie_server=CookieServer(port=19527)
        self.cookie_server.cookie_received.connect(self.on_extension_cookie_received)
        self.cookie_server.start()

        central=QWidget(); central.setObjectName('CentralWidget'); self.setCentralWidget(central)
        main_layout=QHBoxLayout(central); main_layout.setContentsMargins(0,0,0,0); main_layout.setSpacing(0)
        self.sidebar=Sidebar(); self.sidebar.set_api(self.api); main_layout.addWidget(self.sidebar)
        self.product_grid=ProductGrid(); main_layout.addWidget(self.product_grid,1)
        self.history_panel=HistoryPanel(); self.history_panel.setFixedWidth(250); main_layout.addWidget(self.history_panel)

        self.toast=ToastNotification(self)
        self.sidebar.user_info.set_expiration_text('免费版')
        self.sidebar.search_btn.clicked.connect(self.start_search)
        self.sidebar.cookie_mode_widget.mode_changed.connect(self.on_cookie_mode_changed)
        self.sidebar.cookie_mode_widget.guest_cookie_ready.connect(self.on_guest_cookie_ready)
        self.sidebar.user_info.logout_clicked.connect(self.handle_logout)
        self.sidebar.report_btn.clicked.connect(self.on_batch_report_requested)
        self.history_panel.history_selected.connect(self.on_history_selected)
        self.history_panel.delete_requested.connect(self.on_history_delete)
        self.history_panel.clear_all_requested.connect(self.on_clear_all_history)
        self.refresh_history()
        QTimer.singleShot(800, self.show_disclaimer)

    def on_cookie_mode_changed(self, mode):
        if mode=='guest': self.sidebar.country_display.set_active(False,'等待识别...')
        else: self.sidebar.country_display.set_active(False,'等待扩展发送...')

    def on_guest_cookie_ready(self, result):
        if result.get('success'):
            code=result.get('country_code','fr'); self.current_country_code=code
            name=COUNTRY_NAMES.get(code,code)
            display=('UK' if code=='co.uk' else 'US' if code=='com' else code.upper())
            self.sidebar.country_display.set_active(True,f'{display} {name}',code)
        else:
            self.sidebar.country_display.set_active(False,'获取失败')

    def on_extension_cookie_received(self, cookie_json, domain):
        try:
            if self.api.set_cookie(cookie_json):
                self.sidebar.cookie_mode_widget.set_login_cookie_received(domain)
                code=next((k for k,v in DOMAINS.items() if v in (domain or '')),None) or getattr(self.api,'_current_country_code','fr')
                self.current_country_code=code
                name=COUNTRY_NAMES.get(code,code); display=('UK' if code=='co.uk' else 'US' if code=='com' else code.upper())
                self.sidebar.country_display.set_active(True,f'{display} {name}',code)
                self.user_worker=UserInfoWorker(self.api); self.user_worker.finished.connect(self.on_user_info_loaded); self.user_worker.start()
        except Exception as e:
            QMessageBox.warning(self,'提示',f'Cookie 处理失败: {e}')

    def on_user_info_loaded(self, user_info, avatar_bytes):
        if user_info:
            pixmap=QPixmap()
            if avatar_bytes: pixmap.loadFromData(avatar_bytes)
            self.current_user_id=user_info.get('user_id')
            self.sidebar.user_info.set_user_info(user_info.get('username','Unknown User'),'Online',pixmap if not pixmap.isNull() else None)
        else:
            self.current_user_id=None; self.sidebar.user_info.reset_to_default(); self.sidebar.user_info.set_expiration_text('免费版')

    def show_disclaimer(self):
        content=('本软件仅供市场调研及数据分析使用。\n\n'
                 '1. 严禁使用本软件从事任何违反法律法规的活动。\n\n'
                 '2. 用户需自行承担因不当使用产生的一切法律责任。\n\n'
                 '3. 严禁用于网络攻击等恶意行为。\n\n'
                 '4. 请遵守目标网站的使用协议，合理使用。\n\n'
                 '点击【同意并继续】即代表您已阅读并接受本条款。')
        dlg=CustomConfirmDialog(self,'使用须知与免责声明',content,'同意并继续',True)
        if dlg.exec()!=QDialog.DialogCode.Accepted:
            self.close()

    def handle_logout(self):
        self.api=VintedAPI(); self.sidebar.set_api(self.api); self.current_user_id=None; self.current_country_code=None
        self.sidebar.user_info.reset_to_default(); self.sidebar.user_info.set_expiration_text('免费版'); self.sidebar.cookie_mode_widget.reset_status(); self.sidebar.country_display.set_active(False,'等待识别...')
        self.toast.show_message('已退出登录', True)

    def stop_all_tasks(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.worker.wait(1200)
            if self.worker.isRunning(): self.worker.terminate(); self.worker.wait(300)
        if self.report_worker and self.report_worker.isRunning():
            try:
                if hasattr(self.report_worker,'stop'): self.report_worker.stop()
                else: self.report_worker.requestInterruption()
                self.report_worker.wait(1500)
            except Exception: pass
        self.image_loader.clear_queue()

    def start_search(self):
        self.stop_all_tasks()
        try:
            per_page=int(self.sidebar.per_page_input.text().strip())
            if not 1<=per_page<=500: raise ValueError
        except Exception:
            QMessageBox.warning(self,'提示','每页数量必须在 1-500 之间！'); return
        mode=self.sidebar.cookie_mode_widget.current_mode
        if mode=='guest' and not self.sidebar.cookie_mode_widget.is_ready():
            QMessageBox.warning(self,'提示','请先点击「自动获取」获取 Cookie！'); return
        if mode=='login' and not self.sidebar.cookie_mode_widget.is_ready():
            QMessageBox.warning(self,'提示','请使用浏览器扩展发送 Cookie！'); return
        brand_id=self.sidebar.get_selected_brand_id()
        params={
            'search_text':self.sidebar.search_input.text().strip(), 'per_page':per_page,
            'price_min':self.sidebar.min_price.text().strip() or None, 'price_max':self.sidebar.max_price.text().strip() or None,
            'status_text':self.sidebar.status_combo.currentText(), 'sort_by_popularity':self.sidebar.sort_check.isChecked(),
            'sort_by_newest':self.sidebar.newest_check.isChecked(), 'brand_ids':[brand_id] if brand_id else []
        }
        self.current_search_params=params.copy(); self.accumulated_items=[]; self.product_grid.clear_cards(); self.worker_has_error=False
        self.sidebar.search_btn.setText('正在查询...'); self.sidebar.search_btn.setIcon(self.sidebar.search_icon_loading); self.sidebar.search_btn.setEnabled(False); self.sidebar.search_btn.setStyleSheet(SEARCH_BTN_LOADING_STYLE)
        self.worker=SearchWorker(self.api,params); self.worker.item_ready.connect(self.add_single_card); self.worker.error_occurred.connect(self.on_error); self.worker.finished_search.connect(self.on_finished); self.worker.start()

    def add_single_card(self,item):
        self.accumulated_items.append(item); card=ProductCard(item,self.image_loader); card.report_requested.connect(self.handle_report_item); self.product_grid.add_card(card)

    def on_error(self,error_msg):
        self.worker_has_error=True
        if '401' in error_msg or 'Unauthorized' in error_msg: QMessageBox.warning(self,'查询出错','Cookie 已过期，请重新获取！')
        else: QMessageBox.warning(self,'查询出错',str(error_msg))

    def on_finished(self):
        self.sidebar.search_btn.setText('开始查询'); self.sidebar.search_btn.setIcon(self.sidebar.search_icon_normal); self.sidebar.search_btn.setEnabled(True); self.sidebar.search_btn.setStyleSheet('')
        if self.accumulated_items:
            self.history_manager.save_history(self.current_search_params,self.accumulated_items); self.refresh_history()
        elif not self.worker_has_error:
            QMessageBox.information(self,'提示','未找到相关商品')

    def _find_item_by_id(self,item_id):
        for item in self.accumulated_items:
            try:
                if int(item.get('id'))==int(item_id):
                    return item
            except Exception:
                continue
        return None

    def _report_login_ready(self):
        if self.sidebar.cookie_mode_widget.current_mode != 'login':
            self.toast.show_message('访客模式不支持举报，请切换到登录模式', False)
            return None
        if not self.sidebar.cookie_mode_widget.is_ready():
            self.toast.show_message('请先同步登录 Cookie', False)
            return None

        # Re-read the authenticated user immediately before reporting.
        # This mirrors the recovered original EXE and prevents a stale
        # asynchronously cached self.current_user_id from being used after
        # Cookie re-sync/account switching.
        user_info = self.api.get_current_user(force=True)
        if not user_info or not user_info.get('user_id'):
            self.toast.show_message('登录过期，请重新同步', False)
            return None
        self.current_user_id = user_info.get('user_id')
        return user_info

    def handle_report_item(self,item_or_id):
        user_info=self._report_login_ready()
        if not user_info:
            return
        # New cards emit the complete item object so a report never depends on
        # accumulated_items/history cache timing. Keep id lookup for old cards.
        item=item_or_id if isinstance(item_or_id,dict) else self._find_item_by_id(item_or_id)
        if not item:
            self.toast.show_message('未找到该商品信息', False); return
        self.toast.show_message('正在读取 Vinted 当前举报原因…', True)
        live=self.api.get_report_reasons(item)
        if not live.get('success'):
            self.toast.show_message(live.get('message','无法读取当前举报原因'), False); return
        dlg=ReportDialog(self,is_batch=False,count=1,reasons=live.get('reasons'))
        if dlg.exec()!=QDialog.DialogCode.Accepted:
            return
        reason_id,message=dlg.get_data()
        if not reason_id:
            self.toast.show_message('未选择有效的举报原因',False); return
        self._start_single_report(item, user_info.get('user_id'), reason_id, message)

    def on_batch_report_requested(self):
        user_info=self._report_login_ready()
        if not user_info:
            return
        items=self.product_grid.selected_items()
        if not items:
            self.toast.show_message('请先勾选商品，或使用“全选”', False)
            return
        self.toast.show_message('正在读取 Vinted 当前举报原因…', True)
        live=self.api.get_report_reasons(items[0])
        if not live.get('success'):
            self.toast.show_message(live.get('message','无法读取当前举报原因'), False); return
        dlg=ReportDialog(self,is_batch=True,count=len(items),reasons=live.get('reasons'))
        if dlg.exec()!=QDialog.DialogCode.Accepted:
            return
        reason_id,message=dlg.get_data()
        if not reason_id:
            self.toast.show_message('未选择有效的举报原因',False); return

        # Selection can still be prepared in bulk, but every outgoing report
        # gets an explicit confirmation in the desktop app.
        self._report_queue=list(items)
        self._report_queue_meta={
            'user_id': int(user_info.get('user_id')),
            'reason_id': int(reason_id),
            'message': message,
            'total': len(items),
            'confirmed': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0,
        }
        self.sidebar.report_btn.setEnabled(False)
        self._prompt_next_report()

    def _prompt_next_report(self):
        meta=self._report_queue_meta
        if not meta:
            self.sidebar.report_btn.setEnabled(True)
            return
        if not self._report_queue:
            self._finish_report_queue()
            return

        item=self._report_queue[0]
        item_id=item.get('id') if isinstance(item,dict) else item
        title=(item.get('title') if isinstance(item,dict) else '') or ''
        done=meta['confirmed']+meta['skipped']

        box=QMessageBox(self)
        box.setWindowTitle('确认提交举报')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f'待确认 {done+1}/{meta["total"]}\n商品 ID: {item_id}'+(f'\n{title}' if title else ''))
        box.setInformativeText('确认后才会使用当前已同步的登录 Cookie 提交这一条。')
        yes=box.addButton('确认提交', QMessageBox.ButtonRole.AcceptRole)
        skip=box.addButton('跳过', QMessageBox.ButtonRole.DestructiveRole)
        cancel=box.addButton('结束队列', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked=box.clickedButton()

        if clicked is yes:
            meta['confirmed']+=1
            # Re-read the authenticated user again just before the actual POST.
            fresh=self.api.get_current_user(force=True)
            if not fresh or not fresh.get('user_id'):
                self.toast.show_message('登录状态已失效，请重新同步 Cookie',False)
                self._finish_report_queue(cancelled=True)
                return
            meta['user_id']=int(fresh.get('user_id'))
            self.report_worker=ReportWorker(self.api,item,meta['user_id'],meta['reason_id'],meta['message'])
            self.report_worker.finished.connect(self._on_queue_report_finished)
            self.report_worker.start()
            self.sidebar.report_btn.setText(f'提交中 {done+1}/{meta["total"]}')
            return
        if clicked is skip:
            meta['skipped']+=1
            self._report_queue.pop(0)
            QTimer.singleShot(0,self._prompt_next_report)
            return

        self._finish_report_queue(cancelled=True)

    def _on_queue_report_finished(self,success,message):
        meta=self._report_queue_meta
        if not meta:
            return
        if success:
            meta['success']+=1
        else:
            meta['failed']+=1
        if self._report_queue:
            self._report_queue.pop(0)
        self.report_worker=None
        if message:
            short=message if len(message)<=180 else message[:177]+'...'
            self.toast.show_message(short,success)
        QTimer.singleShot(50,self._prompt_next_report)

    def _finish_report_queue(self,cancelled=False):
        meta=self._report_queue_meta or {}
        self._report_queue=[]
        self._report_queue_meta=None
        self.sidebar.report_btn.setText('举报选中')
        self.sidebar.report_btn.setEnabled(True)
        if not cancelled:
            self.product_grid.clear_selection()
        msg=(f'队列结束：已确认 {meta.get("confirmed",0)}，'
             f'请求成功 {meta.get("success",0)}，失败 {meta.get("failed",0)}，'
             f'跳过 {meta.get("skipped",0)}')
        self.toast.show_message(msg, meta.get('failed',0)==0)

    def _start_single_report(self,item,user_id,reason_id,message):
        if self.report_worker and self.report_worker.isRunning():
            self.toast.show_message('已有举报任务正在运行', False); return
        self.sidebar.report_btn.setEnabled(False)
        self.report_worker=ReportWorker(self.api,item,int(user_id),int(reason_id),message)
        self.report_worker.finished.connect(self._on_single_report_finished)
        self.report_worker.start()
        self.toast.show_message('正在通过当前 Cookie 会话执行 Vinted 官方举报流程…', True)

    def _on_single_report_finished(self,success,message):
        self.sidebar.report_btn.setEnabled(True)
        self.toast.show_message(message or ('举报成功' if success else '举报失败'), success)
        self.report_worker=None

    def refresh_history(self): self.history_panel.load_history_entries(self.history_manager.get_history_list())

    def on_history_selected(self,timestamp):
        try: params,results=self.history_manager.load_history(timestamp)
        except Exception: QMessageBox.warning(self,'提示','无法加载历史记录'); return
        self.product_grid.clear_cards(); self.accumulated_items=list(results or [])
        for item in self.accumulated_items:
            card=ProductCard(item,self.image_loader); card.report_requested.connect(self.handle_report_item); self.product_grid.add_card(card)
        self.setWindowTitle(f'Vinted 助手 - 历史记录 ({timestamp})')
        QTimer.singleShot(1800,lambda:self.setWindowTitle('Vinted 助手'))

    def on_history_delete(self,timestamp):
        dlg=CustomConfirmDialog(self,'删除记录',f'确定要删除这条历史记录吗？\n\n• 此操作不可恢复\n• 删除日期: {timestamp}','确认删除',True)
        if dlg.exec()!=QDialog.DialogCode.Accepted: return
        if self.history_manager.delete_history(timestamp): self.refresh_history(); self.toast.show_message('历史记录已删除',True)
        else: self.toast.show_message('删除失败',False)

    def on_clear_all_history(self):
        dlg=CustomConfirmDialog(self,'清空历史','确定要清空所有历史记录吗？\n\n• 此操作将删除所有已保存的搜索记录\n• 此操作不可恢复','确认清空',True)
        if dlg.exec()==QDialog.DialogCode.Accepted:
            ok=self.history_manager.clear_all_history(); self.refresh_history(); self.toast.show_message('历史记录已清空' if ok else '清空失败',ok)

    def closeEvent(self,event):
        self.stop_all_tasks(); event.accept()


def main():
    app=QApplication(sys.argv); app.setStyleSheet(STYLESHEET)
    login=LoginDialog()
    if login.exec()!=QDialog.DialogCode.Accepted:
        return
    window=MainWindow(); window.sidebar.user_info.set_expiration_text(getattr(login,'expiration_info','免费版') or '免费版'); window.show(); sys.exit(app.exec())

if __name__=='__main__': main()