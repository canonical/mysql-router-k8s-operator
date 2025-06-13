#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from pathlib import Path

import pytest
import tenacity
import yaml
from pytest_operator.plugin import OpsTest

from . import architecture, juju_
from .helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    MYSQL_DEFAULT_APP_NAME,
    MYSQL_ROUTER_DEFAULT_APP_NAME,
    get_credentials,
    is_connection_possible,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = MYSQL_DEFAULT_APP_NAME
MYSQL_ROUTER_APP_NAME = MYSQL_ROUTER_DEFAULT_APP_NAME
APPLICATION_APP_NAME = APPLICATION_DEFAULT_APP_NAME
DATA_INTEGRATOR = "data-integrator"
SLOW_TIMEOUT = 15 * 60
MODEL_CONFIG = {"logging-config": "<root>=INFO;unit=DEBUG"}
TEST_DATABASE_NAME = "testdatabase"

TLS_SETUP_SLEEP_TIME = 30
if juju_.is_3_or_higher:
    TLS_APP_NAME = "self-signed-certificates"
    if architecture.architecture == "arm64":
        TLS_CHANNEL = "latest/edge"
    else:
        TLS_CHANNEL = "latest/stable"
    TLS_CONFIG = {"ca-common-name": "Test CA"}
else:
    TLS_APP_NAME = "tls-certificates-operator"
    if architecture.architecture == "arm64":
        TLS_CHANNEL = "legacy/edge"
    else:
        TLS_CHANNEL = "legacy/stable"
    TLS_CONFIG = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}


async def confirm_cluster_ip_endpoints(ops_test: OpsTest) -> None:
    """Helper function to test the cluster ip endpoints"""
    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(SLOW_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            data_integrator_unit = ops_test.model.applications[DATA_INTEGRATOR].units[0]
            credentials = await get_credentials(data_integrator_unit)

    assert credentials["mysql"]["database"] == TEST_DATABASE_NAME, "Database is empty"
    assert credentials["mysql"]["username"] is not None, "Username is empty"
    assert credentials["mysql"]["password"] is not None, "Password is empty"

    endpoint_name = f"mysql-router-k8s-service.{ops_test.model.name}.svc.cluster.local."
    assert credentials["mysql"]["endpoints"] == f"{endpoint_name}:6446", "Endpoint is unexpected"
    assert (
        credentials["mysql"]["read-only-endpoints"] == f"{endpoint_name}:6447"
    ), "Read-only endpoint is unexpected"


async def confirm_endpoint_connectivity(ops_test: OpsTest) -> None:
    """Helper to confirm endpoint connectivity"""
    for attempt in tenacity.Retrying(
        reraise=True,
        stop=tenacity.stop_after_delay(SLOW_TIMEOUT),
        wait=tenacity.wait_fixed(10),
    ):
        with attempt:
            data_integrator_unit = ops_test.model.applications[DATA_INTEGRATOR].units[0]
            credentials = await get_credentials(data_integrator_unit)
            assert credentials["mysql"]["endpoints"] is not None, "Endpoints missing"

            connection_config = {
                "username": credentials["mysql"]["username"],
                "password": credentials["mysql"]["password"],
                "host": credentials["mysql"]["endpoints"].split(",")[0].split(":")[0],
            }

            extra_connection_options = {
                "port": credentials["mysql"]["endpoints"].split(":")[1],
                "ssl_disabled": False,
            }

            assert is_connection_possible(
                connection_config, **extra_connection_options
            ), "Connection not possible through endpoints"


@pytest.mark.abort_on_fail
async def test_expose_external(ops_test, charm) -> None:
    """Test the expose-external config option."""
    await ops_test.model.set_config(MODEL_CONFIG)

    mysql_router_resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    logger.info("Deploying mysql-k8s, mysql-router-k8s and data-integrator")
    await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            channel="8.0/edge",
            application_name=MYSQL_APP_NAME,
            config={"profile": "testing"},
            base="ubuntu@22.04",
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            charm,
            application_name=MYSQL_ROUTER_APP_NAME,
            base="ubuntu@22.04",
            resources=mysql_router_resources,
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            DATA_INTEGRATOR,
            channel="latest/edge",
            application_name=DATA_INTEGRATOR,
            base="ubuntu@24.04",
            config={"database-name": TEST_DATABASE_NAME},
            num_units=1,
        ),
    )

    logger.info("Relating mysql-k8s, mysql-router-k8s and data-integrator")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.relate(
            f"{MYSQL_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:backend-database"
        )
        await ops_test.model.relate(
            f"{MYSQL_ROUTER_APP_NAME}:database", f"{DATA_INTEGRATOR}:mysql"
        )

        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME, MYSQL_ROUTER_APP_NAME, DATA_INTEGRATOR],
            status="active",
            timeout=SLOW_TIMEOUT,
        )

        logger.info("Testing endpoint when expose-external=false (default)")
        await confirm_cluster_ip_endpoints(ops_test)

        logger.info("Testing endpoint when expose-external=nodeport")
        mysql_router_application = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]

        await mysql_router_application.set_config({"expose-external": "nodeport"})
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_ROUTER_APP_NAME],
            status="active",
            timeout=SLOW_TIMEOUT,
        )

        await confirm_endpoint_connectivity(ops_test)

        logger.info("Testing endpoint when expose-external=loadbalancer")
        await mysql_router_application.set_config({"expose-external": "loadbalancer"})
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_ROUTER_APP_NAME],
            status="active",
            timeout=SLOW_TIMEOUT,
        )

        await confirm_endpoint_connectivity(ops_test)


@pytest.mark.abort_on_fail
async def test_expose_external_with_tls(ops_test: OpsTest) -> None:
    """Test endpoints when mysql-router-k8s is related to a TLS operator."""
    mysql_router_application = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]

    logger.info("Resetting expose-external=false")
    await mysql_router_application.set_config({"expose-external": "false"})
    await ops_test.model.wait_for_idle(
        apps=[MYSQL_ROUTER_APP_NAME],
        status="active",
        timeout=SLOW_TIMEOUT,
    )

    logger.info("Deploying TLS operator")
    await ops_test.model.deploy(
        TLS_APP_NAME,
        channel=TLS_CHANNEL,
        config=TLS_CONFIG,
        base="ubuntu@22.04",
    )
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[TLS_APP_NAME],
            status="active",
            timeout=SLOW_TIMEOUT,
        )

        logger.info("Relate mysql-router-k8s with TLS operator")
        await ops_test.model.relate(MYSQL_ROUTER_APP_NAME, TLS_APP_NAME)

        time.sleep(TLS_SETUP_SLEEP_TIME)

        logger.info("Testing endpoint when expose-external=false(default)")
        await confirm_cluster_ip_endpoints(ops_test)

        logger.info("Testing endpoint when expose-external=nodeport")
        await mysql_router_application.set_config({"expose-external": "nodeport"})
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_ROUTER_APP_NAME],
            status="active",
            timeout=SLOW_TIMEOUT,
        )

        await confirm_endpoint_connectivity(ops_test)

        logger.info("Testing endpoint when expose-external=loadbalancer")
        await mysql_router_application.set_config({"expose-external": "loadbalancer"})
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_ROUTER_APP_NAME],
            status="active",
            timeout=SLOW_TIMEOUT,
        )

        await confirm_endpoint_connectivity(ops_test)
