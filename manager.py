from manager.btc_node import BtcNode
from manager.wasabi_backend import WasabiBackend
from manager.wasabi_clients import WasabiClient
from manager import utils
import manager.commands.genscen
from time import sleep, time
import sys
import random
import os
import datetime
import json
import argparse
import shutil
import tempfile
import multiprocessing
import multiprocessing.pool
import math

DISTRIBUTOR_UTXOS = 20
BATCH_SIZE = 5
BTC = 100_000_000
SCENARIO = {
    "name": "default",
    "rounds": 10,  # the number of coinjoins after which the simulation stops (0 for no limit)
    "blocks": 0,  # the number of mined blocks after which the simulation stops (0 for no limit)
    "default_version": "2.0.4",
    "wallets": [
        {"funds": [200000, 50000], "anon_score_target": 7},
        {"funds": [3000000], "redcoin_isolation": True},
        {"funds": [1000000, 500000], "skip_rounds": [0, 1, 2]},
        {"funds": [3000000, 15000]},
        {"funds": [1000000, 500000]},
        {"funds": [3000000, 600000]},
    ],
}

args = None
driver = None
node = None
coordinator = None
distributor = None
clients = []
versions = set()
invoices = {}

current_round = 0
current_block = 0


def prepare_image(name, path=None):
    prefixed_name = args.image_prefix + name
    if driver.has_image(prefixed_name):
        if args.force_rebuild:
            if args.image_prefix:
                driver.pull(prefixed_name)
                print(f"- image pulled {prefixed_name}")
            else:
                driver.build(name, f"./containers/{name}" if path is None else path)
                print(f"- image rebuilt {prefixed_name}")
        else:
            print(f"- image reused {prefixed_name}")
    elif args.image_prefix:
        driver.pull(prefixed_name)
        print(f"- image pulled {prefixed_name}")
    else:
        driver.build(name, f"./containers/{name}" if path is None else path)
        print(f"- image built {prefixed_name}")


def prepare_client_images():
    for version in versions:
        major_version = version[0]
        name = f"wasabi-client:{version}"
        path = f"./containers/wasabi-clients/v{major_version}/{version}"
        prepare_image(name, path)


def prepare_images():
    print("Preparing images")
    prepare_image("btc-node")
    prepare_image("wasabi-backend")
    prepare_client_images()


def start_infrastructure():
    print("Starting infrastructure")
    btc_node_ip, btc_node_ports = driver.run(
        "btc-node",
        f"{args.image_prefix}btc-node",
        ports={18443: 18443, 18444: 18444},
        cpu=4.0,
        memory=8192,
    )
    global node
    node = BtcNode(
        host=btc_node_ip if args.proxy else args.control_ip,
        port=18443 if args.proxy else btc_node_ports[18443],
        internal_ip=btc_node_ip,
        proxy=args.proxy,
    )
    node.wait_ready()
    print("- started btc-node")

    wasabi_backend_ip, wasabi_backend_ports = driver.run(
        "wasabi-backend",
        f"{args.image_prefix}wasabi-backend",
        ports={37127: 37127},
        env={
            "WASABI_BIND": "http://0.0.0.0:37127",
            "ADDR_BTC_NODE": args.btc_node_ip or node.internal_ip,
        },
        cpu=8.0,
        memory=8192,
    )
    sleep(1)
    with open("./containers/wasabi-backend/WabiSabiConfig.json", "r") as config_file:
        backend_config = json.load(config_file)
    backend_config.update(SCENARIO.get("backend", {}))

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        scenario_file = tmp_file.name
        tmp_file.write(json.dumps(backend_config, indent=2).encode())

    driver.upload(
        "wasabi-backend",
        scenario_file,
        "/home/wasabi/.walletwasabi/backend/WabiSabiConfig.json",
    )

    global coordinator
    coordinator = WasabiBackend(
        host=wasabi_backend_ip if args.proxy else args.control_ip,
        port=37127 if args.proxy else wasabi_backend_ports[37127],
        internal_ip=wasabi_backend_ip,
        proxy=args.proxy,
    )
    coordinator.wait_ready()
    print("- started wasabi-backend")

    distributor_version = SCENARIO.get(
        "distributor_version", SCENARIO["default_version"]
    )
    wasabi_client_distributor_ip, wasabi_client_distributor_ports = driver.run(
        "wasabi-client-distributor",
        f"{args.image_prefix}wasabi-client:{distributor_version}",
        env={
            "ADDR_BTC_NODE": args.btc_node_ip or node.internal_ip,
            "ADDR_WASABI_BACKEND": args.wasabi_backend_ip or coordinator.internal_ip,
        },
        ports={37128: 37128},
        cpu=1.0,
        memory=2048,
    )
    global distributor
    distributor = init_wasabi_client(
        distributor_version,
        wasabi_client_distributor_ip if args.proxy else args.control_ip,
        port=37128 if args.proxy else wasabi_client_distributor_ports[37128],
        name="wasabi-client-distributor",
        delay=(0, 0),
        stop=(0, 0),
    )
    if not distributor.wait_wallet(timeout=60):
        print(f"- could not start distributor (application timeout)")
        raise Exception("Could not start distributor")
    print("- started distributor")


