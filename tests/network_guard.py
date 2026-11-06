"""Which local servers tests may reach (conftest._tests_never_reach_real_servers blocks all others): only the
ones a test starts itself, such as mcp_fake_server.FakeMcpServer."""


class LocalTestServers:
    ports: set[int] = set()

    @classmethod
    def allow(cls, port: int) -> None:
        cls.ports.add(port)

    @classmethod
    def allowed(cls, host: str, port: int | None) -> bool:
        return host in ("127.0.0.1", "localhost") and port in cls.ports
