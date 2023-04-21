import dataclasses
import logging

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

import mysql_shell

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _Relation:
    _relation: ops.Relation
    _interface: data_interfaces.DatabaseProvides

    @property
    def _local_databag(self) -> ops.RelationDataContent:
        return self._relation.data[self._interface.local_app]

    @property
    def _remote_databag(self) -> dict:
        return self._interface.fetch_relation_data()[self.id]

    @property
    def id(self) -> int:
        return self._relation.id

    @property
    def user_created(self) -> bool:
        for key in ["database", "username", "password", "endpoints"]:
            if key not in self._local_databag:
                return False
        return True

    @property
    def database(self) -> str:
        return self._remote_databag["database"]

    @property
    def username(self) -> str:
        return f"relation-{self.id}"

    def _set_databag(self, password: str, endpoint: str) -> None:
        read_write_endpoint = f"{endpoint}:6446"
        read_only_endpoint = f"{endpoint}:6447"
        logger.debug(
            f"Setting databag {self.id=} {self.database=}, {self.username=}, {read_write_endpoint=}, {read_only_endpoint=}"
        )
        self._interface.set_database(self.id, self.database)
        self._interface.set_credentials(self.id, self.username, password)
        self._interface.set_endpoints(self.id, read_write_endpoint)
        self._interface.set_read_only_endpoints(self.id, read_only_endpoint)
        logger.debug(
            f"Set databag {self.id=} {self.database=}, {self.username=}, {read_write_endpoint=}, {read_only_endpoint=}"
        )

    def _delete_databag(self) -> None:
        logger.debug(f"Deleting databag {self.id=}")
        self._local_databag.clear()
        logger.debug(f"Deleted databag {self.id=}")

    def create_database_and_user(self, endpoint: str, shell: mysql_shell.Shell) -> None:
        password = shell.create_application_database_and_user(self.username, self.database)
        self._set_databag(password, endpoint)

    def delete_user(self, shell: mysql_shell.Shell) -> None:
        self._delete_databag()
        shell.delete_user(self.username)


@dataclasses.dataclass
class RelationEndpoint:
    interface: data_interfaces.DatabaseProvides

    @property
    def _relations(self) -> list[_Relation]:
        return [_Relation(relation, self.interface) for relation in self.interface.relations]

    def _requested_users(self, event, event_is_database_requires_broken: bool) -> list[_Relation]:
        if event_is_database_requires_broken:
            # Cluster connection is being removed; delete all users
            return []
        requested_users = []
        for relation in self._relations:
            if isinstance(event, ops.RelationBrokenEvent) and event.relation.id == relation.id:
                # Relation is being removed; delete user
                continue
            requested_users.append(relation)
        return requested_users

    @property
    def _created_users(self) -> list[_Relation]:
        return [relation for relation in self._relations if relation.user_created]

    @property
    def missing_relation(self) -> bool:
        return len(self._relations) == 0

    def reconcile_users(
        self,
        event,
        event_is_database_requires_broken: bool,
        endpoint: str,
        shell: mysql_shell.Shell,
    ) -> None:
        requested_users = self._requested_users(event, event_is_database_requires_broken)
        created_users = self._created_users
        for relation in requested_users:
            if relation not in created_users:
                relation.create_database_and_user(endpoint, shell)
        for relation in created_users:
            if relation not in requested_users:
                relation.delete_user(shell)
