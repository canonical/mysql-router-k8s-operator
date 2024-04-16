# Minor Rollback

> :information_source: **Example**: MySQL Router 8.0.34 -> MySQL Router 8.0.33<br/>
(including simple charm revision bump: from revision 43 to revision 42)

> **:warning: WARNING**: do NOT trigger `rollback` during the **running** `upgrade` action! It may cause unpredictable MySQL Cluster and/or MySQL Router state!

## Minor rollback steps

The rollback is NOT necessary if `sacrificial unit` is created before the upgrade, just remove it using scale-down the application. Otherwise perform the rollback:

1. **Rollback**. Perform the charm rollback using `juju refresh`. The unit with the maximal ordinal will be rolled-back first and rollback continues for entire application.
2. **Check**. Make sure the charm and cluster are in healthy state again.

## Manual Rollback

After a `juju refresh`, case there any version incompatibilities in charm revisions or it dependencies, or any other unexpected failure in the upgrade process, the upgrade process will be halted an enter a failure state.

Although the underlying MySQL Cluster and MySQL Router continue to work, it’s important to rollback the charm to previous revision so an update can be later attempted after a further inspection of the failure.

To execute a rollback we take the same procedure as the upgrade, the difference being the charm revision to upgrade to. In case of this tutorial example, one would refresh the charm back to revision `88`, the steps being:

## Step 1: Rollback

When using the charm from charmhub:

```shell
juju refresh mysql-router-k8s --revision=88 --trust
```

When deploying from a local charm file, you need to have the previous revision's `.charm` file and the `mysql-image` resource. Then, run:

```shell
juju refresh mysql-router-k8s --trust --path=<path_to_charm_file> \
       --resource mysql-router-image=<image>
```
The resource reference can be found under the `upstream-source` key in the charm's `metadata.yaml` file. You can access this file by:
* Simply unpacking the `.charm` file
* Finding the corresponding [release](https://github.com/canonical/mysql-router-k8s-operator/releases) in the charm's GitHub repository and navigating to `metadata.yaml`.

After the refresh command, the `juju` controller revision for the application will be back in sync with the running MySQL Router K8s revision.

## Step 2: Check

The future [improvement is planned](https://warthogs.atlassian.net/browse/DPE-2620) to check the state on pod/cluster on a low level. At the moment check `juju status` to make sure the cluster [state](/t/11866) is OK.