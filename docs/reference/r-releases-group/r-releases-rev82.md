# MySQL Router K8s revision 82
<sub>January 3, 2024</sub>

Dear community, this is to inform you that new MySQL Router K8s is published in `8.0/stable` [charmhub](https://charmhub.io/mysql-router-k8s?channel=8.0/stable) channel for Kubernetes.

## The features you can start using today:

* [[DPE-1799](https://warthogs.atlassian.net/browse/DPE-1799)] Add rotation of mysql-router logs in [[PR#143](https://github.com/canonical/mysql-router-k8s-operator/pull/143)]
* [[DPE-3022](https://warthogs.atlassian.net/browse/DPE-3022)] Updated data_platform_libs/data_interfaces to version 24 in [[PR#163](https://github.com/canonical/mysql-router-k8s-operator/pull/163)]
* [[DPE-2760](https://warthogs.atlassian.net/browse/DPE-2760)] Use "Relation Secrets" in [[PR#152](https://github.com/canonical/mysql-router-k8s-operator/pull/152)]
* [[DPE-2807](https://warthogs.atlassian.net/browse/DPE-2807)] Add discourse documentation gatekeeper sync in [[PR#149](https://github.com/canonical/mysql-router-k8s-operator/pull/149)]

## Bugfixes included:

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-router-k8s-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/mysql-router-k8s-operator/releases) provide a detailed list of bugfixes/PRs/Git commits for each revision.

* Updated logrotate dateformat to tolerate more than 24hrs of uptime in [[PR#169](https://github.com/canonical/mysql-router-k8s-operator/pull/169)][[DPE-3063](https://warthogs.atlassian.net/browse/DPE-3063)] 
* Fixed recovering from hook errors when creating/deleting MySQL users in [[PR#165](https://github.com/canonical/mysql-router-k8s-operator/pull/165)]
* Fixed upgrade compatibility check in [[PR#164](https://github.com/canonical/mysql-router-k8s-operator/pull/164)]
* Improved upgrade stability in [[PR#153](https://github.com/canonical/mysql-router-k8s-operator/pull/153)]
* Decreased verbosity for `httpx` and `httpcore` logger level to WARNING in [[PR#176](https://github.com/canonical/mysql-router-k8s-operator/pull/176)]
* Switch to `maintenance` Juju status (instead of `waiting`) while router is starting in [[PR#147](https://github.com/canonical/mysql-router-k8s-operator/pull/147)]

## What is inside the charms:

* Charmed MySQL Router K8s ships MySQL Router “8.0.34-0ubuntu0.22.04.1”
* CLI mysql-shell version is "8.0.34-0ubuntu0.22.04.1~ppa1"
* The Prometheus mysql-router-exporter is "4.0.5-0ubuntu0.22.04.1~ppa1"
* K8s charms [based on our](https://github.com/orgs/canonical/packages?tab=packages&q=charmed) rock (Ubuntu LTS “22.04” - ubuntu:22.04-based) based on SNAP revision 69
* Principal charms supports the latest LTS series “22.04” only
* Subordinate charms support LTS “22.04” and “20.04” only

## Technical notes:

* Upgrade (`juju refresh`) is possible from this revision 69+
* **WARNING**: Downgrade from revision 82 to revision 69 is not possible due to [[PR#158](https://github.com/canonical/mysql-router-k8s-operator/pull/158)]
* Use this operator together with a modern operator "[Charmed MySQL K8s](https://charmhub.io/mysql-k8s)"

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/data-platform) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/12177).

Consider [opening a GitHub issue](https://github.com/canonical/mysql-router-k8s-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/mysql-router-k8s-operator/blob/main/CONTRIBUTING.md) to the project!