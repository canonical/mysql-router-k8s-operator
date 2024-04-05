# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import juju_

skip_if_lower_than_3_1 = pytest.mark.skipif(
    not juju_.is_3_1_or_higher,
    reason="Skips juju <3.1.x as we have a dependency for self-signed-certificates",
)
