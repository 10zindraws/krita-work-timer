"""
Storage module for Krita Work Timer
Handles persistent storage of work times per file using content hashing
"""

import json
import hashlib
import zipfile
import os
import struct
import xml.etree.ElementTree as ET
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from krita import Krita


class WorkTimerStorage:
    """Manages persistent storage of work times for individual files."""
    
    STORAGE_VERSION = 2  # Bumped for cognitive profile support
    STORAGE_FILENAME = "krita_work_timer_data.json"
    
    def __init__(self):
        self._data: Dict[str, Any] = {
            "version": self.STORAGE_VERSION,
            "files": {},
            "settings": {
                "t_limit_minutes": 20,
                "user_bias": 0.0,  # -1 to 1: thinking preference
                "implicit_trust_enabled": False,
                "auto_accept_threshold": 0.85,
                "auto_discard_threshold": 0.20
            },
            "cognitive_profile": {}  # Cognitive work profile data
        }
        self._storage_path = self._get_storage_path()
        self._load()
    
    def _get_storage_path(self) -> Path:
        """Get the path where we store our data file."""
        # Use Krita's resource folder for persistence across versions
        krita_resources = Path(Krita.instance().readSetting("", "ResourceDirectory", ""))
        
        if not krita_resources or not krita_resources.exists():
            # Fallback to appdata
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                krita_resources = Path(appdata) / "krita"
            else:
                krita_resources = Path.home() / ".krita"
        
        # Create our plugin's data directory
        plugin_data_dir = krita_resources / "work_timer_data"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        
        return plugin_data_dir / self.STORAGE_FILENAME
    
    def _load(self) -> None:
        """Load data from storage file."""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    # Merge with defaults to handle version upgrades
                    self._data["version"] = loaded_data.get("version", self.STORAGE_VERSION)
                    self._data["files"] = loaded_data.get("files", {})
                    self._data["settings"] = {
                        **self._data["settings"],
                        **loaded_data.get("settings", {})
                    }
                    self._data["cognitive_profile"] = loaded_data.get("cognitive_profile", {})
            except (json.JSONDecodeError, IOError) as e:
                print(f"WorkTimer: Error loading storage: {e}")
    
    def _save(self) -> None:
        """Save data to storage file."""
        try:
            with open(self._storage_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"WorkTimer: Error saving storage: {e}")
    
    @staticmethod
    def compute_file_hash(filepath: str) -> Optional[str]:
        """
        Compute a STABLE unique identifier for a file.
        
        For .kra/.ora files: Use the document UUID from documentinfo.xml
        (this is created once and never changes, surviving all saves).
        
        For other files: Use a hash of the filepath (since content changes
        with every save, we can't rely on content hashing).
        
        This ensures work time persists across sessions and file saves.
        """
        if not filepath or not os.path.exists(filepath):
            return None
        
        try:
            hasher = hashlib.sha256()
            
            # Check if file is a ZIP-based format (.kra, .ora, etc.)
            is_zip_format = filepath.lower().endswith(('.kra', '.ora', '.krz'))
            
            if is_zip_format:
                try:
                    with zipfile.ZipFile(filepath, 'r') as archive:
                        # Extract document UUID from documentinfo.xml - this is STABLE
                        if 'documentinfo.xml' in archive.namelist():
                            doc_info = archive.read('documentinfo.xml').decode('utf-8')
                            
                            # Parse UUID using regex (more reliable than full XML parse)
                            # Look for <md:uuid>...</md:uuid> or just <uuid>...</uuid>
                            uuid_match = re.search(r'<(?:md:)?uuid>([^<]+)</(?:md:)?uuid>', doc_info)
                            if uuid_match:
                                doc_uuid = uuid_match.group(1).strip()
                                if doc_uuid:
                                    # Use UUID directly - it's already unique
                                    return hashlib.sha256(doc_uuid.encode('utf-8')).hexdigest()[:32]
                            
                            # Fallback: look for creation-date which is also stable
                            date_match = re.search(r'<(?:dcterms:)?created>([^<]+)</(?:dcterms:)?created>', doc_info)
                            if date_match:
                                creation_date = date_match.group(1).strip()
                                if creation_date:
                                    hasher.update(creation_date.encode('utf-8'))
                                    # Also add mimetype for verification
                                    if 'mimetype' in archive.namelist():
                                        hasher.update(archive.read('mimetype'))
                                    return hasher.hexdigest()[:32]
                except zipfile.BadZipFile:
                    pass  # Fall through to path-based hashing
            
            # For non-archive files (.png, .jpg, etc.), use filepath-based identification
            # Content hashing doesn't work because the content changes with every save
            # Normalize the path for consistent hashing
            normalized_path = os.path.normcase(os.path.abspath(filepath))
            hasher.update(normalized_path.encode('utf-8'))
            return hasher.hexdigest()[:32]
            
        except (IOError, OSError) as e:
            print(f"WorkTimer: Error computing hash for {filepath}: {e}")
            return None
    
    @staticmethod
    def compute_content_fingerprint(filepath: str) -> Optional[str]:
        """
        Compute a content-based fingerprint for non-archive image files.
        
        This fingerprint is used to detect when files have been moved/renamed.
        It combines:
        - Image dimensions (width x height)
        - File size
        - A sample of pixel data from the middle of the file
        
        This fingerprint survives file moves but changes when the image is edited.
        For archive files (.kra), returns None (they use UUID-based identification).
        
        Returns: A 32-character hex fingerprint, or None if unable to compute.
        """
        if not filepath or not os.path.exists(filepath):
            return None
        
        # Skip archive formats - they use UUID-based identification
        if filepath.lower().endswith(('.kra', '.ora', '.krz')):
            return None
        
        try:
            hasher = hashlib.sha256()
            file_size = os.path.getsize(filepath)
            
            # Add file size to fingerprint
            hasher.update(f"size:{file_size}".encode('utf-8'))
            
            # Try to extract image dimensions
            dimensions = WorkTimerStorage._get_image_dimensions(filepath)
            if dimensions:
                width, height = dimensions
                hasher.update(f"dim:{width}x{height}".encode('utf-8'))
            
            # Sample content from middle of file (more stable than header/footer)
            # This part of pixel data is less likely to be affected by metadata changes
            with open(filepath, 'rb') as f:
                # Read a sample from the middle of the file
                if file_size > 8192:
                    # For larger files, sample from the middle
                    middle_offset = file_size // 2 - 2048
                    f.seek(middle_offset)
                    sample = f.read(4096)
                else:
                    # For small files, use the whole content
                    sample = f.read()
                
                hasher.update(sample)
            
            return hasher.hexdigest()[:32]
            
        except (IOError, OSError) as e:
            print(f"WorkTimer: Error computing fingerprint for {filepath}: {e}")
            return None
    
    @staticmethod
    def _get_image_dimensions(filepath: str) -> Optional[Tuple[int, int]]:
        """
        Extract image dimensions from common image formats.
        
        Supports: PNG, JPEG, GIF, BMP, WebP, TIFF
        Returns: (width, height) tuple or None if unable to parse.
        """
        try:
            with open(filepath, 'rb') as f:
                header = f.read(32)
                
                if len(header) < 8:
                    return None
                
                # PNG: signature + IHDR chunk
                if header[:8] == b'\x89PNG\r\n\x1a\n':
                    # IHDR chunk starts at byte 8, width/height are at bytes 16-23
                    if len(header) >= 24:
                        width = struct.unpack('>I', header[16:20])[0]
                        height = struct.unpack('>I', header[20:24])[0]
                        return (width, height)
                
                # JPEG: look for SOF0 or SOF2 marker
                if header[:2] == b'\xff\xd8':
                    f.seek(2)
                    while True:
                        marker = f.read(2)
                        if len(marker) < 2:
                            break
                        if marker[0] != 0xFF:
                            break
                        marker_type = marker[1]
                        
                        # SOF0 (0xC0) or SOF2 (0xC2) contain dimensions
                        if marker_type in (0xC0, 0xC2):
                            f.read(3)  # Skip length and precision
                            dim_data = f.read(4)
                            if len(dim_data) == 4:
                                height = struct.unpack('>H', dim_data[0:2])[0]
                                width = struct.unpack('>H', dim_data[2:4])[0]
                                return (width, height)
                        
                        # Skip other segments
                        if marker_type == 0xD9:  # EOI
                            break
                        if marker_type in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01, 0x00):
                            continue  # No length field
                        
                        length_data = f.read(2)
                        if len(length_data) < 2:
                            break
                        length = struct.unpack('>H', length_data)[0]
                        f.seek(length - 2, 1)  # Skip segment content
                
                # GIF: dimensions at bytes 6-9
                if header[:6] in (b'GIF87a', b'GIF89a'):
                    width = struct.unpack('<H', header[6:8])[0]
                    height = struct.unpack('<H', header[8:10])[0]
                    return (width, height)
                
                # BMP: dimensions at bytes 18-25
                if header[:2] == b'BM':
                    f.seek(18)
                    dim_data = f.read(8)
                    if len(dim_data) >= 8:
                        width = struct.unpack('<I', dim_data[0:4])[0]
                        height = abs(struct.unpack('<i', dim_data[4:8])[0])
                        return (width, height)
                
                # WebP: RIFF header with VP8 chunk
                if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
                    f.seek(12)
                    chunk_header = f.read(8)
                    if chunk_header[:4] == b'VP8 ':
                        # Lossy WebP
                        f.seek(3, 1)  # Skip to frame tag
                        frame_data = f.read(6)
                        if len(frame_data) >= 6:
                            width = struct.unpack('<H', frame_data[0:2])[0] & 0x3FFF
                            height = struct.unpack('<H', frame_data[2:4])[0] & 0x3FFF
                            return (width, height)
                    elif chunk_header[:4] == b'VP8L':
                        # Lossless WebP
                        f.read(1)  # Skip signature
                        size_data = f.read(4)
                        if len(size_data) >= 4:
                            bits = struct.unpack('<I', size_data)[0]
                            width = (bits & 0x3FFF) + 1
                            height = ((bits >> 14) & 0x3FFF) + 1
                            return (width, height)
                
                return None
                
        except (IOError, OSError, struct.error):
            return None
    
    @staticmethod
    def get_krita_editing_time(filepath: str) -> Optional[int]:
        """
        Read Krita's embedded "Total editing time" from a .kra file.
        
        Krita stores this in documentinfo.xml as <editing-time>SECONDS</editing-time>
        or <time>SECONDS</time> in the calligra namespace.
        
        Returns the editing time in seconds, or None if not found.
        """
        if not filepath or not os.path.exists(filepath):
            return None
        
        if not filepath.lower().endswith(('.kra', '.ora', '.krz')):
            return None
        
        try:
            with zipfile.ZipFile(filepath, 'r') as archive:
                if 'documentinfo.xml' not in archive.namelist():
                    return None
                
                doc_info = archive.read('documentinfo.xml').decode('utf-8')
                
                # Look for editing-time in various formats Krita might use
                # Format 1: <editing-time>SECONDS</editing-time>
                time_match = re.search(r'<(?:calligra:)?editing-time>([\d.]+)</(?:calligra:)?editing-time>', doc_info)
                if time_match:
                    try:
                        return int(float(time_match.group(1)))
                    except ValueError:
                        pass
                
                # Format 2: <time>SECONDS</time> within editing-cycles
                time_match = re.search(r'<time>([\d.]+)</time>', doc_info)
                if time_match:
                    try:
                        return int(float(time_match.group(1)))
                    except ValueError:
                        pass
                
                return None
                
        except (zipfile.BadZipFile, IOError, OSError) as e:
            print(f"WorkTimer: Error reading editing time from {filepath}: {e}")
            return None
    
    @staticmethod
    def get_file_initial_time(filepath: str) -> Tuple[int, str]:
        """
        Determine the initial work time for a file based on its metadata.
        
        For .kra files with "Total editing time" > 1 minute:
            Returns (adjusted_time, "krita_metadata")
            The time is adjusted using a logarithmic scaling factor to account
            for thinking time between brushstrokes.
        
        For files with <= 1 minute or no metadata:
            Returns (0, "new_file")
        
        The adjustment formula accounts for:
        - Short sessions: More thinking time proportionally (higher multiplier)
        - Long sessions: Less thinking overhead proportionally (lower multiplier)
        - Baseline: ~1.3x for medium sessions, scaling from 1.5x to 1.15x
        
        Returns: (initial_seconds, source_type)
        """
        krita_time = WorkTimerStorage.get_krita_editing_time(filepath)
        
        if krita_time is None or krita_time <= 60:  # 1 minute threshold
            return (0, "new_file")
        
        # Apply thinking time adjustment
        # Use logarithmic scaling: shorter sessions get higher multiplier
        # Formula: multiplier = 1.15 + 0.35 / (1 + log10(minutes))
        # This gives:
        #   - 2 min session: ~1.41x multiplier
        #   - 10 min session: ~1.32x multiplier  
        #   - 30 min session: ~1.27x multiplier
        #   - 60 min session: ~1.23x multiplier
        #   - 120 min session: ~1.22x multiplier
        # This is more accurate than a static 1.3x as it accounts for
        # the fact that thinking/planning happens more at the start
        
        import math
        minutes = krita_time / 60.0
        
        # Clamp minimum to avoid log(0)
        if minutes < 0.5:
            minutes = 0.5
        
        # Logarithmic scaling formula
        multiplier = 1.15 + 0.35 / (1.0 + math.log10(minutes))
        
        # Clamp multiplier to reasonable range (1.15 to 1.5)
        multiplier = max(1.15, min(1.5, multiplier))
        
        adjusted_time = int(krita_time * multiplier)
        
        return (adjusted_time, "krita_metadata")
    
    def get_work_time(self, file_hash: str) -> int:
        """Get total work time in seconds for a file hash."""
        if file_hash in self._data["files"]:
            return self._data["files"][file_hash].get("total_seconds", 0)
        return 0
    
    def set_work_time(self, file_hash: str, total_seconds: int, filename: str = "", 
                       filepath: str = "", content_fingerprint: str = "") -> None:
        """Set total work time for a file hash.
        
        Args:
            file_hash: The path-based hash identifier
            total_seconds: Total work time in seconds
            filename: Optional filename for display
            filepath: Optional full path (for future reference)
            content_fingerprint: Optional content fingerprint for move detection
        """
        if file_hash not in self._data["files"]:
            self._data["files"][file_hash] = {}
        
        self._data["files"][file_hash]["total_seconds"] = total_seconds
        self._data["files"][file_hash]["last_accessed"] = datetime.now().isoformat()
        
        if filename:
            self._data["files"][file_hash]["last_filename"] = filename
        
        if filepath:
            self._data["files"][file_hash]["last_filepath"] = filepath
        
        if content_fingerprint:
            self._data["files"][file_hash]["content_fingerprint"] = content_fingerprint
        
        self._save()
    
    def add_work_time(self, file_hash: str, seconds_to_add: int, filename: str = "") -> int:
        """Add work time to existing total. Returns new total."""
        current = self.get_work_time(file_hash)
        new_total = current + seconds_to_add
        self.set_work_time(file_hash, new_total, filename)
        return new_total
    
    def find_by_content_fingerprint(self, fingerprint: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Find a file record by its content fingerprint.
        
        This is used to detect when a file has been moved to a new location.
        If the same content fingerprint exists under a different path hash,
        we can migrate the record.
        
        Args:
            fingerprint: The content fingerprint to search for
            
        Returns:
            Tuple of (old_hash, record_data) if found, None otherwise
        """
        if not fingerprint:
            return None
        
        for file_hash, record in self._data["files"].items():
            stored_fingerprint = record.get("content_fingerprint", "")
            if stored_fingerprint == fingerprint:
                return (file_hash, record)
        
        return None
    
    def migrate_file_record(self, old_hash: str, new_hash: str, new_filepath: str, 
                            new_filename: str = "") -> bool:
        """
        Migrate a file record from an old hash to a new hash.
        
        This is used when a file has been detected as moved (same content fingerprint,
        different path hash). The work time and other data are preserved.
        
        Args:
            old_hash: The original path-based hash
            new_hash: The new path-based hash for the moved file
            new_filepath: The new file path
            new_filename: The new filename
            
        Returns:
            True if migration successful, False otherwise
        """
        if old_hash not in self._data["files"]:
            return False
        
        if old_hash == new_hash:
            return True  # No migration needed
        
        # Get old path for logging before we delete the record
        old_path = self._data["files"][old_hash].get("last_filepath", old_hash[:8])
        
        # Copy record to new hash
        old_record = self._data["files"][old_hash].copy()
        old_record["last_accessed"] = datetime.now().isoformat()
        old_record["last_filepath"] = new_filepath
        old_record["migrated_from"] = old_hash
        
        if new_filename:
            old_record["last_filename"] = new_filename
        
        # Store under new hash
        self._data["files"][new_hash] = old_record
        
        # Remove old record
        del self._data["files"][old_hash]
        
        self._save()
        
        print(f"WorkTimer: Migrated file record from {old_path} to {new_filepath}")
        
        return True
    
    def get_t_limit(self) -> int:
        """Get T_limit in minutes."""
        return self._data["settings"].get("t_limit_minutes", 20)
    
    def set_t_limit(self, minutes: int) -> None:
        """Set T_limit in minutes (clamped to 15-25 range)."""
        minutes = max(15, min(25, minutes))
        self._data["settings"]["t_limit_minutes"] = minutes
        self._save()
    
    def adjust_t_limit(self, delta: int) -> int:
        """Adjust T_limit by delta minutes. Returns new value."""
        current = self.get_t_limit()
        new_value = max(15, min(25, current + delta))
        self.set_t_limit(new_value)
        return new_value
    
    # ==================== Cognitive Profile Storage ====================
    
    def get_cognitive_profile_data(self) -> Dict[str, Any]:
        """Get cognitive profile data for loading into CognitiveProfile."""
        return self._data.get("cognitive_profile", {})
    
    def set_cognitive_profile_data(self, profile_data: Dict[str, Any]) -> None:
        """Save cognitive profile data."""
        self._data["cognitive_profile"] = profile_data
        self._save()
    
    def get_user_bias(self) -> float:
        """Get user thinking bias (-1 to 1)."""
        return self._data["settings"].get("user_bias", 0.0)
    
    def set_user_bias(self, bias: float) -> None:
        """Set user thinking bias (-1 to 1)."""
        bias = max(-1.0, min(1.0, bias))
        self._data["settings"]["user_bias"] = bias
        self._save()
    
    def get_implicit_trust_enabled(self) -> bool:
        """Check if implicit trust mode is enabled."""
        return self._data["settings"].get("implicit_trust_enabled", False)
    
    def set_implicit_trust_enabled(self, enabled: bool) -> None:
        """Enable or disable implicit trust mode."""
        self._data["settings"]["implicit_trust_enabled"] = enabled
        self._save()
    
    def get_confidence_thresholds(self) -> tuple:
        """Get auto-accept and auto-discard thresholds."""
        settings = self._data["settings"]
        return (
            settings.get("auto_accept_threshold", 0.85),
            settings.get("auto_discard_threshold", 0.20)
        )
    
    def set_confidence_thresholds(self, accept: float, discard: float) -> None:
        """Set confidence thresholds for auto-decisions."""
        self._data["settings"]["auto_accept_threshold"] = max(0.5, min(1.0, accept))
        self._data["settings"]["auto_discard_threshold"] = max(0.0, min(0.5, discard))
        self._save()
    
    # ==================== File Records ====================
    
    def get_all_file_records(self) -> Dict[str, Any]:
        """Get all file records for debugging/export."""
        return self._data["files"].copy()
    
    def cleanup_old_records(self, days_threshold: int = 365) -> int:
        """Remove records not accessed in specified days. Returns count removed."""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=days_threshold)
        removed = 0
        
        hashes_to_remove = []
        for file_hash, record in self._data["files"].items():
            last_accessed_str = record.get("last_accessed", "")
            if last_accessed_str:
                try:
                    last_accessed = datetime.fromisoformat(last_accessed_str)
                    if last_accessed < cutoff:
                        hashes_to_remove.append(file_hash)
                except ValueError:
                    pass
        
        for file_hash in hashes_to_remove:
            del self._data["files"][file_hash]
            removed += 1
        
        if removed > 0:
            self._save()
        
        return removed
