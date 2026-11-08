"""Remote server lists have no fixed limit: a Matricxon cluster can have hundreds of nodes, all remote."""

from app.schemas import LlamaCppServerConfig, MatricxonServerConfig, SdCppConfig
from app.schemas.cluster_outside import OutsideRemove


def test_hundreds_of_remote_hosts_are_accepted_for_every_engine() -> None:
    hosts = [f"http://10.0.{i // 250}.{i % 250 + 1}:8420" for i in range(500)]
    assert len(MatricxonServerConfig(mode="remote", remote_hosts=hosts).remote_hosts) == 500
    assert len(MatricxonServerConfig(cluster_hosts=hosts, voter_hosts=hosts).cluster_hosts) == 500
    assert len(LlamaCppServerConfig(mode="remote", remote_hosts=hosts).remote_hosts) == 500
    assert len(SdCppConfig(mode="remote", remote_hosts=hosts).remote_hosts) == 500
    assert len(OutsideRemove(hosts=hosts * 2).hosts) == 1000
