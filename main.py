import logging
import os.path
import signal
import argparse

from bots.services.multiprocessing import service_manager
from bots.services.scenario import services_from_config
from bots.services.healthcheck import HealthCheckService
from bots.services.vega_wallet import VegaWalletService
from bots.config.config import read_config, local_network_config_path, ensure_wallet_token_file
from bots.vega_sim.network import market_sim_network_from_devops_network_name, network_from_devops_network_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("-c", "--config", default="./config.toml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    config = read_config(args.config)
    scenarios_config = dict() if "scenario" not in config else config["scenario"]

    vegawallet_config = config["vegawallet"]
    services = [
        HealthCheckService(host="0.0.0.0", port=8080),
        VegaWalletService(
            vegawallet_config.get("binary"), 
            vegawallet_config.get("network", "mainnet-mirror"), 
            vegawallet_config.get("passphrase_file"), 
            vegawallet_config.get("home"), 
            vegawallet_config.get("wallet_name")
        ),
    ]

    
    os.environ["VEGA_USER_WALLET_NAME"] = "vegamarketsim"
    os.environ["VEGA_WALLET_TOKENS_PASSPHRASE_FILE"] = vegawallet_config.get("passphrase_file")
    
    devops_network_name = vegawallet_config.get("network", "mainnet-mirror")
    market_sim_network_name = market_sim_network_from_devops_network_name(devops_network_name)
    
    base_path = os.path.abspath("./network")
    network_config_path = local_network_config_path(config.get("network_config_file"), devops_network_name, base_path)
    wallet_token_path = ensure_wallet_token_file("vegamarketsim", vegawallet_config.get("api_token", ""), base_path)
    vega_network = network_from_devops_network_name(devops_network_name, base_path, wallet_token_path)
    services += services_from_config(vega_network, market_sim_network_name, scenarios_config)

    


    processes = service_manager(services)

    signal.sigwait([signal.SIGINT, signal.SIGKILL,signal.SIGABRT, signal.SIGTERM, signal.SIGQUIT])
    logging.info("Program received stop signal")

    for process in processes:
        process.kill()
    

   

if __name__ == "__main__":
    main()
