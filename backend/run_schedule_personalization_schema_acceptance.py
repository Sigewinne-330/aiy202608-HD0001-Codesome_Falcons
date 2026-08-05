"""Run the additive personalization migration twice in an isolated MySQL DB."""

from pathlib import Path
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

from check_schedule_personalization_readiness import inspect_personalization_schema
TEST_DATABASE = "ibuddy_personalization_acceptance"


def _url(database=None):
    query = {"charset": "utf8mb4"}
    test_socket = os.getenv("SCHEDULING_MYSQL_TEST_SOCKET", "/tmp/mysql.sock")
    if test_socket:
        query["unix_socket"] = test_socket
    return URL.create(
        "mysql+pymysql",
        username=os.getenv("SCHEDULING_MYSQL_TEST_USER", "root"),
        password=os.getenv("SCHEDULING_MYSQL_TEST_PASSWORD") or None,
        host=os.getenv("SCHEDULING_MYSQL_TEST_HOST", "127.0.0.1"),
        port=int(os.getenv("SCHEDULING_MYSQL_TEST_PORT", "3306")),
        database=database,
        query=query,
    )


def _migration_statements():
    migration_path = Path(__file__).with_name("migrate_schedule_personalization.sql")
    lines = [
        line for line in migration_path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ]
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]


def main() -> int:
    if not TEST_DATABASE.startswith("ibuddy_personalization_acceptance"):
        raise RuntimeError("refusing to use an unexpected acceptance database")

    server_engine = create_engine(_url(), pool_pre_ping=True)
    test_engine = None
    database_created = False
    try:
        with server_engine.begin() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`"))
            connection.execute(text(
                f"CREATE DATABASE `{TEST_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            ))
        database_created = True

        test_engine = create_engine(_url(TEST_DATABASE), pool_pre_ping=True)
        with test_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE `user` ("
                "`id` INT NOT NULL AUTO_INCREMENT, "
                "`username` VARCHAR(50) NOT NULL, "
                "PRIMARY KEY (`id`), UNIQUE KEY `uq_user_username` (`username`)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            ))
            connection.execute(text(
                "CREATE TABLE `schedule_audit_events` ("
                "`id` INT NOT NULL AUTO_INCREMENT, `user_id` INT NOT NULL, "
                "PRIMARY KEY (`id`)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            ))

        statements = _migration_statements()
        for _ in range(2):
            with test_engine.begin() as connection:
                for statement in statements:
                    connection.exec_driver_sql(statement)

        result = inspect_personalization_schema(test_engine)
        result["migration_passes"] = 2
        print(result)
        return 0 if result["ok"] else 1
    except OperationalError as exc:
        error_code = getattr(getattr(exc, "orig", None), "args", ["unknown"])[0]
        print({"ok": False, "environment_error": "mysql_unavailable", "database_error_code": error_code})
        return 2
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if database_created:
            with server_engine.begin() as connection:
                connection.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`"))
        server_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
