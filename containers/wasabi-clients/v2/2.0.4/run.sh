#!/bin/bash
if [ -z "$ADDR_BTC_NODE" ]; then
    export ADDR_BTC_NODE="btc-node"
fi
if [ -z "$ADDR_WASABI_BACKEND" ]; then
    export ADDR_WASABI_BACKEND="wasabi-backend"
fi
mkdir -p /home/wasabi/.walletwasabi/client
( echo "cat <<EOF" ; cat /home/wasabi/Config.json ; echo EOF ) | sh > /home/wasabi/.walletwasabi/client/Config.json
./WalletWasabi.Daemon