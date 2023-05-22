# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation(s) to one or more application charms"""

import dataclasses
import logging
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

import mysql_shell

if typing.TYPE_CHECKING:
    import charm

logger = logging.getLogger(__name__)


@dataclasses.dataclass(kw_only=True)
class _Relation:
    """Relation to one application charm"""

    _relation: ops.Relation
    _interface: data_interfaces.DatabaseProvides
    _model_name: str

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
    def _database(self) -> str:
        """Requested database name"""
        return self._remote_databag["database"]

    @property
    def status(self) -> typing.Optional[ops.StatusBase]:
        """Non-active status"""
        if self._remote_databag.get("extra-user-roles"):
            return ops.BlockedStatus(
                f"{self._relation.app.name} app requested unsupported extra user role"
            )

    def _get_username(self, database_requires_username: str) -> str:
        """Database username"""
        # Prefix username with username from database requires relation.
        # This ensures a unique username if MySQL Router is deployed in a different Juju model
        # from MySQL.
        # (Relation IDs are only unique within a Juju model.)
        return f"{database_requires_username}-{self.id}"

    def _set_databag(self, *, username: str, password: str, router_endpoint: str) -> None:
        """Share connection information with application charm."""
        read_write_endpoint = f"{router_endpoint}:6446"
        read_only_endpoint = f"{router_endpoint}:6447"
        logger.debug(
            f"Setting databag {self.id=} {self._database=}, {username=}, {read_write_endpoint=}, {read_only_endpoint=}"
        )
        self._interface.set_database(self.id, self._database)
        self._interface.set_credentials(self.id, username, password)
        self._interface.set_endpoints(self.id, read_write_endpoint)
        self._interface.set_read_only_endpoints(self.id, read_only_endpoint)
        logger.debug(
            f"Set databag {self.id=} {self._database=}, {username=}, {read_write_endpoint=}, {read_only_endpoint=}"
        )

    def _delete_databag(self) -> None:
        """Remove connection information from databag."""
        logger.debug(f"Deleting databag {self.id=}")
        self._local_databag.clear()
        logger.debug(f"Deleted databag {self.id=}")

    def create_database_and_user(self, *, router_endpoint: str, shell: mysql_shell.Shell) -> None:
        """Create database & user and update databag."""
        username = self._get_username(shell.username)
        password = shell.create_application_database_and_user(
            username=username, database=self._database
        )
        self._set_databag(username=username, password=password, router_endpoint=router_endpoint)

    def delete_user(self, *, shell: mysql_shell.Shell) -> None:
        """Delete user and update databag."""
        self._delete_databag()
        shell.delete_user(self._get_username(shell.username))

    def is_breaking(self, event):
        """Whether relation will be broken after the current event is handled"""
        return isinstance(event, ops.RelationBrokenEvent) and event.relation.id == self.id


class RelationEndpoint:
    """Relation endpoint for application charm(s)"""

    NAME = "database"

    def __init__(self, charm_: "charm.MySQLRouterOperatorCharm") -> None:
        self._interface = data_interfaces.DatabaseProvides(charm_, relation_name=self.NAME)
        self._model_name = charm_.model.name
        charm_.framework.observe(
            self._interface.on.database_requested,
            charm_.reconcile_database_relations,
        )
        charm_.framework.observe(
            charm_.on[self.NAME].relation_broken,
            charm_.reconcile_database_relations,
        )

    @property
    def _relations(self) -> list[_Relation]:
        return [
            _Relation(_relation=relation, _interface=self._interface, _model_name=self._model_name)
            for relation in self._interface.relations
        ]

    def _requested_users(self, *, event) -> list[_Relation]:
        """Related application charms that have requested a database & user"""
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

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        active_relations = [
            relation for relation in self._relations if not relation.is_breaking(event)
        ]
        if not active_relations:
            return ops.BlockedStatus(f"Missing relation: {self.NAME}")
        for relation in active_relations:
            if status := relation.status:
                return status

    def reconcile_users(
        self,
        *,
        event,
        router_endpoint: str,
        shell: mysql_shell.Shell,
    ) -> None:
        """Create requested users and delete inactive users.

        When the relation to the MySQL charm is broken, the MySQL charm will delete all users
        created by this charm. Therefore, this charm does not need to delete users when that
        relation is broken.
        """
        logger.debug(f"Reconciling users {event=}, {router_endpoint=}")
        requested_users = self._requested_users(event=event)
        created_users = self._created_users
        logger.debug(f"State of reconcile users {requested_users=}, {created_users=}")
        for relation in requested_users:
            if relation not in created_users:
                relation.create_database_and_user(router_endpoint=router_endpoint, shell=shell)
        for relation in created_users:
            if relation not in requested_users:
                relation.delete_user(shell=shell)
        logger.debug(f"Reconciled users {event=}, {router_endpoint=}")
