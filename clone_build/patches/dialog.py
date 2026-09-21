from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QParallelAnimationGroup, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QCursor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QHBoxLayout, QWidget, QFrame,
    QGraphicsDropShadowEffect, QTextEdit
)
from ui.sidebar import StylizedDropdown


class CustomButton(QLabel):
    clicked = pyqtSignal()
    def __init__(self, text, is_primary=False, parent=None):
        super().__init__(text, parent)
        self.is_primary = is_primary; self.is_hovered=False; self.is_pressed=False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.setFixedHeight(40)
        self._update_style()
    def enterEvent(self, event): self.is_hovered=True; self._update_style(); super().enterEvent(event)
    def leaveEvent(self, event): self.is_hovered=False; self.is_pressed=False; self._update_style(); super().leaveEvent(event)
    def mousePressEvent(self, event):
        if event.button()==Qt.MouseButton.LeftButton: self.is_pressed=True; self._update_style()
        super().mousePressEvent(event)
    def mouseReleaseEvent(self, event):
        if event.button()==Qt.MouseButton.LeftButton:
            inside=self.rect().contains(event.pos()); self.is_pressed=False; self._update_style()
            if inside: self.clicked.emit()
        super().mouseReleaseEvent(event)
    def _update_style(self):
        is_delete = self.text() in ('删除','举报','确认举报')
        if self.is_primary:
            if is_delete: bg = '#991B1B' if self.is_pressed else '#B91C1C' if self.is_hovered else '#DC2626'
            else: bg = '#1E40AF' if self.is_pressed else '#2563EB' if self.is_hovered else '#3B82F6'
            color='white'
        else:
            bg='#D1D5DB' if self.is_pressed else '#F3F4F6' if self.is_hovered else '#E5E7EB'; color='#4B5563'
        self.setStyleSheet(f'QLabel{{background-color:{bg};color:{color};border-radius:8px;font-weight:600;font-size:13px;padding:0 16px;}}')


