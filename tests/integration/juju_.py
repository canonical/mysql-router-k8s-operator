# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import juju.unit


async def run_action(unit: juju.unit.Unit, action_name, *, check_return_code=True, **params):
    action = await unit.run_action(action_name=action_name, **params)
    result = await action.wait()

    assert result.results.get("return-code") == 0 if check_return_code else True
    return result.results
