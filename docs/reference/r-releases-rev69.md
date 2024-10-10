# MySQL Router K8s revision 69
<sub>October 20, 2023</sub>

Dear community, this is to inform you that new MySQL Router K8s is published in `8.0/stable` [charmhub](https://charmhub.io/mysql-router-k8s?channel=8.0/stable) channel for Kubernetes.

## The features you can start using today:

* [Add Juju 3 support](/t/12179) (Juju 2 is still supported)
* Charm [minor upgrades](/t/TODO) and [minor rollbacks](/t/TODO)
* Workload updated to [MySQL Router 8.0.34](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-34.html)
* [Support](https://charmhub.io/mysql-router-k8s/integrations?channel=8.0/stable) for modern `mysql_client` and `tls-certificates` interfaces
* Support `juju expose`
* New and complete documentation on CharmHub

## Bugfixes included:

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-router-k8s-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/mysql-router-k8s-operator/releases) provide a detailed list of bugfixes/PRs/Git commits for each revision.

## What is inside the charms:

* Charmed MySQL Router K8s ships the latest MySQL Router “8.0.34-0ubuntu0.22.04.1”
* CLI mysql-shell updated to "8.0.34-0ubuntu0.22.04.1~ppa1"
* The Prometheus mysql-router-exporter is "4.0.5-0ubuntu0.22.04.1~ppa1"
* K8s charms [based on our](https://github.com/orgs/canonical/packages?tab=packages&q=charmed) ROCK OCI ([resource-revision 43](https://github.com/canonical/mysql-router-k8s-operator/releases/tag/rev69), based on Ubuntu LTS “22.04”)
* Principal charms supports the latest LTS series “22.04” only.

## Technical notes:

* Upgrade (`juju refresh`) is possible from this revision 69+.
* Use this operator together with [Charmed MySQL K8s](https://charmhub.io/mysql-k8s)

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Matrix public channel](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/12177).

Consider [opening a GitHub issue](https://github.com/canonical/mysql-router-k8s-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/mysql-router-k8s-operator/blob/main/CONTRIBUTING.md) to the project!

## Footer:

It is the first stable release of the operator "MySQL Router K8s" by Canonical Data.<br/>Well done, Team!