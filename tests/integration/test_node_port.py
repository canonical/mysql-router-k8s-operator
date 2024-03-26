#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from .helpers import (
    execute_queries_on_unit,
    get_inserted_data_by_application,
    get_server_config_credentials,
    get_tls_ca,
    get_unit_address,
    is_connection_possible,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MYSQL_APP_NAME = "mysql-k8s"
MYSQL_ROUTER_APP_NAME = "mysql-router-k8s"
SELF_SIGNED_CERTIFICATE_NAME = "self-signed-certificates"
APPLICATION_APP_NAME = "mysql-test-app"
DATA_INTEGRATOR = "data-integrator"
SLOW_TIMEOUT = 15 * 60
MODEL_CONFIG = {"logging-config": "<root>=INFO;unit=DEBUG"}


server_config_credentials = None


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_node_port_with_data_integrator(ops_test: OpsTest):
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
            config={"profile": "testing"},
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
            DATA_INTEGRATOR,
            channel="latest/edge",
            application_name=DATA_INTEGRATOR,
            series="jammy",
            config={"database-name": "test"},
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
        # Relate mysqlrouter with data integrator
        await ops_test.model.relate(
            f"{DATA_INTEGRATOR}:mysql", f"{MYSQL_ROUTER_APP_NAME}:database"
        )
        # Relate mysqlrouter with application next
        await ops_test.model.relate(
            f"{APPLICATION_APP_NAME}:database", f"{MYSQL_ROUTER_APP_NAME}:database"
        )

        # Now, we should have one
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME, MYSQL_ROUTER_APP_NAME, APPLICATION_APP_NAME, DATA_INTEGRATOR],
            status="active",
            raise_on_blocked=True,
            timeout=SLOW_TIMEOUT,
        )

    # Ensure that the data inserted by sample application is present in the database
    application_unit = application_app.units[0]
    inserted_data = await get_inserted_data_by_application(application_unit)

    mysql_unit = mysql_app.units[0]
    mysql_unit_address = await get_unit_address(ops_test, mysql_unit.name)

    global server_config_credentials
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

    # Ensure the endpoints are set respectively to NodePort and ClusterIP for the data-integrator
    # and the application-app
    for app_name in [DATA_INTEGRATOR, APPLICATION_APP_NAME]:
        try:
            endpoint = yaml.safe_load(
                subprocess.check_output(
                    [
                        "juju",
                        "show-unit",
                        f"{app_name}/0",
                    ]
                )
            )[f"{app_name}/0"]["relation-info"][1]["application-data"]["endpoints"]
            if app_name == DATA_INTEGRATOR:
                assert "svc.cluster.local" not in endpoint
            else:
                assert "svc.cluster.local" in endpoint
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get the unit info for {app_name}: {e.output}")
            raise


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_tls(ops_test: OpsTest):
    """Test the database relation."""
    # Build and deploy applications
    logger.info(f"Deploying {SELF_SIGNED_CERTIFICATE_NAME}")
    await ops_test.model.deploy(
        SELF_SIGNED_CERTIFICATE_NAME,
        application_name=SELF_SIGNED_CERTIFICATE_NAME,
        series="jammy",
        num_units=1,
    )
    await ops_test.model.wait_for_idle(
        apps=[SELF_SIGNED_CERTIFICATE_NAME],
        status="active",
        raise_on_blocked=True,
        timeout=SLOW_TIMEOUT,
    )

    asyncio.sleep(120)

    async with ops_test.fast_forward():
        # Relate the certificates with the other apps
        await asyncio.gather(
            ops_test.model.relate(
                f"{APPLICATION_APP_NAME}", f"{SELF_SIGNED_CERTIFICATE_NAME}:certificates"
            ),
            ops_test.model.relate(
                f"{MYSQL_ROUTER_APP_NAME}", f"{SELF_SIGNED_CERTIFICATE_NAME}:certificates"
            ),
        )
        # Now, we should have one
        await ops_test.model.wait_for_idle(
            apps=[MYSQL_APP_NAME, MYSQL_ROUTER_APP_NAME, APPLICATION_APP_NAME, DATA_INTEGRATOR],
            status="active",
            raise_on_blocked=True,
            timeout=SLOW_TIMEOUT,
        )

    # test for ca presence in a given unit
    logger.info("Assert TLS file exists")
    assert await get_tls_ca(
        ops_test, MYSQL_ROUTER_APP_NAME + "/0"
    ), "No CA found after TLS relation"

    # After relating to only encrypted connection should be possible
    logger.info("Asserting connections after relation")
    unit_name = MYSQL_ROUTER_APP_NAME + "/0"
    unit_ip = await get_unit_address(ops_test, unit_name)

    global server_config_credentials
    config = dict(server_config_credentials | {"host": unit_ip})
    assert is_connection_possible(
        config, **{"ssl_disabled": False}
    ), f"Encrypted connection not possible to unit {unit_name} with enabled TLS"
    assert not is_connection_possible(
        config, **{"ssl_disabled": True}
    ), f"Unencrypted connection possible to unit {unit_name} with enabled TLS"
