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


class StatusException(Exception):
    """Exception with ops status"""

    def __init__(self, status: ops.StatusBase) -> None:
        super().__init__(status.message)
        self.status = status


class _IncompleteDatabag(StatusException):
    """Databag is missing required key"""

    def __init__(self, *, app_name: str, endpoint_name: str) -> None:
        super().__init__(
            ops.WaitingStatus(f"Waiting for {app_name} app on {endpoint_name} endpoint")
        )


class _Databag(dict):
    def __init__(
        self,
        interface: data_interfaces.DatabaseRequires | data_interfaces.DatabaseProvides,
        relation: ops.Relation,
    ) -> None:
        super().__init__(interface.fetch_relation_data()[relation.id])
        self._app_name = relation.app.name
        self._endpoint_name = relation.name

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            logger.debug(
                f"Required {key=} missing from databag for {self._app_name=} on {self._endpoint_name=}"
            )
            raise _IncompleteDatabag(app_name=self._app_name, endpoint_name=self._endpoint_name)


class _RelationBreaking(Exception):
    """Relation will be broken after the current event is handled"""


class _UnsupportedExtraUserRole(StatusException):
    """Application charm requested unsupported extra user role"""

    def __init__(self, *, app_name: str, endpoint_name: str) -> None:
        message = (
            f"{app_name} app requested unsupported extra user role on {endpoint_name} endpoint"
        )
        logger.warning(message)
        super().__init__(ops.BlockedStatus(message))


class _Relation:
    """Relation to one application charm"""

    def __init__(self, *, relation: ops.Relation) -> None:
        self._id = relation.id

    def __eq__(self, other) -> bool:
        if not isinstance(other, _Relation):
            return False
        return self._id == other._id

    def _get_username(self, database_requires_username: str) -> str:
        """Database username"""
        # Prefix username with username from database requires relation.
        # This ensures a unique username if MySQL Router is deployed in a different Juju model
        # from MySQL.
        # (Relation IDs are only unique within a Juju model.)
        return f"{database_requires_username}-{self._id}"


class _RequestedUser(_Relation):
    """Related application charm that has requested a database & user"""

    def __init__(
        self, *, relation: ops.Relation, interface: data_interfaces.DatabaseProvides, event
    ) -> None:
        super().__init__(relation=relation)
        self._interface = interface
        if isinstance(event, ops.RelationBrokenEvent) and event.relation.id == self._id:
            raise _RelationBreaking
        # Application charm databag
        remote_databag = _Databag(interface=interface, relation=relation)
        self._database: str = remote_databag["database"]
        if remote_databag.get("extra-user-roles"):
            raise _UnsupportedExtraUserRole(
                app_name=relation.app.name, endpoint_name=relation.name
            )

    def _set_databag(self, *, username: str, password: str, router_endpoint: str) -> None:
        """Share connection information with application charm."""
        read_write_endpoint = f"{router_endpoint}:6446"
        read_only_endpoint = f"{router_endpoint}:6447"
        logger.debug(
            f"Setting databag {self._id=} {self._database=}, {username=}, {read_write_endpoint=}, {read_only_endpoint=}"
        )
        self._interface.set_database(self._id, self._database)
        self._interface.set_credentials(self._id, username, password)
        self._interface.set_endpoints(self._id, read_write_endpoint)
        self._interface.set_read_only_endpoints(self._id, read_only_endpoint)
        logger.debug(
            f"Set databag {self._id=} {self._database=}, {username=}, {read_write_endpoint=}, {read_only_endpoint=}"
        )

    def create_database_and_user(self, *, router_endpoint: str, shell: mysql_shell.Shell) -> None:
        """Create database & user and update databag."""
        username = self._get_username(shell.username)
        password = shell.create_application_database_and_user(
            username=username, database=self._database
        )
        self._set_databag(username=username, password=password, router_endpoint=router_endpoint)


class _UserNotCreated(Exception):
    """Database & user has not been provided to related application charm"""


class _CreatedUser(_Relation):
    """Related application charm that has been provided with a database & user"""

    def __init__(
        self, *, relation: ops.Relation, interface: data_interfaces.DatabaseProvides
    ) -> None:
        super().__init__(relation=relation)
        self._local_databag = relation.data[interface.local_app]
        for key in ["database", "username", "password", "endpoints"]:
            if key not in self._local_databag:
                raise _UserNotCreated

    def _delete_databag(self) -> None:
        """Remove connection information from databag."""
        logger.debug(f"Deleting databag {self._id=}")
        self._local_databag.clear()
        logger.debug(f"Deleted databag {self._id=}")

    def delete_user(self, *, shell: mysql_shell.Shell) -> None:
        """Delete user and update databag."""
        self._delete_databag()
        shell.delete_user(self._get_username(shell.username))


class RelationEndpoint:
    """Relation endpoint for application charm(s)"""

    NAME = "database"

    def __init__(self, charm_: "charm.MySQLRouterOperatorCharm") -> None:
        self._interface = data_interfaces.DatabaseProvides(charm_, relation_name=self.NAME)
        charm_.framework.observe(
            charm_.on[self.NAME].relation_joined,
            charm_.reconcile_database_relations,
        )
        charm_.framework.observe(
            self._interface.on.database_requested,
            charm_.reconcile_database_relations,
        )
        charm_.framework.observe(
            charm_.on[self.NAME].relation_broken,
            charm_.reconcile_database_relations,
        )

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
        requested_users = []
        created_users = []
        for relation in self._interface.relations:
            try:
                requested_users.append(
                    _RequestedUser(relation=relation, interface=self._interface, event=event)
                )
            except (_RelationBreaking, _IncompleteDatabag, _UnsupportedExtraUserRole):
                pass
            try:
                created_users.append(_CreatedUser(relation=relation, interface=self._interface))
            except _UserNotCreated:
                pass
        logger.debug(f"State of reconcile users {requested_users=}, {created_users=}")
        for relation in requested_users:
            if relation not in created_users:
                relation.create_database_and_user(router_endpoint=router_endpoint, shell=shell)
        for relation in created_users:
            if relation not in requested_users:
                relation.delete_user(shell=shell)
        logger.debug(f"Reconciled users {event=}, {router_endpoint=}")

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        requested_users = []
        exceptions: list[StatusException] = []
        for relation in self._interface.relations:
            try:
                requested_users.append(
                    _RequestedUser(relation=relation, interface=self._interface, event=event)
                )
            except _RelationBreaking:
                pass
            except (_IncompleteDatabag, _UnsupportedExtraUserRole) as exception:
                exceptions.append(exception)
        # Always report unsupported extra user role
        for exception in exceptions:
            if isinstance(exception, _UnsupportedExtraUserRole):
                return exception.status
        if requested_users:
            # At least one relation is active—do not report about inactive relations
            return
        for exception in exceptions:
            if isinstance(exception, _IncompleteDatabag):
                return exception.status
        return ops.BlockedStatus(f"Missing relation: {self.NAME}")
