# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to MySQL charm"""

import dataclasses
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

if typing.TYPE_CHECKING:
    import charm


@dataclasses.dataclass(kw_only=True)
class ConnectionInformation:
    """Information for connection to MySQL cluster

    User has permission to:
    - Create databases & users
    - Grant all privileges on a database to a user
    (Different from user that MySQL Router runs with after bootstrap.)
    """

    host: str
    port: str
    username: str
    password: str


class _IncompleteDatabag(KeyError):
    """Databag is missing required key"""


class _Databag(dict):
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            raise _IncompleteDatabag


@dataclasses.dataclass
class _Relation:
    """Relation to MySQL charm"""

    _interface: data_interfaces.DatabaseRequires

    @property
    def _relation(self) -> ops.Relation:
        relations = self._interface.relations
        assert len(relations) == 1
        return relations[0]

    @property
    def _id(self) -> int:
        return self._relation.id

    @property
    def _remote_databag(self) -> _Databag:
        """MySQL charm databag"""
        return _Databag(self._interface.fetch_relation_data()[self._id])

    @property
    def _endpoint(self) -> str:
        """MySQL cluster primary endpoint"""
        endpoints = self._remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        return endpoints[0]

    @property
    def connection_info(self) -> ConnectionInformation:
        return ConnectionInformation(
            host=self._endpoint.split(":")[0],
            port=self._endpoint.split(":")[1],
            username=self._remote_databag["username"],
            password=self._remote_databag["password"],
        )

    def is_breaking(self, event):
        """Whether relation will be broken after the current event is handled"""
        return isinstance(event, ops.RelationBrokenEvent) and event.relation.id == self._id


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

    @property
    def _relation(self) -> typing.Optional[_Relation]:
        """Relation to MySQL charm"""
        if not self._interface.relations:
            return
        return _Relation(self._interface)

    def _is_missing_relation(self, event) -> bool:
        """Whether relation to MySQL charm does (or will) not exist"""
        return self._relation is None or self._relation.is_breaking(event)

    def get_connection_info(self, event) -> typing.Optional[ConnectionInformation]:
        if self._is_missing_relation(event=event):
            return
        try:
            return self._relation.connection_info
        except _IncompleteDatabag:
            return

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        if self._is_missing_relation(event=event):
            return ops.BlockedStatus(f"Missing relation: {self.NAME}")
        if self.get_connection_info(event=event) is None:
            # Connection information has not been provided by the MySQL charm
            return ops.WaitingStatus(f"Waiting for related app on endpoint: {self.NAME}")
