# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Migrate from refresh v2 charm with downtime"""

import datetime
import logging
import time

import charm_ as charm
import charm_json
import lightkube
import lightkube.core.exceptions
import lightkube.models.authorization_v1
import lightkube.resources.apps_v1
import lightkube.resources.authorization_v1
import lightkube.resources.core_v1

logger = logging.getLogger(__name__)


# Derived from https://github.com/canonical/charm-refresh/blob/b6044ea4782ff43fdf0bc91ead088942b6054107/charm_refresh/_main.py#L536-L560
class _KubernetesUnit(charm.Unit):
    def __new__(cls, name: str, /, *, controller_revision: str, pod_uid: str, pod_name: str):
        instance: _KubernetesUnit = super().__new__(cls, name)
        instance.controller_revision = controller_revision
        instance.pod_uid = pod_uid
        instance.pod_name = pod_name
        return instance

    def __repr__(self):
        return (
            f"{type(self).__name__}({repr(str(self))}, "
            f"controller_revision={repr(self.controller_revision)}, pod_uid={repr(self.pod_uid)}, "
            f"pod_name={repr(self.pod_name)})"
        )

    @classmethod
    def from_pod(cls, pod: lightkube.resources.core_v1.Pod, /):
        # Example: "mysql-k8s-0"
        pod_name = pod.metadata.name
        app_name, unit_number = pod_name.rsplit("-", maxsplit=1)
        # Example: "mysql-k8s/0"
        unit_name = f"{app_name}/{unit_number}"
        return cls(
            unit_name,
            controller_revision=pod.metadata.labels["controller-revision-hash"],
            pod_uid=pod.metadata.uid,
            pod_name=pod_name,
        )


