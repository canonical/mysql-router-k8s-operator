# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL Router charm"""

import abc
import logging
import typing

import charm_refresh
import ops
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

import container
import lifecycle
import logrotate
import relations.cos
import relations.database_provides
import relations.database_requires
import relations.tls
import server_exceptions
import workload

logger = logging.getLogger(__name__)


class MySQLRouterCharm(ops.CharmBase, abc.ABC):
    """MySQL Router charm"""

    _READ_WRITE_PORT = 6446
    _READ_ONLY_PORT = 6447
    _READ_WRITE_X_PORT = 6448
    _READ_ONLY_X_PORT = 6449

    _TRACING_RELATION_NAME = "tracing"
    _TRACING_PROTOCOL = "otlp_http"

    refresh: charm_refresh.Refresh

    def __init__(self, *args) -> None:
        super().__init__(*args)
        # Instantiate before registering other event observers
        self._unit_lifecycle = lifecycle.Unit(
            self, subordinated_relation_endpoint_names=self._subordinate_relation_endpoint_names
        )

        self._workload_type = workload.Workload
        self._authenticated_workload_type = workload.AuthenticatedWorkload
        self._database_requires = relations.database_requires.RelationEndpoint(self)
        self._database_provides = relations.database_provides.RelationEndpoint(self)
        self._cos_relation = relations.cos.COSRelation(self, self._container)
        self.tls = relations.tls.RelationEndpoint(self)

        self.tracing = TracingEndpointRequirer(
            self, relation_name=self._TRACING_RELATION_NAME, protocols=[self._TRACING_PROTOCOL]
        )

        # Observe all events (except custom events)
        for bound_event in self.on.events().values():
            if bound_event.event_type == ops.CollectStatusEvent:
                continue
            self.framework.observe(bound_event, self.reconcile)

    @property
    @abc.abstractmethod
    def _subordinate_relation_endpoint_names(self) -> typing.Optional[typing.Iterable[str]]:
        """Subordinate relation endpoint names

        Does NOT include relations where charm is principal
        """

    @property
    @abc.abstractmethod
    def _container(self) -> container.Container:
        """Workload container (snap or rock)"""

    @property
    @abc.abstractmethod
    def _logrotate(self) -> logrotate.LogRotate:
        """logrotate"""

    @property
    @abc.abstractmethod
    def _read_write_endpoint(self) -> str:
        """MySQL Router read-write endpoint"""

    @property
    @abc.abstractmethod
    def _read_only_endpoint(self) -> str:
        """MySQL Router read-only endpoint"""

    @property
    @abc.abstractmethod
    def _exposed_read_write_endpoint(self) -> str:
        """The exposed read-write endpoint"""

    @property
    @abc.abstractmethod
    def _exposed_read_only_endpoint(self) -> str:
        """The exposed read-only endpoint"""

    @abc.abstractmethod
    def is_externally_accessible(self, *, event) -> typing.Optional[bool]:
        """Whether endpoints should be externally accessible.

        Only defined in vm charm to return True/False. In k8s charm, returns None.
        """

    @property
    def _tls_certificate_saved(self) -> bool:
        """Whether a TLS certificate is available to use"""
        return self.tls.certificate_saved

    @property
    def _tls_key(self) -> typing.Optional[str]:
        """Custom TLS key"""
        return self.tls.key

    @property
    def _tls_certificate_authority(self) -> typing.Optional[str]:
        """Custom TLS certificate authority"""
        return self.tls.certificate_authority

    @property
    def _tls_certificate(self) -> typing.Optional[str]:
        """Custom TLS certificate"""
        return self.tls.certificate

    @property
    def tracing_endpoint(self) -> typing.Optional[str]:
        """Otlp http endpoint for charm instrumentation."""
        if self.tracing.is_ready():
            return self.tracing.get_endpoint(self._TRACING_PROTOCOL)

    def _cos_exporter_config(self, event) -> typing.Optional[relations.cos.ExporterConfig]:
        """Returns the exporter config for MySQLRouter exporter if cos relation exists"""
        cos_relation_exists = (
            self._cos_relation.relation_exists
            and not self._cos_relation.is_relation_breaking(event)
        )
        if cos_relation_exists:
            return self._cos_relation.exporter_user_config

    def get_workload(self, *, event):
        """MySQL Router workload"""
        if connection_info := self._database_requires.get_connection_info(event=event):
            return self._authenticated_workload_type(
                container_=self._container,
                logrotate_=self._logrotate,
                connection_info=connection_info,
                cos=self._cos_relation,
                charm_=self,
            )
        return self._workload_type(
            container_=self._container, logrotate_=self._logrotate, cos=self._cos_relation
        )

    @staticmethod
    # TODO python3.10 min version: Use `list` instead of `typing.List`
    def _prioritize_statuses(statuses: typing.List[ops.StatusBase]) -> ops.StatusBase:
        """Report the highest priority status.

        (Statuses of the same type are reported in the order they were added to `statuses`)
        """
        status_priority = (
            ops.BlockedStatus,
            ops.MaintenanceStatus,
            ops.WaitingStatus,
            # Catch any unknown status type
            ops.StatusBase,
        )
        for status_type in status_priority:
            for status in statuses:
                if isinstance(status, status_type):
                    return status
        return ops.ActiveStatus()

    def _determine_app_status(self, *, event) -> ops.StatusBase:
        """Report app status."""
        if self.refresh.app_status_higher_priority:
            return self.refresh.app_status_higher_priority
        statuses = []
        for endpoint in (self._database_requires, self._database_provides):
            if status := endpoint.get_status(event):
                statuses.append(status)
        return self._prioritize_statuses(statuses)

    def _determine_unit_status(self, *, event) -> ops.StatusBase:
        """Report unit status."""
        if self.refresh.unit_status_higher_priority:
            return self.refresh.unit_status_higher_priority
        statuses = []
        workload_status = self.get_workload(event=event).status
        if workload_status:
            statuses.append(workload_status)
        if not statuses and self.refresh.unit_status_lower_priority:
            return self.refresh.unit_status_lower_priority
        return self._prioritize_statuses(statuses)

    def set_status(self, *, event, app=True, unit=True) -> None:
        """Set charm status."""
        if app and self._unit_lifecycle.authorized_leader:
            self.app.status = self._determine_app_status(event=event)
            logger.debug(f"Set app status to {self.app.status}")
        if unit:
            self.unit.status = self._determine_unit_status(event=event)
            logger.debug(f"Set unit status to {self.unit.status}")

    @abc.abstractmethod
    def wait_until_mysql_router_ready(self, *, event) -> None:
        """Wait until a connection to MySQL Router is possible.

        Retry every 5 seconds for up to 30 seconds.
        """

    @abc.abstractmethod
    def _reconcile_node_port(self, *, event) -> None:
        """Reconcile node port.

        Only applies to Kubernetes charm
        """

    @abc.abstractmethod
    def _reconcile_ports(self, *, event) -> None:
        """Reconcile exposed ports.

        Only applies to Machine charm
        """

    # =======================
    #  Handlers
    # =======================

    def reconcile(self, event=None) -> None:  # noqa: C901
        """Handle most events."""
        workload_ = self.get_workload(event=event)
        logger.debug(
            "State of reconcile "
            f"{self._unit_lifecycle.authorized_leader=}, "
            f"{isinstance(workload_, workload.AuthenticatedWorkload)=}, "
            f"{workload_.container_ready=}, "
            f"{self.refresh.workload_allowed_to_start=}, "
            f"{self._database_requires.is_relation_breaking(event)=}, "
            f"{self.refresh.in_progress=}, "
            f"{self._cos_relation.is_relation_breaking(event)=}"
        )

        try:
            if self._unit_lifecycle.authorized_leader:
                if self._database_requires.is_relation_breaking(event):
                    if self.refresh.in_progress:
                        logger.warning(
                            "Modifying relations during an upgrade is not supported. The charm may be in a broken, unrecoverable state. Re-deploy the charm"
                        )
                    self._database_provides.delete_all_databags()
                elif (
                    not self.refresh.in_progress
                    and isinstance(workload_, workload.AuthenticatedWorkload)
                    and workload_.container_ready
                ):
                    self._reconcile_node_port(event=event)
                    self._database_provides.reconcile_users(
                        event=event,
                        router_read_write_endpoint=self._read_write_endpoint,
                        router_read_only_endpoint=self._read_only_endpoint,
                        exposed_read_write_endpoint=self._exposed_read_write_endpoint,
                        exposed_read_only_endpoint=self._exposed_read_only_endpoint,
                        shell=workload_.shell,
                    )
            # todo: consider moving `self.refresh.workload_allowed_to_start` inside `workload._reconcile()`
            if workload_.container_ready and self.refresh.workload_allowed_to_start:
                workload_.reconcile(
                    event=event,
                    tls=self._tls_certificate_saved,
                    unit_name=self.unit.name,
                    exporter_config=self._cos_exporter_config(event),
                    key=self._tls_key,
                    certificate=self._tls_certificate,
                    certificate_authority=self._tls_certificate_authority,
                )
                if not self.refresh.in_progress and isinstance(
                    workload_, workload.AuthenticatedWorkload
                ):
                    self._reconcile_ports(event=event)

            # Empty waiting status means we're waiting for database requires relation before
            # starting workload
            if not workload_.status or workload_.status == ops.WaitingStatus():
                self.refresh.next_unit_allowed_to_refresh = True
            self.set_status(event=event)
        except server_exceptions.Error as e:
            # If not for `unit=False`, another `server_exceptions.Error` could be thrown here
            self.set_status(event=event, unit=False)
            self.unit.status = e.status
            logger.debug(f"Set unit status to {self.unit.status}")
