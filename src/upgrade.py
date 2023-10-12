# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In-place upgrades

Based off specification: DA058 - In-Place Upgrades - Kubernetes v2
(https://docs.google.com/document/d/1tLjknwHudjcHs42nzPVBNkHs98XxAOT2BXGGpP7NyEU/)
"""

import abc
import json
import logging
import pathlib
import typing

import ops
import poetry.core.constraints.version as poetry_version

logger = logging.getLogger(__name__)

PEER_RELATION_ENDPOINT_NAME = "upgrade-version-a"
RESUME_ACTION_NAME = "resume-upgrade"


def _unit_number(unit_: ops.Unit) -> int:
    return int(unit_.name.split("/")[-1])


class PeerRelationNotReady(Exception):
    """Upgrade peer relation not available (to this unit)"""


class Upgrade(abc.ABC):
    """In-place upgrades"""

    def __init__(self, charm_: ops.CharmBase) -> None:
        relations = charm_.model.relations[PEER_RELATION_ENDPOINT_NAME]
        if not relations:
            raise PeerRelationNotReady
        assert len(relations) == 1
        self._peer_relation = relations[0]
        self._unit: ops.Unit = charm_.unit
        self._unit_databag = self._peer_relation.data[self._unit]
        self._unit_name = self._unit.name
        self._app_databag = self._peer_relation.data[charm_.app]
        self._app_name = charm_.app.name
        self._current_versions = {}  # For this unit
        for version, file_name in {
            "charm": "charm_version",
            "workload": "workload_version",
        }.items():
            self._current_versions[version] = pathlib.Path(file_name).read_text().strip()

    @property
    def unit_state(self) -> typing.Optional[str]:
        """Unit upgrade state"""
        return self._unit_databag.get("state")

    @unit_state.setter
    def unit_state(self, value: str) -> None:
        self._unit_databag["state"] = value

    @property
    def is_compatible(self) -> bool:
        """Whether upgrade is supported from previous versions"""
        try:
            previous_version_strs: dict[str, str] = json.loads(self._app_databag["versions"])
        except KeyError as exception:
            logger.debug("`versions` missing from peer relation", exc_info=exception)
            return False
        previous_versions: dict[str, poetry_version.Version] = {
            key: poetry_version.Version.parse(value)
            for key, value in previous_version_strs.items()
        }
        current_versions = {
            key: poetry_version.Version.parse(value)
            for key, value in self._current_versions.items()
        }
        try:
            if (
                previous_versions["charm"] > current_versions["charm"]
                or previous_versions["charm"].major != current_versions["charm"].major
            ):
                logger.debug(
                    f'{previous_versions["charm"]=} incompatible with {current_versions["charm"]=}'
                )
                return False
            if (
                previous_versions["workload"] > current_versions["workload"]
                or previous_versions["workload"].major != current_versions["workload"].major
                or previous_versions["workload"].minor != current_versions["workload"].minor
            ):
                logger.debug(
                    f'{previous_versions["workload"]=} incompatible with {current_versions["workload"]=}'
                )
                return False
            logger.debug(
                f"Versions before upgrade compatible with versions after upgrade {previous_version_strs=} {self._current_versions=}"
            )
            return True
        except KeyError as exception:
            logger.debug(f"Version missing from {previous_versions=}", exc_info=exception)
            return False

    @property
    @abc.abstractmethod
    def in_progress(self) -> bool:
        pass

    @property
    def _sorted_units(self) -> list[ops.Unit]:
        """Units sorted from highest to lowest unit number"""
        return sorted((self._unit, *self._peer_relation.units), key=_unit_number, reverse=True)

    @property
    @abc.abstractmethod
    def _unit_active_status(self) -> ops.ActiveStatus:
        """Status shown during upgrade if unit is healthy"""

    @property
    def unit_juju_status(self) -> typing.Optional[ops.StatusBase]:
        if self.in_progress:
            return self._unit_active_status

    @property
    def app_status(self) -> typing.Optional[ops.StatusBase]:
        if self.in_progress:
            if len(self._sorted_units) >= 2 and self._partition > _unit_number(self._sorted_units[1]):
                # User confirmation needed to resume upgrade (i.e. upgrade second unit)
                return ops.BlockedStatus(
                    f"Upgrading. Check that highest number unit is healthy and run `juju run {self._app_name}/leader {RESUME_ACTION_NAME}`. To rollback, `juju refresh` to the previous revision"
                )
            else:
                return ops.MaintenanceStatus(
                    "Upgrading. To rollback, `juju refresh` to the previous revision"
                )

    def set_versions_in_app_databag(self) -> None:
        """Save current versions in app databag

        Used after next upgrade to check compatibility (i.e. whether that upgrade should be
        allowed)
        """
        assert not self.in_progress
        logger.debug(f"Setting {self._current_versions=} in upgrade peer relation app databag")
        self._app_databag["versions"] = json.dumps(self._current_versions)
        logger.debug(f"Set {self._current_versions=} in upgrade peer relation app databag")

    @property
    @abc.abstractmethod
    def _partition(self) -> int:
        """Specifies which units should upgrade

        Unit numbers >= partition should upgrade
        Unit numbers < partition should not upgrade

        Based on Kubernetes StatefulSet partition
        (https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#partitions)

        For Kubernetes, unit numbers are guaranteed to be sequential
        For machines, unit numbers are not guaranteed to be sequential
        """

    @_partition.setter
    @abc.abstractmethod
    def _partition(self, value: int) -> None:
        pass

    @abc.abstractmethod
    def _get_unit_workload_version(self, unit: ops.Unit):
        """Get unique identifier for a unit's workload version.

        If and only if this version changes, the workload will restart (during upgrade or
        rollback).

        On Kubernetes, the workload & charm are upgraded together
        On machines, the charm is upgraded before the workload

        This identifier should be comparable to `_app_workload_version` to determine if the unit &
        app are the same workload version.
        """
        if not self._app_name == unit.name.split("/")[0]:
            raise ValueError(f"{unit=} must belong to {self._app_name=}")

    @property
    @abc.abstractmethod
    def _app_workload_version(self):
        """Unique identifier for the app's workload version

        This should match the workload version in the current Juju app charm version.

        This identifier should be comparable to `_get_unit_workload_version` to determine if the
        app & unit are the same workload version.
        """

    def reconcile_partition(self, *, action_event: ops.ActionEvent = None) -> None:
        """If ready, set partition to upgrade next unit.

        Automatically upgrades next unit if all upgraded units are healthy—except if only one unit
        has upgraded (need manual user confirmation [via Juju action] to upgrade next unit)

        Handle Juju action to:
        - confirm first upgraded unit is healthy and resume upgrade
        - force upgrade of next unit if 1 or more upgraded units are unhealthy
        """
        force = action_event and action_event.params.get("force") is True

        units = self._sorted_units

        def determine_partition() -> int:
            for upgrade_order_index, unit in enumerate(units):
                # Note: upgrade_order_index != unit number
                if (
                    force is False and self._peer_relation.data[unit].get("state") != "healthy"
                ) or self._get_unit_workload_version(unit) != self._app_workload_version:
                    if not action_event and upgrade_order_index == 1:
                        # User confirmation needed to resume upgrade (i.e. upgrade second unit)
                        return _unit_number(units[0])
                    return _unit_number(unit)
            return _unit_number(units[-1])  # Lowest unit number

        partition = determine_partition()
        self._partition = partition
        logger.debug(f"Reconcile partition: set to {partition} {action_event=} {force=}")
        if action_event:
            assert len(units) >= 2
            if partition > _unit_number(units[1]):
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
                # allows it (e.g. if the charm container of a higher unit is not ready). We will
                # reset the partition if another event runs on the leader unit (and the action must
                # be run again). This is also applicable `if not force`, but is unlikely to happen
                # since all units are "healthy" `if not force`.
                message = f"Attempting to upgrade unit {partition}"
            else:
                message = f"Upgrade resumed. Unit {partition} is upgrading next"
            action_event.set_results({"result": message})
            logger.debug(f"Resume upgrade event succeeded: {message}")
