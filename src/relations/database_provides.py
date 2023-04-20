import dataclasses
import logging
import secrets
import string

import charms.data_platform_libs.v0.data_interfaces as data_interfaces
import ops

from constants import PASSWORD_LENGTH

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Relation:
    interface: data_interfaces.DatabaseProvides

    @property
    def active(self) -> bool:
        """Whether relation is currently active"""
        if not self._exists:
            return False
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
    def _exists(self) -> bool:
        relations = self.interface.relations
        if relations:
            assert len(relations) == 1
            return True
        return False

    @property
    def _database_requested(self) -> bool:
        return self._remote_databag.get("database") is not None

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
        if (
            isinstance(event, ops.charm.RelationBrokenEvent)
            and self._exists
            and event.relation.id == self._id
        ):
            # Relation is being removed
            return False
        if self._exists and self._database_requested:
            return True
        return self.active

    def set_databag(self, password: str, endpoint: str) -> None:
        endpoint = f"{endpoint}:6446"
        read_only_endpoint = f"{endpoint}:6447"
        logger.debug(
            f"Setting databag {self.database=}, {self.username=}, {endpoint=}, {read_only_endpoint=}"
        )
        self.interface.set_database(self._id, self.database)
        self.interface.set_credentials(self._id, self.username, password)
        self.interface.set_endpoints(self._id, endpoint)
        self.interface.set_read_only_endpoints(self._id, read_only_endpoint)
        logger.debug(
            f"Set databag {self.database=}, {self.username=}, {endpoint=}, {read_only_endpoint=}"
        )

    def delete_databag(self) -> None:
        logger.debug("Deleting databag")
        self._local_databag.clear()
        logger.debug("Deleted databag")

    @staticmethod
    def generate_password() -> str:
        choices = string.ascii_letters + string.digits
        return "".join([secrets.choice(choices) for _ in range(PASSWORD_LENGTH)])
