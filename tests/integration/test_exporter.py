#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from pathlib import Path

import pytest
import urllib3
import yaml
from pytest_operator.plugin import OpsTest

from .helpers import get_unit_address

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_ROUTER_APP_NAME = "mysql-router-k8s"
APPLICATION_APP_NAME = "mysql-test-app"
GRAFANA_AGENT_APP_NAME = "grafana-agent-k8s"
SLOW_TIMEOUT = 25 * 60


@pytest.mark.group(1)
@pytest.mark.unstable
@pytest.mark.abort_on_fail
async def test_exporter_endpoint(ops_test: OpsTest) -> None:
    """Test that exporter endpoint is functional."""
    http = urllib3.PoolManager()

    # Build and deploy applications
    mysqlrouter_charm = await ops_test.build_charm(".")
    mysqlrouter_resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    logger.info("Deploying all the applications")

    applications = await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            channel="8.0/edge",
            application_name=MYSQL_APP_NAME,
            config={"profile": "testing"},
            series="jammy",
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            mysqlrouter_charm,
            application_name=MYSQL_ROUTER_APP_NAME,
            series="jammy",
            resources=mysqlrouter_resources,
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            APPLICATION_APP_NAME,
            channel="latest/edge",
            application_name=APPLICATION_APP_NAME,
            series="jammy",
            num_units=1,
        ),
        ops_test.model.deploy(
            GRAFANA_AGENT_APP_NAME,
            application_name=GRAFANA_AGENT_APP_NAME,
            num_units=1,
            series="jammy",
            channel="latest/stable",
        ),
    )

    [mysql_app, mysqlrouter_app, application_app, grafana_agent_app] = applications

    async with ops_test.fast_forward("60s"):
        logger.info("Waiting for mysqlrouter to be in BlockedStatus")
        await ops_test.model.block_until(
            lambda: ops_test.model.applications[MYSQL_ROUTER_APP_NAME].status == "blocked",
            timeout=SLOW_TIMEOUT,
        )

        logger.info("Relating mysql, mysqlrouter and application")
        await ops_test.model.relate(
            f"{MYSQL_ROUTER_APP_NAME}:backend-database", f"{MYSQL_APP_NAME}:database"
        )
        await ops_test.model.relate(
            f"{APPLICATION_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:database"
        )

        await ops_test.model.wait_for_idle(
            apps=[MYSQL_ROUTER_APP_NAME], status="active", timeout=SLOW_TIMEOUT
        )

        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME, MYSQL_ROUTER_APP_NAME, APPLICATION_APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=SLOW_TIMEOUT,
        )

    unit = mysqlrouter_app.units[0]
    unit_address = await get_unit_address(ops_test, unit.name)

    try:
        http.request("GET", f"http://{unit_address}:49152/metrics")
    except urllib3.exceptions.MaxRetryError as e:
        assert (
            "[Errno 111] Connection refused" in e.reason.args[0]
        ), "❌ expected connection refused error"
    else:
        assert False, "❌ can connect to metrics endpoint without relation with cos"

    logger.info("Relating mysqlrouter with grafana agent")
    await ops_test.model.relate(
        f"{GRAFANA_AGENT_APP_NAME}:grafana-dashboards-consumer",
        f"{MYSQL_ROUTER_APP_NAME}:grafana-dashboard",
    )
    await ops_test.model.relate(
        f"{GRAFANA_AGENT_APP_NAME}:logging-provider", f"{MYSQL_ROUTER_APP_NAME}:logging"
    )
    await ops_test.model.relate(
        f"{GRAFANA_AGENT_APP_NAME}:metrics-endpoint", f"{MYSQL_ROUTER_APP_NAME}:metrics-endpoint"
    )

    time.sleep(30)

    jmx_resp = http.request("GET", f"http://{unit_address}:49152/metrics")
    assert jmx_resp.status == 200, "❌ cannot connect to metrics endpoint with relation with cos"
    assert "mysqlrouter_route_health" in str(
        jmx_resp.data
    ), "❌ did not find expected metric in response"

    logger.info("Removing relation between mysqlrouter and grafana agent")
    await mysqlrouter_app.remove_relation(
        f"{GRAFANA_AGENT_APP_NAME}:metrics-endpoint", f"{MYSQL_ROUTER_APP_NAME}:metrics-endpoint"
    )

    time.sleep(30)

    try:
        http.request("GET", f"http://{unit_address}:49152/metrics")
    except urllib3.exceptions.MaxRetryError as e:
        assert (
            "[Errno 111] Connection refused" in e.reason.args[0]
        ), "❌ expected connection refused error"
    else:
        assert False, "❌ can connect to metrics endpoint without relation with cos"
