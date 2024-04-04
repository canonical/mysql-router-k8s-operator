# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest


@pytest.fixture(autouse=True)
def disable_tenacity_retry(monkeypatch):
    for retry_class in (
        "retry_if_exception",
        "retry_if_exception_type",
        "retry_if_not_exception_type",
        "retry_unless_exception_type",
        "retry_if_exception_cause_type",
        "retry_if_result",
        "retry_if_not_result",
        "retry_if_exception_message",
        "retry_if_not_exception_message",
        "retry_any",
        "retry_all",
        "retry_always",
        "retry_never",
    ):
        monkeypatch.setattr(f"tenacity.{retry_class}.__call__", lambda *args, **kwargs: False)


@pytest.fixture(autouse=True)
def patch(monkeypatch):
    monkeypatch.setattr(
        "abstract_charm.MySQLRouterCharm.wait_until_mysql_router_ready",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("workload.AuthenticatedWorkload._router_username", "")
    monkeypatch.setattr("mysql_shell.Shell._run_code", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "mysql_shell.Shell.get_mysql_router_user_for_unit", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("mysql_shell.Shell.is_router_in_cluster_set", lambda *args, **kwargs: True)
    monkeypatch.setattr("upgrade.Upgrade.in_progress", False)
    monkeypatch.setattr("upgrade.Upgrade.versions_set", True)
    monkeypatch.setattr("upgrade.Upgrade.is_compatible", True)


@pytest.fixture(autouse=True)
def kubernetes_patch(monkeypatch):
    monkeypatch.setattr("kubernetes_charm.KubernetesRouterCharm.model_service_domain", "")
    monkeypatch.setattr(
        "rock.Rock._run_command", lambda *args, **kwargs: "null"  # Use "null" for `json.loads()`
    )
    monkeypatch.setattr("rock._Path.read_text", lambda *args, **kwargs: "")
    monkeypatch.setattr("rock._Path.write_text", lambda *args, **kwargs: None)
    monkeypatch.setattr("rock._Path.unlink", lambda *args, **kwargs: None)
    monkeypatch.setattr("rock._Path.mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr("rock._Path.rmtree", lambda *args, **kwargs: None)
    monkeypatch.setattr("lightkube.Client", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "kubernetes_charm.KubernetesRouterCharm._patch_service", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("kubernetes_upgrade._Partition.get", lambda *args, **kwargs: 0)
    monkeypatch.setattr("kubernetes_upgrade._Partition.set", lambda *args, **kwargs: None)


@pytest.fixture(params=[True, False])
def juju_has_secrets(request, monkeypatch):
    monkeypatch.setattr("ops.JujuVersion.has_secrets", request.param)
    return request.param
