# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to MySQL charm"""

import dataclasses
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

if typing.TYPE_CHECKING:
    import charm


@dataclasses.dataclass
class Relation:
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
    def _remote_databag(self) -> dict:
        """MySQL charm databag"""
        return self._interface.fetch_relation_data()[self._id]

    @property
    def _endpoint(self) -> str:
        """MySQL cluster primary endpoint"""
        endpoints = self._remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        return endpoints[0]

    @property
    def host(self) -> str:
        """MySQL cluster primary host"""
        return self._endpoint.split(":")[0]

    @property
    def port(self) -> str:
        """MySQL cluster primary port"""
        return self._endpoint.split(":")[1]

    @property
    def username(self) -> str:
        """Admin username"""
        return self._remote_databag["username"]

    @property
    def password(self) -> str:
        """Admin password"""
        return self._remote_databag["password"]

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
            charm_.on[self.NAME].relation_broken,
            charm_.reconcile_database_relations,
        )

    @property
    def relation(self) -> typing.Optional[Relation]:
        """Relation to MySQL charm"""
        if not self._interface.is_resource_created():
            return
        return Relation(self._interface)

    def _is_missing_relation(self, event) -> bool:
        """Whether relation to MySQL charm does (or will) not exist"""
        # Cannot use `self.relation.is_breaking()` in case relation exists but resource not created
        if self._interface.relations and Relation(self._interface).is_breaking(event):
            return True
        return len(self._interface.relations) == 0

    def get_status(self, event) -> typing.Optional[ops.StatusBase]:
        """Report non-active status."""
        if self._is_missing_relation(event):
            return ops.BlockedStatus(f"Missing relation: {self.NAME}")
        if self.relation is None:
            # Resource (database & user) has not been created by the MySQL charm
            return ops.WaitingStatus(f"Waiting for related app on endpoint: {self.NAME}")
