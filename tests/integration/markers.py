# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import juju_

skip_juju_lower_than_3_1 = pytest.mark.skipif(
    juju_.is_3_1_or_higher,
    reason="Skips juju <3.1.x as we have a dependency for self-signed-certificates",
)
