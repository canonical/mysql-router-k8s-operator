# How to deploy and manage units

## Basic Usage

To deploy a single unit of MySQL Router using its default configuration
```shell
juju deploy mysql-router-k8s --channel 8.0 --trust
```

It is customary to use MySQL Router in HA setup. Hence usually more than one unit (preferably an odd number to prohibit a "split-brain" scenario) is deployed. To deploy MySQL Router in HA mode, specify the number of desired units with the `-n` option.
```shell
juju deploy mysql-router-k8s --channel 8.0 --trust -n <number_of_replicas>
```

## Scaling

Both scaling-up and scaling-down operations are performed using `juju scale-application`:
```shell
juju scale-application mysql-router-k8s <desired_num_of_units>
```

> :tipping_hand_man: **Tip**: scaling-down to zero units is supported to safe K8s resources!