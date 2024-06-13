#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import requests
import tenacity
import yaml
from pytest_operator.plugin import OpsTest

from . import juju_
from .helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    MYSQL_DEFAULT_APP_NAME,
    MYSQL_ROUTER_DEFAULT_APP_NAME,
    get_tls_certificate_issuer,
    get_unit_address,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = MYSQL_DEFAULT_APP_NAME
MYSQL_ROUTER_APP_NAME = MYSQL_ROUTER_DEFAULT_APP_NAME
APPLICATION_APP_NAME = APPLICATION_DEFAULT_APP_NAME
GRAFANA_AGENT_APP_NAME = "grafana-agent-k8s"
SLOW_TIMEOUT = 25 * 60
RETRY_TIMEOUT = 3 * 60

if juju_.is_3_or_higher:
    TLS_APP_NAME = "self-signed-certificates"
    TLS_CONFIG = {"ca-common-name": "Test CA"}
else:
    TLS_APP_NAME = "tls-certificates-operator"
    TLS_CONFIG = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_exporter_endpoint(ops_test: OpsTest) -> None:
    """Test that exporter endpoint is functional."""
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
        requests.get(f"http://{unit_address}:49152/metrics", stream=False)
    except requests.exceptions.ConnectionError as e:
        assert "[Errno 111] Connection refused" in str(e), "❌ expected connection refused error"
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

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(RETRY_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            response = requests.get(f"http://{unit_address}:49152/metrics", stream=False)
            assert (
                response.status_code == 200
            ), "❌ cannot connect to metrics endpoint with relation with cos"
            assert "mysqlrouter_route_health" in str(
                response.text
            ), "❌ did not find expected metric in response"

    logger.info("Removing relation between mysqlrouter and grafana agent")
    await mysqlrouter_app.remove_relation(
        f"{GRAFANA_AGENT_APP_NAME}:metrics-endpoint", f"{MYSQL_ROUTER_APP_NAME}:metrics-endpoint"
    )

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(RETRY_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            try:
                requests.get(f"http://{unit_address}:49152/metrics", stream=False)
            except requests.exceptions.ConnectionError as e:
                assert "[Errno 111] Connection refused" in str(
                    e
                ), "❌ expected connection refused error"
            else:
                assert False, "❌ can connect to metrics endpoint without relation with cos"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_exporter_endpoint_with_tls(ops_test: OpsTest) -> None:
    """Test that the exporter endpoint works when related with TLS"""
    mysql_router_app = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]
    mysql_router_unit = mysql_router_app.units[0]

    issuer = await get_tls_certificate_issuer(
        ops_test,
        mysql_router_unit.name,
        host="127.0.0.1",
        port=6446,
    )
    assert (
        "Issuer: CN = MySQL_Router_Auto_Generated_CA_Certificate" in issuer
    ), "Expected mysqlrouter autogenerated certificate"

    logger.info(f"Deploying {TLS_APP_NAME}")
    await ops_test.model.deploy(
        TLS_APP_NAME,
        application_name=TLS_APP_NAME,
        channel="stable",
        config=TLS_CONFIG,
        series="jammy",
    )

    await ops_test.model.wait_for_idle([TLS_APP_NAME], status="active", timeout=SLOW_TIMEOUT)

    logger.info(f"Relating mysqlrouter with {TLS_APP_NAME}")

    await ops_test.model.relate(
        f"{MYSQL_ROUTER_APP_NAME}:certificates", f"{TLS_APP_NAME}:certificates"
    )

    unit_address = await get_unit_address(ops_test, mysql_router_app.units[0].name)

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(RETRY_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            try:
                requests.get(f"http://{unit_address}:49152/metrics", stream=False)
            except requests.exceptions.ConnectionError as e:
                assert "[Errno 111] Connection refused" in str(
                    e
                ), "❌ expected connection refused error"
            else:
                assert False, "❌ can connect to metrics endpoint without relation with cos"

    logger.info("Relating mysqlrouter with grafana agent")
    await ops_test.model.relate(
        f"{GRAFANA_AGENT_APP_NAME}:metrics-endpoint", f"{MYSQL_ROUTER_APP_NAME}:metrics-endpoint"
    )

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(RETRY_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            response = requests.get(f"http://{unit_address}:49152/metrics", stream=False)
            assert (
                response.status_code == 200
            ), "❌ cannot connect to metrics endpoint with relation with cos"
            assert "mysqlrouter_route_health" in str(
                response.text
            ), "❌ did not find expected metric in response"

    issuer = await get_tls_certificate_issuer(
        ops_test,
        mysql_router_unit.name,
        host="127.0.0.1",
        port=6446,
    )
    assert "CN = Test CA" in issuer, f"Expected mysqlrouter certificate from {TLS_APP_NAME}"

    logger.info("Removing relation between mysqlrouter and grafana agent")
    await mysql_router_app.remove_relation(
        f"{GRAFANA_AGENT_APP_NAME}:metrics-endpoint", f"{MYSQL_ROUTER_APP_NAME}:metrics-endpoint"
    )

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(RETRY_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            try:
                requests.get(f"http://{unit_address}:49152/metrics", stream=False)
            except requests.exceptions.ConnectionError as e:
                assert "[Errno 111] Connection refused" in str(
                    e
                ), "❌ expected connection refused error"
            else:
                assert False, "❌ can connect to metrics endpoint without relation with cos"

    logger.info(f"Removing relation between mysqlrouter and {TLS_APP_NAME}")
    await mysql_router_app.remove_relation(
        f"{MYSQL_ROUTER_APP_NAME}:certificates", f"{TLS_APP_NAME}:certificates"
    )

    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(RETRY_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            issuer = await get_tls_certificate_issuer(
                ops_test,
                mysql_router_unit.name,
                host="127.0.0.1",
                port=6446,
            )
            assert (
                "Issuer: CN = MySQL_Router_Auto_Generated_CA_Certificate" in issuer
            ), "Expected mysqlrouter autogenerated certificate"
