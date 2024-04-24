# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In-place upgrades on Kubernetes

Implements specification: DA058 - In-Place Upgrades - Kubernetes v2
(https://docs.google.com/document/d/1tLjknwHudjcHs42nzPVBNkHs98XxAOT2BXGGpP7NyEU/)
"""

import functools
import logging
import typing

import lightkube
import lightkube.core.exceptions
import lightkube.models.apps_v1
import lightkube.resources.apps_v1
import lightkube.resources.core_v1
import ops

import upgrade
import workload

logger = logging.getLogger(__name__)


class DeployedWithoutTrust(Exception):
    """Deployed without `juju deploy --trust` or `juju trust`

    Needed to access Kubernetes StatefulSet
    """

    def __init__(self, *, app_name: str):
        super().__init__(
            f"Run `juju trust {app_name} --scope=cluster` and `juju resolve` for each unit (or remove & re-deploy {app_name} with `--trust`)"
        )


class _Partition:
    """StatefulSet partition getter/setter"""

    # Note: I realize this isn't very Pythonic (it'd be nicer to use a property). Because of how
    # ops is structured, we don't have access to the app name when we initialize this class. We
    # need to only initialize this class once so that there is a single cache. Therefore, the app
    # name needs to be passed as argument to the methods (instead of as an argument to __init__)—
    # so we can't use a property.

    def __init__(self):
        # Cache lightkube API call for duration of charm execution
        self._cache: dict[str, int] = {}

    def get(self, *, app_name: str) -> int:
        return self._cache.setdefault(
            app_name,
            lightkube.Client()
            .get(res=lightkube.resources.apps_v1.StatefulSet, name=app_name)
            .spec.updateStrategy.rollingUpdate.partition,
        )

    def set(self, *, app_name: str, value: int) -> None:
        lightkube.Client().patch(
            res=lightkube.resources.apps_v1.StatefulSet,
            name=app_name,
            obj={"spec": {"updateStrategy": {"rollingUpdate": {"partition": value}}}},
        )
        self._cache[app_name] = value


class Upgrade(upgrade.Upgrade):
    """In-place upgrades on Kubernetes"""

    def __init__(self, charm_: ops.CharmBase, *args, **kwargs):
        try:
            partition.get(app_name=charm_.app.name)
        except lightkube.core.exceptions.ApiError as e:
            if e.status.code == 403:
                raise DeployedWithoutTrust(app_name=charm_.app.name)
            raise
        super().__init__(charm_, *args, **kwargs)

    def _get_unit_healthy_status(
        self, *, workload_status: typing.Optional[ops.StatusBase]
    ) -> typing.Optional[ops.StatusBase]:
        if (
            self._unit_workload_container_versions[self._unit.name]
            == self._app_workload_container_version
        ):
            if isinstance(workload_status, ops.WaitingStatus):
                return ops.WaitingStatus(
                    f'Router {self._current_versions["workload"]}; Charmed operator {self._current_versions["charm"]}'
                )
            return ops.ActiveStatus(
                f'Router {self._current_versions["workload"]} running; Charmed operator {self._current_versions["charm"]}'
            )
        if isinstance(workload_status, ops.WaitingStatus):
            return ops.WaitingStatus(
                f'Router {self._current_versions["workload"]}; Charmed operator {self._current_versions["charm"]}'
            )
        # During a rollback, non-upgraded units will restart
        # (Juju bug: https://bugs.launchpad.net/juju/+bug/2036246)
        # To explain this behavior to the user, we include "(restart pending)" in the status
        # message. For non-upgraded units: the charm and workload version will be the same, but
        # since the Kubernetes controller revision hash is different, the unit (pod) will restart
        # during rollback.
        return ops.ActiveStatus(
            f'Router {self._current_versions["workload"]} running (restart pending); Charmed operator {self._current_versions["charm"]}'
        )

    @property
    def upgrade_resumed(self) -> bool:
        return self._partition < upgrade.unit_number(self._sorted_units[0])

    @property
    def _partition(self) -> int:
        """Specifies which units should upgrade

        Unit numbers >= partition should upgrade
        Unit numbers < partition should not upgrade

        https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#partitions

        For Kubernetes, unit numbers are guaranteed to be sequential
        """
        return partition.get(app_name=self._app_name)

    @_partition.setter
    def _partition(self, value: int) -> None:
        partition.set(app_name=self._app_name, value=value)

    @functools.cached_property  # Cache lightkube API call for duration of charm execution
    def _unit_workload_container_versions(self) -> dict[str, str]:
        """{Unit name: Kubernetes controller revision hash}

        Even if the workload container version is the same, the workload will restart if the
        controller revision hash changes. (Juju bug: https://bugs.launchpad.net/juju/+bug/2036246).

        Therefore, we must use the revision hash instead of the workload container version. (To
        satisfy the requirement that if and only if this version changes, the workload will
        restart.)
        """
        pods = lightkube.Client().list(
            res=lightkube.resources.core_v1.Pod, labels={"app.kubernetes.io/name": self._app_name}
        )

        def get_unit_name(pod_name: str) -> str:
            *app_name, unit_number = pod_name.split("-")
            return f'{"-".join(app_name)}/{unit_number}'

        return {
            get_unit_name(pod.metadata.name): pod.metadata.labels["controller-revision-hash"]
            for pod in pods
        }

    @functools.cached_property  # Cache lightkube API call for duration of charm execution
    def _app_workload_container_version(self) -> str:
        """App's Kubernetes controller revision hash"""
        stateful_set = lightkube.Client().get(
            res=lightkube.resources.apps_v1.StatefulSet, name=self._app_name
        )
        return stateful_set.status.updateRevision

    def reconcile_partition(self, *, action_event: ops.ActionEvent = None) -> None:
        """If ready, lower partition to upgrade next unit.

        If upgrade is not in progress, set partition to 0. (If a unit receives a stop event, it may
        raise the partition even if an upgrade is not in progress.)

        Automatically upgrades next unit if all upgraded units are healthy—except if only one unit
        has upgraded (need manual user confirmation [via Juju action] to upgrade next unit)

        Handle Juju action to:
        - confirm first upgraded unit is healthy and resume upgrade
        - force upgrade of next unit if 1 or more upgraded units are unhealthy
        """
        force = bool(action_event and action_event.params["force"] is True)

        units = self._sorted_units

        def determine_partition() -> int:
            if not self.in_progress:
                return 0
            logger.debug(f"{self._peer_relation.data=}")
            for upgrade_order_index, unit in enumerate(units):
                # Note: upgrade_order_index != unit number
                state = self._peer_relation.data[unit].get("state")
                if state:
                    state = upgrade.UnitState(state)
                if (
                    not force and state is not upgrade.UnitState.HEALTHY
                ) or self._unit_workload_container_versions[
                    unit.name
                ] != self._app_workload_container_version:
                    if not action_event and upgrade_order_index == 1:
                        # User confirmation needed to resume upgrade (i.e. upgrade second unit)
                        return upgrade.unit_number(units[0])
                    return upgrade.unit_number(unit)
            return 0

        partition_ = determine_partition()
        logger.debug(f"{self._partition=}, {partition_=}")
        # Only lower the partition—do not raise it.
        # If this method is called during the action event and then called during another event a
        # few seconds later, `determine_partition()` could return a lower number during the action
        # and then a higher number a few seconds later.
        # This can cause the unit to hang.
        # Example: If partition is lowered to 1, unit 1 begins to upgrade, and partition is set to
        # 2 right away, the unit/Juju agent will hang
        # Details: https://chat.charmhub.io/charmhub/pl/on8rd538ufn4idgod139skkbfr
        # This does not address the situation where another unit > 1 restarts and sets the
        # partition during the `stop` event, but that is unlikely to occur in the small time window
        # that causes the unit to hang.
        if partition_ < self._partition:
            self._partition = partition_
            logger.debug(
                f"Lowered partition to {partition_} {action_event=} {force=} {self.in_progress=}"
            )
        if action_event:
            assert len(units) >= 2
            if self._partition > upgrade.unit_number(units[1]):
                message = "Highest number unit is unhealthy. Upgrade will not resume."
                logger.debug(f"Resume upgrade event failed: {message}")
                action_event.fail(message)
                return
            if force:
                # If a unit was unhealthy and the upgrade was forced, only the next unit will
                # upgrade. As long as 1 or more units are unhealthy, the upgrade will need to be
                # forced for each unit.

                # Include "Attempting to" because (on Kubernetes) we only control the partition,
                # not which units upgrade. Kubernetes may not upgrade a unit even if the partition
                # allows it (e.g. if the charm container of a higher unit is not ready). This is
                # also applicable `if not force`, but is unlikely to happen since all units are
                # healthy `if not force`.
                message = f"Attempting to upgrade unit {self._partition}"
            else:
                message = f"Upgrade resumed. Unit {self._partition} is upgrading next"
            action_event.set_results({"result": message})
            logger.debug(f"Resume upgrade event succeeded: {message}")

    @property
    def authorized(self) -> bool:
        raise Exception("Not supported on Kubernetes")

    def upgrade_unit(self, *, workload_: workload.Workload, tls: bool) -> None:
        raise Exception("Not supported on Kubernetes")


partition = _Partition()
