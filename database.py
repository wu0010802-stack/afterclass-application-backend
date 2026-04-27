
import pg8000.native
import urllib.parse
import queue
import threading
from config import Config

# ---------- Connection pool ----------
# pg8000 connections are not thread-safe, but they are cheap to hand off between
# requests within the same process. With gunicorn sync workers each worker is
# single-threaded, so a small per-process pool removes the per-request TCP +
# auth handshake (typically 10-50ms on managed Postgres).
_POOL_MAX = 5
_pool: "queue.Queue[pg8000.native.Connection]" = queue.Queue(maxsize=_POOL_MAX)
_pool_lock = threading.Lock()


def _create_connection():
    db_url = Config.DATABASE_URL
    if db_url:
        url = urllib.parse.urlparse(db_url)
        return pg8000.native.Connection(
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port or 5432,
            database=url.path[1:],
        )
    return pg8000.native.Connection(
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        database=Config.DB_NAME,
    )


class _PooledConnection:
    """Wraps a pg8000 connection so .close() returns it to the pool.

    If a query fails the connection is marked broken and discarded on close
    (it may be in an aborted transaction). On clean close we issue a ROLLBACK
    so any uncommitted transaction left behind by sloppy callers does not
    leak to the next user.
    """

    __slots__ = ("_conn", "_broken", "_closed")

    def __init__(self, conn):
        self._conn = conn
        self._broken = False
        self._closed = False

    def run(self, *args, **kwargs):
        try:
            return self._conn.run(*args, **kwargs)
        except Exception:
            self._broken = True
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        conn = self._conn
        if self._broken:
            try:
                conn.close()
            except Exception:
                pass
            return
        # Reset any lingering transaction state before returning to the pool.
        try:
            conn.run("ROLLBACK")
        except Exception:
            pass
        try:
            _pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db_connection():
    try:
        conn = _pool.get_nowait()
    except queue.Empty:
        conn = _create_connection()
    return _PooledConnection(conn)


# ---------- Schema initialization ----------

_INDEXES = [
    # Registration lookups by student (query-registration, joins)
    "CREATE INDEX IF NOT EXISTS idx_registrations_student_id ON registrations(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_registrations_class_id ON registrations(class_id)",
    "CREATE INDEX IF NOT EXISTS idx_registrations_created_at ON registrations(created_at DESC)",
    # Registration <-> courses joins + capacity counts
    "CREATE INDEX IF NOT EXISTS idx_reg_courses_registration_id ON registration_courses(registration_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_courses_course_status ON registration_courses(course_id, status)",
    # Registration <-> supplies joins
    "CREATE INDEX IF NOT EXISTS idx_reg_supplies_registration_id ON registration_supplies(registration_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_supplies_supply_id ON registration_supplies(supply_id)",
    # Student lookup by name (+ optional birthday)
    "CREATE INDEX IF NOT EXISTS idx_students_name ON students(name)",
    # Inquiries / changes feeds are sorted by created_at DESC
    "CREATE INDEX IF NOT EXISTS idx_inquiries_created_at ON inquiries(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reg_changes_created_at ON registration_changes(created_at DESC)",
]


