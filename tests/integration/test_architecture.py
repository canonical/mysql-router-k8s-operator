#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from . import markers
from .helpers import get_charm

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MYSQL_ROUTER_APP_NAME = METADATA["name"]


@pytest.mark.group(1)
@markers.amd64_only
async def test_arm_charm_on_amd_host(ops_test: OpsTest) -> None:
    """Tries deploying an arm64 charm on amd64 host."""
    charm = await get_charm(".", "arm64", 1)

    resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    await ops_test.model.deploy(
        charm,
        application_name=MYSQL_ROUTER_APP_NAME,
        num_units=1,
        resources=resources,
        base="ubuntu@22.04",
    )

    await ops_test.model.wait_for_idle(
        apps=[MYSQL_ROUTER_APP_NAME],
        status="error",
        raise_on_error=False,
    )


@pytest.mark.group(1)
@markers.arm64_only
async def test_amd_charm_on_arm_host(ops_test: OpsTest) -> None:
    """Tries deploying an amd64 charm on arm64 host."""
    charm = await get_charm(".", "amd64", 0)

    resources = {
        "mysql-router-image": METADATA["resources"]["mysql-router-image"]["upstream-source"]
    }

    await ops_test.model.deploy(
        charm,
        application_name=MYSQL_ROUTER_APP_NAME,
        num_units=1,
        resources=resources,
        base="ubuntu@22.04",
    )

    await ops_test.model.wait_for_idle(
        apps=[MYSQL_ROUTER_APP_NAME],
        status="error",
        raise_on_error=False,
    )