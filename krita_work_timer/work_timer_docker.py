"""
Work Timer Docker for Krita
UI display widget - tracking logic is in the Extension
"""

from typing import Optional

from krita import DockWidget, Krita

from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QEvent, QPoint
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QDialog,
    QSizePolicy, QSpacerItem, QApplication, QPushButton
)
from PyQt5.QtGui import QFont, QWheelEvent, QMouseEvent

from .timer_manager import TimerState


class ResetTimeConfirmDialog(QDialog):
    """
    Confirmation dialog for resetting tracked time.
    Shows a warning icon and asks the user to confirm the irreversible action.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reset Tracked Time")
        self.setWindowFlags(
            Qt.Dialog | 
            Qt.WindowTitleHint | 
            Qt.WindowCloseButtonHint
        )
        self.setModal(True)
        
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Warning message container with icon
        warning_container = QWidget()
        warning_layout = QHBoxLayout(warning_container)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.setSpacing(12)
        
        # Warning icon from Krita's icon library
        icon_label = QLabel()
        icon_label.setObjectName("warningIcon")
        try:
            warning_icon = Krita.instance().icon("dialog-warning")
            icon_label.setPixmap(warning_icon.pixmap(32, 32))
        except Exception:
            # Fallback to text if icon not available
            icon_label.setText("⚠")
            icon_label.setStyleSheet("font-size: 24px; color: #f39c12;")
        icon_label.setFixedSize(32, 32)
        warning_layout.addWidget(icon_label)
        
        # Warning text
        warning_text = QLabel("You will not be able to undo this, are you sure?")
        warning_text.setObjectName("warningText")
        warning_text.setWordWrap(True)
        warning_font = QFont()
        warning_font.setPointSize(10)
        warning_text.setFont(warning_font)
        warning_layout.addWidget(warning_text, 1)
        
        layout.addWidget(warning_container)
        
        # Button container
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(12)
        button_layout.addStretch()
        
        # Yes button
        self._yes_button = QPushButton("Yes")
        self._yes_button.setObjectName("yesButton")
        self._yes_button.setMinimumWidth(80)
        self._yes_button.setMinimumHeight(32)
        self._yes_button.setCursor(Qt.PointingHandCursor)
        self._yes_button.clicked.connect(self.accept)
        button_layout.addWidget(self._yes_button)
        
        # No button
        self._no_button = QPushButton("No")
        self._no_button.setObjectName("noButton")
        self._no_button.setMinimumWidth(80)
        self._no_button.setMinimumHeight(32)
        self._no_button.setCursor(Qt.PointingHandCursor)
        self._no_button.clicked.connect(self.reject)
        button_layout.addWidget(self._no_button)
        
        layout.addWidget(button_container)
        
        # Set a reasonable fixed width
        self.setFixedWidth(340)
    
    def _apply_styles(self) -> None:
        """Apply styling to match Krita's palette."""
        style = """
            ResetTimeConfirmDialog {
                background-color: palette(window);
            }
            
            #warningText {
                color: palette(text);
            }
            
            #yesButton, #noButton {
                padding: 6px 16px;
                border: 1px solid palette(mid);
                border-radius: 4px;
                background-color: palette(button);
                color: palette(buttonText);
            }
            
            #yesButton:hover, #noButton:hover {
                background-color: palette(light);
            }
            
            #yesButton:pressed, #noButton:pressed {
                background-color: palette(dark);
            }
        """
        self.setStyleSheet(style)


