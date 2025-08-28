# How to deploy and manage units

## Basic Usage

To deploy a single unit of MySQL Router using its default configuration
```shell
juju deploy mysql-router-k8s --channel 8.0 --trust
```

To deploy MySQL Router in high-availability mode, specify the number of desired units with the `-n` option.
```shell
juju deploy mysql-router-k8s --channel 8.0 --trust -n <number_of_replicas>
```

## Scaling

Both scaling-up and scaling-down operations are performed using `juju scale-application`:
```shell
juju scale-application mysql-router-k8s <desired_num_of_units>
```