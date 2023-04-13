import dataclasses
import secrets
import string

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

from constants import PASSWORD_LENGTH


@dataclasses.dataclass
class Relation:
    interface: data_interfaces.DatabaseProvides

    @property
    def active(self) -> bool:
        """Whether relation is currently active"""
        for key in ["database", "username", "password", "endpoints"]:
            if key not in self._local_databag:
                return False
        return True

    @property
    def database(self) -> str:
        return self._remote_databag["database"]

    @property
    def username(self) -> str:
        return f"relation-{self._id}"

    @property
    def _relation(self) -> ops.model.Relation:
        relations = self.interface.relations
        assert len(relations) == 1
        return relations[0]

    @property
    def _id(self) -> int:
        return self._relation.id

    @property
    def _remote_databag(self) -> dict:
        return self.interface.fetch_relation_data()[self._id]

    @property
    def _local_databag(self) -> ops.model.RelationDataContent:
        return self._relation.data[self.interface.local_app]

    def is_desired_active(self, event) -> bool:
        """Whether relation should be active once the event is handled"""
        if isinstance(event, ops.charm.RelationBrokenEvent) and event.relation.id == self._id:
            # Relation is being removed
            return False
        if isinstance(event, data_interfaces.DatabaseRequestedEvent):
            return True
        return self.active

    def set_databag(self, password: str, endpoint: str) -> None:
        self.interface.set_database(self._id, self.database)
        self.interface.set_credentials(self._id, self.username, password)
        self.interface.set_endpoints(self._id, f"{endpoint}:6446")
        self.interface.set_read_only_endpoints(self._id, f"{endpoint}:6447")

    def delete_databag(self) -> None:
        self._local_databag.clear()

    @staticmethod
    def generate_password() -> str:
        choices = string.ascii_letters + string.digits
        return "".join([secrets.choice(choices) for _ in range(PASSWORD_LENGTH)])
