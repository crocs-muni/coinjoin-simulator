from .wasabi_client_base import WasabiClientBase, WALLET_NAME
from time import sleep, time
from .client_versions_enum import VersionsEnum

class WasabiClientV204(WasabiClientBase):

    def __init__(self, 
                 host="localhost", 
                 port=37128, 
                 name="wasabi-client", 
                 delay=0, 
                 proxy="", 
                 version=VersionsEnum["2.0.4"],
                 skip_rounds=[]):
        super().__init__(host, port, name, delay, proxy, version, skip_rounds)
