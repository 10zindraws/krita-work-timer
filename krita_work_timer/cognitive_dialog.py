"""
Cognitive Work Dialog for Krita Work Timer
Non-blocking dialog to ask user about cognitive work during idle time
Also includes notification toast for auto-decisions
"""

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPropertyAnimation, QRect
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QWidget, QGraphicsDropShadowEffect,
    QFrame
)
from PyQt5.QtGui import QFont, QColor


class CognitiveWorkDialog(QDialog):
    """
    Sleek, non-modal dialog asking if user was doing cognitive work.
    
    Designed to be non-intrusive but noticeable.
    Styled to match Krita's palette while being modern and clean.
    Shows confidence level to help user understand system's learning.
    """
    
    # Signals
    response_given = pyqtSignal(bool)  # True = was thinking, False = wasn't
    
    def __init__(self, idle_seconds: int, confidence: float = 0.5, parent=None):
        super().__init__(parent)
        
        self._idle_seconds = idle_seconds
        self._idle_minutes = max(1, idle_seconds // 60)
        self._confidence = confidence
        self._setup_ui()
        self._setup_style()
    
    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle("Work Timer")
        self.setWindowFlags(
            Qt.Dialog | 
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setModal(False)  # Non-blocking
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Question label
        question_text = self._format_question()
        self.question_label = QLabel(question_text)
        self.question_label.setWordWrap(True)
        self.question_label.setAlignment(Qt.AlignCenter)
        
        question_font = QFont()
        question_font.setPointSize(11)
        self.question_label.setFont(question_font)
        
        layout.addWidget(self.question_label)
        
        # Confidence indicator (subtle)
        if self._confidence > 0:
            confidence_text = self._format_confidence()
            self.confidence_label = QLabel(confidence_text)
            self.confidence_label.setAlignment(Qt.AlignCenter)
            confidence_font = QFont()
            confidence_font.setPointSize(8)
            self.confidence_label.setFont(confidence_font)
            self.confidence_label.setObjectName("confidenceLabel")
            layout.addWidget(self.confidence_label)
        
        # Buttons container
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(12)
        
        # Yes button
        self.yes_button = QPushButton("Yes, add time")
        self.yes_button.setMinimumHeight(36)
        self.yes_button.setCursor(Qt.PointingHandCursor)
        self.yes_button.clicked.connect(self._on_yes)
        
        # No button
        self.no_button = QPushButton("No, discard")
        self.no_button.setMinimumHeight(36)
        self.no_button.setCursor(Qt.PointingHandCursor)
        self.no_button.clicked.connect(self._on_no)
        
        button_layout.addWidget(self.no_button)
        button_layout.addWidget(self.yes_button)
        
        layout.addWidget(button_container)
        
        # Set fixed width for clean look
        self.setFixedWidth(340)
    
    def _format_question(self) -> str:
        """Format the question text based on idle time."""
        if self._idle_minutes == 1:
            time_str = "the past minute"
        else:
            time_str = f"the past {self._idle_minutes} mins"
        
        return f"Were you thinking or researching\nabout this project {time_str}?"
    
    def _format_confidence(self) -> str:
        """Format confidence indicator text."""
        pct = int(self._confidence * 100)
        if pct >= 70:
            return f"I'm fairly sure you were thinking ({pct}%)"
        elif pct <= 30:
            return f"Probably not thinking ({pct}%)"
        else:
            return f"Not sure ({pct}%)"
    
    def _setup_style(self) -> None:
        """Apply modern, sleek styling that respects Krita's palette."""
        # Using Krita-compatible colors with modern styling
        self.setStyleSheet("""
            CognitiveWorkDialog {
                background-color: palette(window);
                border: 1px solid palette(mid);
                border-radius: 8px;
            }
            
            QLabel {
                color: palette(window-text);
                background: transparent;
            }
            
            #confidenceLabel {
                color: palette(mid);
                font-style: italic;
            }
            
            QPushButton {
                border: 1px solid palette(mid);
                border-radius: 6px;
                padding: 8px 16px;
                background-color: palette(button);
                color: palette(button-text);
                font-weight: 500;
            }
            
            QPushButton:hover {
                background-color: palette(light);
                border-color: palette(highlight);
            }
            
            QPushButton:pressed {
                background-color: palette(midlight);
            }
            
            QPushButton#yesButton {
                background-color: palette(highlight);
                color: palette(highlighted-text);
                border-color: palette(highlight);
            }
            
            QPushButton#yesButton:hover {
                background-color: palette(highlight);
                opacity: 0.9;
            }
        """)
        
        # Set object names for specific styling
        self.yes_button.setObjectName("yesButton")
        self.no_button.setObjectName("noButton")
        
        # Add subtle shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
    
    def _on_yes(self) -> None:
        """Handle Yes button click."""
        self.response_given.emit(True)
        self.accept()
    
    def _on_no(self) -> None:
        """Handle No button click."""
        self.response_given.emit(False)
        self.reject()
    
    def showEvent(self, event) -> None:
        """Center dialog when shown."""
        super().showEvent(event)
        
        # Try to position near the top-right of the parent/screen
        if self.parent():
            parent_geo = self.parent().geometry()
            x = parent_geo.right() - self.width() - 20
            y = parent_geo.top() + 60
            self.move(x, y)
        else:
            # Center on screen
            from PyQt5.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.availableGeometry()
                x = screen_geo.right() - self.width() - 40
                y = screen_geo.top() + 80
                self.move(x, y)
    
    def keyPressEvent(self, event) -> None:
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key_Y:
            self._on_yes()
        elif event.key() == Qt.Key_N or event.key() == Qt.Key_Escape:
            self._on_no()
        else:
            super().keyPressEvent(event)


class CognitiveNotification(QFrame):
    """
    Non-intrusive notification for auto-decisions.
    
    Shows briefly what decision was made and allows undo.
    Used when trust level is high enough for implicit decisions.
    """
    
    # Signals
    undo_requested = pyqtSignal()
    dismissed = pyqtSignal()
    
    # How long the notification stays visible (ms)
    DISPLAY_DURATION = 5000
    UNDO_WINDOW = 8000  # Time user has to undo
    
    def __init__(self, was_accepted: bool, seconds: int, parent=None):
        super().__init__(parent)
        
        self._was_accepted = was_accepted
        self._seconds = seconds
        self._minutes = max(1, seconds // 60)
        
        self._setup_ui()
        self._setup_style()
        
        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._on_dismiss)
        self._dismiss_timer.start(self.DISPLAY_DURATION)
    
    def _setup_ui(self) -> None:
        """Set up the notification UI."""
        self.setWindowFlags(
            Qt.Tool |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        
        # Message
        if self._was_accepted:
            msg = f"Added {self._minutes} min thinking time"
            icon = "✓"
        else:
            msg = f"Discarded {self._minutes} min idle time"
            icon = "✗"
        
        icon_label = QLabel(icon)
        icon_label.setObjectName("notifIcon")
        
        msg_label = QLabel(msg)
        msg_label.setObjectName("notifMessage")
        
        # Undo button
        undo_btn = QPushButton("Undo")
        undo_btn.setObjectName("undoButton")
        undo_btn.setCursor(Qt.PointingHandCursor)
        undo_btn.clicked.connect(self._on_undo)
        
        layout.addWidget(icon_label)
        layout.addWidget(msg_label)
        layout.addStretch()
        layout.addWidget(undo_btn)
        
        self.setFixedHeight(40)
        self.setMinimumWidth(280)
    
    def _setup_style(self) -> None:
        """Apply notification styling."""
        accepted_style = """
            CognitiveNotification {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
            #notifIcon {
                color: #27ae60;
                font-size: 14px;
            }
            #notifMessage {
                color: palette(text);
            }
            #undoButton {
                background: transparent;
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 4px 8px;
                color: palette(text);
            }
            #undoButton:hover {
                background: palette(midlight);
            }
        """
        
        discarded_style = """
            CognitiveNotification {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
            #notifIcon {
                color: #7f8c8d;
                font-size: 14px;
            }
            #notifMessage {
                color: palette(text);
            }
            #undoButton {
                background: transparent;
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 4px 8px;
                color: palette(text);
            }
            #undoButton:hover {
                background: palette(midlight);
            }
        """
        
        self.setStyleSheet(accepted_style if self._was_accepted else discarded_style)
        
        # Add shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
    
    def _on_undo(self) -> None:
        """Handle undo button click."""
        self._dismiss_timer.stop()
        self.undo_requested.emit()
        self.close()
    
    def _on_dismiss(self) -> None:
        """Handle auto-dismiss."""
        self.dismissed.emit()
        self.close()
    
    def showEvent(self, event) -> None:
        """Position notification when shown."""
        super().showEvent(event)
        
        # Position at top-right of parent or screen
        if self.parent():
            parent_geo = self.parent().geometry()
            x = parent_geo.right() - self.width() - 20
            y = parent_geo.top() + 60
            self.move(x, y)
        else:
            from PyQt5.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.availableGeometry()
                x = screen_geo.right() - self.width() - 40
                y = screen_geo.top() + 80
                self.move(x, y)
