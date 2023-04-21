import dataclasses
import logging
import secrets
import string

import ops

from constants import PASSWORD_LENGTH

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Shell:
    _container: ops.Container
    _username: str
    _password: str
    _host: str
    _port: str

    def _run_commands(self, commands: list[str]) -> None:
        commands.insert(
            0, f"shell.connect('{self._username}:{self._password}@{self._host}:{self._port}"
        )
        # TODO
        # TODO: catch exceptions

    def _run_sql(self, sql_statements: list[str]) -> None:
        commands = []
        for statement in sql_statements:
            # Escape double quote (") characters in statement
            statement = statement.replace('"', r"\"")
            commands.append('session.run_sql("' + statement + '")')
        self._run_commands(commands)

    @staticmethod
    def _generate_password() -> str:
        choices = string.ascii_letters + string.digits
        return "".join([secrets.choice(choices) for _ in range(PASSWORD_LENGTH)])

    def create_application_database_and_user(self, username: str, database: str) -> str:
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

    def delete_user(self, username: str) -> None:
        logger.debug(f"Deleting {username=}")
        self._run_sql([f"DROP USER `{username}`"])
        logger.debug(f"Deleted {username=}")