def fund_distributor(btc_amount):
    print("Funding distributor")
    for _ in range(DISTRIBUTOR_UTXOS):
        node.fund_address(
            distributor.get_new_address(),
            math.ceil(btc_amount * BTC / DISTRIBUTOR_UTXOS) // BTC,
        )
    while (balance := distributor.get_balance()) < btc_amount * BTC:
        sleep(1)
    print(f"- funded (current balance {balance / BTC:.8f} BTC)")


def init_wasabi_client(version, ip, port, name, delay, stop):
    return WasabiClient(version)(
        host=ip,
        port=port,
        name=name,
        proxy=args.proxy,
        version=version,
        delay=delay,
        stop=stop,
    )


def start_client(idx, wallet):
    version = wallet.get("version", SCENARIO["default_version"])

    if "anon_score_target" in wallet:
        anon_score_target = wallet["anon_score_target"]
    else:
        anon_score_target = SCENARIO.get("default_anon_score_target", None)

    if anon_score_target is not None and version < "2.0.3":
        anon_score_target = None
        print(
            f"Anon Score Target is ignored for wallet {idx} as it is curently supported only for version 2.0.3 and newer"
        )

    if "redcoin_isolation" in wallet:
        redcoin_isolation = wallet["redcoin_isolation"]
    else:
        redcoin_isolation = SCENARIO.get("default_redcoin_isolation", None)

    if redcoin_isolation is not None and version < "2.0.3":
        redcoin_isolation = None
        print(
            f"Redcoin isolation is ignored for wallet {idx} as it is curently supported only for version 2.0.3 and newer"
        )

    sleep(random.random() * 3)
    name = f"wasabi-client-{idx:03}"
    try:
        ip, manager_ports = driver.run(
            name,
            f"{args.image_prefix}wasabi-client:{version}",
            env={
                "ADDR_BTC_NODE": args.btc_node_ip or node.internal_ip,
                "ADDR_WASABI_BACKEND": args.wasabi_backend_ip
                or coordinator.internal_ip,
                "WASABI_ANON_SCORE_TARGET": (
                    str(anon_score_target) if anon_score_target else None
                ),
                "WASABI_REDCOIN_ISOLATION": (
                    str(redcoin_isolation) if redcoin_isolation else None
                ),
            },
            ports={37128: 37129 + idx},
            cpu=(0.3 if version < "2.0.4" else 0.1),
            memory=(1024 if version < "2.0.4" else 768),
        )
    except Exception as e:
        print(f"- could not start {name} ({e})")
        return None

    delay = (wallet.get("delay_blocks", 0), wallet.get("delay_rounds", 0))
    stop = (wallet.get("stop_blocks", 0), wallet.get("stop_rounds", 0))
    client = init_wasabi_client(
        version,
        ip if args.proxy else args.control_ip,
        37128 if args.proxy else manager_ports[37128],
        f"wasabi-client-{idx:03}",
        delay,
        stop,
    )

    start = time()
    if not client.wait_wallet(timeout=60):
        print(
            f"- could not start {name} (application timeout {time() - start} seconds)"
        )
        return None
    print(f"- started {client.name} (wait took {time() - start} seconds)")
    return client


def start_clients(wallets):
    print("Starting clients")
    with multiprocessing.pool.ThreadPool() as pool:
        new_clients = pool.starmap(start_client, enumerate(wallets, start=len(clients)))

        for _ in range(3):
            restart_idx = list(
                map(
                    lambda x: x[0],
                    filter(
                        lambda x: x[1] is None,
                        enumerate(new_clients, start=len(clients)),
                    ),
                )
            )

            if not restart_idx:
                break
            print(f"- failed to start {len(restart_idx)} clients; retrying ...")
            for idx in restart_idx:
                driver.stop(f"wasabi-client-{idx:03}")
            sleep(60)
            restarted_clients = pool.starmap(
                start_client,
                ((idx, wallets[idx - len(clients)]) for idx in restart_idx),
            )
            for idx, client in enumerate(restarted_clients):
                if client is not None:
                    new_clients[restart_idx[idx]] = client
        else:
            new_clients = list(filter(lambda x: x is not None, new_clients))
            print(
                f"- failed to start {len(wallets) - len(new_clients)} clients; continuing ..."
            )
    clients.extend(new_clients)


