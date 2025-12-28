"""
Timer Manager for Krita Work Timer
Handles all timing logic, state machine, and buffer management
"""

from enum import Enum, auto
from typing import Optional, Callable, Tuple, Dict, Any
from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class TimerState(Enum):
    """States for the work timer state machine."""
    STOPPED = auto()      # No document open or tracking disabled
    RUNNING = auto()      # Actively tracking work time
    BUFFER = auto()       # No activity, 60-second buffer countdown
    PAUSED = auto()       # Buffer expired, waiting for activity
    COGNITIVE_CHECK = auto()  # Showing cognitive work dialog


class CognitiveDecisionType(Enum):
    """Type of cognitive work decision."""
    AUTO_ACCEPT = auto()   # Auto-accepted based on confidence
    AUTO_DISCARD = auto()  # Auto-discarded based on confidence
    USER_ACCEPT = auto()   # User confirmed thinking
    USER_REJECT = auto()   # User rejected thinking


class TimerManager(QObject):
    """
    Manages the work timer state machine.
    
    States:
    - STOPPED: Initial state, no tracking
    - RUNNING: Activity detected, counting work time
    - BUFFER: No activity for a moment, 60s countdown before pausing
    - PAUSED: Buffer expired, timer paused at T_pause
    - COGNITIVE_CHECK: Activity detected after pause, asking user about cognitive work
    
    Transitions:
    - STOPPED → RUNNING: Document opened + activity detected
    - RUNNING → BUFFER: No activity detected
    - BUFFER → RUNNING: Activity detected within 60s
    - BUFFER → PAUSED: 60s expires without activity
    - PAUSED → COGNITIVE_CHECK: Activity detected within T_limit
    - PAUSED → STOPPED: T_limit exceeded (auto-discard)
    - COGNITIVE_CHECK → RUNNING: User confirms cognitive work (add idle time)
    - COGNITIVE_CHECK → RUNNING: User denies cognitive work (discard idle time)
    """
    
    # Signals
    state_changed = pyqtSignal(TimerState)
    time_updated = pyqtSignal(int)  # Total seconds
    cognitive_check_needed = pyqtSignal(int, float, object)  # Idle seconds, confidence, decision
    cognitive_auto_decided = pyqtSignal(bool, int, float)  # was_accepted, seconds, confidence
    
    # Constants
    BUFFER_DURATION_MS = 60 * 1000  # 60 seconds
    TICK_INTERVAL_MS = 1000  # 1 second
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # State
        self._state = TimerState.STOPPED
        self._total_seconds = 0
        self._buffer_seconds = 0
        self._pause_timestamp = 0  # When we entered PAUSED state
        self._idle_seconds = 0  # Time spent in PAUSED state
        
        # Configuration
        self._t_limit_minutes = 20  # Will be loaded from storage
        
        # Cognitive decision callback (set by extension)
        self._cognitive_decision_callback: Optional[Callable] = None
        
        # Last cognitive check info for undo support
        self._last_auto_decision: Optional[Tuple[bool, int, float]] = None
        
        # Timers
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self.TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._on_tick)
        
        self._buffer_timer = QTimer(self)
        self._buffer_timer.setSingleShot(True)
        self._buffer_timer.timeout.connect(self._on_buffer_expired)
    
    @property
    def state(self) -> TimerState:
        """Current timer state."""
        return self._state
    
    @property
    def total_seconds(self) -> int:
        """Total tracked work time in seconds."""
        return self._total_seconds
    
    @property
    def t_limit_minutes(self) -> int:
        """Current T_limit in minutes."""
        return self._t_limit_minutes
    
    @t_limit_minutes.setter
    def t_limit_minutes(self, value: int) -> None:
        """Set T_limit (clamped to 15-25)."""
        self._t_limit_minutes = max(15, min(25, value))
    
    @property
    def idle_seconds(self) -> int:
        """Current idle time in seconds."""
        return self._idle_seconds
    
    def set_cognitive_decision_callback(self, callback: Optional[Callable]) -> None:
        """Set callback for cognitive decisions. Called with (idle_seconds) -> (confidence, decision)."""
        self._cognitive_decision_callback = callback
    
    def set_total_seconds(self, seconds: int) -> None:
        """Set the total seconds (used when loading from storage)."""
        self._total_seconds = max(0, seconds)
        self.time_updated.emit(self._total_seconds)
    
    def _set_state(self, new_state: TimerState) -> None:
        """Change state and emit signal."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self.state_changed.emit(new_state)
    
    def start(self) -> None:
        """Start or resume the timer."""
        if self._state == TimerState.STOPPED:
            self._set_state(TimerState.RUNNING)
            self._tick_timer.start()
    
    def stop(self) -> None:
        """Completely stop the timer."""
        self._tick_timer.stop()
        self._buffer_timer.stop()
        self._set_state(TimerState.STOPPED)
        self._buffer_seconds = 0
        self._idle_seconds = 0
    
    def reset(self) -> None:
        """Reset the timer to zero."""
        self.stop()
        self._total_seconds = 0
        self.time_updated.emit(0)
    
    def on_activity_detected(self) -> None:
        """Called when user activity is detected."""
        if self._state == TimerState.STOPPED:
            # Start tracking
            self._set_state(TimerState.RUNNING)
            self._tick_timer.start()
        
        elif self._state == TimerState.RUNNING:
            # Already running, just reset buffer state
            pass
        
        elif self._state == TimerState.BUFFER:
            # Activity within buffer period - go back to running
            self._buffer_timer.stop()
            self._buffer_seconds = 0
            self._set_state(TimerState.RUNNING)
        
        elif self._state == TimerState.PAUSED:
            # Activity after pause - check if within T_limit
            if self._idle_seconds <= self._t_limit_minutes * 60:
                # Get cognitive decision from profile
                if self._cognitive_decision_callback:
                    confidence, decision = self._cognitive_decision_callback(self._idle_seconds)
                    
                    # Import here to avoid circular dependency
                    from .cognitive_profile import ConfidenceDecision
                    
                    if decision == ConfidenceDecision.AUTO_ACCEPT:
                        # Auto-accept: add time without asking
                        self._total_seconds += self._idle_seconds
                        self.time_updated.emit(self._total_seconds)
                        self._last_auto_decision = (True, self._idle_seconds, confidence)
                        self.cognitive_auto_decided.emit(True, self._idle_seconds, confidence)
                        self._idle_seconds = 0
                        self._set_state(TimerState.RUNNING)
                        self._tick_timer.start()
                        
                    elif decision == ConfidenceDecision.AUTO_DISCARD:
                        # Auto-discard: discard time without asking
                        self._last_auto_decision = (False, self._idle_seconds, confidence)
                        self.cognitive_auto_decided.emit(False, self._idle_seconds, confidence)
                        self._idle_seconds = 0
                        self._set_state(TimerState.RUNNING)
                        self._tick_timer.start()
                        
                    else:
                        # ASK_USER: show dialog
                        self._set_state(TimerState.COGNITIVE_CHECK)
                        self.cognitive_check_needed.emit(self._idle_seconds, confidence, decision)
                else:
                    # No callback - always ask (fallback behavior)
                    self._set_state(TimerState.COGNITIVE_CHECK)
                    idle_minutes = max(1, self._idle_seconds // 60)
                    self.cognitive_check_needed.emit(self._idle_seconds, 0.5, None)
            else:
                # Beyond T_limit - discard and resume
                self._idle_seconds = 0
                self._set_state(TimerState.RUNNING)
                self._tick_timer.start()
        
        elif self._state == TimerState.COGNITIVE_CHECK:
            # Waiting for dialog response - ignore activity
            pass
    
    def on_activity_stopped(self) -> None:
        """Called when no activity is detected for a moment."""
        if self._state == TimerState.RUNNING:
            # Start buffer countdown
            self._set_state(TimerState.BUFFER)
            self._buffer_seconds = 0
            self._buffer_timer.start(self.BUFFER_DURATION_MS)
    
    def on_cognitive_response(self, was_thinking: bool) -> None:
        """
        Handle user's response to cognitive work question.
        
        Args:
            was_thinking: True if user was doing cognitive work, False otherwise
        """
        if self._state != TimerState.COGNITIVE_CHECK:
            return
        
        if was_thinking:
            # Add idle time to total
            self._total_seconds += self._idle_seconds
            self.time_updated.emit(self._total_seconds)
        
        # Reset idle tracking and resume
        self._idle_seconds = 0
        self._set_state(TimerState.RUNNING)
        self._tick_timer.start()
    
    def undo_last_auto_decision(self) -> Optional[Tuple[bool, int]]:
        """
        Undo the last auto-decision if available.
        
        Returns:
            (was_accepted, seconds) if undo was performed, None otherwise
        """
        if self._last_auto_decision is None:
            return None
        
        was_accepted, seconds, _ = self._last_auto_decision
        
        if was_accepted:
            # Was auto-accepted, so subtract the time
            self._total_seconds = max(0, self._total_seconds - seconds)
            self.time_updated.emit(self._total_seconds)
        else:
            # Was auto-discarded, so add the time
            self._total_seconds += seconds
            self.time_updated.emit(self._total_seconds)
        
        result = (was_accepted, seconds)
        self._last_auto_decision = None
        return result
    
    def _on_tick(self) -> None:
        """Called every second by the tick timer."""
        if self._state == TimerState.RUNNING:
            self._total_seconds += 1
            self.time_updated.emit(self._total_seconds)
        
        elif self._state == TimerState.BUFFER:
            # Still count as work time during buffer
            self._total_seconds += 1
            self._buffer_seconds += 1
            self.time_updated.emit(self._total_seconds)
        
        elif self._state == TimerState.PAUSED:
            # Count idle time (not added to total yet)
            self._idle_seconds += 1
            
            # Check if we exceeded T_limit
            if self._idle_seconds > self._t_limit_minutes * 60:
                # Auto-discard idle time
                self._idle_seconds = 0
                # Stay paused, waiting for next activity
    
    def _on_buffer_expired(self) -> None:
        """Called when the 60-second buffer expires."""
        if self._state == TimerState.BUFFER:
            # Transition to paused
            self._set_state(TimerState.PAUSED)
            self._idle_seconds = 0  # Start counting idle time from now
    
    def get_display_time(self) -> tuple:
        """
        Get the current time for display purposes.
        
        Returns:
            Tuple of (hours, minutes) for display
        """
        total_minutes = self._total_seconds // 60
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return (hours, minutes)
    
    def format_time(self) -> str:
        """
        Format the current time as a human-readable string.
        
        Returns:
            String like "8 hrs 32 mins" or "45 mins" or "1 hr 5 mins"
        """
        hours, minutes = self.get_display_time()
        
        parts = []
        
        if hours > 0:
            hr_label = "hr" if hours == 1 else "hrs"
            parts.append(f"{hours} {hr_label}")
        
        if minutes > 0 or hours == 0:
            min_label = "min" if minutes == 1 else "mins"
            parts.append(f"{minutes} {min_label}")
        
        return " ".join(parts)
