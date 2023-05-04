# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to MySQL charm"""

import dataclasses
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops


@dataclasses.dataclass
class _Relation:
    """Relation to MySQL charm"""

    _interface: data_interfaces.DatabaseRequires

    @property
    def id(self) -> int:
        relations = self._interface.relations
        assert len(relations) == 1
        return relations[0].id

    @property
    def _remote_databag(self) -> dict:
        """MySQL charm databag"""
        return self._interface.fetch_relation_data()[self.id]

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
        return isinstance(event, ops.RelationBrokenEvent) and event.relation.id == self.id


@dataclasses.dataclass
class RelationEndpoint:
    """Relation endpoint for MySQL charm"""

    interface: data_interfaces.DatabaseRequires

    NAME = "backend-database"

    @property
    def relation(self) -> typing.Optional[_Relation]:
        """Relation to MySQL charm"""
        if not self.interface.is_resource_created():
            return
        return _Relation(self.interface)

    @property
    def missing_relation(self) -> bool:
        """Whether relation to MySQL charm does not exist"""
        return self.relation is None
