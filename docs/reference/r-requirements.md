## Juju version

The charm supports both [Juju 2.9 LTS](https://github.com/juju/juju/releases) and [Juju 3.1](https://github.com/juju/juju/releases).

The minimum supported Juju versions are:

* 2.9.32+
* 3.1.7+ (Juju secrets refactored/stabilized in Juju 3.1.7)

## Kubernetes requirements

* Kubernetes 1.27+
* Canonical MicroK8s 1.27+ (snap channel 1.27-strict/stable and newer)
## Minimum requirements

Make sure your machine meets the following requirements:
- Ubuntu 22.04 (Jammy) or later.
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required OCI/ROCKs and charms.

## Supported architectures

The charm is based on [ROCK OCI](https://github.com/canonical/charmed-mysql-rock) named "[charmed-mysql](https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql)", which is recursively based on SNAP "[charmed-mysql](https://snapcraft.io/charmed-mysql)", which is currently available for `amd64` only! The architecture `arm64` support is planned. Please [contact us](/t/12177) if you are interested in new architecture!

<a name="mysql-gr-limits"></a>
## Charmed MySQL K8s requirements
* Please also keep in mind ["Charmed MySQL K8s" requirements](https://charmhub.io/mysql-k8s/docs/r-requirements#mysql-gr-limits).

test2