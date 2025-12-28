"""
Work Timer Extension for Krita
Core tracking logic that runs regardless of docker visibility
"""

from typing import Optional, Tuple, Dict
import uuid as uuid_module

from krita import Extension, Krita

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, QUuid

from .storage import WorkTimerStorage
from .activity_monitor import ActivityMonitor
from .timer_manager import TimerManager, TimerState
from .cognitive_dialog import CognitiveWorkDialog, CognitiveNotification
from .cognitive_profile import CognitiveProfile, ConfidenceDecision


class WorkTimerExtension(Extension):
    """
    Extension that handles all work time tracking.
    
    This runs as long as the plugin is enabled, regardless of 
    whether the docker is visible or not.
    """
    
    # Singleton instance
    _instance: Optional['WorkTimerExtension'] = None
    
    # Signals for UI updates
    time_updated = pyqtSignal(int)
    state_changed = pyqtSignal(TimerState)
    
    # How often to check for document changes (ms)
    DOCUMENT_CHECK_INTERVAL = 2000
    
    # How long without activity before we consider user idle (ms)
    IDLE_THRESHOLD = 3000
    
    def __init__(self, parent):
        super().__init__(parent)
        WorkTimerExtension._instance = self
        
        # Core components
        self._storage = WorkTimerStorage()
        self._activity_monitor = ActivityMonitor()
        self._timer_manager = TimerManager()
        self._cognitive_profile = CognitiveProfile()
        
        # State tracking
        self._current_file_hash: Optional[str] = None
        self._current_file_path: Optional[str] = None
        self._current_doc_id: Optional[str] = None  # Unique ID for current document (saved or unsaved)
        self._current_doc_name: Optional[str] = None  # Document name (e.g., "Untitled-1" or "myfile.kra")
        self._current_root_uuid: Optional[str] = None  # Root node UUID - truly unique per document
        self._last_activity_time = 0
        self._cognitive_dialog: Optional[CognitiveWorkDialog] = None
        self._cognitive_notification: Optional[CognitiveNotification] = None
        
        # Unsaved document time tracking (in-memory only, discarded if not saved)
        # Maps root node UUID (truly unique per document) to accumulated seconds
        # This ensures each unsaved document has its own time tracking
        self._unsaved_doc_times: Dict[str, int] = {}
        
        # Timers (will be set up in setup())
        self._doc_check_timer: Optional[QTimer] = None
        self._idle_check_timer: Optional[QTimer] = None
        
        self._initialized = False
    
    @classmethod
    def instance(cls) -> Optional['WorkTimerExtension']:
        """Get the singleton instance."""
        return cls._instance
    
    def setup(self):
        """Called once when Krita starts. Set up the extension."""
        pass  # We'll do actual setup in createActions when app is ready
    
    def createActions(self, window):
        """Called when a new window is created. Initialize tracking here."""
        if self._initialized:
            return
        
        self._initialized = True
        
        # Connect signals
        self._connect_signals()
        
        # Set up document monitoring
        self._doc_check_timer = QTimer()
        self._doc_check_timer.setInterval(self.DOCUMENT_CHECK_INTERVAL)
        self._doc_check_timer.timeout.connect(self._check_document)
        self._doc_check_timer.start()
        
        # Idle detection timer
        self._idle_check_timer = QTimer()
        self._idle_check_timer.setInterval(1000)
        self._idle_check_timer.timeout.connect(self._check_idle)
        self._idle_check_timer.start()
        
        # Load T_limit from storage
        self._timer_manager.t_limit_minutes = self._storage.get_t_limit()
        
        # Load cognitive profile
        self._cognitive_profile.from_dict(self._storage.get_cognitive_profile_data())
        self._cognitive_profile.set_user_bias(self._storage.get_user_bias())
        self._cognitive_profile.enable_implicit_trust(self._storage.get_implicit_trust_enabled())
        
        # Set cognitive decision callback
        self._timer_manager.set_cognitive_decision_callback(self._get_cognitive_decision)
        
        # Start activity monitoring
        self._activity_monitor.start_monitoring()
        
        # Initial document check
        QTimer.singleShot(500, self._check_document)
    
    def _connect_signals(self) -> None:
        """Connect all signal handlers."""
        # Activity monitor
        self._activity_monitor.activity_detected.connect(self._on_activity)
        self._activity_monitor.focus_changed.connect(self._on_focus_changed)
        
        # Timer manager
        self._timer_manager.time_updated.connect(self._on_time_updated)
        self._timer_manager.state_changed.connect(self._on_state_changed)
        self._timer_manager.cognitive_check_needed.connect(self._show_cognitive_dialog)
        self._timer_manager.cognitive_auto_decided.connect(self._show_cognitive_notification)
    
    @property
    def timer_manager(self) -> TimerManager:
        """Access to timer manager for UI."""
        return self._timer_manager
    
    @property
    def storage(self) -> WorkTimerStorage:
        """Access to storage for UI."""
        return self._storage
    
    @property
    def cognitive_profile(self) -> CognitiveProfile:
        """Access to cognitive profile for UI."""
        return self._cognitive_profile
    
    def _get_current_document_path(self) -> Optional[str]:
        """Get the file path of the currently active document."""
        app = Krita.instance()
        doc = app.activeDocument()
        
        if doc is None:
            return None
        
        path = doc.fileName()
        if not path:
            return None
        
        # Track any saved file
        return path
    
    def _get_current_document_info(self) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], bool]:
        """
        Get information about the currently active document.
        
        Returns:
            Tuple of (doc_name, doc_unique_id, root_uuid, file_path, is_saved)
            - doc_name: The document's display name (e.g., "Untitled-1" or "myfile.kra")
            - doc_unique_id: A unique identifier for this document instance (for storage keys)
            - root_uuid: The root node's UUID - truly unique per document instance
            - file_path: The file path if saved, None if unsaved
            - is_saved: True if document has been saved to disk
        """
        app = Krita.instance()
        doc = app.activeDocument()
        
        if doc is None:
            return (None, None, None, None, False)
        
        doc_name = doc.name()  # This is consistent for the document's lifetime
        file_path = doc.fileName()
        is_saved = bool(file_path)
        
        # Get the root node's UUID - this is truly unique per document instance
        # It's created when the document is created and persists through saves
        root_uuid = None
        try:
            root_node = doc.rootNode()
            if root_node:
                # uniqueId() returns a QUuid, convert to string
                root_uuid = str(root_node.uniqueId())
                # Remove braces if present (QUuid.toString() format)
                if root_uuid.startswith('{'):
                    root_uuid = root_uuid[1:-1]
        except Exception as e:
            print(f"WorkTimer: Error getting root UUID: {e}")
        
        if is_saved:
            # For saved documents, use the file path as the unique ID for storage
            doc_unique_id = file_path
        else:
            # For unsaved documents, use the root UUID as the unique identifier
            # This ensures each unsaved document has its own time tracking
            # even if they have the same display name (e.g., multiple "Untitled-1")
            doc_unique_id = f"unsaved:{root_uuid}" if root_uuid else f"unsaved:{doc_name}"
        
        return (doc_name, doc_unique_id, root_uuid, file_path if is_saved else None, is_saved)
    
    def _check_document(self) -> None:
        """Check if the active document has changed or been saved."""
        doc_name, doc_id, root_uuid, file_path, is_saved = self._get_current_document_info()
        
        # Check if an unsaved document was just saved
        # Using root_uuid ensures we correctly identify the same document even across saves
        # This happens when: same root UUID, previously unsaved, now has a file path
        if (root_uuid and 
            root_uuid == self._current_root_uuid and 
            self._current_doc_id and 
            self._current_doc_id.startswith("unsaved:") and 
            is_saved):
            # Document was just saved! Transfer unsaved time to saved file
            old_unsaved_id = self._current_doc_id
            self._transfer_unsaved_time_to_saved(old_unsaved_id, file_path, doc_name)
            # Update tracking state
            self._current_doc_id = doc_id
            self._current_file_path = file_path
            # Note: Keep _current_root_uuid the same - it doesn't change on save
            return
        
        # Check if we switched to a different document
        # We use root_uuid as the primary identifier since it's truly unique per document
        if root_uuid != self._current_root_uuid:
            # Document changed - save current progress and switch
            self._save_current_progress()
            
            self._current_doc_name = doc_name
            self._current_doc_id = doc_id
            self._current_root_uuid = root_uuid
            self._current_file_path = file_path
            
            # Check if we have a valid document - either by root_uuid (most reliable)
            # or by file_path (for saved docs) or doc_id (for any tracked doc)
            has_valid_document = root_uuid is not None or file_path is not None or doc_id is not None
            
            if has_valid_document:
                if is_saved and file_path:
                    # Saved document - use persistent storage
                    self._handle_saved_document(file_path)
                elif doc_id:
                    # Unsaved document - track in memory using root_uuid as key
                    self._handle_unsaved_document(doc_id)
                else:
                    # Edge case: document exists but not fully initialized
                    # Start timer anyway, will be updated on next check
                    self._timer_manager.start()
            else:
                # No document at all
                self._current_file_hash = None
                self._current_root_uuid = None
                self._timer_manager.stop()
                self._timer_manager.set_total_seconds(0)
    
    def _handle_saved_document(self, file_path: str) -> None:
        """Handle switching to a saved document."""
        import os
        filename = os.path.basename(file_path)
        
        # Compute hash for the saved document
        new_hash = WorkTimerStorage.compute_file_hash(file_path)
        self._current_file_hash = new_hash
        
        if new_hash:
            # Try to load existing time from our storage first
            existing_time = self._storage.get_work_time(new_hash)
            
            # For non-archive files, try move detection via content fingerprint
            if existing_time == 0 and not file_path.lower().endswith(('.kra', '.ora', '.krz')):
                content_fingerprint = WorkTimerStorage.compute_content_fingerprint(file_path)
                print(f"WorkTimer: Checking for moved file. Path: {file_path}, Hash: {new_hash[:8]}..., Fingerprint: {content_fingerprint[:8] if content_fingerprint else 'None'}...")
                
                if content_fingerprint:
                    # Check if this file exists under a different path (was moved)
                    match = self._storage.find_by_content_fingerprint(content_fingerprint)
                    
                    if match:
                        old_hash, old_record = match
                        old_path = old_record.get("last_filepath", "unknown")
                        print(f"WorkTimer: Found matching fingerprint! Old path: {old_path}, Old hash: {old_hash[:8]}...")
                        # Migrate the record to the new path
                        if self._storage.migrate_file_record(old_hash, new_hash, file_path, filename):
                            existing_time = old_record.get("total_seconds", 0)
                            print(f"WorkTimer: Detected moved file, restored {existing_time // 60} mins")
                    else:
                        print(f"WorkTimer: No matching fingerprint found in storage. This appears to be a new file.")
            
            if existing_time == 0:
                # No stored time - check if file has embedded editing time
                initial_time, source = WorkTimerStorage.get_file_initial_time(file_path)
                
                if source == "krita_metadata" and initial_time > 0:
                    existing_time = initial_time
                    content_fingerprint = WorkTimerStorage.compute_content_fingerprint(file_path)
                    self._storage.set_work_time(new_hash, existing_time, filename, 
                                                file_path, content_fingerprint or "")
                    print(f"WorkTimer: Initialized from Krita metadata: {existing_time // 60} mins")
            
            self._timer_manager.set_total_seconds(existing_time)
            self._timer_manager.start()
            
            # Start cognitive profile session
            self._cognitive_profile.start_session(new_hash)
            self._cognitive_profile.update_project_work_time(new_hash, existing_time)
        else:
            self._timer_manager.set_total_seconds(0)
            self._timer_manager.start()
    
    def _handle_unsaved_document(self, doc_id: str) -> None:
        """Handle switching to an unsaved document."""
        self._current_file_hash = None
        
        # Restore any previously accumulated time for this unsaved doc
        existing_time = self._unsaved_doc_times.get(doc_id, 0)
        
        self._timer_manager.set_total_seconds(existing_time)
        self._timer_manager.start()
        
        # Use a placeholder hash for cognitive profile
        self._cognitive_profile.start_session(doc_id)
    
    def _transfer_unsaved_time_to_saved(self, unsaved_doc_id: str, file_path: str, doc_name: str = "") -> None:
        """
        Transfer time from an unsaved document to its newly saved file.
        
        Called when user saves a previously unsaved document.
        """
        import os
        
        # Get the current timer value (includes unsaved time)
        current_time = self._timer_manager.total_seconds
        
        # Also check if there's stored unsaved time (in case timer was reset)
        stored_unsaved_time = self._unsaved_doc_times.get(unsaved_doc_id, 0)
        if stored_unsaved_time > current_time:
            current_time = stored_unsaved_time
        
        # Update our state
        self._current_file_path = file_path
        new_hash = WorkTimerStorage.compute_file_hash(file_path)
        self._current_file_hash = new_hash
        
        if new_hash:
            filename = os.path.basename(file_path)
            
            # Check if there's existing time for this file (edge case: saving over existing file)
            existing_time = self._storage.get_work_time(new_hash)
            
            # Add our current session time to any existing time
            total_time = existing_time + current_time
            
            # Save to persistent storage
            content_fingerprint = ""
            if not file_path.lower().endswith(('.kra', '.ora', '.krz')):
                content_fingerprint = WorkTimerStorage.compute_content_fingerprint(file_path) or ""
            
            self._storage.set_work_time(new_hash, total_time, filename, file_path, content_fingerprint)
            
            # Update timer display with the total
            self._timer_manager.set_total_seconds(total_time)
            
            # Start cognitive profile session for the saved file
            self._cognitive_profile.start_session(new_hash)
            self._cognitive_profile.update_project_work_time(new_hash, total_time)
            
            print(f"WorkTimer: Transferred {current_time // 60} mins to saved file: {filename}")
        
        # Clean up unsaved tracking
        if unsaved_doc_id in self._unsaved_doc_times:
            del self._unsaved_doc_times[unsaved_doc_id]
    
    def _save_current_progress(self) -> None:
        """Save progress for the current file or unsaved document."""
        if self._timer_manager.total_seconds == 0:
            return
        
        if self._current_file_hash and self._current_file_path:
            # Saved document - persist to storage
            import os
            filename = os.path.basename(self._current_file_path)
            filepath = self._current_file_path
            content_fingerprint = ""
            
            # Compute content fingerprint for non-archive files (for move detection)
            if not self._current_file_path.lower().endswith(('.kra', '.ora', '.krz')):
                content_fingerprint = WorkTimerStorage.compute_content_fingerprint(
                    self._current_file_path
                ) or ""
            
            self._storage.set_work_time(
                self._current_file_hash,
                self._timer_manager.total_seconds,
                filename,
                filepath,
                content_fingerprint
            )
        elif self._current_doc_id and self._current_doc_id.startswith("unsaved:"):
            # Unsaved document - store in memory
            self._unsaved_doc_times[self._current_doc_id] = self._timer_manager.total_seconds
    
    def _on_activity(self) -> None:
        """Handle activity detection."""
        import time
        self._last_activity_time = time.time()
        
        # Record activity for cognitive profile
        self._cognitive_profile.record_activity()
        
        # Track activity for any document (saved or unsaved)
        if self._current_doc_id:
            self._timer_manager.on_activity_detected()
    
    def _on_focus_changed(self, has_focus: bool) -> None:
        """Handle window focus changes (negative signal)."""
        if has_focus:
            self._cognitive_profile.record_focus_regained()
        else:
            self._cognitive_profile.record_focus_lost()
    
    def _check_idle(self) -> None:
        """Check if user has gone idle."""
        import time
        
        if self._last_activity_time == 0:
            return
        
        elapsed_ms = (time.time() - self._last_activity_time) * 1000
        
        if elapsed_ms > self.IDLE_THRESHOLD:
            if self._timer_manager.state == TimerState.RUNNING:
                self._timer_manager.on_activity_stopped()
    
    def _on_time_updated(self, total_seconds: int) -> None:
        """Handle time updates."""
        # Periodic save (every 30 seconds)
        if total_seconds > 0 and total_seconds % 30 == 0:
            self._save_current_progress()
        
        # Update project work time in profile
        if self._current_file_hash:
            self._cognitive_profile.update_project_work_time(self._current_file_hash, total_seconds)
    
    def _on_state_changed(self, state: TimerState) -> None:
        """Handle state changes."""
        pass  # Docker will observe timer_manager directly
    
    def _get_cognitive_decision(self, idle_seconds: int) -> Tuple[float, ConfidenceDecision]:
        """
        Get cognitive decision from profile.
        
        Called by timer_manager when activity resumes after pause.
        Returns (confidence, decision) tuple.
        """
        confidence, decision, _ = self._cognitive_profile.calculate_confidence(
            idle_seconds,
            project_hash=self._current_file_hash
        )
        return (confidence, decision)
    
    def _show_cognitive_dialog(self, idle_seconds: int, confidence: float, decision: object) -> None:
        """Show the cognitive work dialog."""
        if self._cognitive_dialog is not None:
            self._cognitive_dialog.close()
        
        # Get main window as parent for proper positioning
        app = Krita.instance()
        main_window = app.activeWindow()
        parent = main_window.qwindow() if main_window else None
        
        self._cognitive_dialog = CognitiveWorkDialog(idle_seconds, confidence, parent)
        self._cognitive_dialog.response_given.connect(self._on_cognitive_response)
        self._cognitive_dialog.show()
    
    def _show_cognitive_notification(self, was_accepted: bool, seconds: int, confidence: float) -> None:
        """Show notification for auto-decision."""
        if self._cognitive_notification is not None:
            self._cognitive_notification.close()
        
        # Get main window as parent for proper positioning
        app = Krita.instance()
        main_window = app.activeWindow()
        parent = main_window.qwindow() if main_window else None
        
        self._cognitive_notification = CognitiveNotification(was_accepted, seconds, parent)
        self._cognitive_notification.undo_requested.connect(self._on_notification_undo)
        self._cognitive_notification.show()
        
        # Record the decision in profile (for learning)
        self._cognitive_profile.record_validation(
            seconds, 
            was_accepted,
            project_hash=self._current_file_hash
        )
    
    def _on_notification_undo(self) -> None:
        """Handle undo request from notification."""
        result = self._timer_manager.undo_last_auto_decision()
        if result:
            was_accepted, seconds = result
            # Record the correction (opposite of original)
            self._cognitive_profile.record_validation(
                seconds,
                not was_accepted,  # Opposite
                project_hash=self._current_file_hash
            )
    
    def _on_cognitive_response(self, was_thinking: bool) -> None:
        """Handle cognitive work dialog response."""
        # Get idle seconds before processing
        idle_seconds = self._timer_manager.idle_seconds
        
        # Record validation in profile (for learning)
        self._cognitive_profile.record_validation(
            idle_seconds, 
            was_thinking,
            project_hash=self._current_file_hash
        )
        
        # Adjust T_limit based on response (legacy behavior)
        if was_thinking:
            new_limit = self._storage.adjust_t_limit(1)  # +1 minute
        else:
            new_limit = self._storage.adjust_t_limit(-1)  # -1 minute
        
        self._timer_manager.t_limit_minutes = new_limit
        
        # Inform timer manager
        self._timer_manager.on_cognitive_response(was_thinking)
        
        # Clean up dialog
        if self._cognitive_dialog:
            self._cognitive_dialog = None
        
        # Save profile periodically
        self._save_cognitive_profile()
    
    def _save_cognitive_profile(self) -> None:
        """Save cognitive profile to storage."""
        self._storage.set_cognitive_profile_data(self._cognitive_profile.to_dict())
    
    def shutdown(self) -> None:
        """Clean up when plugin is disabled or Krita closes."""
        self._save_current_progress()
        self._save_cognitive_profile()
        self._activity_monitor.stop_monitoring()
        
        if self._doc_check_timer:
            self._doc_check_timer.stop()
        if self._idle_check_timer:
            self._idle_check_timer.stop()
        
        if self._cognitive_dialog:
            self._cognitive_dialog.close()
        if self._cognitive_notification:
            self._cognitive_notification.close()