def prepare_invoices(wallets):
    print("Preparing invoices")
    client_invoices = [
        (client, wallet.get("funds", [])) for client, wallet in zip(clients, wallets)
    ]

    global invoices
    for client, funds in client_invoices:
        for fund in funds:
            block = 0
            round = 0
            if isinstance(fund, int):
                value = fund
            elif isinstance(fund, dict):
                value = fund.get("value", 0)
                block = fund.get("delay_blocks", 0)
                round = fund.get("delay_rounds", 0)
            addressed_invoice = (client.get_new_address(), value)
            if (block, round) not in invoices:
                invoices[(block, round)] = [addressed_invoice]
            else:
                invoices[(block, round)].append(addressed_invoice)

    for addressed_invoices in invoices.values():
        random.shuffle(addressed_invoices)

    print(f"- prepared {sum(map(len, invoices.values()))} invoices")


def pay_invoices(addressed_invoices):
    print(
        f"- paying {len(addressed_invoices)} invoices (batch size {BATCH_SIZE}, block {current_block}, round {current_round})"
    )
    try:
        for batch in utils.batched(addressed_invoices, BATCH_SIZE):
            for _ in range(3):
                try:
                    result = distributor.send(batch)
                    if str(result) == "timeout":
                        print("- transaction timeout")
                        continue
                    break
                except Exception as e:
                    # https://github.com/zkSNACKs/WalletWasabi/issues/12764
                    if "Bad Request" in str(e):
                        print("- transaction error (bad request)")
                    else:
                        print(f"- transaction error ({e})")
            else:
                print("- invoice payment failed")
                raise Exception("Invoice payment failed")

    except Exception as e:
        print("- invoice payment failed")
        raise e


def start_coinjoin(client):
    sleep(random.random() / 10)
    client.start_coinjoin()


def stop_coinjoin(client):
    sleep(random.random() / 10)
    client.stop_coinjoin()


def update_coinjoins():
    def start_condition(client):
        if client.stop[0] > 0 and current_block >= client.stop[0]:
            return False
        if client.stop[1] > 0 and current_round >= client.stop[1]:
            return False
        if current_block < client.delay[0]:
            return False
        if current_round < client.delay[1]:
            return False
        return True

    start, stop = [], []
    for client in clients:
        if start_condition(client):
            start.append(client)
        else:
            stop.append(client)

    with multiprocessing.pool.ThreadPool() as pool:
        pool.starmap(start_coinjoin, ((client,) for client in start))

    with multiprocessing.pool.ThreadPool() as pool:
        pool.starmap(stop_coinjoin, ((client,) for client in stop))


def update_invoice_payments():
    due = list(
        filter(
            lambda x: x[0] <= current_block and x[1] <= current_round, invoices.keys()
        )
    )
    for i in due:
        pay_invoices(invoices.pop(i, []))


def stop_coinjoins():
    print("Stopping coinjoins")
    for client in clients:
        client.stop_coinjoin()
        print(f"- stopped mixing {client.name}")


def store_client_logs(client, data_path):
    sleep(random.random() * 3)
    client_path = os.path.join(data_path, client.name)
    os.mkdir(client_path)
    with open(os.path.join(client_path, "coins.json"), "w") as f:
        json.dump(client.list_coins(), f, indent=2)
        print(f"- stored {client.name} coins")
    with open(os.path.join(client_path, "unspent_coins.json"), "w") as f:
        json.dump(client.list_unspent_coins(), f, indent=2)
        print(f"- stored {client.name} unspent coins")
    with open(os.path.join(client_path, "keys.json"), "w") as f:
        json.dump(client.list_keys(), f, indent=2)
        print(f"- stored {client.name} keys")
    try:
        driver.download(client.name, "/home/wasabi/.walletwasabi/client/", client_path)

        print(f"- stored {client.name} logs")
    except:
        print(f"- could not store {client.name} logs")


def store_logs():
    print("Storing logs")
    time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    experiment_path = f"./logs/{time}_{SCENARIO['name']}"
    data_path = os.path.join(experiment_path, "data")
    os.makedirs(data_path)

    with open(os.path.join(experiment_path, "scenario.json"), "w") as f:
        json.dump(SCENARIO, f, indent=2)
        print("- stored scenario")

    stored_blocks = 0
    node_path = os.path.join(data_path, "btc-node")
    os.mkdir(node_path)
    while stored_blocks < node.get_block_count():
        block_hash = node.get_block_hash(stored_blocks)
        block = node.get_block_info(block_hash)
        with open(os.path.join(node_path, f"block_{stored_blocks}.json"), "w") as f:
            json.dump(block, f, indent=2)
        stored_blocks += 1
    print(f"- stored {stored_blocks} blocks")

    try:
        driver.download(
            "wasabi-backend",
            "/home/wasabi/.walletwasabi/backend/",
            os.path.join(data_path, "wasabi-backend"),
        )

        print(f"- stored backend logs")
    except:
        print(f"- could not store backend logs")

    # TODO parallelize (driver cannot be simply passed to new threads)
    for client in clients:
        store_client_logs(client, data_path)

    shutil.make_archive(experiment_path, "zip", *os.path.split(experiment_path))
    print("- zip archive created")


