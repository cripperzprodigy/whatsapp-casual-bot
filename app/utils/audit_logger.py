"""Audit logging for admin actions and security events.

Logs all administrative operations (memory management, user management, toggles, etc.)
to a persistent audit trail for accountability and debugging.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _ensure_audit_dir() -> Path:
    """Create logs directory if it doesn't exist."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True, parents=True)
    return log_dir


async def log_admin_action(
    admin_id: str,
    action: str,
    target: str,
    result: str,
    details: Optional[str] = None
) -> bool:
    """Log an administrative action to the audit trail.
    
    Args:
        admin_id: JID of the admin performing the action
        action: Action type (e.g., "memory_clear_user", "resolve_global", "toggle_search")
        target: Target of the action (e.g., user JID, "GLOBAL", group ID)
        result: Result status ("success", "failure", "denied", etc.)
        details: Optional additional details (error message, etc.)
    
    Returns:
        True if logging succeeded, False otherwise
    """
    try:
        log_dir = _ensure_audit_dir()
        audit_file = log_dir / "admin_audit.log"
        
        timestamp = datetime.utcnow().isoformat()
        log_entry = f"[{timestamp}] admin={admin_id} action={action} target={target} result={result}"
        if details:
            log_entry += f" details={details}"
        log_entry += "\n"
        
        # Thread-safe append to file
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
        
        logger.info(f"Audit logged: {action} by {admin_id} on {target}: {result}")
        return True
    except Exception as e:
        logger.error(f"Failed to log audit action: {e}")
        return False


async def get_audit_log(limit: int = 100) -> list[str]:
    """Retrieve recent audit log entries (owner-only debug utility).
    
    Args:
        limit: Maximum number of lines to retrieve
    
    Returns:
        List of audit log lines, most recent first
    """
    try:
        audit_file = Path("logs") / "admin_audit.log"
        if not audit_file.exists():
            return ["(No audit log found)"]
        
        with open(audit_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Return most recent lines
        return lines[-limit:][::-1]
    except Exception as e:
        logger.error(f"Failed to read audit log: {e}")
        return [f"Error reading audit log: {e}"]
