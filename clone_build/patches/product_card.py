import math, webbrowser
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPropertyAnimation, pyqtProperty, QRect
from PyQt6.QtGui import QPixmap, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGraphicsDropShadowEffect, QCheckBox
import qtawesome as qta


class SkeletonLabel(QLabel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self._bg_color=QColor('#E0E0E0')
        self.anim=QPropertyAnimation(self,b'backgroundColorProp')
        self.anim.setDuration(1500); self.anim.setLoopCount(-1); self.anim.setStartValue(QColor('#CFD8DC')); self.anim.setKeyValueAt(0.5,QColor('#FFFFFF')); self.anim.setEndValue(QColor('#CFD8DC')); self.anim.start()
    def get_bg(self): return self._bg_color
    def set_bg(self,c): self._bg_color=QColor(c); self.update()
    backgroundColorProp=pyqtProperty(QColor,fget=get_bg,fset=set_bg)
    def stop_animation(self):
        if self.anim.state()==QPropertyAnimation.State.Running: self.anim.stop()
    def paintEvent(self,event):
        if self.pixmap() and not self.pixmap().isNull():
            super().paintEvent(event); return
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(Qt.PenStyle.NoPen); p.setBrush(self._bg_color); p.drawRoundedRect(self.rect(),8,8)

class LikeBadge(QWidget):
    def __init__(self,likes=0,parent=None):
        super().__init__(parent); self.likes=likes or 0; self.setFixedHeight(28)
        font=self.font(); font.setPointSize(9); font.setBold(True); self.setFont(font)
        text_w=self.fontMetrics().horizontalAdvance(str(self.likes)); self.setFixedWidth(max(50,text_w+36))
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255,255,255,230)); p.drawRoundedRect(self.rect(),14,14)
        icon=qta.icon('fa5s.heart',color='#EF4444').pixmap(14,14); p.drawPixmap(8,7,icon)
        p.setPen(QColor(0,0,0)); p.setFont(self.font()); p.drawText(QRect(26,0,self.width()-30,self.height()),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,str(self.likes))

class StarRating(QWidget):
    def __init__(self,rating=0.0,parent=None):
        super().__init__(parent); self.rating=float(rating or 0); self.setFixedHeight(16); self.setFixedWidth(80)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rounded=round(self.rating*2)/2
        for i in range(5):
            x=i*16; fill=max(0,min(1,rounded-i)); self.draw_star(p,x+8,8,fill)
    def draw_star(self,painter,cx,cy,clip_ratio=1.0):
        outer=6.5; inner=3.0; path=QPainterPath()
        for i in range(10):
            a=-math.pi/2+i*math.pi/5; r=outer if i%2==0 else inner; x=cx+math.cos(a)*r; y=cy+math.sin(a)*r
            if i==0:path.moveTo(x,y)
            else:path.lineTo(x,y)
        path.closeSubpath(); painter.save()
        painter.setPen(QPen(QColor('#F9BB42'),1.0)); painter.setBrush(QColor(220,220,220)); painter.drawPath(path)
        if clip_ratio>0:
            painter.setClipRect(QRect(int(cx-outer),int(cy-outer),int(outer*2*clip_ratio),int(outer*2)))
            painter.setBrush(QColor('#ffd700')); painter.drawPath(path)
        painter.restore()

class FlagButton(QWidget):
    clicked=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent); self.setFixedSize(28,28); self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.is_hovered=False; self.hide()
    def enterEvent(self,event): self.is_hovered=True; self.update(); super().enterEvent(event)
    def leaveEvent(self,event): self.is_hovered=False; self.update(); super().leaveEvent(event)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.is_hovered: p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#FFF1F2')); p.drawEllipse(self.rect())
        color='#EF4444' if self.is_hovered else '#6B7280'; pm=qta.icon('fa5s.flag',color=color).pixmap(16,16); p.drawPixmap(6,6,pm)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.clicked.emit(); event.accept(); return
        super().mousePressEvent(event)

