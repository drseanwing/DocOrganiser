"""
Shortcut Creator for Document Organizer v2.

Creates different types of shortcuts/links to files:
- Symbolic links (Linux/Mac)
- .url files (cross-platform Internet Shortcut format)
- .desktop files (Linux desktop entries)
"""

import os
from pathlib import Path
from typing import Optional
import structlog


class ShortcutCreator:
    """Handles creation of different types of file shortcuts."""
    
    def __init__(self):
        self.logger = structlog.get_logger("shortcut_creator")
    
    def create_symlink(self, target: Path, link_path: Path) -> bool:
        """
        Create a symbolic link.
        
        Args:
            target: Path to the target file
            link_path: Path where the symlink should be created
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure parent directory exists
            link_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Remove existing symlink if present
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            
            # Create symlink
            link_path.symlink_to(target)
            
            self.logger.info(
                "symlink_created",
                target=str(target),
                link=str(link_path)
            )
            return True
            
        except OSError as e:
            self.logger.error(
                "symlink_failed",
                target=str(target),
                link=str(link_path),
                error=str(e)
            )
            return False
    
    def create_url_shortcut(self, target: Path, shortcut_path: Path) -> bool:
        """
        Create a .url file (Windows Internet Shortcut format).
        Works cross-platform as a pointer to a file.
        
        Format:
        [InternetShortcut]
        URL=file:///path/to/target
        
        Args:
            target: Path to the target file
            shortcut_path: Path where the .url file should be created
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure .url extension
            if not shortcut_path.suffix == '.url':
                shortcut_path = shortcut_path.with_suffix(shortcut_path.suffix + '.url')
            
            # Ensure parent directory exists
            shortcut_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert target to absolute path and file URL
            abs_target = target.resolve()
            file_url = f"file:///{abs_target.as_posix()}"
            
            # Write .url file
            content = f"[InternetShortcut]\nURL={file_url}\n"
            shortcut_path.write_text(content, encoding='utf-8')
            
            self.logger.info(
                "url_shortcut_created",
                target=str(target),
                shortcut=str(shortcut_path)
            )
            return True
            
        except Exception as e:
            self.logger.error(
                "url_shortcut_failed",
                target=str(target),
                shortcut=str(shortcut_path),
                error=str(e)
            )
            return False
    
    def create_desktop_shortcut(self, target: Path, shortcut_path: Path) -> bool:
        """
        Create a .desktop file (Linux desktop entry).
        
        Format:
        [Desktop Entry]
        Type=Link
        Name=filename
        URL=file:///path/to/target
        
        Args:
            target: Path to the target file
            shortcut_path: Path where the .desktop file should be created
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure .desktop extension
            if not shortcut_path.suffix == '.desktop':
                shortcut_path = shortcut_path.with_suffix(shortcut_path.suffix + '.desktop')
            
            # Ensure parent directory exists
            shortcut_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert target to absolute path and file URL
            abs_target = target.resolve()
            file_url = f"file://{abs_target.as_posix()}"
            
            # Write .desktop file
            content = (
                "[Desktop Entry]\n"
                "Type=Link\n"
                f"Name={target.name}\n"
                f"URL={file_url}\n"
            )
            shortcut_path.write_text(content, encoding='utf-8')
            
            # Make executable (optional, for Linux)
            try:
                shortcut_path.chmod(0o755)
            except Exception:
                pass  # Not critical if chmod fails
            
            self.logger.info(
                "desktop_shortcut_created",
                target=str(target),
                shortcut=str(shortcut_path)
            )
            return True
            
        except Exception as e:
            self.logger.error(
                "desktop_shortcut_failed",
                target=str(target),
                shortcut=str(shortcut_path),
                error=str(e)
            )
            return False
    
    def create_shortcut(
        self,
        target: Path,
        shortcut_path: Path,
        shortcut_type: str = "auto"
    ) -> tuple[bool, str]:
        """
        Create a shortcut of the specified type.
        
        Args:
            target: Path to the target file
            shortcut_path: Path where the shortcut should be created
            shortcut_type: Type of shortcut to create ('symlink', 'url', 'desktop', 'auto')
            
        Returns:
            Tuple of (success: bool, actual_type: str)
        """
        if shortcut_type == "auto":
            # Try symlink first (best option)
            if self.create_symlink(target, shortcut_path):
                return True, "symlink"
            # Fall back to .url file
            elif self.create_url_shortcut(target, shortcut_path):
                return True, "url"
            else:
                return False, "none"
        
        elif shortcut_type == "symlink":
            success = self.create_symlink(target, shortcut_path)
            return success, "symlink" if success else "none"
        
        elif shortcut_type == "url":
            success = self.create_url_shortcut(target, shortcut_path)
            return success, "url" if success else "none"
        
        elif shortcut_type == "desktop":
            success = self.create_desktop_shortcut(target, shortcut_path)
            return success, "desktop" if success else "none"
        
        else:
            self.logger.error("unknown_shortcut_type", shortcut_type=shortcut_type)
            return False, "none"