def main():  # noqa: C901
    """Migrate from refresh v2 charm with downtime

    Emergency response to https://github.com/canonical/mysql-router-operators/issues/100

    We made a mistake and released https://github.com/canonical/mysql-router-k8s-operator/pull/411
    to stable without a migration or coordinating with users.

    Now, we have stable releases with refresh v2 and refresh v3. We cannot revert PR#411 since some
    users have already refreshed to v3 (and ran into issue #100).

    To enable users on refresh v2 to refresh without the charm breaking, we added this migration.

    This migration must stay in all future versions of the charm on this track (8.0) so that users
    on refresh v2 can always refresh—users choose when to refresh, and when they refresh we cannot
    require them to refresh to a specific revision (in most cases [i.e. by default] they will
    refresh to the latest revision in the 8.0/stable track).

    High-level design (after `juju refresh` from charm with refresh v2):
    - Hold execution on all units
    - Force all units' pods to be immediately updated to latest StatefulSet ControllerRevision
      (i.e. units are refreshed all at once instead of one at a time)
    - Resume execution after all pods are updated; refresh v3 detects this as initial install case
      and recovers

    This involves downtime (all units are offline while execution is held). In the best case, this
    only lasts a few seconds.

    Also, this migration does not support pausing, rollback to v2, or downgrade to v2.

    This function:
    1. If (initial install and (peer relation missing or Juju app deployed without `--trust`)) or
       (teardown and peer relation missing), `return`.
    2. Checks if the migration has already completed. If it has, `return`.
    3. Checks if a refresh is in progress. If it is not, `return`.
    4. Holds execution in an infinite loop until a refresh is no longer in progress:
        - Get highest unit that has an outdated StatefulSet ControllerRevision
        - Set StatefulSet partition to 0 and delete that unit
        - Sleep

    After this function first returns—except if it returns during #1—a refresh will not be in
    progress (since all units have an up-to-date StatefulSet ControllerRevision). Refresh v3 will
    run, detect this as the initial installation case (instead of as a refresh), and will set the
    versions in its app databag. The versions being set in the app databag is used to track
    completion of the migration.
    """
    refresh_v3_peer_relation = charm_json.PeerRelation.from_endpoint("refresh-v-three")
    if not refresh_v3_peer_relation:
        # Initial install
        # Or teardown: https://github.com/juju/juju/issues/20713
        return
    if refresh_v3_peer_relation.my_app_ro.get("original_charm_version") is not None:
        # Migration already completed
        return

    # Derived from https://github.com/canonical/charm-refresh/blob/b6044ea4782ff43fdf0bc91ead088942b6054107/charm_refresh/_main.py#L1367-L1386
    # Check if Juju app was deployed with `--trust` (needed to call Kubernetes API)
    if not (
        lightkube.Client()
        .create(
            lightkube.resources.authorization_v1.SelfSubjectAccessReview(
                spec=lightkube.models.authorization_v1.SelfSubjectAccessReviewSpec(
                    resourceAttributes=lightkube.models.authorization_v1.ResourceAttributes(
                        name=charm.app,
                        namespace=charm.model,
                        resource="statefulset",
                        verb="patch",
                    )
                )
            )
        )
        .status.allowed
    ):
        logger.warning(
            f"Run `juju trust {charm.app} --scope=cluster`. Needed for in-place refreshes"
        )
        # Refresh v3 will set app status & raise exception so that charm.py
        # `self._reconcile_allowed` is set to `False`
        return

    last_in_progress_log = None
    while True:
        app_controller_revision: str = (
            lightkube.Client()
            .get(lightkube.resources.apps_v1.StatefulSet, charm.app)
            .status.updateRevision
        )
        assert app_controller_revision is not None

        # Sorted from highest to lowest unit number
        units = sorted(
            (
                _KubernetesUnit.from_pod(pod)
                for pod in lightkube.Client().list(
                    lightkube.resources.core_v1.Pod, labels={"app.kubernetes.io/name": charm.app}
                )
            ),
            reverse=True,
        )
        highest_outdated_unit = next(
            (unit for unit in units if unit.controller_revision != app_controller_revision), None
        )
        if highest_outdated_unit is None:
            # Refresh not in progress
            return

        if last_in_progress_log is None or time.time() - last_in_progress_log > 60:
            logger.info(
                "Refresh migration in progress. All units will restart. Ignore app status and do "
                "not run any action. Do not run `juju refresh`. If this application is stuck and "
                "has repeatedly logged this message for longer than 15 minutes, please contact "
                "the developers of this charm for support."
            )
            last_in_progress_log = time.time()
        charm.unit_status = charm.MaintenanceStatus(
            "Migration in progress. Ignore app status, do not run actions, do not run `juju "
            "refresh`. If stuck >15 min, contact us"
        )
        if charm.is_leader:
            charm.app_status = charm.MaintenanceStatus(
                "Migration in progress. Do not run actions and do not run `juju refresh`. If "
                "stuck >15 min, contact charm developers"
            )

        if charm.unit != units[0]:
            # This is not the highest unit number. Give the highest unit number 5 minutes to handle
            # the migration itself (happy path) to avoid deleting already-updated pods. (There's a
            # potential race between API call to list pods on unit A, unit B deleting a pod, and
            # then unit A deleting the same pod. Theoretically the charm should be able to handle
            # this without issues, but avoid this in happy path to reduce risk.)
            last_refresh_time: datetime.datetime = (
                lightkube.Client()
                .get(lightkube.resources.apps_v1.ControllerRevision, app_controller_revision)
                .metadata.creationTimestamp
            )
            assert last_refresh_time is not None

            if datetime.datetime.now(
                tz=datetime.timezone.utc
            ) - last_refresh_time < datetime.timedelta(minutes=5):
                logger.debug("Waiting up to 5 minutes for highest unit number to handle migration")
                time.sleep(10)
                continue

        lightkube.Client().patch(
            lightkube.resources.apps_v1.StatefulSet,
            charm.app,
            {"spec": {"updateStrategy": {"rollingUpdate": {"partition": 0}}}},
        )
        logger.info(f"Set partition to 0. Deleting pod {highest_outdated_unit.pod_name}")
        try:
            # Setting the partition to 0 is not enough to refresh all units.
            # See https://canonical-charm-refresh.readthedocs-hosted.com/latest/juju-refresh/#kubernetes
            # > After every restart of the charm container, the Juju agent will fail the pebble
            # > health check until after the unit successfully executes the start event.
            # Since we are holding execution, units will not successfully execute the start event
            # and thus will not succeed the Kubernetes readiness probe* and allow the next pod to
            # be refreshed. Instead of succeeding the readiness probe, delete the outdated pods so
            # that they are re-created on the up-to-date StatefulSet ControllerRevision.
            #
            # * There is a race condition where pods will temporarily succeed the Kubernetes
            #   readiness probe (see
            #   https://canonical-charm-refresh.readthedocs-hosted.com/latest/juju-refresh/#kubernetes),
            #   but we cannot rely on this.
            lightkube.Client().delete(
                lightkube.resources.core_v1.Pod, highest_outdated_unit.pod_name
            )
        except lightkube.core.exceptions.ApiError as exception:
            if exception.status.code == 404:
                # Pod not found
                # Expected to occur if pod already deleted
                pass
            else:
                raise
        time.sleep(3)