class ProductCard(QFrame):
    report_requested=pyqtSignal(object)
    selection_changed=pyqtSignal(int, bool)
    def __init__(self,data,image_loader=None,parent=None):
        super().__init__(parent); self.data=data or {}; self.image_loader=image_loader; self.images_loaded=False
        self.setObjectName('ProductCard'); self.setFixedSize(215,320)
        self.shadow=QGraphicsDropShadowEffect(self); self.shadow.setBlurRadius(15); self.shadow.setXOffset(0); self.shadow.setYOffset(3); self.shadow.setColor(QColor(0,0,0,15)); self.setGraphicsEffect(self.shadow)
        self.setup_ui()
    def setup_ui(self):
        layout=QVBoxLayout(self); layout.setContentsMargins(10,10,10,10); layout.setSpacing(4)
        image_container=QWidget(); image_container.setFixedSize(195,180)
        il=QVBoxLayout(image_container); il.setContentsMargins(0,0,0,0); il.setSpacing(0)
        self.image_label=SkeletonLabel(); self.image_label.setFixedSize(195,180); self.image_label.setStyleSheet('border-radius:8px;'); self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter); il.addWidget(self.image_label)
        self.like_badge=LikeBadge(self.data.get('likes',0),image_container); self.like_badge.move(195-self.like_badge.width()-8,8); self.like_badge.raise_()
        self.select_box=QCheckBox(image_container); self.select_box.setFixedSize(24,24); self.select_box.move(8,8); self.select_box.setToolTip('选择此商品'); self.select_box.setStyleSheet('QCheckBox{background:rgba(255,255,255,235);border-radius:5px;padding:2px;}'); self.select_box.stateChanged.connect(self._on_selection_changed); self.select_box.raise_()
        self.flag_btn=FlagButton(image_container); self.flag_btn.move(38,8); self.flag_btn.clicked.connect(self.handle_flag_clicked); self.flag_btn.raise_()
        layout.addWidget(image_container)
        self.title_label=QLabel(self.data.get('title','Product Title')); self.title_label.setObjectName('ProductTitle'); self.title_label.setWordWrap(False); self.title_label.setFixedHeight(20); self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft); layout.addWidget(self.title_label)
        ps=QHBoxLayout(); ps.setSpacing(8)
        cur=self.data.get('currency') or self.data.get('currency_code') or '€'; price=self.data.get('price','0.00'); self.price_label=QLabel(f'{cur} {price}' if str(cur) in '$€£' else f'{price} {cur}'); self.price_label.setObjectName('ProductPrice'); ps.addWidget(self.price_label); ps.addStretch()
        self.status_label=QLabel(self.data.get('status','未知')); self.status_label.setObjectName('ProductStatus'); self.status_label.setStyleSheet('color:#00897B;background-color:#ECFDF5;border:1px solid #B2DFDB;border-radius:5px;padding:1px 3px;'); ps.addWidget(self.status_label); layout.addLayout(ps)
        seller=QHBoxLayout(); seller.setSpacing(8)
        self.avatar_label=QLabel(); self.avatar_label.setFixedSize(40,40); self.avatar_label.setStyleSheet('QLabel{background-color:#E5E7EB;border-radius:20px;}'); self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.avatar_label.setPixmap(qta.icon('fa5s.user',color='#9CA3AF').pixmap(22,22)); seller.addWidget(self.avatar_label)
        info=QVBoxLayout(); info.setContentsMargins(0,0,0,0); info.setSpacing(2)
        self.username_label=QLabel(self.data.get('seller_username','Unknown')); self.username_label.setObjectName('SellerUsername'); self.username_label.setStyleSheet('color:#374151;'); info.addWidget(self.username_label)
        rating=float(self.data.get('seller_feedback_reputation',0) or 0); count=int(self.data.get('seller_feedback_count',0) or 0)
        if count>0:
            self.rating_widget=StarRating(rating); info.addWidget(self.rating_widget)
            self.feedback_label=QLabel(f'{count} 条评价'); self.feedback_label.setStyleSheet('color:#666666;margin-top:-4px;'); info.addWidget(self.feedback_label)
        else:
            self.feedback_label=QLabel('暂无评价'); self.feedback_label.setStyleSheet('color:#999999;margin-top:-2px;'); info.addWidget(self.feedback_label)
        seller.addLayout(info,1); layout.addLayout(seller)

    def is_selected(self):
        return bool(self.select_box.isChecked()) if hasattr(self,'select_box') else False

    def set_selected(self,selected,emit_signal=True):
        if not hasattr(self,'select_box'):
            return
        old=self.select_box.blockSignals(not emit_signal)
        try:
            self.select_box.setChecked(bool(selected))
            self._apply_selected_style()
        finally:
            self.select_box.blockSignals(old)

    def _on_selection_changed(self,state):
        self._apply_selected_style()
        item_id=self.data.get('id')
        try: item_id=int(item_id) if item_id is not None else 0
        except Exception: item_id=0
        self.selection_changed.emit(item_id, self.select_box.isChecked())

    def _apply_selected_style(self):
        self.setProperty('selected', self.is_selected())
        self.style().unpolish(self); self.style().polish(self); self.update()

    def create_circular_pixmap(self,pixmap,size=40):
        if pixmap is None or pixmap.isNull(): return QPixmap()
        scaled=pixmap.scaled(size,size,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation); out=QPixmap(size,size); out.fill(Qt.GlobalColor.transparent); p=QPainter(out); p.setRenderHint(QPainter.RenderHint.Antialiasing); path=QPainterPath(); path.addEllipse(0,0,size,size); p.setClipPath(path); x=(scaled.width()-size)//2; y=(scaled.height()-size)//2; p.drawPixmap(-x,-y,scaled); p.end(); return out
    def load_images(self):
        if self.images_loaded: return
        self.images_loaded=True
        if self.image_loader and self.data.get('image_path'): self.image_loader.load(self.data.get('image_path'),self.on_image_loaded)
        if self.image_loader and self.data.get('seller_avatar'): self.image_loader.load(self.data.get('seller_avatar'),self.on_seller_avatar_loaded)
    def on_image_loaded(self,pixmap):
        if pixmap and not pixmap.isNull(): self.image_label.stop_animation(); self.image_label.setPixmap(pixmap.scaled(self.image_label.size(),Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation))
    def on_seller_avatar_loaded(self,pixmap):
        if pixmap and not pixmap.isNull(): self.avatar_label.setPixmap(self.create_circular_pixmap(pixmap,40))
    def handle_flag_clicked(self):
        if self.data:
            try:self.report_requested.emit(dict(self.data))
            except Exception:pass
    def enterEvent(self,event): self.flag_btn.show(); self.shadow.setBlurRadius(25); self.shadow.setColor(QColor(0,0,0,30)); super().enterEvent(event)
    def leaveEvent(self,event): self.flag_btn.hide(); self.shadow.setBlurRadius(15); self.shadow.setColor(QColor(0,0,0,15)); super().leaveEvent(event)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            url=self.data.get('url')
            if url:
                try:webbrowser.open(url)
                except Exception:pass
        super().mousePressEvent(event)