def run():

    try:
        print(f"=== Scenario {SCENARIO['name']} ===")
        prepare_images()
        start_infrastructure()
        fund_distributor(1000)
        start_clients(SCENARIO["wallets"])
        prepare_invoices(SCENARIO["wallets"])

        print("Running simulation")
        global current_round
        global current_block
        initial_block = node.get_block_count()
        while (SCENARIO["rounds"] == 0 or current_round < SCENARIO["rounds"]) and (
            SCENARIO["blocks"] == 0 or current_block < SCENARIO["blocks"]
        ):
            for _ in range(3):
                try:
                    current_round = sum(
                        1
                        for _ in driver.peek(
                            "wasabi-backend",
                            "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt",
                        ).split("\n")[:-1]
                    )
                    break
                except Exception as e:
                    print(f"- could not get rounds".ljust(60), end="\r")
                    print(f"Round exception: {e}", file=sys.stderr)

            for _ in range(3):
                try:
                    current_block = node.get_block_count() - initial_block
                    break
                except Exception as e:
                    print(f"- could not get blocks".ljust(60), end="\r")
                    print(f"Block exception: {e}", file=sys.stderr)

            update_invoice_payments()
            update_coinjoins()
            print(
                f"- coinjoin rounds: {current_round} (block {current_block})".ljust(60),
                end="\r",
            )
            sleep(1)
        print()
        print(f"- limit reached")
    except KeyboardInterrupt:
        print()
        print("KeyboardInterrupt received")
    except Exception as e:
        print(f"Terminating exception: {e}", file=sys.stderr)
    finally:
        stop_coinjoins()
        if not args.no_logs:
            store_logs()
        driver.cleanup(args.image_prefix)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    subparsers = parser.add_subparsers(dest="command", title="command")

    parser.add_argument(
        "--driver",
        type=str,
        choices=["docker", "podman", "kubernetes"],
        default="docker",
    )
    parser.add_argument("--no-logs", action="store_true", default=False)

    build_subparser = subparsers.add_parser("build", help="build images")
    build_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    build_subparser.add_argument("--namespace", type=str, default="coinjoin")
    build_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )

    run_subparser = subparsers.add_parser("run", help="run simulation")
    run_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    run_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )
    run_subparser.add_argument(
        "--scenario", type=str, help="scenario specification file"
    )
    run_subparser.add_argument(
        "--btc-node-ip", type=str, help="override btc-node ip", default=""
    )
    run_subparser.add_argument(
        "--wasabi-backend-ip",
        type=str,
        help="override wasabi-backend ip",
        default="",
    )
    run_subparser.add_argument(
        "--control-ip", type=str, help="control ip", default="localhost"
    )
    run_subparser.add_argument("--proxy", type=str, default="")
    run_subparser.add_argument("--namespace", type=str, default="coinjoin")
    run_subparser.add_argument("--reuse-namespace", action="store_true", default=False)

    clean_subparser = subparsers.add_parser("clean", help="clean up")
    clean_subparser.add_argument("--namespace", type=str, default="coinjoin")
    clean_subparser.add_argument(
        "--reuse-namespace", action="store_true", default=False
    )
    clean_subparser.add_argument("--proxy", type=str, default="")
    clean_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )

    genscen_subparser = subparsers.add_parser("genscen", help="generate scenario file")
    manager.commands.genscen.setup_parser(genscen_subparser)

    args = parser.parse_args()

    if args.command == "genscen":
        manager.commands.genscen.handler(args)
        exit(0)

    match args.driver:
        case "docker":
            from manager.driver.docker import DockerDriver

            driver = DockerDriver(args.namespace)
        case "podman":
            from manager.driver.podman import PodmanDriver

            driver = PodmanDriver()
        case "kubernetes":
            from manager.driver.kubernetes import KubernetesDriver

            driver = KubernetesDriver(args.namespace, args.reuse_namespace)
        case _:
            print(f"Unknown driver '{args.driver}'")
            exit(1)

    if args.command == "run":
        if args.scenario:
            with open(args.scenario) as f:
                SCENARIO.update(json.load(f))

    versions.add(SCENARIO["default_version"])
    if "distributor_version" in SCENARIO:
        versions.add(SCENARIO["distributor_version"])
    for wallet in SCENARIO["wallets"]:
        if "version" in wallet:
            versions.add(wallet["version"])

    match args.command:
        case "build":
            prepare_images()
        case "clean":
            driver.cleanup(args.image_prefix)
        case "run":
            run()
        case _:
            print(f"Unknown command '{args.command}'")
            exit(1)
