# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import importlib.metadata

# libjuju version != juju agent version, but the major version should be identical—which is good
_libjuju_version = importlib.metadata.version("juju")
is_3_1_or_higher = (
    len(_libjuju_version.split(".")) >= 2
    and int(_libjuju_version.split(".")[0]) >= 3
    and int(_libjuju_version.split(".")[1]) >= 1
)
