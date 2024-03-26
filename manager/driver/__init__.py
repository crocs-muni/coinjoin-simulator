from abc import ABC, abstractmethod
from multiprocessing.pool import ThreadPool


class Driver(ABC):
    @abstractmethod
    def has_image(self, name):
        pass

    @abstractmethod
    def build(self, name, path):
        pass

    @abstractmethod
    def pull(self, name):
        pass

    @abstractmethod
    def run(
        self,
        name,
        image,
        env=None,
        ports=None,
        skip_ip=False,
        cpu=0.1,
        memory=768,
    ):
        pass

    @abstractmethod
    def stop(self, name):
        pass

    def stop_many(self, names):
        with ThreadPool() as p:
            p.map(lambda x: self.stop(x), names)

    @abstractmethod
    def download(self, name, src_path, dst_path):
        pass

    @abstractmethod
    def peek(self, name, path):
        pass

    @abstractmethod
    def upload(self, name, src_path, dst_path):
        pass

    @abstractmethod
    def cleanup(self, image_prefix="", versions=None):
        pass
