# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL Shell in Python execution mode

https://dev.mysql.com/doc/mysql-shell/8.0/en/
"""

import dataclasses
import logging
import secrets
import string

import ops

_PASSWORD_LENGTH = 24
logger = logging.getLogger(__name__)


@dataclasses.dataclass(kw_only=True)
class Shell:
    """MySQL Shell connected to MySQL cluster"""

    _container: ops.Container
    _username: str
    _password: str
    _host: str
    _port: str

    _TEMPORARY_SCRIPT_FILE = "/tmp/script.py"

    def _run_commands(self, commands: list[str]) -> None:
        """Connect to MySQL cluster and run commands."""
        commands.insert(
            0, f"shell.connect('{self._username}:{self._password}@{self._host}:{self._port}')"
        )
        self._container.push(self._TEMPORARY_SCRIPT_FILE, "\n".join(commands))
        try:
            process = self._container.exec(
                ["mysqlsh", "--no-wizard", "--python", "--file", self._TEMPORARY_SCRIPT_FILE]
            )
            process.wait_output()
        except ops.pebble.ExecError as e:
            logger.exception(f"Failed to run {commands=}\nstderr:\n{e.stderr}\n")
            raise
        finally:
            self._container.remove_path(self._TEMPORARY_SCRIPT_FILE)

    def _run_sql(self, sql_statements: list[str]) -> None:
        """Connect to MySQL cluster and execute SQL."""
        commands = []
        for statement in sql_statements:
            # Escape double quote (") characters in statement
            statement = statement.replace('"', r"\"")
            commands.append('session.run_sql("' + statement + '")')
        self._run_commands(commands)

    @staticmethod
    def _generate_password() -> str:
        choices = string.ascii_letters + string.digits
        return "".join([secrets.choice(choices) for _ in range(_PASSWORD_LENGTH)])

    def create_application_database_and_user(self, *, username: str, database: str) -> str:
        """Create database and user for related database_provides application."""
        logger.debug(f"Creating {database=} and {username=}")
        password = self._generate_password()
        self._run_sql(
            [
                f"CREATE DATABASE IF NOT EXISTS `{database}`",
                f"CREATE USER `{username}` IDENTIFIED BY '{password}'",
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO `{username}`",
            ]
        )
        logger.debug(f"Created {database=} and {username=}")
        return password

    def create_mysql_router_user(self, username: str) -> str:
        """Create user to run MySQL Router service."""
        logger.debug(f"Creating router {username=}")
        password = self._generate_password()
        self._run_commands(
            [
                "cluster = dba.get_cluster()",
                "cluster.setup_router_account('"
                + username
                + "', {'password': '"
                + password
                + "'})",
            ]
        )
        logger.debug(f"Created router {username=}")
        return password

    def change_mysql_router_user_password(self, username: str) -> str:
        """Change MySQL Router service user password."""
        logger.debug(f"Changing router password {username=}")
        password = self._generate_password()
        self._run_sql([f"ALTER USER `{username}` IDENTIFIED BY '{password}'"])
        logger.debug(f"Changed router password {username=}")
        return password

    def delete_user(self, username: str) -> None:
        """Delete user."""
        logger.debug(f"Deleting {username=}")
        self._run_sql([f"DROP USER `{username}`"])
        logger.debug(f"Deleted {username=}")
