import os
import shutil
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class DatabaseBackupManager:
    """
    Safely backs up SQLite databases using the sqlite3 online backup API.
    Implements a Grandfather-Father-Son (GFS) rotation scheme:
    - Daily backups: keep last 7.
    - Weekly backups: keep last 4.
    - Monthly backups: keep last 12.
    """

    def __init__(self, live_db_path: str, backups_root: Optional[str] = None):
        self.live_db_path = Path(live_db_path).resolve()
        
        if backups_root:
            self.backups_root = Path(backups_root).resolve()
        else:
            self.backups_root = self.live_db_path.parent / "backups"
            
        self.daily_dir = self.backups_root / "daily"
        self.weekly_dir = self.backups_root / "weekly"
        self.monthly_dir = self.backups_root / "monthly"
        
        for d in [self.daily_dir, self.weekly_dir, self.monthly_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _safe_sqlite_backup(self, src_path: Path, dst_path: Path) -> None:
        """Uses SQLite's backup API to copy pages safely without blocking database operations."""
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        src_conn = sqlite3.connect(src_path)
        dst_conn = sqlite3.connect(dst_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

    def create_backup(self) -> str:
        """
        Creates a new database backup and performs GFS rotation.
        Returns the path of the daily backup created.
        """
        if not self.live_db_path.exists():
            raise FileNotFoundError(f"Live database not found at: {self.live_db_path}")

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        week_str = now.strftime("%Y_W_%W")
        month_str = now.strftime("%Y_%m")

        # 1. Create Daily Backup
        daily_path = self.daily_dir / f"backup_daily_{date_str}.db"
        logger.info(f"Creating daily database backup to: {daily_path}")
        self._safe_sqlite_backup(self.live_db_path, daily_path)

        # 2. Check and Create Weekly Backup (once per week)
        weekly_path = self.weekly_dir / f"backup_weekly_{week_str}.db"
        if not weekly_path.exists():
            logger.info(f"Creating weekly database backup to: {weekly_path}")
            self._safe_sqlite_backup(self.live_db_path, weekly_path)

        # 3. Check and Create Monthly Backup (once per month)
        monthly_path = self.monthly_dir / f"backup_monthly_{month_str}.db"
        if not monthly_path.exists():
            logger.info(f"Creating monthly database backup to: {monthly_path}")
            self._safe_sqlite_backup(self.live_db_path, monthly_path)

        # 4. Perform GFS Rotation Cleanup
        self._rotate_bucket(self.daily_dir, "backup_daily_*.db", 7)
        self._rotate_bucket(self.weekly_dir, "backup_weekly_*.db", 4)
        self._rotate_bucket(self.monthly_dir, "backup_monthly_*.db", 12)

        return daily_path.as_posix()

    def _rotate_bucket(self, directory: Path, pattern: str, keep_count: int) -> None:
        """Lists files in the directory matching the pattern and deletes the oldest ones exceeding keep_count."""
        files = sorted(list(directory.glob(pattern)))
        if len(files) > keep_count:
            # oldest files first (sorted alphabetically works because of YYYY-MM-DD names)
            to_delete = files[:-keep_count]
            for f in to_delete:
                try:
                    f.unlink()
                    logger.info(f"Deleted rotated old backup: {f.name}")
                except Exception as e:
                    logger.error(f"Failed to delete rotated old backup {f.name}: {e}")

    def list_backups(self) -> List[Dict[str, Any]]:
        """Lists all daily, weekly, and monthly database backups."""
        backups = []
        for bucket, directory in [("daily", self.daily_dir), ("weekly", self.weekly_dir), ("monthly", self.monthly_dir)]:
            for item in directory.glob("*.db"):
                stat = item.stat()
                backups.append({
                    "name": item.name,
                    "path": item.resolve().as_posix(),
                    "bucket": bucket,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size_bytes": stat.st_size,
                })
        return sorted(backups, key=lambda x: x["created_at"], reverse=True)

    def restore_backup(self, backup_path_str: str) -> None:
        """Safely restores the live database from a given backup path."""
        backup_path = Path(backup_path_str).resolve()
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found at: {backup_path_str}")

        logger.info(f"Restoring live database from backup: {backup_path}")
        self._safe_sqlite_backup(backup_path, self.live_db_path)
