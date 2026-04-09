import dataclasses


@dataclasses.dataclass
class Interest:
    name: str


@dataclasses.dataclass
class Data:
    name: str
    content: bytes


class NDNAdapter:
    """Mock NDN adapter — swap internals for ndn-cxx/python-ndn bindings."""

    def create_interest(self, root_hash: str) -> Interest:
        return Interest(name=f"/tfp/content/{root_hash}")

    def express_interest(self, interest: Interest) -> Data:
        return Data(name=interest.name, content=b"mock_shard_data_" + interest.name.encode())
