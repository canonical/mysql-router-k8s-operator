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

from . import markers
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


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@markers.skip_if_lower_than_3_1
async def test_build_and_deploy(ops_test: OpsTest):
    """Test the deployment of the charm."""
    # Build and deploy applications
    mysqlrouter_charm = await ops_test.build_charm(".")
    await ops_test.model.set_config(MODEL_CONFIG)

    mysqlrouter_resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    logger.info("Deploying mysql, mysqlrouter and application")
    await asyncio.gather(
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
        ops_test.model.deploy(
            SELF_SIGNED_CERTIFICATE_NAME,
            application_name=SELF_SIGNED_CERTIFICATE_NAME,
            series="jammy",
            num_units=1,
        ),
    )

    async with ops_test.fast_forward():
        logger.info("Relating mysql, mysqlrouter and application")
        await ops_test.model.relate(
            f"{MYSQL_APP_NAME}", f"{SELF_SIGNED_CERTIFICATE_NAME}:certificates"
        ),
        await ops_test.model.relate(
            f"{MYSQL_ROUTER_APP_NAME}", f"{SELF_SIGNED_CERTIFICATE_NAME}:certificates"
        ),

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
            apps=[
                MYSQL_APP_NAME,
                MYSQL_ROUTER_APP_NAME,
                APPLICATION_APP_NAME,
                DATA_INTEGRATOR,
                SELF_SIGNED_CERTIFICATE_NAME,
            ],
            status="active",
            timeout=SLOW_TIMEOUT,
        )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@markers.skip_if_lower_than_3_1
async def test_tls(ops_test: OpsTest):
    """Test the database relation."""
    logger.info("Assert TLS file exists")
    assert await get_tls_ca(
        ops_test, MYSQL_ROUTER_APP_NAME + "/0"
    ), "No CA found after TLS relation"

    # After relating to only encrypted connection should be possible
    logger.info("Asserting connections after relation")
    unit = ops_test.model.units.get(DATA_INTEGRATOR + "/0")
    action = await unit.run_action("get-credentials")
    creds = (await asyncio.wait_for(action.wait(), 60)).results["mysql"]
    config = {
        "username": creds["username"],
        "password": creds["password"],
        "host": creds["endpoints"].split(":")[0],
    }

    extra_opts = {
        "ssl_disabled": False,
        "port": creds["endpoints"].split(":")[1],
    }
    assert is_connection_possible(
        config, **extra_opts
    ), f"Encryption enabled - connection not possible to unit {MYSQL_ROUTER_APP_NAME}/0"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@markers.skip_if_lower_than_3_1
async def test_node_port_and_clusterip_setup():
    """Test the nodeport."""
    for app_name in [DATA_INTEGRATOR, APPLICATION_APP_NAME]:
        try:
            relation_info = yaml.safe_load(
                subprocess.check_output(
                    [
                        "juju",
                        "show-unit",
                        f"{app_name}/0",
                    ]
                )
            )[f"{app_name}/0"]["relation-info"]
            if app_name == DATA_INTEGRATOR:
                endpoint = list(filter(lambda x: x["endpoint"] == "mysql", relation_info))[0][
                    "application-data"
                ]["endpoints"]
                assert "svc.cluster.local" not in endpoint
            else:
                endpoint = list(filter(lambda x: x["endpoint"] == "database", relation_info))[0][
                    "application-data"
                ]["endpoints"]
                assert "svc.cluster.local" in endpoint
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get the unit info for {app_name}: {e.output}")
            raise


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@markers.skip_if_lower_than_3_1
async def test_data_integrator(ops_test: OpsTest):
    """Test the nodeport."""
    application_app = ops_test.model.applications.get(APPLICATION_APP_NAME)
    mysql_app = ops_test.model.applications.get(MYSQL_APP_NAME)

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
