# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import importlib.metadata

import juju.unit

# libjuju version != juju agent version, but the major version should be identical—which is good
_libjuju_version = importlib.metadata.version("juju")
juju_major_version = int(_libjuju_version.split(".")[0])
is_3_1_or_higher = (
    len(_libjuju_version.split(".")) >= 2
    and int(_libjuju_version.split(".")[0]) >= 3
    and int(_libjuju_version.split(".")[1]) >= 1
)

is_3_or_higher = int(_libjuju_version.split(".")[0]) >= 3


async def run_action(unit: juju.unit.Unit, action_name, **params):
    action = await unit.run_action(action_name=action_name, **params)
    result = await action.wait()
    # Syntax changed across libjuju major versions
    if juju_major_version <= 2:
        assert result.results.get("Code") == "0"
    else:
        assert result.results.get("return-code") == 0
    return result.results
