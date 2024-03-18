# MySQL Router K8s revision 96
<sub>WIP</sub>

> **WARNING**: release is in progress, the charm is available in 8.0/candidate only!!!

Dear community, this is to inform you that new MySQL Router K8s is published in `8.0/stable` [charmhub](https://charmhub.io/mysql-router-k8s?channel=8.0/stable) channel for Kubernetes.

## The features you can start using today:

* Updated [MySQL Router to 8.0.35](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-35.html) in [#191](https://github.com/canonical/mysql-router-k8s-operator/pull/191)
* Juju 3.1.7+ support in [#2037120](https://bugs.launchpad.net/juju/+bug/2037120)
* Enable poetry hashes & charmcraft strict dependencies in [#179](https://github.com/canonical/mysql-router-k8s-operator/pull/179)
* Add [Allure Report beta](https://canonical.github.io/mysql-router-k8s-operator) in [#198](https://github.com/canonical/mysql-router-k8s-operator/pull/198)
 

## Bugfixes included:

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-router-k8s-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/mysql-router-k8s-operator/releases) provide a detailed list of bugfixes/PRs/Git commits for each revision.

* Bootstrap mysql-router with force option in [#187](https://github.com/canonical/mysql-router-k8s-operator/pull/187)
* Fix upgrade compatibility check in [#202](https://github.com/canonical/mysql-router-k8s-operator/pull/202)
* Retry if MySQL Server is unreachable in [#190](https://github.com/canonical/mysql-router-k8s-operator/pull/190)

## What is inside the charms:

* Charmed MySQL Router K8s ships MySQL Router “8.0.35-0ubuntu0.22.04.1”
* CLI mysql-shell version is "8.0.35-0ubuntu0.22.04.1~ppa1"
* The Prometheus mysql-router-exporter is "4.0.5-0ubuntu0.22.04.1~ppa1"
* K8s charms [based on our](https://github.com/orgs/canonical/packages?tab=packages&q=charmed) ROCK OCI (Ubuntu LTS “22.04” - ubuntu:22.04-based)
* Principal charms supports the latest LTS series “22.04” only

## Technical notes:

* Upgrade (`juju refresh`) is possible from this revision 69+
* Use this operator together with a modern operator "[Charmed MySQL K8s](https://charmhub.io/mysql-k8s)"

## How to reach us:

If you would like to chat with us about your use-cases or ideas,  [choose your way from the list](/t/12177).

Consider [opening a GitHub issue](https://github.com/canonical/mysql-router-k8s-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/mysql-router-k8s-operator/blob/main/CONTRIBUTING.md) to the project!