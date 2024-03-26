from io import BytesIO
import os
import tarfile
from . import Driver
import podman
import docker


class PodmanDriver(Driver):
    def __init__(self):
        self.client = podman.PodmanClient()

    def has_image(self, name):
        try:
            docker.from_env().images.get(name)
            return True
        except docker.errors.ImageNotFound:
            return False

    def build(self, name, path):
        docker.from_env().images.build(path=path, tag=name, rm=True, nocache=True)

    def pull(self, name):
        docker.from_env().images.pull(name)

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
            stream, _ = docker.from_env().containers.get(name).get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)

            print(f"- stored backend logs")
        except:
            print(f"- could not store backend logs")

    def peek(self, name, path):
        stream, _ = docker.from_env().containers.get(name).get_archive(path)

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
        docker.from_env().containers.get(name).put_archive(
            os.path.dirname(dst_path), fo
        )

    def cleanup(self, image_prefix="", versions=None):
        image_names = set([
            f"{image_prefix}btc-node",
            f"{image_prefix}wasabi-backend"])
        
        if versions:
            for version in versions:
                image_names.add(f"{image_prefix}wasabi-client-{version}")

        containers = list(
            filter(
                lambda x: x.attrs["Config"]["Image"] in image_names,
                docker.from_env().containers.list(),
            )
        )
        self.stop_many(map(lambda x: x.name, containers))
