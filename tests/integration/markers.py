# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import architecture, juju_

skip_if_lower_than_3_1 = pytest.mark.skipif(
    not juju_.is_3_1_or_higher,
    reason="Skips juju <3.1.x as we have a dependency for self-signed-certificates",
)
amd64_only = pytest.mark.skipif(
    architecture.architecture != "amd64", reason="Requires amd64 architecture"
)
arm64_only = pytest.mark.skipif(
    architecture.architecture != "arm64", reason="Requires arm64 architecture"
)