def init_db():
    """Initialize database with normalized schema. Idempotent."""
    try:
        conn = get_db_connection()
        try:
            # Students table
            conn.run('''CREATE TABLE IF NOT EXISTS students (
                          id SERIAL PRIMARY KEY,
                          name TEXT NOT NULL,
                          birthday DATE,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')

            # Migration: drop legacy UNIQUE on name
            try:
                conn.run("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_name_key")
            except Exception:
                pass

            # Migration: ensure birthday column exists
            try:
                conn.run("ALTER TABLE students ADD COLUMN IF NOT EXISTS birthday DATE")
            except Exception:
                pass

            # Classes
            conn.run('''CREATE TABLE IF NOT EXISTS classes (
                          id SERIAL PRIMARY KEY,
                          name TEXT NOT NULL UNIQUE
                        )''')

            # Courses
            conn.run('''CREATE TABLE IF NOT EXISTS courses (
                          id SERIAL PRIMARY KEY,
                          name TEXT NOT NULL UNIQUE,
                          price INTEGER NOT NULL,
                          sessions INTEGER,
                          frequency TEXT,
                          description TEXT,
                          capacity INTEGER DEFAULT 30,
                          video_url TEXT,
                          allow_waitlist BOOLEAN DEFAULT TRUE
                        )''')
            for stmt in (
                "ALTER TABLE courses ADD COLUMN IF NOT EXISTS capacity INTEGER DEFAULT 30",
                "ALTER TABLE courses ADD COLUMN IF NOT EXISTS video_url TEXT",
                "ALTER TABLE courses ADD COLUMN IF NOT EXISTS allow_waitlist BOOLEAN DEFAULT TRUE",
            ):
                try:
                    conn.run(stmt)
                except Exception:
                    pass

            # Supplies
            conn.run('''CREATE TABLE IF NOT EXISTS supplies (
                          id SERIAL PRIMARY KEY,
                          name TEXT NOT NULL UNIQUE,
                          price INTEGER NOT NULL
                        )''')

            # Registrations
            conn.run('''CREATE TABLE IF NOT EXISTS registrations (
                          id SERIAL PRIMARY KEY,
                          student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
                          class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
                          class_name TEXT,
                          email TEXT,
                          is_paid BOOLEAN DEFAULT FALSE,
                          remark TEXT DEFAULT '',
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')
            for stmt in (
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL",
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS email TEXT",
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE",
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS remark TEXT DEFAULT ''",
            ):
                try:
                    conn.run(stmt)
                except Exception:
                    pass

            # Registration <-> courses
            conn.run('''CREATE TABLE IF NOT EXISTS registration_courses (
                          id SERIAL PRIMARY KEY,
                          registration_id INTEGER REFERENCES registrations(id) ON DELETE CASCADE,
                          course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
                          status TEXT DEFAULT 'enrolled',
                          price_snapshot INTEGER DEFAULT 0,
                          UNIQUE(registration_id, course_id)
                        )''')
            for stmt in (
                "ALTER TABLE registration_courses ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'enrolled'",
                "ALTER TABLE registration_courses ADD COLUMN IF NOT EXISTS price_snapshot INTEGER DEFAULT 0",
            ):
                try:
                    conn.run(stmt)
                except Exception:
                    pass

            # Registration <-> supplies
            conn.run('''CREATE TABLE IF NOT EXISTS registration_supplies (
                          id SERIAL PRIMARY KEY,
                          registration_id INTEGER REFERENCES registrations(id) ON DELETE CASCADE,
                          supply_id INTEGER REFERENCES supplies(id) ON DELETE CASCADE,
                          price_snapshot INTEGER DEFAULT 0,
                          UNIQUE(registration_id, supply_id)
                        )''')
            try:
                conn.run("ALTER TABLE registration_supplies ADD COLUMN IF NOT EXISTS price_snapshot INTEGER DEFAULT 0")
            except Exception:
                pass

            # Settings
            conn.run('''CREATE TABLE IF NOT EXISTS settings (
                          key TEXT PRIMARY KEY,
                          value TEXT NOT NULL
                        )''')

            # Inquiries
            conn.run('''CREATE TABLE IF NOT EXISTS inquiries (
                          id SERIAL PRIMARY KEY,
                          name TEXT NOT NULL,
                          phone TEXT NOT NULL,
                          question TEXT NOT NULL,
                          is_read BOOLEAN DEFAULT FALSE,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')

            # Registration change log
            conn.run('''CREATE TABLE IF NOT EXISTS registration_changes (
                          id SERIAL PRIMARY KEY,
                          registration_id INTEGER REFERENCES registrations(id) ON DELETE CASCADE,
                          student_name TEXT NOT NULL,
                          change_type TEXT NOT NULL,
                          change_description TEXT NOT NULL,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )''')

            # Seed data + class migration
            insert_initial_data(conn)
            migrate_class_names(conn)

            # Default settings
            for key, value in (
                ('registration_start', '2026-02-02T16:00'),
                ('registration_end', '2026-02-20T23:59'),
            ):
                try:
                    conn.run(
                        "INSERT INTO settings (key, value) VALUES (:key, :value) ON CONFLICT (key) DO NOTHING",
                        key=key, value=value,
                    )
                except Exception:
                    pass

            # Indexes (idempotent)
            for stmt in _INDEXES:
                try:
                    conn.run(stmt)
                except Exception:
                    pass

            print("Connected to PostgreSQL 'afterschool' database and tables ready.")
        finally:
            conn.close()
    except Exception as e:
        print(f"Database Initialization Error: {e}")


def insert_initial_data(conn):
    courses_data = [
        ('幼兒感統 (限小幼班)', 8000, 20, '每週1次，1次1小時', None),
        ('兒童舞蹈 (大中小幼班)', 4400, 20, '每週1次，1次1小時', None),
        ('足球 (中大班)', 5000, 20, '每週1次，1次1小時', None),
        ('足球 (中小班)', 5000, 20, '每週1次，1次1小時', None),
        ('3C3Q積木與桌遊 (大中小)', 5200, 20, '每週1次，1次1小時', None),
        ('幼兒美術 (大中小幼)', 4400, 20, '每週1次，1次1小時', None),
        ('菁英美語 (限大班)', 7000, 40, '每週2次', '教材費另計$1500'),
        ('菁英美語教材費', 1500, None, None, '選修菁英美語者必選'),
    ]
    for course in courses_data:
        try:
            conn.run(
                "INSERT INTO courses (name, price, sessions, frequency, description) VALUES (:name, :price, :sessions, :frequency, :description) ON CONFLICT (name) DO NOTHING",
                name=course[0], price=course[1], sessions=course[2], frequency=course[3], description=course[4],
            )
        except Exception:
            pass

    supplies_data = [
        ('全套舞蹈服裝', 1400),
        ('舞衣', 700),
        ('舞鞋', 250),
        ('舞襪', 150),
        ('舞袋', 300),
    ]
    for supply in supplies_data:
        try:
            conn.run(
                "INSERT INTO supplies (name, price) VALUES (:name, :price) ON CONFLICT (name) DO NOTHING",
                name=supply[0], price=supply[1],
            )
        except Exception:
            pass


def migrate_class_names(conn):
    """Migrate string class names to classes table references."""
    try:
        standard_classes = [
            "天堂鳥 Bird of Paradise", "茉莉 Jasmine", "玫瑰 Rose", "薔薇 Multiflora",
            "百合 Lily", "櫻花 Cherry Blossom", "芙蓉 Hibiscus", "牡丹 Peony",
            "向日葵 Sunflower", "滿天星 Baby's Breath",
        ]
        for cls_name in standard_classes:
            conn.run("INSERT INTO classes (name) VALUES (:name) ON CONFLICT (name) DO NOTHING", name=cls_name)

        existing_names = conn.run("SELECT DISTINCT class_name FROM registrations WHERE class_name IS NOT NULL")
        for row in existing_names:
            name = row[0]
            if name:
                conn.run("INSERT INTO classes (name) VALUES (:name) ON CONFLICT (name) DO NOTHING", name=name)

        conn.run("""
            UPDATE registrations
            SET class_id = (SELECT id FROM classes WHERE classes.name = registrations.class_name)
            WHERE class_id IS NULL AND class_name IS NOT NULL
        """)
    except Exception as e:
        print(f"Migration Warning (Class Names): {e}")
