import logging
import time
import multiprocessing
import bots.config.types
import requests

from bots.services.service import Service
from bots.services.multiprocessing import threaded
from bots.vega_sim.network import network_from_devops_network_name

from vega_sim.scenario.constants import Network
from vega_sim.devops.scenario import DevOpsScenario
from vega_sim.network_service import VegaServiceNetwork

from vega_sim.devops.wallet import ScenarioWallet
from vega_sim.devops.scenario import DevOpsScenario
from vega_sim.devops.classes import (
    MarketMakerArgs,
    MarketManagerArgs,
    AuctionTraderArgs,
    RandomTraderArgs,
    SensitiveTraderArgs,
    SimulationArgs,
)

from vega_sim.api.market import MarketConfig
# , SpotMarketConfig


from vega_sim.scenario.common.utils.price_process import Granularity


class ScenarioService(Service):
    def __init__(
        self,
        name: str,
        scenario_config: dict[str, any],
        vega: VegaServiceNetwork,
        network: str,
        scenario: DevOpsScenario,
    ) -> None:
        self.name = name
        self.vega = vega
        self.scenario_config = scenario_config
        self.network = network
        self.scenario = scenario
        self.logger = logging.getLogger(f"scenario-{name}")
        self.running = False

    def check(self):
        self.logger.info("Checking if all required wallet exists for scenario")
        # TBD

    def wait(self):
        for i in range(1, 10):
            self.logger.info("Waiting for vegawallet to start")
            try:
                r = requests.get("http://127.0.0.1:1789/api/v2/health")
                if r.status_code >= 200 and r.status_code < 300:
                    self.logger.info("Wallet started")
                    time.sleep(3)
                    return
                # prints the int of the status code. Find more at httpstatusrappers.com :)
            except requests.ConnectionError:
                pass

            time.sleep(3)


    @threaded
    def start(self):
        self.logger.info("Starting scenario")

        self.running = True
        self.scenario.market_name = self.scenario_config.market_name
        self.scenario.step_length_seconds = self.scenario_config.step_length_seconds
        self.scenario.run_iteration(
            vega=self.vega,
            network=Network[self.network],
            pause_at_completion=False,
            raise_datanode_errors=False,
            raise_step_errors=False,
            run_with_snitch=False,
        )
        self.running = False


def services_from_config(
    vega_sim_network_name: str,
    scenarios_wallets: dict[str, ScenarioWallet],
    scenarios_config: bots.config.types.ScenariosConfigType,
    network_config_path: str,
    wallet_config: bots.config.types.WalletConfig,
    wallet_mutex: multiprocessing.Lock,
) -> list[Service]:
    if scenarios_config is None or len(scenarios_config) < 1:
        raise ValueError("Cannot create services because scenarios are none")

    scenarios = _scenarios_from_config(scenarios_config, scenarios_wallets)

    services = []

    vega_network = network_from_devops_network_name(
        vega_sim_network_name, wallet_config.home, network_config_path, wallet_config.binary, wallet_mutex
    )
    for scenario_name in scenarios:


        services.append(
            ScenarioService(
                scenario_name,
                scenarios_config[scenario_name],
                vega_network,
                vega_sim_network_name,
                scenarios[scenario_name],
            )
        )

    return services


def _scenarios_from_config(
    config: bots.config.types.ScenariosConfigType, scenarios_wallets: dict[str, ScenarioWallet]
) -> dict[str, DevOpsScenario]:
    result = {}

    for scenario_name in config:
        result.update(
            {
                f"{scenario_name}": DevOpsScenario(
                    binance_code=config[scenario_name].binance_code,
                    feed_price_multiplier=config[scenario_name].feed_price_multiplier,
                    market_manager_args=MarketManagerArgs(
                        # market_name=config[scenario_name].market_name,
                        # market_code=config[scenario_name].market_code,
                        # asset_name=config[scenario_name].market_manager.asset_name,
                        # adp=config[scenario_name].market_manager.adp,
                        # mdp=config[scenario_name].market_manager.mdp,
                        # pdp=config[scenario_name].market_manager.pdp,
                        market_config=MarketConfig({
                            "decimalPlaces": str(config[scenario_name].market_manager.mdp),
                            "positionDecimalPlaces": str(config[scenario_name].market_manager.pdp),
                            "instrument": {
                                "code": config[scenario_name].market_code,
                                "name": config[scenario_name].market_name,
                            }
                        })
                    ),
                    market_maker_args=MarketMakerArgs(
                        market_kappa=config[scenario_name].market_maker.market_kappa,
                        market_order_arrival_rate=config[scenario_name].market_maker.market_order_arrival_rate,
                        order_kappa=config[scenario_name].market_maker.order_kappa,
                        order_size=config[scenario_name].market_maker.order_size,
                        order_levels=config[scenario_name].market_maker.order_levels,
                        order_spacing=config[scenario_name].market_maker.order_spacing,
                        order_clipping=config[scenario_name].market_maker.order_clipping,
                        inventory_lower_boundary=config[scenario_name].market_maker.inventory_lower_boundary,
                        inventory_upper_boundary=config[scenario_name].market_maker.inventory_upper_boundary,
                        fee_amount=config[scenario_name].market_maker.fee_amount,
                        commitment_amount=config[scenario_name].market_maker.commitment_amount,
                        initial_mint=config[scenario_name].market_maker.initial_mint,
                        isolated_margin_factor=config[scenario_name].market_maker.isolated_margin_factor,
                    ),
                    auction_trader_args=AuctionTraderArgs(
                        initial_volume=config[scenario_name].auction_trader.initial_volume,
                        initial_mint=config[scenario_name].auction_trader.initial_mint,
                    ),
                    random_trader_args=RandomTraderArgs(
                        order_intensity=config[scenario_name].random_trader.order_intensity,
                        order_volume=config[scenario_name].random_trader.order_volume,
                        step_bias=config[scenario_name].random_trader.step_bias,
                        initial_mint=config[scenario_name].random_trader.initial_mint,
                    ),
                    sensitive_trader_args=SensitiveTraderArgs(
                        scale=config[scenario_name].sensitive_trader.scale,
                        max_order_size=config[scenario_name].sensitive_trader.max_order_size,
                        initial_mint=config[scenario_name].sensitive_trader.initial_mint,
                    ),
                    simulation_args=SimulationArgs(
                        n_steps=config[scenario_name].simulation.n_steps,
                        granularity=_dispatch_granularity(config[scenario_name].simulation.granularity),
                        coinbase_code=config[scenario_name].simulation.coinbase_code,
                        start_date=config[scenario_name].simulation.start_date,
                        randomise_history=config[scenario_name].simulation.randomise_history,
                    ),
                    scenario_wallet=scenarios_wallets[scenario_name] if scenario_name in scenarios_wallets else None,
                )
            }
        )

    return result


def _dispatch_bool(val: str) -> bool:
    if isinstance(val, bool):
        return val

    return val.lower() in ["true", "t", "on"]


def _dispatch_granularity(val: str) -> Granularity:
    if val == "MINUTE":
        return Granularity.MINUTE
    elif val == "FIVE_MINUTE":
        return Granularity.FIVE_MINUTE
    elif val == "FIFTEEN_MINUTE":
        return Granularity.FIFTEEN_MINUTE
    elif val == "HOUR":
        return Granularity.HOUR
    elif val == "SIX_HOUR":
        return Granularity.SIX_HOUR
    elif val == "DAY":
        return Granularity.DAY
    else:
        return int(val)
