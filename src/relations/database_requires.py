import dataclasses

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import mysql.connector
import ops


@dataclasses.dataclass
class Relation:
    interface: data_interfaces.DatabaseRequires

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

    @property
    def _id(self) -> int:
        relations = self.interface.relations
        assert len(relations) == 1
        return relations[0].id

    @property
    def _remote_databag(self) -> dict:
        return self.interface.fetch_relation_data()[self._id]

    @property
    def _endpoint(self) -> str:
        endpoints = self._remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        return endpoints[0]

    @property
    def _active(self) -> bool:
        """Whether relation is currently active"""
        if not self.interface.relations:
            return False
        return self.interface.is_resource_created()

    def is_desired_active(self, event) -> bool:
        """Whether relation should be active once the event is handled"""
        if isinstance(event, ops.charm.RelationBrokenEvent) and event.relation.id == self._id:
            # Relation is being removed; it is no longer active
            return False
        return self._active

    def create_application_database_and_user(
        self, username: str, password: str, database: str
    ) -> None:
        self._execute_sql_statements(
            [
                f"CREATE DATABASE IF NOT EXISTS `{database}`",
                f"CREATE USER `{username}` IDENTIFIED BY '{password}'",
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO `{username}`",
            ]
        )

    def delete_application_user(self, username: str) -> None:
        self._execute_sql_statements([f"DROP USER IF EXISTS `{username}`"])

    def _execute_sql_statements(self, statements: list[str]) -> None:
        # TODO: catch exceptions?
        with mysql.connector.connect(
            username=self.username, password=self.password, host=self.host, port=self.port
        ) as connection, connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
