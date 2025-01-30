# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to the cos charms."""

import logging
import typing
from dataclasses import dataclass

import ops

import container
import relations.secrets
import utils
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from rock import CONTAINER_NAME

if typing.TYPE_CHECKING:
    import abstract_charm

logger = logging.getLogger(__name__)


@dataclass
class ExporterConfig:
    """Configuration for the MySQL Router exporter"""

    url: str
    username: str
    password: str
    listen_port: str


class COSRelation:
    """Relation with the cos bundle."""

    _EXPORTER_PORT = "9152"
    HTTP_SERVER_PORT = "8443"
    _METRICS_RELATION_NAME = "metrics-endpoint"
    _LOGGING_RELATION_NAME = "logging"
    _PEER_RELATION_NAME = "cos"
    _ROUTER_LOG_FILES_TARGET = "/var/log/mysqlrouter/**/*log*"

    MONITORING_USERNAME = "monitoring"
    _MONITORING_PASSWORD_KEY = "monitoring-password"

    def __init__(self, charm_: "abstract_charm.MySQLRouterCharm", container_: container.Container):
        self._grafana_dashboards = GrafanaDashboardProvider(charm_)
        self._metrics_endpoint = MetricsEndpointProvider(
            charm_,
            refresh_event=charm_.on.start,
            jobs=[{"static_configs": [{"targets": [f"*:{self._EXPORTER_PORT}"]}]}],
        )
        self._loki_push = LogProxyConsumer(
            charm_,
            relation_name=self._LOGGING_RELATION_NAME,
            logs_scheme={
                CONTAINER_NAME: {
                    "log-files": [self._ROUTER_LOG_FILES_TARGET],
                },
            },
        )

        self._charm = charm_
        self._container = container_

        charm_.framework.observe(
            charm_.on[self._METRICS_RELATION_NAME].relation_created,
            charm_.reconcile,
        )
        charm_.framework.observe(
            charm_.on[self._METRICS_RELATION_NAME].relation_broken,
            charm_.reconcile,
        )

        self._secrets = relations.secrets.RelationSecrets(
            charm_,
            self._PEER_RELATION_NAME,
            unit_secret_fields=[self._MONITORING_PASSWORD_KEY],
        )

    @property
    def exporter_user_config(self) -> ExporterConfig:
        """Returns user config needed for the router exporter service."""
        return ExporterConfig(
            url=f"https://127.0.0.1:{self.HTTP_SERVER_PORT}",
            username=self.MONITORING_USERNAME,
            password=self.get_monitoring_password(),
            listen_port=self._EXPORTER_PORT,
        )

    @property
    def relation_exists(self) -> bool:
        """Whether relation with cos exists."""
        return len(self._charm.model.relations.get(self._METRICS_RELATION_NAME, [])) == 1

    def get_monitoring_password(self) -> str:
        """Gets the monitoring password from unit peer data, or generate and cache it."""
        monitoring_password = self._secrets.get_value(
            relations.secrets.UNIT_SCOPE, self._MONITORING_PASSWORD_KEY
        )
        if monitoring_password:
            return monitoring_password

        monitoring_password = utils.generate_password()
        self._secrets.set_value(
            relations.secrets.UNIT_SCOPE, self._MONITORING_PASSWORD_KEY, monitoring_password
        )
        return monitoring_password

    def _reset_monitoring_password(self) -> None:
        """Reset the monitoring password from unit peer data."""
        self._secrets.set_value(relations.secrets.UNIT_SCOPE, self._MONITORING_PASSWORD_KEY, None)

    def is_relation_breaking(self, event) -> bool:
        """Whether relation will be broken after the current event is handled."""
        if not self.relation_exists:
            return False

        return (
            isinstance(event, ops.RelationBrokenEvent)
            and event.relation.id == self._charm.model.relations[self._METRICS_RELATION_NAME][0].id
        )
