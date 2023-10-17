# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In-place upgrades on Kubernetes

Implements specification: DA058 - In-Place Upgrades - Kubernetes v2
(https://docs.google.com/document/d/1tLjknwHudjcHs42nzPVBNkHs98XxAOT2BXGGpP7NyEU/)
"""

import functools
import logging

import lightkube
import lightkube.core.exceptions
import lightkube.models.apps_v1
import lightkube.resources.apps_v1
import lightkube.resources.core_v1
import ops

import upgrade

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

    @property
    def _unit_active_status(self) -> ops.ActiveStatus:
        # During a rollback, non-upgraded units will restart
        # (Juju bug: https://bugs.launchpad.net/juju/+bug/2036246)
        # To explain this behavior to the user, we include the controller revision hash in the
        # status message. For non-upgraded units: the charm version will be the same, but since the
        # revision hash is different, the unit (pod) will restart during rollback.

        # Example: mysql-router-k8s-6c67d5f56c
        revision_hash = self._unit_workload_versions[self._unit.name]
        # Example: 6c67d5f56c
        revision_hash = revision_hash.removeprefix(f"{self._app_name}-")
        return ops.ActiveStatus(f'{self._current_versions["charm"]} {revision_hash}')

    @property
    def _partition(self) -> int:
        return partition.get(app_name=self._app_name)

    @_partition.setter
    def _partition(self, value: int) -> None:
        partition.set(app_name=self._app_name, value=value)

    @functools.cached_property  # Cache lightkube API call for duration of charm execution
    def _unit_workload_versions(self) -> dict[str, str]:
        """{Unit name: Kubernetes controller revision hash}

        Even if the workload version is the same, the workload will restart if the controller
        revision hash changes. (Juju bug: https://bugs.launchpad.net/juju/+bug/2036246).

        Therefore, we must use the revision hash instead of the workload version. (To satisfy the
        requirement that if and only if this version changes, the workload will restart.)
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
    def _app_workload_version(self) -> str:
        """App's Kubernetes controller revision hash"""
        stateful_set = lightkube.Client().get(
            res=lightkube.resources.apps_v1.StatefulSet, name=self._app_name
        )
        return stateful_set.status.updateRevision


partition = _Partition()
