# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to MySQL charm"""

import dataclasses
import logging
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

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


class _MissingRelation(StatusException):
    """Relation to MySQL charm does (or will) not exist"""

    def __init__(self, *, endpoint_name: str) -> None:
        super().__init__(ops.BlockedStatus(f"Missing relation: {endpoint_name}"))


class ConnectionInformation:
    """Information for connection to MySQL cluster

    User has permission to:
    - Create databases & users
    - Grant all privileges on a database to a user
    (Different from user that MySQL Router runs with after bootstrap.)
    """

    def __init__(self, *, interface: data_interfaces.DatabaseRequires, event) -> None:
        relations = interface.relations
        endpoint_name = interface.relation_name
        if not relations:
            logger.debug(f"No relations on {endpoint_name=}")
            raise _MissingRelation(endpoint_name=endpoint_name)
        assert len(relations) == 1
        relation = relations[0]
        if isinstance(event, ops.RelationBrokenEvent) and event.relation.id == relation.id:
            # Relation will be broken after the current event is handled
            logger.debug(f"Relation breaking on {endpoint_name=}")
            raise _MissingRelation(endpoint_name=endpoint_name)
        # MySQL charm databag
        remote_databag = _Databag(interface=interface, relation=relation)
        endpoints = remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        endpoint = endpoints[0]
        self.host: str = endpoint.split(":")[0]
        self.port: str = endpoint.split(":")[1]
        self.username: str = remote_databag["username"]
        self.password: str = remote_databag["password"]


class RelationEndpoint:
    """Relation endpoint for MySQL charm"""

    NAME = "backend-database"

    def __init__(self, charm_: "charm.MySQLRouterOperatorCharm") -> None:
        self._interface = data_interfaces.DatabaseRequires(
            charm_,
            relation_name=self.NAME,
            # Database name disregarded by MySQL charm if "mysqlrouter" extra user role requested
            database_name="mysql_innodb_cluster_metadata",
            extra_user_roles="mysqlrouter",
        )
        charm_.framework.observe(
            charm_.on[self.NAME].relation_created,
            charm_.reconcile_database_relations,
        )
        charm_.framework.observe(
            self._interface.on.database_created,
            charm_.reconcile_database_relations,
        )
        charm_.framework.observe(
            self._interface.on.endpoints_changed,
            charm_.reconcile_database_relations,
        )
        charm_.framework.observe(
            charm_.on[self.NAME].relation_broken,
            charm_.reconcile_database_relations,
        )

    def get_connection_info(self, *, event) -> typing.Optional[ConnectionInformation]:
        """Information for connection to MySQL cluster"""
        try:
            return ConnectionInformation(interface=self._interface, event=event)
        except (_MissingRelation, _IncompleteDatabag):
            return

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        try:
            ConnectionInformation(interface=self._interface, event=event)
        except (_MissingRelation, _IncompleteDatabag) as exception:
            return exception.status