class AccuracyDialog(QDialog):
    """
    Dialog that shows accuracy/confidence info when user right-clicks the docker.
    Closes when clicking anywhere outside the dialog.
    Also provides a Reset Tracked Time button.
    """
    
    def __init__(self, parent=None, reset_callback=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setModal(False)
        
        self._reset_callback = reset_callback
        self._setup_ui()
    
    def set_reset_callback(self, callback) -> None:
        """Set the callback function for reset time action."""
        self._reset_callback = callback
    
    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        
        # Title
        title_label = QLabel("Prediction Accuracy")
        title_label.setObjectName("accuracyTitle")
        title_font = QFont()
        title_font.setPointSize(9)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Accuracy container
        accuracy_container = QFrame()
        accuracy_container.setObjectName("accuracyContainer")
        accuracy_layout = QHBoxLayout(accuracy_container)
        accuracy_layout.setContentsMargins(8, 6, 8, 6)
        accuracy_layout.setSpacing(4)
        
        self._trust_label = QLabel("Accuracy:")
        self._trust_label.setObjectName("accuracyLabel")
        trust_label_font = QFont()
        trust_label_font.setPointSize(8)
        self._trust_label.setFont(trust_label_font)
        
        self._trust_value = QLabel("Learning")
        self._trust_value.setObjectName("accuracyValue")
        trust_value_font = QFont()
        trust_value_font.setPointSize(8)
        trust_value_font.setBold(True)
        self._trust_value.setFont(trust_value_font)
        
        accuracy_layout.addWidget(self._trust_label)
        accuracy_layout.addWidget(self._trust_value)
        accuracy_layout.addStretch()
        
        layout.addWidget(accuracy_container)
        
        # Reset Tracked Time button
        self._reset_button = QPushButton("Reset Tracked Time")
        self._reset_button.setObjectName("resetButton")
        self._reset_button.setCursor(Qt.PointingHandCursor)
        reset_font = QFont()
        reset_font.setPointSize(8)
        self._reset_button.setFont(reset_font)
        self._reset_button.setMinimumHeight(28)
        self._reset_button.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_button)
        
        # Apply styling
        self._apply_styles()
    
    def _on_reset_clicked(self) -> None:
        """Handle reset button click."""
        self.hide()  # Close this popup first
        
        if self._reset_callback:
            self._reset_callback()
    
    def _apply_styles(self) -> None:
        """Apply styling to the dialog."""
        style = """
            AccuracyDialog {
                background-color: palette(window);
                border: 1px solid palette(mid);
                border-radius: 8px;
            }
            
            #accuracyTitle {
                color: palette(text);
                background: transparent;
            }
            
            #accuracyContainer {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
            
            #accuracyLabel {
                color: palette(mid);
                background: transparent;
            }
            
            #accuracyValue {
                color: palette(text);
                background: transparent;
            }
            
            #resetButton {
                background-color: palette(button);
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 4px 8px;
                color: palette(buttonText);
                margin-top: 4px;
            }
            
            #resetButton:hover {
                background-color: palette(light);
                border-color: palette(dark);
            }
            
            #resetButton:pressed {
                background-color: palette(dark);
            }
        """
        self.setStyleSheet(style)
    
    def update_accuracy(self, label: str, percentage: float) -> None:
        """Update accuracy display."""
        self._trust_value.setText(label)
        
        # Color based on level
        if label == "High":
            self._trust_value.setStyleSheet("color: #27ae60;")  # Green
        elif label == "Medium":
            self._trust_value.setStyleSheet("color: #f39c12;")  # Orange
        else:
            self._trust_value.setStyleSheet("color: #747474;")  # Gray
    
    def showAt(self, global_pos: QPoint) -> None:
        """Show the dialog at the specified global position."""
        self.adjustSize()
        self.move(global_pos)
        self.show()


