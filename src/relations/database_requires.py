import dataclasses
import logging
import secrets
import string
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import mysql.connector
import ops

from constants import PASSWORD_LENGTH

logger = logging.getLogger(__name__)


class _Relation:
    def __init__(self, interface: data_interfaces.DatabaseRequires) -> None:
        self._interface = interface

    @property
    def _id(self) -> int:
        relations = self._interface.relations
        assert len(relations) == 1
        return relations[0].id

    @property
    def _remote_databag(self) -> dict:
        return self._interface.fetch_relation_data()[self._id]

    @property
    def _endpoint(self) -> str:
        endpoints = self._remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        return endpoints[0]

    @property
    def host(self) -> str:
        return self._endpoint.split(":")[0]

    @property
    def port(self) -> str:
        return self._endpoint.split(":")[1]

    @property
    def username(self) -> str:
        return self._remote_databag["username"]

    @property
    def password(self) -> str:
        return self._remote_databag["password"]

    def is_breaking(self, event):
        return isinstance(event, ops.charm.RelationBrokenEvent) and event.relation.id == self._id

    # TODO: move methods below to mysqlsh Python file
    def create_application_database_and_user(self, username: str, database: str) -> str:
        logger.debug(f"Creating {database=} and {username=}")
        password = self._generate_password()
        self._execute_sql_statements(
            [
                f"CREATE DATABASE IF NOT EXISTS `{database}`",
                f"CREATE USER `{username}` IDENTIFIED BY '{password}'",
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO `{username}`",
            ]
        )
        logger.debug(f"Created {database=} and {username=}")
        return password

    def delete_application_user(self, username: str) -> None:
        logger.debug(f"Deleting {username=}")
        self._execute_sql_statements([f"DROP USER `{username}`"])
        logger.debug(f"Deleted {username=}")

    def _execute_sql_statements(self, statements: list[str]) -> None:
        # TODO: catch exceptions?
        with mysql.connector.connect(
            username=self.username, password=self.password, host=self.host, port=self.port
        ) as connection, connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    @staticmethod
    def _generate_password() -> str:
        choices = string.ascii_letters + string.digits
        return "".join([secrets.choice(choices) for _ in range(PASSWORD_LENGTH)])


@dataclasses.dataclass
class RelationEndpoint:
    def __init__(self, interface: data_interfaces.DatabaseRequires) -> None:
        self.interface = interface

    @property
    def relation(self) -> typing.Optional[_Relation]:
        if not self.interface.relations:
            return
        return _Relation(self.interface)
