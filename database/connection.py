import sqlite3
import logging
import threading
from pathlib import Path
from contextlib import contextmanager

try:
    import sqlite_vec
    HAS_VEC = True
except ImportError:
    HAS_VEC = False

logger = logging.getLogger(__name__)

class DatabaseConnectionPool:
    """Manages SQLite connections with WAL mode enabled and connection pooling."""
    
    def __init__(self, db_path: str, max_read_connections: int = 5):
        self.db_path = Path(db_path)
        self.max_read_connections = max_read_connections
        
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Locks for thread safety
        self._write_lock = threading.Lock()
        self._read_pool_lock = threading.Lock()
        
        # Pool storage
        self._read_connections = []
        self._write_conn = None
        
        self._init_db()
        
    def _init_db(self):
        """Initialize database settings."""
        with self.get_write_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA cache_size = -64000;")
            
    def _load_extensions(self, conn: sqlite3.Connection):
        """Load required extensions into connection."""
        if HAS_VEC:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            
    @contextmanager
    def get_read_connection(self):
        """Get a read-only connection from the pool, or create one."""
        conn = None
        with self._read_pool_lock:
            if self._read_connections:
                conn = self._read_connections.pop()
                
        if conn is None:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._load_extensions(conn)
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA cache_size = -64000;")
            
        try:
            yield conn
        finally:
            with self._read_pool_lock:
                if len(self._read_connections) < self.max_read_connections:
                    self._read_connections.append(conn)
                else:
                    conn.close()
            
    @contextmanager
    def get_write_connection(self):
        """Get the single serialized write connection."""
        with self._write_lock:
            if self._write_conn is None:
                self._write_conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._write_conn.row_factory = sqlite3.Row
                self._load_extensions(self._write_conn)
                
            try:
                yield self._write_conn
                self._write_conn.commit()
            except Exception as e:
                self._write_conn.rollback()
                raise e
            
    async def start(self):
        logger.info(f"Database connection pool started. DB path: {self.db_path}")
        if HAS_VEC:
            logger.info("sqlite-vec extension loaded successfully.")
        
    async def stop(self):
        logger.info("Database connection pool stopped.")
        with self._read_pool_lock:
            for conn in self._read_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._read_connections.clear()
            
        with self._write_lock:
            if self._write_conn:
                try:
                    self._write_conn.close()
                except Exception:
                    pass
                self._write_conn = None

