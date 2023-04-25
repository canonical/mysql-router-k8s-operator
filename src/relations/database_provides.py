# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation(s) to one or more application charms"""

import dataclasses
import logging

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

import mysql_shell

logger = logging.getLogger(__name__)


@dataclasses.dataclass(kw_only=True)
class _Relation:
    """Relation to one application charm"""

    _relation: ops.Relation
    _interface: data_interfaces.DatabaseProvides

    @property
    def id(self) -> int:
        return self._relation.id

    @property
    def _local_databag(self) -> ops.RelationDataContent:
        """MySQL Router charm databag"""
        return self._relation.data[self._interface.local_app]

    @property
    def _remote_databag(self) -> dict:
        """MySQL charm databag"""
        return self._interface.fetch_relation_data()[self.id]

    @property
    def user_created(self) -> bool:
        """Whether database user has been shared with application charm"""
        for key in ["database", "username", "password", "endpoints"]:
            if key not in self._local_databag:
                return False
        return True

    @property
    def database(self) -> str:
        """Requested database name"""
        return self._remote_databag["database"]

    @property
    def username(self) -> str:
        """Database username"""
        return f"relation-{self.id}"

    def _set_databag(self, *, password: str, router_endpoint: str) -> None:
        """Share connection information with application charm."""
        read_write_endpoint = f"{router_endpoint}:6446"
        read_only_endpoint = f"{router_endpoint}:6447"
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
        """Remove connection information from databag."""
        logger.debug(f"Deleting databag {self.id=}")
        self._local_databag.clear()
        logger.debug(f"Deleted databag {self.id=}")

    def create_database_and_user(self, *, router_endpoint: str, shell: mysql_shell.Shell) -> None:
        """Create database & user and update databag."""
        password = shell.create_application_database_and_user(
            username=self.username, database=self.database
        )
        self._set_databag(password=password, router_endpoint=router_endpoint)

    def delete_user(self, *, shell: mysql_shell.Shell) -> None:
        """Delete user and update databag."""
        self._delete_databag()
        shell.delete_user(self.username)


@dataclasses.dataclass
class RelationEndpoint:
    """Relation endpoint for application charm(s)"""

    interface: data_interfaces.DatabaseProvides

    NAME = "database"

    @property
    def _relations(self) -> list[_Relation]:
        return [
            _Relation(_relation=relation, _interface=self.interface)
            for relation in self.interface.relations
        ]

    def _requested_users(
        self, *, event, event_is_database_requires_broken: bool
    ) -> list[_Relation]:
        """Related application charms that have requested a database & user"""
        if event_is_database_requires_broken:
            # MySQL cluster connection is being removed; delete all users
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
        """Users that have been created and shared with an application charm"""
        return [relation for relation in self._relations if relation.user_created]

    @property
    def missing_relation(self) -> bool:
        """Whether zero relations to application charms exist"""
        return len(self._relations) == 0

    def reconcile_users(
        self,
        *,
        event,
        event_is_database_requires_broken: bool,
        router_endpoint: str,
        shell: mysql_shell.Shell,
    ) -> None:
        """Create requested users and delete inactive users."""
        logger.debug(
            f"Reconciling users {event=}, {event_is_database_requires_broken=}, {router_endpoint=}"
        )
        requested_users = self._requested_users(
            event=event, event_is_database_requires_broken=event_is_database_requires_broken
        )
        created_users = self._created_users
        logger.debug(f"State of reconcile users {requested_users=}, {created_users=}")
        for relation in requested_users:
            if relation not in created_users:
                relation.create_database_and_user(router_endpoint=router_endpoint, shell=shell)
        for relation in created_users:
            if relation not in requested_users:
                relation.delete_user(shell=shell)
        logger.debug(
            f"Reconciled users {event=}, {event_is_database_requires_broken=}, {router_endpoint=}"
        )
