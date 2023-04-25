import dataclasses
import typing

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops


@dataclasses.dataclass
class _Relation:
    _interface: data_interfaces.DatabaseRequires

    @property
    def _id(self) -> int:
        relations = self._interface.relations
        assert len(relations) == 1
        return relations[0].id

    @property
    def _remote_databag(self) -> dict:
        return self._interface.fetch_relation_data()[self._id]

    @property
    def _endpoint(self) -> str:
        endpoints = self._remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        return endpoints[0]

    @property
    def host(self) -> str:
        return self._endpoint.split(":")[0]

    @property
    def port(self) -> str:
        return self._endpoint.split(":")[1]

    @property
    def username(self) -> str:
        return self._remote_databag["username"]

    @property
    def password(self) -> str:
        return self._remote_databag["password"]

    def is_breaking(self, event):
        return isinstance(event, ops.RelationBrokenEvent) and event.relation.id == self._id


@dataclasses.dataclass
class RelationEndpoint:
    interface: data_interfaces.DatabaseRequires
    NAME = "backend-database"

    @property
    def relation(self) -> typing.Optional[_Relation]:
        if not self.interface.is_resource_created():
            return
        return _Relation(self.interface)

    @property
    def missing_relation(self) -> bool:
        return self.relation is None
