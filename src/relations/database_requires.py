# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to MySQL charm"""

import dataclasses
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

if typing.TYPE_CHECKING:
    import charm


class _IncompleteDatabag(KeyError):
    """Databag is missing required key"""


class _Databag(dict):
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            raise _IncompleteDatabag


class _MissingRelation(Exception):
    """Relation to MySQL charm does (or will) not exist"""


class ConnectionInformation:
    """Information for connection to MySQL cluster

    User has permission to:
    - Create databases & users
    - Grant all privileges on a database to a user
    (Different from user that MySQL Router runs with after bootstrap.)
    """

    def __init__(self, *, interface: data_interfaces.DatabaseRequires, event):
        relations = interface.relations
        if not relations:
            raise _MissingRelation
        assert len(relations) == 1
        relation = relations[0]
        if isinstance(event, ops.RelationBrokenEvent) and event.relation.id == relation.id:
            # Relation will be broken after the current event is handled
            raise _MissingRelation
        # MySQL charm databag
        remote_databag = _Databag(interface.fetch_relation_data()[relation.id])
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

    def get_connection_info(self, event) -> typing.Optional[ConnectionInformation]:
        """Information for connection to MySQL cluster"""
        try:
            return ConnectionInformation(interface=self._interface, event=event)
        except (_MissingRelation, _IncompleteDatabag):
            return

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        try:
            ConnectionInformation(interface=self._interface, event=event)
        except _MissingRelation:
            return ops.BlockedStatus(f"Missing relation: {self.NAME}")
        except _IncompleteDatabag:
            # Connection information has not been provided by the MySQL charm
            return ops.WaitingStatus(f"Waiting for related app on endpoint: {self.NAME}")
