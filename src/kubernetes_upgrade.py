# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In-place upgrades on Kubernetes

Implements specification: DA058 - In-Place Upgrades - Kubernetes v2
(https://docs.google.com/document/d/1tLjknwHudjcHs42nzPVBNkHs98XxAOT2BXGGpP7NyEU/)
"""

import functools
import logging

import lightkube
import lightkube.models.apps_v1
import lightkube.resources.apps_v1
import lightkube.resources.core_v1
import ops

import upgrade

logger = logging.getLogger(__name__)


class StatefulSet:
    """Juju app StatefulSet"""

    def __init__(self, app_name: str):
        self._app_name = app_name
        self._client = lightkube.Client()

    @property
    def partition(self) -> int:
        stateful_set = self._client.get(
            res=lightkube.resources.apps_v1.StatefulSet, name=self._app_name
        )
        return stateful_set.spec.updateStrategy.rollingUpdate.partition

    @partition.setter
    def partition(self, value: int) -> None:
        self._client.patch(
            res=lightkube.resources.apps_v1.StatefulSet,
            name=self._app_name,
            obj={"spec": {"updateStrategy": {"rollingUpdate": {"partition": value}}}},
        )


class Upgrade(upgrade.Upgrade):
    """In-place upgrades on Kubernetes"""

    @functools.cached_property
    # Cache result (so that it's consistent) for duration of Juju hook execution
    def in_progress(self) -> bool:
        stateful_set_revision = self._app_workload_version
        # TODO: move caching to a lightkube wrapper so this function can be defined in base class
        client = lightkube.Client()
        pods = client.list(
            res=lightkube.resources.core_v1.Pod, labels={"app.kubernetes.io/name": self._app_name}
        )
        pod_revisions = [pod.metadata.labels["controller-revision-hash"] for pod in pods]
        logger.debug(f"{stateful_set_revision=} {pod_revisions=}")
        return any(revision != stateful_set_revision for revision in pod_revisions)

    @property
    def _unit_active_status(self) -> ops.ActiveStatus:
        # During a rollback, non-upgraded units will restart
        # (Juju bug: https://bugs.launchpad.net/juju/+bug/2036246)
        # To explain this behavior to the user, we include the controller revision hash in the
        # status message. For non-upgraded units: the charm version will be the same, but since the
        # revision hash is different, the unit (pod) will restart during rollback.

        # Example: mysql-router-k8s-6c67d5f56c
        revision_hash = self._get_unit_workload_version(self._unit)
        # Example: 6c67d5f56c
        revision_hash = revision_hash.removeprefix(f"{self._app_name}-")
        return ops.ActiveStatus(f'{self._current_versions["charm"]} {revision_hash}')

    @upgrade.Upgrade._partition.setter
    def _partition(self, value: int) -> None:
        StatefulSet(self._app_name).partition = value

    def _get_unit_workload_version(self, unit: ops.Unit) -> str:
        """Get a unit's Kubernetes controller revision hash.

        Even if the workload version is the same, the workload will restart if the controller
        revision hash changes. (Juju bug: https://bugs.launchpad.net/juju/+bug/2036246).

        Therefore, we must use the revision hash instead of the workload version. (To satisfy the
        requirement that if and only if this version changes, the workload will restart.)
        """
        super()._get_unit_workload_version(unit)
        client = lightkube.Client()
        pod = client.get(res=lightkube.resources.core_v1.Pod, name=unit.name.replace("/", "-"))
        return pod.metadata.labels["controller-revision-hash"]

    @property
    def _app_workload_version(self) -> str:
        """App's Kubernetes controller revision hash"""
        client = lightkube.Client()
        stateful_set = client.get(res=lightkube.resources.apps_v1.StatefulSet, name=self._app_name)
        return stateful_set.status.updateRevision
