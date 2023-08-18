import logging
import multiprocessing
from typing import Optional

from vega_sim.network_service import VegaServiceNetwork
from vega_sim.scenario.constants import Network

def market_sim_network_from_devops_network_name(net_name: str) -> str:
    mapping = {
        "devnet1": "DEVNET1",
        "stagnet1": "STAGNET1",
        "fairground": "FAIRGROUND",
        "mainnet-mirror": "MAINNET_MIRROR",
        "mainnet_mirror": "MAINNET_MIRROR"
    }

    return mapping[net_name]


def network_from_devops_network_name(vega_sim_network_name: str, network_config_path: str, wallet_binary: str, wallet_mutex: Optional[multiprocessing.Lock] = None) -> VegaServiceNetwork:
    logging.info(f"Creating the vega network service for {vega_sim_network_name}")
    return VegaServiceNetwork(
        network=Network[vega_sim_network_name],
        wallet_path=wallet_binary,
        run_with_console=False,
        run_with_wallet=False,
        governance_symbol = "VEGA",
        network_config_path = network_config_path,
        wallet_mutex = wallet_mutex,
    )