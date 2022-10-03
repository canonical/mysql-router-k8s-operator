# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the database provides relation."""

import json
import logging

from charms.data_platform_libs.v0.database_provides import (
    DatabaseProvides,
    DatabaseRequestedEvent,
)
from ops.framework import Object

from constants import (
    CREDENTIALS_SHARED,
    DATABASE_PROVIDES_RELATION,
    MYSQL_DATABASE_CREATED,
    MYSQL_ROUTER_PROVIDES_DATA,
    MYSQL_ROUTER_REQUIRES_APPLICATION_DATA,
    PEER,
    UNIT_BOOTSTRAPPED,
)

logger = logging.getLogger(__name__)


class DatabaseProvidesRelation(Object):
    """Encapsulation of the relation between mysqlrouter and the consumer application."""

    def __init__(self, charm):
        super().__init__(charm, DATABASE_PROVIDES_RELATION)

        self.charm = charm
        self.database_provides_relation = DatabaseProvides(
            self.charm, relation_name=DATABASE_PROVIDES_RELATION
        )

        self.framework.observe(
            self.database_provides_relation.on.database_requested, self._on_database_requested
        )
        self.framework.observe(
            self.charm.on[PEER].relation_changed, self._on_peer_relation_changed
        )

    # =======================
    #  Handlers
    # =======================

    def _on_database_requested(self, event: DatabaseRequestedEvent) -> None:
        """Handle the database requested event."""
        if not self.charm.unit.is_leader():
            return

        self.charm.app_peer_data[MYSQL_ROUTER_PROVIDES_DATA] = json.dumps(
            {"database": event.database, "extra_user_roles": event.extra_user_roles}
        )

    def _on_peer_relation_changed(self, _) -> None:
        """Handle the peer relation changed event."""
        if not self.charm.unit.is_leader():
            return

        if self.charm.app_peer_data.get(CREDENTIALS_SHARED):
            return

        if not self.charm.app_peer_data.get(MYSQL_DATABASE_CREATED):
            return

        if not self.charm.unit_peer_data.get(UNIT_BOOTSTRAPPED):
            return

        database_provides_relations = self.charm.model.relations.get(DATABASE_PROVIDES_RELATION)
        if not database_provides_relations:
            return

        requires_application_data = json.loads(
            self.charm.app_peer_data[MYSQL_ROUTER_REQUIRES_APPLICATION_DATA]
        )
        provides_relation_id = database_provides_relations[0].id

        self.database_provides_relation.set_credentials(
            provides_relation_id,
            requires_application_data["username"],
            self.charm._get_secret("app", "application-password"),
        )

        self.database_provides_relation.set_endpoints(
            provides_relation_id, f"{self.charm.read_write_endpoint}:6446"
        )

        self.database_provides_relation.set_read_only_endpoints(
            provides_relation_id, f"{self.charm.read_only_endpoint}:6447"
        )

        self.charm.app_peer_data[CREDENTIALS_SHARED] = "true"
