import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_type_sql(col):
    """将 SQLAlchemy Column 类型转为 SQL DDL 片段"""
    t = col.type
    type_name = type(t).__name__
    if type_name == "VARCHAR" or type_name == "String":
        return f"VARCHAR({t.length or 255})"
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
    if type_name == "DATE" or type_name == "Date":
        return "DATE"
    if type_name == "BOOLEAN" or type_name == "Boolean":
        return "BOOLEAN"
    return type_name.upper()


def auto_sync_tables(engine_obj, base):
    """对比 ORM 模型和数据库实际结构，自动补齐缺失的列"""
    inspector = inspect(engine_obj)
    model_tables = {t.name: t for t in base.metadata.sorted_tables}

    with engine_obj.connect() as conn:
        for table_name, table in model_tables.items():
            if not inspector.has_table(table_name):
                continue

            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue

                col_type = _column_type_sql(col)
                nullable = "" if col.nullable else "NOT NULL"
                default_val = ""
                if col.default and col.default.arg is not None:
                    default_val = f" DEFAULT {col.default.arg}"
                if col.server_default and hasattr(col.server_default, "arg"):
                    default_val = f" DEFAULT {col.server_default.arg}"

                comment = ""
                if col.comment:
                    comment = f" COMMENT '{col.comment}'"

                sql = (
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {col.name} {col_type} {nullable}{default_val}{comment}"
                )
                logger.info(f"[auto-sync] 新增列: {table_name}.{col.name} ({col_type})")
                conn.execute(text(sql))
                conn.commit()
