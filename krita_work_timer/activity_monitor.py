"""
Activity Monitor for Krita Work Timer
Detects meaningful user interactions with the canvas and application
"""

from PyQt5.QtCore import QObject, QEvent, pyqtSignal, QTimer
from PyQt5.QtWidgets import QApplication


class ActivityMonitor(QObject):
    """
    Monitors user activity through Qt event filtering.
    
    Detects:
    - Mouse movements and clicks (on canvas)
    - Keyboard input
    - Tablet/Pen interactions
    - Scroll events
    
    Tracks:
    - Activity intensity (events per time window)
    - Activity types for pattern classification
    
    Filters out:
    - Menu interactions (not meaningful work)
    - Window management events
    - System events
    """
    
    # Emitted when meaningful activity is detected
    activity_detected = pyqtSignal()
    
    # Emitted when window focus changes
    focus_changed = pyqtSignal(bool)  # True = focus gained, False = focus lost
    
    # Event types we consider as meaningful activity
    ACTIVITY_EVENTS = {
        QEvent.MouseButtonPress,
        QEvent.MouseButtonRelease,
        QEvent.MouseMove,
        QEvent.KeyPress,
        QEvent.KeyRelease,
        QEvent.TabletPress,
        QEvent.TabletRelease,
        QEvent.TabletMove,
        QEvent.Wheel,
        QEvent.TouchBegin,
        QEvent.TouchUpdate,
        QEvent.TouchEnd,
    }
    
    # High-intensity activity events (direct canvas work)
    HIGH_INTENSITY_EVENTS = {
        QEvent.TabletPress,
        QEvent.TabletMove,
        QEvent.MouseButtonPress,
    }
    
    # Low-intensity activity events (navigation, UI)
    LOW_INTENSITY_EVENTS = {
        QEvent.Wheel,
        QEvent.KeyPress,
    }
    
    # Throttle activity signals to avoid overwhelming the system
    THROTTLE_MS = 500
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_monitoring = False
        self._throttle_timer = QTimer(self)
        self._throttle_timer.setSingleShot(True)
        self._can_emit = True
        self._throttle_timer.timeout.connect(self._reset_throttle)
        
        # Activity intensity tracking
        self._high_intensity_count = 0
        self._low_intensity_count = 0
        self._last_intensity_reset = 0
        
        # Focus tracking
        self._has_focus = True
    
    def start_monitoring(self) -> None:
        """Start monitoring user activity."""
        if not self._is_monitoring:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                self._is_monitoring = True
    
    def stop_monitoring(self) -> None:
        """Stop monitoring user activity."""
        if self._is_monitoring:
            app = QApplication.instance()
            if app:
                app.removeEventFilter(self)
                self._is_monitoring = False
    
    def _reset_throttle(self) -> None:
        """Reset the throttle to allow new activity signals."""
        self._can_emit = True
    
    def _is_meaningful_event(self, obj: QObject, event: QEvent) -> bool:
        """
        Determine if an event represents meaningful work activity.
        
        We want to capture:
        - Drawing/editing on canvas
        - Keyboard shortcuts and text input
        - Tool interactions
        
        We want to ignore:
        - Pure menu browsing without action
        - Window focus changes
        - Tooltip displays
        """
        event_type = event.type()
        
        # Track focus changes (negative signal)
        if event_type == QEvent.WindowActivate:
            if not self._has_focus:
                self._has_focus = True
                self.focus_changed.emit(True)
            return False
        elif event_type == QEvent.WindowDeactivate:
            if self._has_focus:
                self._has_focus = False
                self.focus_changed.emit(False)
            return False
        
        # Quick reject for non-activity events
        if event_type not in self.ACTIVITY_EVENTS:
            return False
        
        # Track intensity
        if event_type in self.HIGH_INTENSITY_EVENTS:
            self._high_intensity_count += 1
        elif event_type in self.LOW_INTENSITY_EVENTS:
            self._low_intensity_count += 1
        
        # Get the widget class name for filtering
        class_name = obj.__class__.__name__ if obj else ""
        
        # Filter out menu interactions (menus should not count as work)
        if "Menu" in class_name:
            return False
        
        # Filter out tooltips
        if "ToolTip" in class_name:
            return False
        
        # Filter out scrollbars (debatable, but pure scrolling isn't work)
        # Actually, let's include scrollbar - navigating canvas is work
        
        # Mouse move without buttons pressed is often just hovering
        # But for tablets, any movement is likely intentional
        if event_type == QEvent.MouseMove:
            from PyQt5.QtCore import Qt
            from PyQt5.QtGui import QMouseEvent
            if isinstance(event, QMouseEvent):
                # Only count mouse moves with buttons pressed (dragging)
                if event.buttons() == Qt.NoButton:
                    return False
        
        # Keyboard events - filter out pure modifier keys
        if event_type in (QEvent.KeyPress, QEvent.KeyRelease):
            from PyQt5.QtCore import Qt
            from PyQt5.QtGui import QKeyEvent
            if isinstance(event, QKeyEvent):
                # Ignore standalone modifier keys
                if event.key() in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
                    return False
        
        return True
    
    def get_intensity_ratio(self) -> float:
        """
        Get ratio of high-intensity to total activity.
        
        Returns value from 0.0 (all low intensity) to 1.0 (all high intensity).
        """
        total = self._high_intensity_count + self._low_intensity_count
        if total == 0:
            return 0.5  # Default to medium
        return self._high_intensity_count / total
    
    def reset_intensity_tracking(self) -> tuple:
        """
        Reset intensity counters and return current values.
        
        Returns:
            (high_count, low_count, ratio)
        """
        high = self._high_intensity_count
        low = self._low_intensity_count
        ratio = self.get_intensity_ratio()
        
        self._high_intensity_count = 0
        self._low_intensity_count = 0
        
        return (high, low, ratio)
    
    @property
    def has_focus(self) -> bool:
        """Check if window currently has focus."""
        return self._has_focus
    
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Qt event filter - intercepts all application events."""
        if self._is_meaningful_event(obj, event):
            if self._can_emit:
                self._can_emit = False
                self._throttle_timer.start(self.THROTTLE_MS)
                self.activity_detected.emit()
        
        # Never consume the event - always pass it on
        return False
    
    def is_monitoring(self) -> bool:
        """Check if currently monitoring."""
        return self._is_monitoring
