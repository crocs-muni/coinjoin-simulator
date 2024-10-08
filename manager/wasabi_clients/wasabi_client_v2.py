from .wasabi_client_base import WasabiClientBase, WALLET_NAME
from time import sleep, time


class WasabiClientV2(WasabiClientBase):

    def __init__(
        self,
        host="localhost",
        port=37128,
        name="wasabi-client",
        proxy="",
        version="2.0.3",
        delay=(0, 0),
        stop=(0, 0),
    ):
        super().__init__(host, port, name, proxy, version, delay, stop)

    def select(self, timeout=5, repeat=10):
        request = {"method": "selectwallet", "params": [WALLET_NAME]}
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
