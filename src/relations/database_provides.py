# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation(s) to one or more application charms"""

import logging
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

import mysql_shell
import relations.remote_databag as remote_databag
import status_exception

if typing.TYPE_CHECKING:
    import abstract_charm

logger = logging.getLogger(__name__)


class _RelationBreaking(Exception):
    """Relation will be broken for this unit after the current event is handled

    If this unit is tearing down, the relation could still exist for other units.
    """


class _UnsupportedExtraUserRole(status_exception.StatusException):
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
        self._relation = relation

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


class _RelationThatRequestedUser(_Relation):
    """Related application charm that has requested a database & user"""

    def __init__(
        self, *, relation: ops.Relation, interface: data_interfaces.DatabaseProvides, event
    ) -> None:
        super().__init__(relation=relation)
        self._interface = interface
        if event and isinstance(event, ops.RelationBrokenEvent) and event.relation.id == self._id:
            raise _RelationBreaking
        # Application charm databag
        databag = remote_databag.RemoteDatabag(interface=interface, relation=relation)
        self._database: str = databag["database"]
        if databag.get("extra-user-roles"):
            raise _UnsupportedExtraUserRole(
                app_name=relation.app.name, endpoint_name=relation.name
            )

    @property
    def is_exposed(self) -> bool:
        """Whether the relation is exposed."""
        return (
            self._relation.data[self._relation.app].get("external-node-connectivity", "false")
            == "true"
        )

    def _set_databag(
        self,
        *,
        username: str,
        password: str,
        router_read_write_endpoint: str,
        router_read_only_endpoint: str,
    ) -> None:
        """Share connection information with application charm."""
        logger.debug(
            f"Setting databag {self._id=} {self._database=}, {username=}, {router_read_write_endpoint=}, {router_read_only_endpoint=}"
        )
        self._interface.set_database(self._id, self._database)
        self._interface.set_credentials(self._id, username, password)
        self._interface.set_endpoints(self._id, router_read_write_endpoint)
        self._interface.set_read_only_endpoints(self._id, router_read_only_endpoint)
        logger.debug(
            f"Set databag {self._id=} {self._database=}, {username=}, {router_read_write_endpoint=}, {router_read_only_endpoint=}"
        )

    def create_database_and_user(
        self,
        *,
        router_read_write_endpoint: str,
        router_read_only_endpoint: str,
        exposed_read_write_endpoint: str,
        exposed_read_only_endpoint: str,
        shell: mysql_shell.Shell,
    ) -> None:
        """Create database & user and update databag."""
        username = self._get_username(shell.username)
        # Delete user if exists
        # (If the user was previously created by this charm—but the hook failed—the user will
        # persist in MySQL but will not persist in the databag. Therefore, we lose the user's
        # password and need to re-create the user.)
        logger.debug("Deleting user if exists before creating user")
        shell.delete_user(username, must_exist=False)
        logger.debug("Deleted user if exists before creating user")

        password = shell.create_application_database_and_user(
            username=username, database=self._database
        )

        rw_endpoint = (
            exposed_read_write_endpoint if self.is_exposed else router_read_write_endpoint
        )
        ro_endpoint = exposed_read_only_endpoint if self.is_exposed else router_read_only_endpoint
        self._set_databag(
            username=username,
            password=password,
            router_read_write_endpoint=rw_endpoint,
            router_read_only_endpoint=ro_endpoint,
        )


class _UserNotShared(Exception):
    """Database & user has not been provided to related application charm"""


class _RelationWithSharedUser(_Relation):
    """Related application charm that has been provided with a database & user"""

    def __init__(
        self, *, relation: ops.Relation, interface: data_interfaces.DatabaseProvides
    ) -> None:
        super().__init__(relation=relation)
        self._interface = interface
        self._local_databag = self._interface.fetch_my_relation_data([relation.id])[relation.id]
        for key in ("database", "username", "password", "endpoints", "read-only-endpoints"):
            if key not in self._local_databag:
                raise _UserNotShared

    def delete_databag(self) -> None:
        """Remove connection information from databag."""
        logger.debug(f"Deleting databag {self._id=}")
        self._interface.delete_relation_data(self._id, list(self._local_databag))
        logger.debug(f"Deleted databag {self._id=}")

    def delete_user(self, *, shell: mysql_shell.Shell) -> None:
        """Delete user and update databag."""
        self.delete_databag()
        # Delete user if exists
        # (If the user was previously deleted by this charm—but the hook failed—the user will be
        # deleted in MySQL but will persist in the databag.)
        shell.delete_user(self._get_username(shell.username), must_exist=False)


