"""
Cognitive Profile for Krita Work Timer
Manages per-user cognitive work patterns and confidence-based decision making

This module implements:
- Per-user behavior profiling with statistical distributions
- Confidence scoring for auto-accept/auto-discard/ask decisions
- Pause pattern classification (micro-thinking, planning, context-switch, break)
- Project-specific learning modifiers
- Bayesian updating with exponential decay
"""

import math
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime


class PausePattern(Enum):
    """Classification of pause patterns."""
    MICRO_THINKING = auto()    # ≤3 min, frequent, usually validated
    PLANNING_PAUSE = auto()    # 5–12 min, often validated
    CONTEXT_SWITCH = auto()    # Often rejected, focus lost
    BREAK = auto()             # Long, low validation rate
    UNKNOWN = auto()           # Not enough data to classify


class ConfidenceDecision(Enum):
    """Decision based on confidence scoring."""
    AUTO_ACCEPT = auto()       # ≥85% confidence - auto-add time
    AUTO_DISCARD = auto()      # ≤20% confidence - auto-discard
    ASK_USER = auto()          # Between - ask the user


@dataclass
class ActivityBurst:
    """Represents a burst of activity before a pause."""
    timestamp: float
    duration_seconds: float
    intensity: float  # 0.0 to 1.0 (low to high activity)
    event_count: int


@dataclass
class PauseEvent:
    """Represents a single pause event for learning."""
    timestamp: float
    duration_seconds: int
    was_validated: bool
    pattern: PausePattern
    pre_pause_intensity: float  # Activity intensity before pause
    session_age_minutes: int     # How long session was running
    hour_of_day: int
    project_hash: Optional[str] = None


@dataclass
class IdleBucket:
    """Statistics for an idle duration bucket."""
    min_seconds: int
    max_seconds: int
    total_count: int = 0
    validated_count: int = 0
    
    @property
    def validation_rate(self) -> float:
        """Get validation rate for this bucket."""
        if self.total_count == 0:
            return 0.5  # Default to uncertain
        return self.validated_count / self.total_count
    
    @property
    def confidence(self) -> float:
        """Get confidence in the validation rate (0-1 based on sample size)."""
        # Wilson score lower bound for 95% confidence
        if self.total_count == 0:
            return 0.0
        n = self.total_count
        p = self.validation_rate
        z = 1.96  # 95% confidence
        denominator = 1 + z * z / n
        centre_adjusted_probability = p + z * z / (2 * n)
        adjusted_standard_deviation = math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
        lower_bound = (centre_adjusted_probability - z * adjusted_standard_deviation) / denominator
        return max(0, min(1, lower_bound))


@dataclass
class ProjectModifier:
    """Per-project learning modifier."""
    file_hash: str
    last_filename: str = ""
    total_validations: int = 0
    total_rejections: int = 0
    avg_validated_idle: float = 300.0  # 5 minutes default
    session_count: int = 0
    total_work_time: int = 0
    
    @property
    def validation_rate(self) -> float:
        """Project-specific validation rate."""
        total = self.total_validations + self.total_rejections
        if total == 0:
            return 0.5
        return self.total_validations / total
    
    @property
    def project_phase(self) -> str:
        """Estimate project phase based on work time."""
        hours = self.total_work_time / 3600
        if hours < 2:
            return "early"
        elif hours < 10:
            return "mid"
        else:
            return "late"


