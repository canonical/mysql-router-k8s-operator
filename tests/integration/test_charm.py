#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .helpers import (
    execute_queries_on_unit,
    get_inserted_data_by_application,
    get_server_config_credentials,
    get_unit_address,
    scale_application,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_ROUTER_APP_NAME = "mysql-router-k8s"
APPLICATION_APP_NAME = "mysql-test-app"
SLOW_TIMEOUT = 15 * 60
MODEL_CONFIG = {"logging-config": "<root>=INFO;unit=DEBUG"}


@pytest.mark.abort_on_fail
async def test_database_relation(ops_test: OpsTest):
    """Test the database relation."""
    # Build and deploy applications
    mysqlrouter_charm = await ops_test.build_charm(".")
    await ops_test.model.set_config(MODEL_CONFIG)

    mysqlrouter_resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    logger.info("Deploying mysql, mysqlrouter and application")
    applications = await asyncio.gather(
        ops_test.model.deploy(
            MYSQL_APP_NAME,
            channel="8.0/edge",
            application_name=MYSQL_APP_NAME,
            series="jammy",
            num_units=3,
            trust=True,  # Necessary after a6f1f01: Fix/endpoints as k8s services (#142)
        ),
        ops_test.model.deploy(
            mysqlrouter_charm,
            application_name=MYSQL_ROUTER_APP_NAME,
            series="jammy",
            resources=mysqlrouter_resources,
            num_units=1,
        ),
        ops_test.model.deploy(
            APPLICATION_APP_NAME,
            channel="latest/edge",
            application_name=APPLICATION_APP_NAME,
            series="jammy",
            num_units=1,
        ),
    )

    mysql_app, application_app = applications[0], applications[2]

    async with ops_test.fast_forward():
        logger.info("Waiting for mysqlrouter to be in BlockedStatus")
        await ops_test.model.block_until(
            lambda: ops_test.model.applications[MYSQL_ROUTER_APP_NAME].status == "blocked",
            timeout=SLOW_TIMEOUT,
        )

        logger.info("Relating mysql, mysqlrouter and application")
        # Relate the database with mysqlrouter
        await ops_test.model.relate(
            f"{MYSQL_ROUTER_APP_NAME}:backend-database", f"{MYSQL_APP_NAME}:database"
        )
        # Relate mysqlrouter with application next
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

    # Ensure that the data inserted by sample application is present in the database
    application_unit = application_app.units[0]
    inserted_data = await get_inserted_data_by_application(application_unit)

    mysql_unit = mysql_app.units[0]
    mysql_unit_address = await get_unit_address(ops_test, mysql_unit.name)
    server_config_credentials = await get_server_config_credentials(mysql_unit)

    select_inserted_data_sql = [
        f"SELECT data FROM continuous_writes_database.random_data WHERE data = '{inserted_data}'",
    ]
    selected_data = await execute_queries_on_unit(
        mysql_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_inserted_data_sql,
    )

    assert len(selected_data) > 0
    assert inserted_data == selected_data[0]

    # Ensure that both mysqlrouter and the application can be scaled up and down
    await scale_application(ops_test, MYSQL_ROUTER_APP_NAME, 2)
    # Scaling the application will ensure that it can read the inserted data
    # from the mysqlrouter connection before going into an active status
    await scale_application(ops_test, APPLICATION_APP_NAME, 2)

    # Disabled until juju fixes k8s scaledown: https://bugs.launchpad.net/juju/+bug/1977582
    # await scale_application(ops_test, MYSQL_ROUTER_APP_NAME, 1)
    # await scale_application(ops_test, APPLICATION_APP_NAME, 1)
