import dataclasses

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops


@dataclasses.dataclass
class Relation:
    interface: data_interfaces.DatabaseRequires

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

    @property
    def _id(self) -> int:
        relations = self.interface.relations
        assert len(relations) == 1
        return relations[0].id

    @property
    def _remote_databag(self) -> dict:
        return self.interface.fetch_relation_data()[self._id]

    @property
    def _endpoint(self) -> str:
        endpoints = self._remote_databag["endpoints"].split(",")
        assert len(endpoints) == 1
        return endpoints[0]

    @property
    def _active(self) -> bool:
        """Whether relation is currently active"""
        if not self.interface.relations:
            return False
        return self.interface.is_resource_created()

    def is_desired_active(self, event) -> bool:
        """Whether relation should be active once the event is handled"""
        if isinstance(event, ops.charm.RelationBrokenEvent) and event.relation.id == self._id:
            # Relation is being removed; it is no longer active
            return False
        return self._active

    def create_application_database_and_user(
        self, username: str, password: str, database: str
    ) -> None:
        # TODO: port method from mysql_router_helpers or mysql charm lib
        pass

    def delete_application_user(self, username: str) -> None:
        # TODO: port method from mysql_router_helpers or mysql charm lib
        pass
