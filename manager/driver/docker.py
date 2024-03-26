from functools import cached_property
from io import BytesIO
import os
import tarfile
from . import Driver
import docker


class DockerDriver(Driver):
    def __init__(self, namespace="coinjoin"):
        self.client = docker.from_env()
        self._namespace = namespace

    @cached_property
    def network(self):
        return self.client.networks.create(self._namespace, driver="bridge")

    def has_image(self, name):
        try:
            self.client.images.get(name)
            return True
        except docker.errors.ImageNotFound:
            return False

    def build(self, name, path):
        self.client.images.build(path=path, tag=name, rm=True, nocache=True)

    def pull(self, name):
        self.client.images.pull(name)

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
        self.client.containers.run(
            image,
            detach=True,
            auto_remove=True,
            name=name,
            hostname=name,
            network=self.network.id,
            ports=ports or {},
            environment=env or {},
        )
        return "", ports

    def stop(self, name):
        try:
            self.client.containers.get(name).stop()
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name, src_path, dst_path):
        try:
            stream, _ = self.client.containers.get(name).get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)
        except:
            pass

    def peek(self, name, path):
        stream, _ = self.client.containers.get(name).get_archive(path)

        fo = BytesIO()
        for d in stream:
            fo.write(d)
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            return tar.extractfile(os.path.basename(path)).read().decode()

    def upload(self, name, src_path, dst_path):
        fo = BytesIO()
        with tarfile.open(fileobj=fo, mode="w") as tar:
            tar.add(src_path, os.path.basename(dst_path))
        fo.seek(0)
        self.client.containers.get(name).put_archive(os.path.dirname(dst_path), fo)

    def cleanup(self, image_prefix="", versions=None):
        image_names = set([
            f"{image_prefix}btc-node",
            f"{image_prefix}wasabi-backend",])
        
        if versions:
            for version in versions:
                image_names.add(f"{image_prefix}wasabi-client-{version}")

        containers = list(
            filter(
                lambda x: x.attrs["Config"]["Image"] in image_names,
                self.client.containers.list(),
            )
        )

        self.stop_many(map(lambda x: x.name, containers))
        networks = self.client.networks.list(self._namespace)
        if networks:
            for network in networks:
                network.remove()
