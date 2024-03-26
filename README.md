# CoinJoin simulation setup

A container-based setup for simulating CoinJoins on RegTest network.

## Usage

1. Install [Docker](https://docker.com/) and [Python](http://python.org/).
2. Clone the repository `git clone --recurse-submodules https://github.com/crocs-muni/coinjoin-simulator`.
3. Install dependencies: `pip install -r requirements.txt`.
4. Run the default scenario with the default driver: `python manager.py run`.
   - [Scenario](#scenarios) definition file can be specified using the `--scenario` option.

For more complex setups see section [Advanced usage](#advanced-usage).

## Scenarios

Scenario definition files can be passed to the simulation script using the `--scenario` option. The scenario definition is a JSON file with the following structure:

```json
{
    "name": "default",
    "rounds": 0,
    "blocks": 120,
    "default_version": "2.0.4",
    "distributor_version": "2.0.4",
    "backend": {
        "MaxInputCountByRound": 200,
        "MinInputCountByRoundMultiplier": 0.2,
        ...
    },
    "wallets": [
        {"funds": [200000, 50000]},
        {"funds": [3000000], "delay": 10},
        {"funds": [1000000, 50000], "delay": 1, "skip_rounds": [3, 5, 6]},
        {"funds": [1000000, 50000], "delay": 1, "skip_rounds": [3, 5, 6], "version": "2.0.3"},
        ...
    ],
}
```

The fields are as follows:
- `name` field is the name of the scenario used for output logs.
- `rounds` field is the number of coinjoin rounds after which the simulation terminates. If set to 0, the simulation will run indefinitely.
- `blocks` field is the number of mined blocks after which the simulation terminates. If set to 0, the simulation will run indefinitely.
- `default_version` field is the string representing of the version of wallet wasabi used for clients without the version specification.
- `distributor_version` field is the string representing of the version of wallet wasabi used for the distributor client.
- `backend` field is the configuration for the `wasabi-backend` container used in the simulation. The provided fields update the defaults.
- `wallets` field is a list of wallet configurations. Each wallet configuration is a dictionary with the following fields:
  - `funds` is a list of funds in satoshis that the wallet will use for coinjoins.
  - `delay` is the number of blocks the wallet will wait before joining coinjoins.
  - `skip_rounds` is a list of coinjoin rounds during which a wallet should not participate.
  - `version` is the string representation of wallet wasabi version used for client running this wallet.


## Advanced usage

The simulation script enables advanced configuration for running on different container platforms with various networking setups. This section describes the advanced configuration and shows common examples.

### Backend driver


#### Docker

The default driver is `docker`. Running `docker` requires [Docker](https://www.docker.com/) installed locally and running.

#### Podman

*Podman support will be likely **removed** in the future versions.*

To run the simulation using `podman`, specify it as driver using `--driver podman` option.

The driver requires [Podman](https://podman.io/) being installed and you may also need to override default IP addresses to communicate via localhost using `--control-ip` and `--wasabi-backend-ip` options. 


#### Kubernetes

To run the simulation on a [Kubernetes](https://kubernetes.io/) cluster, use the `kubernetes` driver. The driver requires a running Kubernetes cluster and `kubectl` configured to access the cluster. 

The `kubernetes` driver relies on used images being accessible publicly from [DockerHub](https://hub.docker.com/). For that, build the images in `containers` directory manually and upload them to the registry. Afterwards, specify the image prefix using `--image-prefix` option when starting the simulation.

In case *NodePorts* are not supported by your cluster, you may also need to run a proxy to access the services, e.g., [Shadowsocks](https://shadowsocks.org/). Use the `--proxy` option to specify the address of the proxy.

If you need to specify custom namespace, use the `--namespace` option. If you also need to reuse existing namespace, use the `--reuse-namespace` option.

##### Example

Running the simulation on a remote cluster using pre-existing namespace and a proxy reachable on localhost port 8123:
```bash
python manager.py run --driver kubernetes --namespace custom-coinjoin-ns --reuse-namespace --image-prefix "crocsmuni/" --proxy "socks5://127.0.0.1:8123" --scenario "scenarios/uniform-dynamic-500-30utxo.json"
```
