from abc import ABC, abstractmethod


class HypervisorProvider(ABC):

    @abstractmethod
    def available(self) -> bool:
        pass

    @abstractmethod
    def create_vm(
        self,
        name: str,
        cpus: int,
        memory_mb: int,
    ) -> None:
        pass

    @abstractmethod
    def create_disk(
        self,
        vm_name: str,
        size_gb: int,
    ) -> None:
        pass

    @abstractmethod
    def attach_iso(
        self,
        vm_name: str,
        iso_path: str,
    ) -> None:
        pass

    @abstractmethod
    def start_vm(self, name: str) -> None:
        pass

    @abstractmethod
    def stop_vm(self, name: str) -> None:
        pass

    @abstractmethod
    def delete_vm(self, name: str) -> None:
        pass

    @abstractmethod
    def vm_exists(self, name: str) -> bool:
        pass