class CustomConfirmDialog(QDialog):
    def __init__(self, parent=None, title='确认', content='', confirm_text='确定', show_cancel=True):
        super().__init__(parent)
        self._result_code=QDialog.DialogCode.Rejected
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.setModal(True)
        outer=QVBoxLayout(self); outer.setContentsMargins(30,30,30,30)
        self.container=QFrame(); self.container.setObjectName('DialogContainer'); self.container.setFixedWidth(360)
        self.container.setStyleSheet('QFrame#DialogContainer{background:white;border-radius:16px;border:1px solid #F3F4F6;}')
        shadow=QGraphicsDropShadowEffect(self); shadow.setBlurRadius(30); shadow.setXOffset(0); shadow.setYOffset(8); shadow.setColor(QColor(0,0,0,60)); self.container.setGraphicsEffect(shadow)
        self.inner_layout=QVBoxLayout(self.container); self.inner_layout.setContentsMargins(24,24,24,24); self.inner_layout.setSpacing(15)
        title_label=QLabel(title); title_label.setFont(QFont('Segoe UI',13,QFont.Weight.Bold)); title_label.setStyleSheet('color:#111827;border:none;background:transparent;'); self.inner_layout.addWidget(title_label)
        self.content_label=QLabel(content); self.content_label.setWordWrap(True); self.content_label.setFont(QFont('Segoe UI',10)); self.content_label.setStyleSheet('color:#4B5563;line-height:1.4;border:none;background:transparent;'); self.inner_layout.addWidget(self.content_label)
        self.inner_layout.addStretch()
        btns=QHBoxLayout(); btns.setSpacing(12)
        if show_cancel:
            self.cancel_btn=CustomButton('取消',False); self.cancel_btn.clicked.connect(self.animate_close_cancel); btns.addWidget(self.cancel_btn)
        self.ok_btn=CustomButton(confirm_text,True); self.ok_btn.clicked.connect(self.animate_close_ok); btns.addWidget(self.ok_btn)
        self.inner_layout.addLayout(btns); outer.addWidget(self.container)
        self.adjustSize(); self.setWindowOpacity(0)
        self.anim_group=QParallelAnimationGroup(self)
    def showEvent(self,event):
        super().showEvent(event); self.adjustSize()
        if self.parentWidget():
            g=self.parentWidget().geometry(); target=QPoint(g.x()+(g.width()-self.width())//2,g.y()+(g.height()-self.height())//2)
        else: target=self.pos()
        self.move(target + QPoint(0,15))
        a1=QPropertyAnimation(self,b'windowOpacity'); a1.setDuration(250); a1.setStartValue(0.0); a1.setEndValue(1.0); a1.setEasingCurve(QEasingCurve.Type.OutCubic)
        a2=QPropertyAnimation(self,b'pos'); a2.setDuration(250); a2.setStartValue(self.pos()); a2.setEndValue(target); a2.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_group=QParallelAnimationGroup(self); self.anim_group.addAnimation(a1); self.anim_group.addAnimation(a2); self.anim_group.start()
    def animate_close_ok(self): self._result_code=QDialog.DialogCode.Accepted; self._start_exit_anim()
    def animate_close_cancel(self): self._result_code=QDialog.DialogCode.Rejected; self._start_exit_anim()
    def _start_exit_anim(self):
        a1=QPropertyAnimation(self,b'windowOpacity'); a1.setDuration(200); a1.setStartValue(self.windowOpacity()); a1.setEndValue(0.0); a1.setEasingCurve(QEasingCurve.Type.InCubic)
        a2=QPropertyAnimation(self,b'pos'); a2.setDuration(200); a2.setStartValue(self.pos()); a2.setEndValue(self.pos()+QPoint(0,15)); a2.setEasingCurve(QEasingCurve.Type.InCubic)
        group=QParallelAnimationGroup(self); group.addAnimation(a1); group.addAnimation(a2); group.finished.connect(self._finish_closing); self._exit_group=group; group.start()
    def _finish_closing(self):
        if self._result_code==QDialog.DialogCode.Accepted: self.accept()
        else: self.reject()


class CustomContentDialog(CustomConfirmDialog):
    def __init__(self,parent=None,title='提示',content_widget=None,confirm_text='确定',show_cancel=False):
        super().__init__(parent,title,'',confirm_text,show_cancel)
        self.content_label.hide()
        if content_widget is not None:
            self.inner_layout.insertWidget(1,content_widget)
        self.container.setFixedWidth(650)


class ReportDialog(CustomContentDialog):
    def __init__(self,parent=None,is_batch=False,count=1,reasons=None):
        content=QWidget(); lay=QVBoxLayout(content); lay.setContentsMargins(0,5,0,5); lay.setSpacing(10)
        txt = (f'已选择 {count} 个商品，将逐条确认提交。\n举报原因从 Vinted 当前页面实时读取：' if is_batch else '举报原因从 Vinted 当前页面实时读取：')
        lab=QLabel(txt); lab.setStyleSheet('color:#4B5563;font-weight:bold;'); lay.addWidget(lab)
        reasons=list(reasons or [])
        items=[(int(x.get('id')), str(x.get('label') or x.get('id'))) for x in reasons if x.get('id') is not None]
        self.reason_combo=StylizedDropdown(items); lay.addWidget(self.reason_combo)
        msg=QLabel('补充说明（可选）:'); msg.setStyleSheet('color:#4B5563;margin-top:5px;'); lay.addWidget(msg)
        self.msg_edit=QTextEdit(); self.msg_edit.setPlaceholderText('务必输入说明理由，否则可能无效'); self.msg_edit.setFixedHeight(70)
        self.msg_edit.setStyleSheet('QTextEdit{border:1px solid #D1D5DB;border-radius:6px;padding:8px;background:white;}'); lay.addWidget(self.msg_edit)
        title='批量举报确认' if is_batch else '举报商品'; confirm='确认举报'
        super().__init__(parent,title,content,confirm,True)
    def get_data(self):
        rid=self.reason_combo.currentData()
        try: rid=int(rid)
        except Exception: rid=0
        return rid, self.msg_edit.toPlainText().strip()