class ScrollableTimerLabel(QLabel):
    """
    Timer display label that supports mouse wheel scrolling to change font size.
    """
    
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 48
    DEFAULT_FONT_SIZE = 16
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._font_size = self.DEFAULT_FONT_SIZE
        self._update_font()
        self.setMouseTracking(True)
    
    def _update_font(self) -> None:
        """Update font with current size."""
        font = QFont()
        font.setPointSize(self._font_size)
        font.setBold(True)
        self.setFont(font)
    
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel to change font size."""
        delta = event.angleDelta().y()
        
        if delta > 0:
            # Scroll up = smaller font (intuitive: scroll up to shrink)
            new_size = max(self.MIN_FONT_SIZE, self._font_size - 1)
        else:
            # Scroll down = larger font (intuitive: scroll down to expand)
            new_size = min(self.MAX_FONT_SIZE, self._font_size + 1)
        
        if new_size != self._font_size:
            self._font_size = new_size
            self._update_font()
        
        event.accept()
    
    def get_font_size(self) -> int:
        """Get current font size."""
        return self._font_size
    
    def set_font_size(self, size: int) -> None:
        """Set font size within allowed range."""
        self._font_size = max(self.MIN_FONT_SIZE, min(self.MAX_FONT_SIZE, size))
        self._update_font()


class WorkTimerDocker(DockWidget):
    """
    Docker widget that displays the Work Timer.
    
    This is purely a UI component - all tracking logic runs in
    WorkTimerExtension, which operates regardless of docker visibility.
    
    Shows:
    - Total work time
    - Current status (Tracking/Paused/No document)
    - Right-click for accuracy indicator (trust level)
    
    Features:
    - Flexible vertical layout that adapts to docker resizing
    - Scroll wheel over timer to adjust font size
    """
    
    TITLE = "Work Timer"
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle(self.TITLE)
        
        # Reference to extension (will be set when available)
        self._extension = None
        self._connected = False
        
        # Accuracy dialog (lazy init)
        self._accuracy_dialog = None
        
        # Set up UI
        self._setup_ui()
        
        # Timer to update display and find extension
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(500)
        self._update_timer.timeout.connect(self._update_display)
        self._update_timer.start()
        
        # Timer to check layout adjustments on resize
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(50)
        self._layout_timer.timeout.connect(self._adjust_layout_for_size)
        self._layout_timer.setSingleShot(True)
        
        # Try to connect to extension immediately
        QTimer.singleShot(100, self._connect_to_extension)
    
    def _setup_ui(self) -> None:
        """Set up the docker UI with sleek Toggl-inspired design."""
        # Main widget
        main_widget = QWidget()
        main_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        main_widget.customContextMenuRequested.connect(self._show_accuracy_dialog)
        self.setWidget(main_widget)
        
        # Main layout with flexible spacing
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)
        
        # Timer container (the main display area)
        self._timer_container = QFrame()
        self._timer_container.setObjectName("timerContainer")
        self._timer_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        timer_layout = QVBoxLayout(self._timer_container)
        timer_layout.setContentsMargins(12, 8, 12, 8)
        timer_layout.setSpacing(0)
        
        # Top spacer (flexible)
        self._top_spacer = QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Expanding)
        timer_layout.addSpacerItem(self._top_spacer)
        
        # "Work time:" label - left aligned
        self._label = QLabel("Work time:")
        self._label.setObjectName("workTimeLabel")
        self._label.setAlignment(Qt.AlignLeft)
        self._label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        label_font = QFont()
        label_font.setPointSize(9)
        self._label.setFont(label_font)
        timer_layout.addWidget(self._label)
        
        # Spacer between label and timer (flexible, shrinks first)
        self._label_timer_spacer = QSpacerItem(0, 4, QSizePolicy.Minimum, QSizePolicy.Preferred)
        timer_layout.addSpacerItem(self._label_timer_spacer)
        
        # Timer display - center aligned, scrollable font size
        self._timer_display = ScrollableTimerLabel("0 mins")
        self._timer_display.setObjectName("timerDisplay")
        self._timer_display.setAlignment(Qt.AlignCenter)
        self._timer_display.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        timer_layout.addWidget(self._timer_display)
        
        # Spacer between timer and status (flexible, shrinks second)
        self._timer_status_spacer = QSpacerItem(0, 4, QSizePolicy.Minimum, QSizePolicy.Preferred)
        timer_layout.addSpacerItem(self._timer_status_spacer)
        
        # Status indicator
        self._status_label = QLabel("No document")
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        status_font = QFont()
        status_font.setPointSize(8)
        self._status_label.setFont(status_font)
        timer_layout.addWidget(self._status_label)
        
        # Bottom spacer (flexible)
        self._bottom_spacer = QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Expanding)
        timer_layout.addSpacerItem(self._bottom_spacer)
        
        main_layout.addWidget(self._timer_container)
        
        # Apply styling
        self._apply_styles()
    
    def _show_accuracy_dialog(self, pos) -> None:
        """Show the accuracy dialog at the right-click position."""
        if not self._accuracy_dialog:
            self._accuracy_dialog = AccuracyDialog(self, reset_callback=self._show_reset_confirmation)
        
        # Update accuracy info
        if self._extension:
            label, percentage = self._extension.cognitive_profile.get_accuracy_indicator()
            self._accuracy_dialog.update_accuracy(label, percentage)
        
        # Show at cursor position
        global_pos = self.widget().mapToGlobal(pos)
        self._accuracy_dialog.showAt(global_pos)
    
    def _show_reset_confirmation(self) -> None:
        """Show the reset time confirmation dialog."""
        if not self._extension:
            return
        
        # Check if there's a document open
        if not self._extension._current_doc_id:
            return
        
        # Show confirmation dialog
        confirm_dialog = ResetTimeConfirmDialog(self)
        result = confirm_dialog.exec_()
        
        if result == QDialog.Accepted:
            # User clicked Yes - reset the tracked time
            self._extension.reset_current_document_time()
    
    def _adjust_layout_for_size(self) -> None:
        """Adjust layout elements based on current docker size."""
        if not self.widget():
            return
        
        container_height = self._timer_container.height()
        
        # Get approximate heights of elements
        label_height = self._label.sizeHint().height() if self._label.isVisible() else 0
        timer_height = self._timer_display.sizeHint().height()
        status_height = self._status_label.sizeHint().height() if self._status_label.isVisible() else 0
        
        # Minimum height needed for just the timer
        min_timer_only = timer_height + 16  # Some padding
        
        # Height needed for timer + status
        min_timer_status = timer_height + status_height + 20
        
        # Height needed for all elements with minimal spacing
        min_all_elements = label_height + timer_height + status_height + 24
        
        # Height for comfortable spacing
        comfortable_height = label_height + timer_height + status_height + 40
        
        # Determine what to show/hide based on available space
        if container_height < min_timer_only:
            # Extreme squeeze: just show timer, no padding
            self._label.setVisible(False)
            self._status_label.setVisible(False)
        elif container_height < min_timer_status:
            # Very small: show only timer
            self._label.setVisible(False)
            self._status_label.setVisible(False)
        elif container_height < min_all_elements:
            # Small: hide label, show timer and status with reduced spacing
            self._label.setVisible(False)
            self._status_label.setVisible(True)
        else:
            # Normal: show everything
            self._label.setVisible(True)
            self._status_label.setVisible(True)
    
    def resizeEvent(self, event) -> None:
        """Handle resize events to adjust layout."""
        super().resizeEvent(event)
        # Debounce layout adjustment
        self._layout_timer.start()
    
    def _apply_styles(self) -> None:
        """Apply sleek, modern styling respecting Krita's palette."""
        style = """
            #timerContainer {
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 8px;
            }
            
            #workTimeLabel {
                color: palette(text);
                background: transparent;
                opacity: 0.8;
            }
            
            #timerDisplay {
                color: palette(text);
                background: transparent;
                padding: 4px 0;
            }
            
            #statusLabel {
                color: palette(mid);
                background: transparent;
            }
        """
        self.widget().setStyleSheet(style)
    
    def _connect_to_extension(self) -> None:
        """Connect to the WorkTimerExtension."""
        if self._connected:
            return
            
        from .work_timer_extension import WorkTimerExtension
        self._extension = WorkTimerExtension.instance()
        
        if self._extension:
            # Connect to timer manager signals for live updates
            self._extension.timer_manager.time_updated.connect(self._on_time_updated)
            self._extension.timer_manager.state_changed.connect(self._on_state_changed)
            self._connected = True
            
            # Initial update
            self._update_display()
    
    @pyqtSlot()
    def _update_display(self) -> None:
        """Update the display from extension state."""
        if not self._extension:
            self._connect_to_extension()
            if not self._extension:
                return
        
        # Update time display
        self._timer_display.setText(self._extension.timer_manager.format_time())
        
        # Update status
        state = self._extension.timer_manager.state
        self._update_status_from_state(state)
    
    @pyqtSlot(int)
    def _on_time_updated(self, total_seconds: int) -> None:
        """Handle time updates from extension."""
        if self._extension:
            self._timer_display.setText(self._extension.timer_manager.format_time())
    
    @pyqtSlot(TimerState)
    def _on_state_changed(self, state: TimerState) -> None:
        """Update UI based on timer state."""
        self._update_status_from_state(state)
    
    def _update_status_from_state(self, state: TimerState) -> None:
        """Update status label based on state."""
        # Check if current document is unsaved
        is_unsaved = False
        has_doc = False
        if self._extension and self._extension._current_doc_name:
            has_doc = True
            if self._extension._current_doc_id:
                is_unsaved = self._extension._current_doc_id.startswith("unsaved:")
        
        if state == TimerState.STOPPED and not has_doc:
            status = "No document"
        elif is_unsaved:
            if state in (TimerState.RUNNING, TimerState.BUFFER):
                status = "Tracking (unsaved)"
            elif state in (TimerState.PAUSED, TimerState.COGNITIVE_CHECK):
                status = "Paused (unsaved)"
            elif state == TimerState.STOPPED:
                status = "Ready (unsaved)"
            else:
                status = "Unsaved"
        else:
            # For saved documents, show appropriate status
            # STOPPED with a document means ready to track (not "No document")
            status_map = {
                TimerState.STOPPED: "Ready" if has_doc else "No document",
                TimerState.RUNNING: "Tracking",
                TimerState.BUFFER: "Tracking",
                TimerState.PAUSED: "Paused",
                TimerState.COGNITIVE_CHECK: "Paused",
            }
            status = status_map.get(state, "")
        
        self._status_label.setText(status)
        
        # Apply different colors based on status
        if "Tracking" in status:
            if is_unsaved:
                self._status_label.setStyleSheet("color: #e67e22;")  # Orange for unsaved
            else:
                self._status_label.setStyleSheet("color: palette(highlight);")
        elif "Paused" in status:
            self._status_label.setStyleSheet("color: #747474;")
        elif "Ready" in status:
            # Ready state - subtle blue-gray to indicate document is loaded
            if is_unsaved:
                self._status_label.setStyleSheet("color: #e67e22;")  # Orange for unsaved
            else:
                self._status_label.setStyleSheet("color: #5d8aa8;")  # Air Force blue - ready but not tracking
        elif status == "Unsaved":
            self._status_label.setStyleSheet("color: #e67e22;")  # Orange
        else:
            self._status_label.setStyleSheet("color: #747474;")
    
    def canvasChanged(self, canvas) -> None:
        """Called when the canvas changes (Krita API)."""
        # Just update display - extension handles tracking
        QTimer.singleShot(100, self._update_display)
    
    def closeEvent(self, event) -> None:
        """Handle docker close."""
        self._update_timer.stop()
        self._layout_timer.stop()
        super().closeEvent(event)
