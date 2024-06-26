import argparse
import json
import os
import sys
import numpy.random
import copy

SCENARIO_TEMPLATE = {
    "name": "template",
    "rounds": 0,
    "blocks": 0,
    "backend": {
        "MaxInputCountByRound": 400,
        "MinInputCountByRoundMultiplier": 0.01,
        "StandardInputRegistrationTimeout": "0d 0h 20m 0s",
        "ConnectionConfirmationTimeout": "0d 0h 6m 0s",
        "OutputRegistrationTimeout": "0d 0h 6m 0s",
        "TransactionSigningTimeout": "0d 0h 6m 0s",
        "FailFastTransactionSigningTimeout": "0d 0h 6m 0s",
        "RoundExpiryTimeout": "0d 0h 10m 0s",
    },
    "wallets": [],
}


def setup_parser(parser: argparse.ArgumentParser):
    parser.add_argument("--name", type=str, help="scenario name")
    parser.add_argument(
        "--client-count", type=int, default=10, help="number of wallets"
    )
    parser.add_argument(
        "--distribution",
        type=str,
        default="lognorm",
        help="fund distribution strategy",
    )
    parser.add_argument(
        "--utxo-count", type=int, default=30, help="number of UTXOs per wallet"
    )
    parser.add_argument(
        "--max-coinjoin",
        type=int,
        default=400,
        help="maximal number of inputs to a coinjoin",
    )
    parser.add_argument(
        "--min-coinjoin",
        type=int,
        default=4,
        help="minimal number of inputs to a coinjoin",
    )
    parser.add_argument(
        "--stop-round",
        type=int,
        default=0,
        help="terminate after N coinjoin rounds, 0 for no limit",
    )
    parser.add_argument(
        "--stop-block",
        type=int,
        default=0,
        help="terminate after N blocks, 0 for no limit",
    )
    parser.add_argument(
        "--skip-rounds",
        type=str,
        required=False,
        help="skip rounds ('random[fraction]' for randomly sampled fraction of rounds, or comma-separated list of rounds to skip)",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument(
        "--out-dir", type=str, default="scenarios", help="output directory"
    )
    parser.add_argument(
        "--distributor-version",
        type=str,
        required=False,
        help="version of the distibutor wallet",
    )
    parser.add_argument(
        "--client-version",
        type=str,
        required=False,
        help="version of the client wallet",
    )
    parser.add_argument(
        "--anon-score-target",
        type=int,
        required=False,
        help="default anon score target used for wallets",
    )
    parser.add_argument(
        "--redcoin-isolation",
        type=bool,
        required=False,
        help="default redcoin isolation setting used for wallets",
    )


def handler(args):
    print("Generating scenario...")
    scenario = copy.deepcopy(SCENARIO_TEMPLATE)
    scenario["name"] = args.name or (
        f"{args.distribution}-static-{args.client_count}-{args.utxo_count}utxo"
    )

    scenario["backend"]["MaxInputCountByRound"] = args.max_coinjoin
    scenario["backend"]["MinInputCountByRoundMultiplier"] = (
        args.min_coinjoin / args.max_coinjoin
    )
    scenario["rounds"] = args.stop_round
    scenario["blocks"] = args.stop_block

    if args.distributor_version:
        scenario["distributor_version"] = args.distributor_version

    if args.client_version:
        scenario["default_version"] = args.client_version

    if args.anon_score_target:
        scenario["default_anon_score_target"] = args.anon_score_target

    if args.redcoin_isolation:
        scenario["default_redcoin_isolation"] = args.redcoin_isolation

    delays = [0] * args.client_count

    skip_rounds = None
    if args.skip_rounds:
        if args.skip_rounds.startswith("random"):
            if args.stop_round == 0:
                print("- cannot use random skip rounds with no stop round")
                sys.exit(1)

            fraction = 2 / 3
            if args.skip_rounds != "random":
                try:
                    fraction = float(args.skip_rounds.split("[")[1].split("]")[0])
                except IndexError:
                    print("- random skip rounds fraction parsing failed")
                    sys.exit(1)
            print(f"- skipping {fraction * 100:.2f}% of rounds")

            skip_rounds = lambda _: sorted(
                map(
                    int,
                    numpy.random.choice(
                        range(0, args.stop_round),
                        size=int(args.stop_round * fraction),
                        replace=False,
                    ),
                )
            )
        else:
            try:
                skip_rounds = lambda idx: (
                    sorted(map(int, args.skip_rounds.split(",")))
                    if idx < args.client_count // 2
                    else []
                )
            except ValueError:
                print("- invalid skip rounds list")
                sys.exit(1)

    for idx, delay in enumerate(delays):
        wallet = dict()
        wallet["delay"] = delay

        dist_name = args.distribution.split("[")[0]
        dist_params = None
        if "[" in args.distribution:
            dist_params = map(
                float, args.distribution.split("[")[1].split("]")[0].split(",")
            )

        match dist_name:
            case "uniform":
                dist_params = dist_params or [0.0, 1.0]
                dist = numpy.random.uniform(*dist_params, args.utxo_count)
                funds = map(round, dist * 10_000_000)
            case "pareto":
                dist_params = dist_params or [1.16]
                dist = numpy.random.pareto(*dist_params, args.utxo_count)
                funds = map(round, dist * 1_000_000)
            case "uniformsum":
                dist_params = dist_params or [0.0, 1.0]
                dist = numpy.random.uniform(*dist_params, args.utxo_count)
                funds = map(round, list(dist / sum(dist) * 100_000_000))
            case "paretosum":
                dist_params = dist_params or [1.16]
                dist = numpy.random.pareto(*dist_params, args.utxo_count)
                funds = map(round, list(dist / sum(dist) * 100_000_000))
            case "lognorm":
                # parameters estimated from mainnet data of Wasabi 2.0 coinjoins
                dist_params = dist_params or [14.1, 2.29]
                dist = numpy.random.lognormal(*dist_params, args.utxo_count)
                funds = map(round, dist // 10)
            case _:
                print("- invalid distribution")
                sys.exit(1)
        wallet["funds"] = list(funds)

        if skip_rounds:
            wallet["skip_rounds"] = skip_rounds(idx)

        scenario["wallets"].append(wallet)

    print(
        f"- requires {(sum(map(lambda x: sum(x['funds']), scenario['wallets'])) / 100_000_000):0.8f} BTC"
    )

    os.makedirs(args.out_dir, exist_ok=True)
    if os.path.exists(f"{args.out_dir}/{scenario['name']}.json") and not args.force:
        print(f"- file {args.out_dir}/{scenario['name']}.json already exists")
        sys.exit(1)

    with open(f"{args.out_dir}/{scenario['name']}.json", "w") as f:
        json.dump(scenario, f, indent=2)

    print(f"- saved to {args.out_dir}/{scenario['name']}.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a scenario file")
    setup_parser(parser)
    handler(parser.parse_args())
