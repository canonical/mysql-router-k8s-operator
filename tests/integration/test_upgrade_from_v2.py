# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .architecture import architecture
from .helpers import (
    APPLICATION_DEFAULT_APP_NAME,
    MYSQL_DEFAULT_APP_NAME,
    MYSQL_ROUTER_DEFAULT_APP_NAME,
    ensure_all_units_continuous_writes_incrementing,
)

logger = logging.getLogger(__name__)

TIMEOUT = 20 * 60
UPGRADE_TIMEOUT = 15 * 60

MYSQL_APP_NAME = MYSQL_DEFAULT_APP_NAME
MYSQL_ROUTER_APP_NAME = MYSQL_ROUTER_DEFAULT_APP_NAME
APPLICATION_APP_NAME = APPLICATION_DEFAULT_APP_NAME

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
RESOURCES = {"mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_deploy_v2(ops_test: OpsTest, series) -> None:
    """Deploy v2 charms and test application."""
    logger.info("Deploying all applications")

    if architecture == "amd64":
        router_rev = 748
        mysql_rev = 346
    elif architecture == "arm64":
        router_rev = 747
        mysql_rev = 348
    else:
        pytest.skip(f"Architecture {architecture} not supported in this test")

    await asyncio.gather(
        ops_test.model.deploy(
            "mysql-k8s",
            channel="8.0/stable",
            revision=mysql_rev,
            application_name=MYSQL_APP_NAME,
            config={"profile": "testing"},
            series=series,
            num_units=1,
            trust=True,
        ),
        ops_test.model.deploy(
            "mysql-router-k8s",
            channel="8.0/stable",
            revision=router_rev,
            application_name=MYSQL_ROUTER_APP_NAME,
            series=series,
            num_units=3,
            trust=True,
        ),
        ops_test.model.deploy(
            "mysql-test-app",
            channel="latest/edge",
            application_name=APPLICATION_APP_NAME,
            series=series,
            num_units=1,
        ),
    )

    logger.info(f"Relating {MYSQL_ROUTER_APP_NAME} to {MYSQL_APP_NAME} and {APPLICATION_APP_NAME}")

    await ops_test.model.relate(
        f"{MYSQL_ROUTER_APP_NAME}:backend-database", f"{MYSQL_APP_NAME}:database"
    )
    await ops_test.model.relate(
        f"{APPLICATION_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:database"
    )

    mysql_router_application = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]
    logger.info("Waiting for applications to become active")
    await ops_test.model.block_until(
        lambda: (
            all(unit.workload_status == "active" for unit in mysql_router_application.units)
            and all(unit.agent_status == "idle" for unit in mysql_router_application.units)
        ),
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
async def test_upgrade_from_v2(ops_test: OpsTest, charm) -> None:
    """Upgrade mysqlrouter from v2 to v3 while ensuring continuous writes incrementing."""
    await ensure_all_units_continuous_writes_incrementing(ops_test)

    mysql_router_application = ops_test.model.applications[MYSQL_ROUTER_APP_NAME]

    logger.info("Refresh the charm with local v3 build")
    await mysql_router_application.refresh(path=charm, resources=RESOURCES)

    logger.info("Block until router become active")
    # sleep to ensure that active status from before re-refresh does not affect below check
    time.sleep(15)

    await ops_test.model.block_until(
        lambda: (
            all(unit.workload_status == "active" for unit in mysql_router_application.units)
            and all(unit.agent_status == "idle" for unit in mysql_router_application.units)
        ),
        timeout=TIMEOUT,
    )

    logger.info("Ensure continuous writes after upgrade")
    await ensure_all_units_continuous_writes_incrementing(ops_test)