class CognitiveProfile:
    """
    Manages the user's cognitive work profile.
    
    Tracks statistical distributions of validated idle times and uses
    confidence scoring to decide when to ask the user vs auto-decide.
    """
    
    # Idle duration buckets (in seconds)
    BUCKET_RANGES = [
        (0, 180),      # 0-3 minutes
        (180, 420),    # 3-7 minutes
        (420, 900),    # 7-15 minutes
        (900, 1500),   # 15-25 minutes
        (1500, 3600),  # 25-60 minutes
    ]
    
    # Confidence thresholds
    AUTO_ACCEPT_THRESHOLD = 0.85
    AUTO_DISCARD_THRESHOLD = 0.20
    
    # Decay factor for exponential weighted averaging (recent matters more)
    DECAY_FACTOR = 0.95
    
    # Minimum samples before auto-decisions are enabled
    MIN_SAMPLES_FOR_AUTO = 10
    
    # Trust level thresholds
    TRUST_LEVEL_HIGH = 0.8
    TRUST_LEVEL_MEDIUM = 0.5
    
    def __init__(self):
        # Idle duration buckets
        self._buckets: Dict[str, IdleBucket] = {}
        self._init_buckets()
        
        # Recent pause events for pattern analysis
        self._recent_pauses: List[PauseEvent] = []
        self._max_recent_pauses = 100
        
        # Activity tracking for intensity calculation
        self._activity_bursts: List[ActivityBurst] = []
        self._last_activity_time = 0.0
        self._activity_count_window = 0
        self._window_start_time = 0.0
        
        # Session tracking
        self._session_start_time = 0.0
        self._consecutive_validated = 0
        self._consecutive_rejected = 0
        
        # Project modifiers
        self._project_modifiers: Dict[str, ProjectModifier] = {}
        self._current_project_hash: Optional[str] = None
        
        # Global statistics
        self._total_validations = 0
        self._total_rejections = 0
        self._longest_validated_streak = 0
        self._current_streak = 0
        
        # Negative signals
        self._focus_lost_count = 0
        self._repeated_rejection_patterns: List[Tuple[int, float]] = []
        
        # User preference bias (-1 to 1: -1 = only count drawing, 1 = count all thinking)
        self._user_bias = 0.0
        
        # Trust system
        self._implicit_trust_enabled = False
        self._notification_mode = False  # If True, show notification instead of dialog
        self._last_notification_time = 0.0
        self._pending_undo: Optional[Tuple[float, int]] = None  # (timestamp, seconds)
        
    def _init_buckets(self) -> None:
        """Initialize idle duration buckets."""
        for min_sec, max_sec in self.BUCKET_RANGES:
            key = self._bucket_key(min_sec)
            self._buckets[key] = IdleBucket(min_seconds=min_sec, max_seconds=max_sec)
    
    def _bucket_key(self, seconds: int) -> str:
        """Get bucket key for a given duration."""
        for min_sec, max_sec in self.BUCKET_RANGES:
            if min_sec <= seconds < max_sec:
                return f"{min_sec}-{max_sec}"
        # Beyond last bucket
        return f"{self.BUCKET_RANGES[-1][0]}-{self.BUCKET_RANGES[-1][1]}"
    
    def _get_bucket(self, seconds: int) -> IdleBucket:
        """Get the bucket for a given duration."""
        key = self._bucket_key(seconds)
        return self._buckets.get(key, self._buckets[list(self._buckets.keys())[-1]])
    
    # ==================== Activity Tracking ====================
    
    def record_activity(self) -> None:
        """Record an activity event for intensity tracking."""
        now = time.time()
        
        # Track activity in current window (30-second windows)
        if now - self._window_start_time > 30:
            # Save previous window as activity burst if meaningful
            if self._activity_count_window > 0:
                duration = now - self._window_start_time
                intensity = min(1.0, self._activity_count_window / 60)  # Normalize
                burst = ActivityBurst(
                    timestamp=self._window_start_time,
                    duration_seconds=duration,
                    intensity=intensity,
                    event_count=self._activity_count_window
                )
                self._activity_bursts.append(burst)
                
                # Keep only recent bursts (last 5 minutes)
                cutoff = now - 300
                self._activity_bursts = [b for b in self._activity_bursts if b.timestamp > cutoff]
            
            # Start new window
            self._window_start_time = now
            self._activity_count_window = 0
        
        self._activity_count_window += 1
        self._last_activity_time = now
    
    def get_pre_pause_intensity(self) -> float:
        """Calculate activity intensity before current pause."""
        if not self._activity_bursts:
            return 0.5  # Default to medium
        
        # Weight recent bursts more heavily
        total_weight = 0.0
        weighted_intensity = 0.0
        
        for i, burst in enumerate(reversed(self._activity_bursts[-5:])):
            weight = self.DECAY_FACTOR ** i
            total_weight += weight
            weighted_intensity += burst.intensity * weight
        
        if total_weight == 0:
            return 0.5
        
        return weighted_intensity / total_weight
    
    # ==================== Pause Pattern Classification ====================
    
    def classify_pause(self, duration_seconds: int, pre_intensity: float) -> PausePattern:
        """
        Classify a pause into a pattern type.
        
        Uses duration, pre-pause intensity, and historical patterns.
        """
        minutes = duration_seconds / 60
        
        # Micro-thinking: short pauses after intense activity
        if minutes <= 3 and pre_intensity > 0.5:
            return PausePattern.MICRO_THINKING
        
        # Planning pause: medium duration, often after moderate activity
        if 5 <= minutes <= 12:
            return PausePattern.PLANNING_PAUSE
        
        # Context switch: check for repeated short rejections
        recent_rejections = sum(
            1 for p in self._recent_pauses[-5:]
            if not p.was_validated and p.duration_seconds < 300
        )
        if recent_rejections >= 2 and minutes < 10:
            return PausePattern.CONTEXT_SWITCH
        
        # Break: long pauses
        if minutes > 15:
            return PausePattern.BREAK
        
        return PausePattern.UNKNOWN
    
    # ==================== Confidence Scoring ====================
    
    def calculate_confidence(
        self, 
        idle_seconds: int,
        project_hash: Optional[str] = None
    ) -> Tuple[float, ConfidenceDecision, Dict[str, float]]:
        """
        Calculate confidence score for whether idle time was cognitive work.
        
        Returns:
            (confidence, decision, factors_breakdown)
        """
        factors = {}
        
        # 1. Base rate from bucket
        bucket = self._get_bucket(idle_seconds)
        base_rate = bucket.validation_rate
        bucket_confidence = bucket.confidence
        factors["bucket_rate"] = base_rate
        factors["bucket_confidence"] = bucket_confidence
        
        # 2. Pre-pause activity intensity
        pre_intensity = self.get_pre_pause_intensity()
        # High intensity before pause → more likely thinking
        intensity_factor = 0.5 + (pre_intensity * 0.3)
        factors["pre_pause_intensity"] = pre_intensity
        
        # 3. Session context
        session_age = (time.time() - self._session_start_time) / 60 if self._session_start_time > 0 else 0
        # Early sessions tend to have more thinking
        session_factor = 1.0 if session_age < 30 else 0.9 if session_age < 60 else 0.8
        factors["session_age_minutes"] = session_age
        factors["session_factor"] = session_factor
        
        # 4. Time of day factor
        hour = datetime.now().hour
        # Research tends to happen more in morning and late afternoon
        time_factor = 1.0
        if 9 <= hour <= 11 or 14 <= hour <= 17:
            time_factor = 1.05
        elif hour < 7 or hour > 22:
            time_factor = 0.9
        factors["hour_of_day"] = hour
        factors["time_factor"] = time_factor
        
        # 5. Consecutive validation streak factor
        streak_factor = 1.0
        if self._consecutive_validated >= 3:
            streak_factor = 1.1  # User in thinking mode
        elif self._consecutive_rejected >= 3:
            streak_factor = 0.85  # User in non-thinking mode
        factors["streak_factor"] = streak_factor
        
        # 6. Project-specific modifier
        project_factor = 1.0
        if project_hash and project_hash in self._project_modifiers:
            modifier = self._project_modifiers[project_hash]
            project_rate = modifier.validation_rate
            # Weight project rate with global rate
            project_factor = 0.7 + (project_rate * 0.3)
            
            # Adjust for project phase
            if modifier.project_phase == "early":
                project_factor *= 1.1  # More thinking in early phase
            elif modifier.project_phase == "late":
                project_factor *= 0.95  # Less thinking in polish phase
            
            factors["project_validation_rate"] = project_rate
            factors["project_phase"] = modifier.project_phase
        factors["project_factor"] = project_factor
        
        # 7. Negative signals adjustment
        negative_adjustment = 1.0
        if self._focus_lost_count > 0:
            negative_adjustment *= max(0.7, 1 - (self._focus_lost_count * 0.05))
        factors["negative_adjustment"] = negative_adjustment
        
        # 8. User bias
        bias_adjustment = 1.0 + (self._user_bias * 0.2)
        factors["user_bias"] = self._user_bias
        
        # Calculate final confidence
        # Start with bucket rate, weighted by bucket confidence
        # Low confidence in bucket → rely more on other factors
        if bucket_confidence > 0.5:
            base_confidence = base_rate
        else:
            # Fall back to global rate or default
            global_rate = self._total_validations / max(1, self._total_validations + self._total_rejections)
            base_confidence = (base_rate * bucket_confidence) + (global_rate * (1 - bucket_confidence))
        
        # Apply all factors
        final_confidence = (
            base_confidence * 
            intensity_factor * 
            session_factor * 
            time_factor * 
            streak_factor * 
            project_factor * 
            negative_adjustment *
            bias_adjustment
        )
        
        # Clamp to [0, 1]
        final_confidence = max(0.0, min(1.0, final_confidence))
        factors["final_confidence"] = final_confidence
        
        # Determine decision
        total_samples = sum(b.total_count for b in self._buckets.values())
        
        if total_samples < self.MIN_SAMPLES_FOR_AUTO:
            # Not enough data - always ask
            decision = ConfidenceDecision.ASK_USER
        elif final_confidence >= self.AUTO_ACCEPT_THRESHOLD:
            decision = ConfidenceDecision.AUTO_ACCEPT
        elif final_confidence <= self.AUTO_DISCARD_THRESHOLD:
            decision = ConfidenceDecision.AUTO_DISCARD
        else:
            decision = ConfidenceDecision.ASK_USER
        
        return final_confidence, decision, factors
    
    # ==================== Learning ====================
    
    def record_validation(
        self, 
        idle_seconds: int, 
        was_validated: bool,
        project_hash: Optional[str] = None
    ) -> None:
        """Record the result of a cognitive work validation."""
        # Update bucket stats with decay
        bucket = self._get_bucket(idle_seconds)
        bucket.total_count += 1
        if was_validated:
            bucket.validated_count += 1
        
        # Apply exponential decay to old entries
        self._apply_decay_to_buckets()
        
        # Update global stats
        if was_validated:
            self._total_validations += 1
            self._consecutive_validated += 1
            self._consecutive_rejected = 0
            self._current_streak += 1
            if self._current_streak > self._longest_validated_streak:
                self._longest_validated_streak = self._current_streak
        else:
            self._total_rejections += 1
            self._consecutive_rejected += 1
            self._consecutive_validated = 0
            self._current_streak = 0
        
        # Record pause event
        pre_intensity = self.get_pre_pause_intensity()
        pattern = self.classify_pause(idle_seconds, pre_intensity)
        session_age = int((time.time() - self._session_start_time) / 60) if self._session_start_time > 0 else 0
        
        event = PauseEvent(
            timestamp=time.time(),
            duration_seconds=idle_seconds,
            was_validated=was_validated,
            pattern=pattern,
            pre_pause_intensity=pre_intensity,
            session_age_minutes=session_age,
            hour_of_day=datetime.now().hour,
            project_hash=project_hash
        )
        self._recent_pauses.append(event)
        
        # Keep only recent pauses
        if len(self._recent_pauses) > self._max_recent_pauses:
            self._recent_pauses = self._recent_pauses[-self._max_recent_pauses:]
        
        # Update project modifier
        if project_hash:
            self._update_project_modifier(project_hash, idle_seconds, was_validated)
        
        # Track rejection patterns for negative signals
        if not was_validated:
            self._repeated_rejection_patterns.append((idle_seconds, pre_intensity))
            if len(self._repeated_rejection_patterns) > 20:
                self._repeated_rejection_patterns = self._repeated_rejection_patterns[-20:]
        
        # Reset focus lost count after any interaction
        self._focus_lost_count = max(0, self._focus_lost_count - 1)
    
    def _apply_decay_to_buckets(self) -> None:
        """Apply exponential decay to bucket statistics."""
        # Apply decay every 50 total samples
        total = sum(b.total_count for b in self._buckets.values())
        if total > 0 and total % 50 == 0:
            for bucket in self._buckets.values():
                bucket.total_count = int(bucket.total_count * self.DECAY_FACTOR)
                bucket.validated_count = int(bucket.validated_count * self.DECAY_FACTOR)
    
    def _update_project_modifier(
        self, 
        project_hash: str, 
        idle_seconds: int, 
        was_validated: bool
    ) -> None:
        """Update project-specific modifier."""
        if project_hash not in self._project_modifiers:
            self._project_modifiers[project_hash] = ProjectModifier(file_hash=project_hash)
        
        modifier = self._project_modifiers[project_hash]
        if was_validated:
            modifier.total_validations += 1
            # Update running average of validated idle time
            modifier.avg_validated_idle = (
                (modifier.avg_validated_idle * (modifier.total_validations - 1) + idle_seconds) /
                modifier.total_validations
            )
        else:
            modifier.total_rejections += 1
    
    # ==================== Negative Signals ====================
    
    def record_focus_lost(self) -> None:
        """Record that window focus was lost."""
        self._focus_lost_count += 1
    
    def record_focus_regained(self) -> None:
        """Record that window focus was regained."""
        # Keep some memory of focus loss
        self._focus_lost_count = max(0, self._focus_lost_count - 0.5)
    
    # ==================== Trust System ====================
    
    def get_trust_level(self) -> float:
        """
        Get current trust level (0-1).
        
        Higher trust = more auto-decisions and notifications instead of dialogs.
        """
        total_samples = self._total_validations + self._total_rejections
        if total_samples < self.MIN_SAMPLES_FOR_AUTO:
            return 0.0
        
        # Calculate based on:
        # 1. Sample size
        sample_confidence = min(1.0, total_samples / 100)
        
        # 2. Consistency of responses (low variance = high trust)
        consistency = 0.5
        if total_samples > 0:
            rate = self._total_validations / total_samples
            # High consistency if rate is strongly positive or negative
            consistency = abs(rate - 0.5) * 2
        
        # 3. Longest streak
        streak_bonus = min(0.2, self._longest_validated_streak / 50)
        
        trust = (sample_confidence * 0.4) + (consistency * 0.4) + streak_bonus
        return min(1.0, trust)
    
    def should_use_notification(self) -> bool:
        """Check if notification mode should be used instead of dialog."""
        if not self._implicit_trust_enabled:
            return False
        return self.get_trust_level() >= self.TRUST_LEVEL_HIGH
    
    def set_user_bias(self, bias: float) -> None:
        """Set user bias (-1 to 1)."""
        self._user_bias = max(-1.0, min(1.0, bias))
    
    def enable_implicit_trust(self, enabled: bool) -> None:
        """Enable or disable implicit trust mode."""
        self._implicit_trust_enabled = enabled
    
    def set_pending_undo(self, seconds: int) -> None:
        """Set a pending undo for auto-accepted time."""
        self._pending_undo = (time.time(), seconds)
    
    def check_and_clear_undo(self, max_age_seconds: float = 10.0) -> Optional[int]:
        """Check if there's a pending undo within time limit."""
        if self._pending_undo is None:
            return None
        
        timestamp, seconds = self._pending_undo
        if time.time() - timestamp <= max_age_seconds:
            self._pending_undo = None
            return seconds
        
        self._pending_undo = None
        return None
    
    # ==================== Session Management ====================
    
    def start_session(self, project_hash: Optional[str] = None) -> None:
        """Start a new work session."""
        self._session_start_time = time.time()
        self._current_project_hash = project_hash
        self._focus_lost_count = 0
        self._activity_bursts.clear()
        
        if project_hash and project_hash in self._project_modifiers:
            self._project_modifiers[project_hash].session_count += 1
    
    def update_project_work_time(self, project_hash: str, total_seconds: int) -> None:
        """Update total work time for a project."""
        if project_hash not in self._project_modifiers:
            self._project_modifiers[project_hash] = ProjectModifier(file_hash=project_hash)
        self._project_modifiers[project_hash].total_work_time = total_seconds
    
    # ==================== Statistics & UI ====================
    
    def get_accuracy_indicator(self) -> Tuple[str, float]:
        """
        Get thinking time accuracy indicator for UI.
        
        Returns:
            (label, percentage)
        """
        trust = self.get_trust_level()
        
        if trust >= self.TRUST_LEVEL_HIGH:
            return ("High", trust * 100)
        elif trust >= self.TRUST_LEVEL_MEDIUM:
            return ("Medium", trust * 100)
        else:
            return ("Learning", trust * 100)
    
    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics for display."""
        total = self._total_validations + self._total_rejections
        return {
            "total_samples": total,
            "validation_rate": self._total_validations / total if total > 0 else 0,
            "longest_streak": self._longest_validated_streak,
            "trust_level": self.get_trust_level(),
            "buckets": {
                key: {
                    "validation_rate": bucket.validation_rate,
                    "sample_count": bucket.total_count
                }
                for key, bucket in self._buckets.items()
            }
        }
    
    def get_pattern_summary(self) -> Dict[str, int]:
        """Get summary of pause patterns."""
        patterns = {p.name: 0 for p in PausePattern}
        for event in self._recent_pauses:
            patterns[event.pattern.name] += 1
        return patterns
    
    # ==================== Serialization ====================
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize profile to dictionary for storage."""
        return {
            "buckets": {
                key: {
                    "min": b.min_seconds,
                    "max": b.max_seconds,
                    "total": b.total_count,
                    "validated": b.validated_count
                }
                for key, b in self._buckets.items()
            },
            "total_validations": self._total_validations,
            "total_rejections": self._total_rejections,
            "longest_validated_streak": self._longest_validated_streak,
            "user_bias": self._user_bias,
            "implicit_trust_enabled": self._implicit_trust_enabled,
            "project_modifiers": {
                key: {
                    "file_hash": m.file_hash,
                    "last_filename": m.last_filename,
                    "total_validations": m.total_validations,
                    "total_rejections": m.total_rejections,
                    "avg_validated_idle": m.avg_validated_idle,
                    "session_count": m.session_count,
                    "total_work_time": m.total_work_time
                }
                for key, m in self._project_modifiers.items()
            }
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load profile from dictionary."""
        if not data:
            return
        
        # Load buckets
        if "buckets" in data:
            for key, b_data in data["buckets"].items():
                if key in self._buckets:
                    self._buckets[key].total_count = b_data.get("total", 0)
                    self._buckets[key].validated_count = b_data.get("validated", 0)
        
        # Load global stats
        self._total_validations = data.get("total_validations", 0)
        self._total_rejections = data.get("total_rejections", 0)
        self._longest_validated_streak = data.get("longest_validated_streak", 0)
        self._user_bias = data.get("user_bias", 0.0)
        self._implicit_trust_enabled = data.get("implicit_trust_enabled", False)
        
        # Load project modifiers
        if "project_modifiers" in data:
            for key, m_data in data["project_modifiers"].items():
                self._project_modifiers[key] = ProjectModifier(
                    file_hash=m_data.get("file_hash", key),
                    last_filename=m_data.get("last_filename", ""),
                    total_validations=m_data.get("total_validations", 0),
                    total_rejections=m_data.get("total_rejections", 0),
                    avg_validated_idle=m_data.get("avg_validated_idle", 300.0),
                    session_count=m_data.get("session_count", 0),
                    total_work_time=m_data.get("total_work_time", 0)
                )
