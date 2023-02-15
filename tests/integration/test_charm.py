#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from .helpers import (
    execute_queries_on_unit,
    get_inserted_data_by_application,
    get_server_config_credentials,
    get_unit_address,
    scale_application,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = "mysql"
MYSQL_ROUTER_APP_NAME = "mysqlrouter"
APPLICATION_APP_NAME = "application"
SLOW_TIMEOUT = 15 * 60


@pytest.mark.abort_on_fail
async def test_database_relation(ops_test: OpsTest):
    """Test the database relation."""
    # Build and deploy applications
    mysqlrouter_charm = await ops_test.build_charm(".")
    application_charm = await ops_test.build_charm("./tests/integration/application-charm/")

    mysqlrouter_resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    applications = await asyncio.gather(
        ops_test.model.deploy(
            "mysql-k8s", channel="latest/edge", application_name=MYSQL_APP_NAME, num_units=3
        ),
        ops_test.model.deploy(
            mysqlrouter_charm,
            application_name=MYSQL_ROUTER_APP_NAME,
            resources=mysqlrouter_resources,
            num_units=1,
            trust=True,  # Needed to be able to delete/create k8s services in the charm
        ),
        ops_test.model.deploy(
            application_charm, application_name=APPLICATION_APP_NAME, num_units=1
        ),
    )

    mysql_app, application_app = applications[0], applications[2]

    # Relate the database with mysqlrouter
    await ops_test.model.relate(
        f"{MYSQL_ROUTER_APP_NAME}:backend-database", f"{MYSQL_APP_NAME}:database"
    )

    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[MYSQL_APP_NAME],
                status="active",
                raise_on_blocked=True,
                timeout=SLOW_TIMEOUT,
            ),
            ops_test.model.wait_for_idle(
                apps=[MYSQL_ROUTER_APP_NAME, APPLICATION_APP_NAME],
                status="waiting",
                raise_on_blocked=True,
                timeout=SLOW_TIMEOUT,
            ),
        )

        # Relate mysqlrouter with application next
        await ops_test.model.relate(
            f"{APPLICATION_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:database"
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

    select_inserted_data_sql = (
        f"SELECT data FROM application_test_database.app_data WHERE data = '{inserted_data}'",
    )
    selected_data = await execute_queries_on_unit(
        mysql_unit_address,
        server_config_credentials["username"],
        server_config_credentials["password"],
        select_inserted_data_sql,
    )

    assert len(selected_data) > 0
    assert inserted_data == selected_data[0]

    # Ensure that both mysqlrouter and the application can be scaled up and down
    scale_application(ops_test, MYSQL_ROUTER_APP_NAME, 2)
    # Scaling the application will ensure that it can read the inserted data
    # from the mysqlrouter connection before going into an active status
    scale_application(ops_test, APPLICATION_APP_NAME, 2)

    scale_application(ops_test, MYSQL_ROUTER_APP_NAME, 1)
