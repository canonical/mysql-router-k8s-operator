# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import juju_

is_3_1_or_higher = pytest.mark.skipif(
    juju_.is_3_1_or_higher,
    reason="Skips juju <3.1.x as we have a dependency for self-signed-certificates",
)
