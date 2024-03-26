from .wasabi_client_base import WasabiClientBase, WALLET_NAME
from time import sleep, time
from .client_versions_enum import VersionsEnum

class WasabiClientV1(WasabiClientBase):

    def __init__(self, 
                 host="localhost", 
                 port=37128, 
                 name="wasabi-client", 
                 delay=0, 
                 proxy="", 
                 version=VersionsEnum["1.1.12.9"],
                 skip_rounds=[]
                 ):
        super().__init__(host, port, name, delay, proxy, version, skip_rounds)

    def select(self, timeout=5, repeat=10):
        request = {
            "method": "selectwallet",
            "params": [WALLET_NAME]
        }
        self._rpc(request, False, timeout=timeout, repeat=repeat)

    def wait_wallet(self, timeout=None):
        start = time()
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except:
                pass

            try:
                self.select(timeout=5)
                self.get_balance(timeout=5)
                return True
            except:
                pass

            sleep(0.1)
        return False
    
    def list_coins(self):
        raise Exception("This method is not yet implemented in the wallet wasabi, need to be patched.")

    def enqueue(self, coins):
        request = {
            "method": "enqueue",
            "params": {
                "coins": list(coins),
                "password": ""
            }
        }
        return self._rpc(request, repeat=3)

    def enqueue_all(self):
        coins = self.list_unspent_coins()
        confirmed_coins = filter(lambda x: x["confirmed"], coins)

        coins = list(map(lambda x: {"transactionid": x["txid"], "index": x["index"]}, confirmed_coins))
        return self.enqueue(coins)

    def dequeue(self, coins):
        request = {
            "method": "dequeue",
            "params": {
                "coins": list(coins),
                "password": ""
            }
        }
        return self._rpc(request, repeat=3)
    
    def dequeue_all(self):
        coins = self.list_unspent_coins()
        confirmed_coins = filter(lambda x: x["confirmed"], coins)

        coins = list(map(lambda x: {"transactionid": x["txid"], "index": x["index"]}, confirmed_coins))
        return self.dequeue(coins)

    def start_coinjoin(self):
        response = self.enqueue_all()
        self.active = True
        return response
    
    def stop_coinjoin(self):
        response = self.dequeue_all()
        self.active = False
        return response