class RelationEndpoint:
    """Relation endpoint for application charm(s)"""

    _NAME = "database"

    def __init__(self, charm_: "abstract_charm.MySQLRouterCharm") -> None:
        self._interface = data_interfaces.DatabaseProvides(charm_, relation_name=self._NAME)
        charm_.framework.observe(charm_.on[self._NAME].relation_created, charm_.reconcile)
        charm_.framework.observe(self._interface.on.database_requested, charm_.reconcile)
        charm_.framework.observe(charm_.on[self._NAME].relation_broken, charm_.reconcile)

    @property
    def is_exposed(self) -> bool:
        return any([relation.is_exposed for relation in self._requested_users()])

    @property
    # TODO python3.10 min version: Use `list` instead of `typing.List`
    def _shared_users(self) -> typing.List[_RelationWithSharedUser]:
        shared_users = []
        for relation in self._interface.relations:
            try:
                shared_users.append(
                    _RelationWithSharedUser(relation=relation, interface=self._interface)
                )
            except _UserNotShared:
                pass
        return shared_users

    def _requested_users(self, event=None) -> typing.List[_RelationThatRequestedUser]:
        requested_users = []
        for relation in self._interface.relations:
            try:
                requested_users.append(
                    _RelationThatRequestedUser(
                        relation=relation, interface=self._interface, event=event
                    )
                )
            except (
                _RelationBreaking,
                remote_databag.IncompleteDatabag,
                _UnsupportedExtraUserRole,
            ):
                pass
        return requested_users

    def reconcile_users(
        self,
        *,
        event,
        router_read_write_endpoint: str,
        router_read_only_endpoint: str,
        exposed_read_write_endpoint: str,
        exposed_read_only_endpoint: str,
        shell: mysql_shell.Shell,
    ) -> None:
        """Create requested users and delete inactive users.

        When the relation to the MySQL charm is broken, the MySQL charm will delete all users
        created by this charm. Therefore, this charm does not need to delete users when that
        relation is broken.
        """
        logger.debug(
            f"Reconciling users {event=}, {router_read_write_endpoint=}, {router_read_only_endpoint=}, "
            f"{exposed_read_write_endpoint=}, {exposed_read_only_endpoint=}"
        )

        logger.debug(
            f"State of reconcile users {self._requested_users(event)=}, {self._shared_users=}"
        )
        for request in self._requested_users(event):
            relation = request.relation
            if request not in self._shared_users:
                request.create_database_and_user(
                    router_read_write_endpoint=router_read_write_endpoint,
                    router_read_only_endpoint=router_read_only_endpoint,
                    exposed_read_write_endpoint=exposed_read_write_endpoint,
                    exposed_read_only_endpoint=exposed_read_only_endpoint,
                    shell=shell,
                )
            logger.debug(f"Reconciled users {event=}")

        for relation in self._shared_users:
            if relation not in self._requested_users(event):
                relation.delete_user(shell=shell)

    def delete_all_databags(self) -> None:
        """Remove connection information from all databags.

        Called when relation with MySQL is breaking

        When the MySQL relation is re-established, it could be a different MySQL cluster—new users
        will need to be created.
        """
        logger.debug("Deleting all application databags")
        for relation in self._shared_users:
            # MySQL charm will delete user; just delete databag
            relation.delete_databag()
        logger.debug("Deleted all application databags")

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        requested_users = []
        exception_reporting_priority = (
            _UnsupportedExtraUserRole,
            remote_databag.IncompleteDatabag,
        )
        # TODO python3.10 min version: Use `list` instead of `typing.List`
        exceptions: typing.List[status_exception.StatusException] = []
        for relation in self._interface.relations:
            try:
                requested_users.append(
                    _RelationThatRequestedUser(
                        relation=relation, interface=self._interface, event=event
                    )
                )
            except _RelationBreaking:
                pass
            except exception_reporting_priority as exception:
                exceptions.append(exception)
        for exception_type in exception_reporting_priority:
            for exception in exceptions:
                if isinstance(exception, exception_type):
                    return exception.status
        if not requested_users:
            return ops.BlockedStatus(f"Missing relation: {self._NAME}")
