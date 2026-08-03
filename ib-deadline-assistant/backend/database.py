import logging
import os
import tempfile

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings


logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _try_acquire_file_lock(file_obj):
    """Acquire a non-blocking, cross-platform lock on one byte."""
    if os.name == "nt":
        file_obj.seek(0, os.SEEK_END)
        if file_obj.tell() == 0:
            file_obj.write(b"\0")
            file_obj.flush()
        file_obj.seek(0)
        try:
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
    else:
        try:
            fcntl.flock(file_obj, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_type_sql(col):
    """Convert a SQLAlchemy column type to a SQL DDL fragment."""
    column_type = col.type
    type_name = type(column_type).__name__
    if type_name == "Enum":
        enum_values = [
            f"'{item.value}'" if hasattr(item, "value") else f"'{item}'"
            for item in column_type.enums
        ]
        return f"ENUM({','.join(enum_values)})"
    if type_name in ("VARCHAR", "String"):
        return f"VARCHAR({column_type.length or 255})"
    if type_name in ("INTEGER", "Integer"):
        return "INT"
    if type_name in ("TEXT", "Text"):
        return "TEXT"
    if type_name in ("DATETIME", "DateTime"):
        return "DATETIME"
    if type_name == "TIMESTAMP":
        return "TIMESTAMP"
    if type_name == "JSON":
        return "JSON"
    if type_name == "FLOAT":
        return "FLOAT"
    if type_name in ("DATE", "Date"):
        return "DATE"
    if type_name in ("BOOLEAN", "Boolean"):
        return "BOOLEAN"
    return type_name.upper()


def auto_sync_tables(engine_obj, base):
    """Add missing model columns once, guarded by a cross-platform file lock."""
    lock_file = os.path.join(tempfile.gettempdir(), "ibuddy_auto_sync.lock")
    with open(lock_file, "a+b") as file_obj:
        if not _try_acquire_file_lock(file_obj):
            logger.info("[auto-sync] another worker owns the schema lock; skipping")
            return

        inspector = inspect(engine_obj)
        model_tables = {table.name: table for table in base.metadata.sorted_tables}

        with engine_obj.connect() as conn:
            for table_name, table in model_tables.items():
                if not inspector.has_table(table_name):
                    continue

                existing_cols = {column["name"] for column in inspector.get_columns(table_name)}
                for column in table.columns:
                    if column.name in existing_cols:
                        continue

                    column_type = _column_type_sql(column)
                    nullable = "" if column.nullable else "NOT NULL"
                    default_value = ""
                    if column.default and column.default.arg is not None:
                        arg = column.default.arg
                        if hasattr(arg, "value"):
                            default_value = f" DEFAULT '{arg.value}'"
                        elif isinstance(arg, str):
                            default_value = f" DEFAULT '{arg}'"
                        else:
                            default_value = f" DEFAULT {arg}"
                    if column.server_default and hasattr(column.server_default, "arg"):
                        default_value = f" DEFAULT {column.server_default.arg}"

                    comment = ""
                    if column.comment:
                        comment = f" COMMENT '{column.comment}'"

                    sql = (
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN {column.name} {column_type} "
                        f"{nullable}{default_value}{comment}"
                    )
                    logger.info("[auto-sync] adding column %s.%s (%s)", table_name, column.name, column_type)
                    conn.execute(text(sql))
                    conn.commit()
