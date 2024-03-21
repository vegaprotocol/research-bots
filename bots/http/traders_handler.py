import flask
import datetime
import logging
import json
import multiprocessing
import bots.config.types
import bots.api.datanode
import bots.config.types

from vega_sim.devops.wallet import ScenarioWallet
from typing import Optional
from bots.api.helpers import by_key
from bots.http.handler import Handler
from bots.wallet.cli import VegaWalletCli
from dataclasses import dataclass, asdict


def is_trader(wallet_name: str) -> bool:
    trader_names = ["market_maker", "auction_trader", "random_trader", "sensitive_trader"]
    return any([trader_name in wallet_name for trader_name in trader_names])


def get_config_attr_name(wallet_name: str) -> str:
    trader_names = ["market_maker", "auction_trader", "random_trader", "sensitive_trader"]
    for trader_name in trader_names:
        if trader_name in wallet_name:
            return trader_name

    raise RuntimeError(f"Attribute unknown for {wallet_name}")


def _get_party_id_to_wanted_token_map(scenario_config: bots.config.types.ScenarioConfig, wallet_keys: dict[str, str]) -> dict[str, float]:
    result = {}

    for wallet_name in wallet_keys:
        if not is_trader(wallet_name):
            continue

        trader_kind = get_config_attr_name(wallet_name)
        trader_params = getattr(scenario_config, trader_kind)

        result[wallet_keys[wallet_name]] = float(trader_params.initial_mint)

    return result

@dataclass
class WantedToken:
    party_id: str
    symbol: str
    vega_asset_id: str
    asset_erc20_address: str
    balance: float
    wanted_tokens: float

@dataclass
class WalletWantedTokens:
    entries: list[WantedToken]

    def as_dict_for_party(self, party_id: str) -> dict:
        result = []
        for wanted_token_entry in [entry for entry in self.entries if entry.party_id == party_id]:
            result = result + [asdict(wanted_token_entry)]

        return result


class Traders(Handler):
    cache_ttl = datetime.timedelta(minutes=1)
    logger = logging.getLogger("report-traders")

    def __init__(
        self,
        host: str,
        port: int,
        scenarios: bots.config.types.ScenariosConfigType,
        api_endpoints: list[str],
        wallet: VegaWalletCli,
        wallet_name: str,
        scenario_wallets: dict[str, ScenarioWallet],
        tokens: list[str],
    ):
        self.host = host
        self.port = port
        self.webserver = None
        self.scenarios = scenarios
        self.api_endpoints = api_endpoints
        self.wallet = wallet
        self.wallet_name = wallet_name
        self.scenario_wallets = scenario_wallets

        # TODO: filter by valid market statuses
        self.markets = by_key(
            bots.api.datanode.get_markets(api_endpoints),
            lambda market: market["tradableInstrument"]["instrument"]["name"],
        )
        self.assets = by_key(bots.api.datanode.get_assets(api_endpoints), lambda asset: asset["id"])

        self.response_cache = None
        self.cache_lock = multiprocessing.Lock()
        self.invalidate_cache = None

        self._tokens = tokens

    def serve(self):
        # for authenticated user we do not want to cache the response
        if self._is_authenticated():
            Traders.logger.info("Serving response without cache for authenticated user")
            resp = self.prepare_response()
        else:
            resp = self._cached_response()
            if resp is None:
                Traders.logger.info("Refreshing cache for traders response")
                with self.cache_lock:
                    cached_resp = self._cached_response()
                    if not cached_resp is None:
                        return cached_resp

                    self.response_cache = self.prepare_response()
                    self.invalidate_cache = datetime.datetime.now() + Traders.cache_ttl
                    resp = self.response_cache
            else:
                Traders.logger.info("Serving traders response from cache")

        json_data = json.dumps({"traders": resp}, indent="    ")
        resp = flask.Response(json_data)
        resp.headers["Content-Type"] = "application/json"
        return resp

    def _cached_response(self) -> Optional[dict[str, dict[str, any]]]:
        if self.invalidate_cache is None:
            return None

        if datetime.datetime.now() > self.invalidate_cache:
            Traders.logger.info("The /traders response cache is too old")
            return None

        return self.response_cache

    def _is_authenticated(self) -> bool:
        if not "Authorization" in flask.request.headers:
            return False

        if len(self._tokens) < 1:
            return False

        authorization_header = flask.request.headers["Authorization"]

        header_parts = authorization_header.split()
        authorization_token = header_parts[-1]

        return authorization_token in self._tokens

    def prepare_response(self) -> dict[str, dict[str, any]]:
        wallet_state = self.wallet.state

        traders = dict()
        for scenario in self.scenarios:
            scenario_config = self.scenarios[scenario]
            scenario_market_name = scenario_config.market_name
            if not scenario_market_name in self.markets:
                Traders.logger.error(
                    f"Market {scenario_market_name} not found in market downloaded from API, traders cannot be reported. There is a config for given market_name"
                )

            scenario_market = self.markets[scenario_market_name]
            assets_ids = self._vega_asset_id_for_market(scenario_market)
            market_id = scenario_market["id"]
            market_tags = self._metadata_for_market(scenario_market)

            base = market_tags["ticker"] if "ticker" in market_tags else ""
            base = market_tags["base"] if "base" in market_tags else base

            wallet_keys = self.wallet.list_keys(scenario)
            wanted_balances = _get_party_id_to_wanted_token_map(scenario_config, wallet_keys)
            assets_ids = self._vega_asset_id_for_market(scenario_market)
            balances = self._compute_wanted_tokens_for_wallet(
                market_id,
                assets_ids,
                wallet_keys.values(),
                wanted_balances,
            )

            scenario_wallet_state = wallet_state.get(scenario, None)

            reported_wallets_count = {}
            for wallet_name in wallet_keys:
                if not is_trader(wallet_name):
                    continue

                trader_pub_key = wallet_keys[wallet_name]
                trader_kind = get_config_attr_name(wallet_name)
                trader_params = getattr(scenario_config, trader_kind)
                # check if we already returned all required wallets. We do not want to return more than enough.
                if is_enough_wallets_reported(trader_kind, trader_params, reported_wallets_count):
                    continue

                reported_wallets_for_trader_kind = reported_wallets_count.get(trader_kind, 0)
                reported_wallets_count[trader_kind] = reported_wallets_for_trader_kind+1

                trader_key = f"{scenario}_{market_id}_{wallet_name}"
                traders[trader_key] = {
                    "name": f"{market_id}_{wallet_name}",
                    "pubKey": trader_pub_key,
                    "parameters": {
                        "marketBase": base,
                        "marketQuote": market_tags["quote"] if "quote" in market_tags else "",
                        # "marketSettlementEthereumContractAddress": scenario_asset["details"]["erc20"][
                        #     "contractAddress"
                        # ],
                        # "marketSettlementVegaAssetID": vega_asset_id,
                        "wantedTokens": balances.as_dict_for_party(trader_pub_key),
                        # "wantedTokens": trader_params.initial_mint,
                        # "balance": float(trader_balance)
                        # / (pow(10, int(self.assets[vega_asset_id]["details"]["decimals"]))),
                        "enableTopUp": scenario_config.enable_top_up,
                    },
                }

                public_key = "*** unknown ***"
                index = -1
                if scenario_wallet_state is not None and trader_pub_key in scenario_wallet_state.keys:
                    public_key = scenario_wallet_state.keys[trader_pub_key].public_key
                    index = scenario_wallet_state.keys[trader_pub_key].index

                traders[trader_key]["wallet"] = {
                    "index": index,
                    "publicKey": public_key,
                }

                if scenario_wallet_state is not None and self._is_authenticated():
                    traders[trader_key]["wallet"][
                        "recoveryPhrase"
                    ] = scenario_wallet_state.recovery_phrase

        return traders

    def _compute_wanted_tokens_for_wallet(self, market_id: str, assets_ids: list[str], wallet_keys: list[str], party_id_to_wanted_balance_map: dict[str, float]) -> WalletWantedTokens:
        entries = []

        for asset_id in assets_ids:
            if not asset_id in self.assets:
                Traders.logger.error(
                    f"Missing asset {asset_id} on the network"
                )

                raise RuntimeError(f"Missing asset {asset_id} on the network")
            asset = self.assets[asset_id]

            if not "erc20" in asset["details"]:
                Traders.logger.error(
                    f"Market created for non ERC20 asset({asset_id}). NON ERC20 assets are not supported"
                )
                continue

            accounts = bots.api.datanode.get_accounts(self.api_endpoints, asset_id)
            # create mapping party_id => balance

            party_to_balance_map = {}
            for account in accounts:
                if account.owner not in party_to_balance_map:
                    party_to_balance_map[account.owner] = 0.0

                if account.market_id not in ["", market_id]:
                        continue

                if not account.type in ["ACCOUNT_TYPE_GENERAL", "ACCOUNT_TYPE_MARGIN", "ACCOUNT_TYPE_BOND"]:
                    continue

                party_to_balance_map[account.owner] += float(account.balance) / (pow(10, int(asset["details"]["decimals"])))


            for party_id in wallet_keys:
                entries = entries + [
                    WantedToken(
                        party_id=party_id, 
                        symbol=asset["details"]["symbol"], 
                        vega_asset_id=asset["id"],
                        asset_erc20_address=asset["details"]["erc20"]["contractAddress"],
                        balance=(party_to_balance_map[party_id] if party_id in party_to_balance_map else 0.0),
                        wanted_tokens=(party_id_to_wanted_balance_map[party_id] if party_id in party_id_to_wanted_balance_map else 0.0),
                    )
                ]

        return WalletWantedTokens(entries)

    def _vega_asset_id_for_market(self, market: dict[str, any]) -> list[str]:
        if not "tradableInstrument" in market:
            return None

        if not "instrument" in market["tradableInstrument"]:
            return None

        if "future" in market["tradableInstrument"]["instrument"]:
            return [market["tradableInstrument"]["instrument"]["future"]["settlementAsset"]]

        if "perpetual" in market["tradableInstrument"]["instrument"]:
            return [market["tradableInstrument"]["instrument"]["perpetual"]["settlementAsset"]]

        if "spot" in market["tradableInstrument"]["instrument"]:
            return [
                market["tradableInstrument"]["instrument"]["spot"]["quoteAsset"],
                market["tradableInstrument"]["instrument"]["spot"]["baseAsset"],
            ]

    def _metadata_for_market(self, market: dict[str, any]) -> dict[str, str]:
        if not "tradableInstrument" in market:
            return dict()
        if not "instrument" in market["tradableInstrument"]:
            return dict()
        if not "metadata" in market["tradableInstrument"]["instrument"]:
            return dict()
        if not "tags" in market["tradableInstrument"]["instrument"]["metadata"]:
            return dict()

        return {
            item.split(":")[0]: item.split(":")[1]
            for item in market["tradableInstrument"]["instrument"]["metadata"]["tags"]
            if len(item.split(":")) >= 2
        }

def is_enough_wallets_reported(trader_type: str, traders_params: any, reported_traders: dict[str, int]) -> bool:
    """
    Return true if no more wallets needed.
    """
    reported_traders_num = reported_traders.get(trader_type, 0)
    maximum_traders = getattr(traders_params, "traders", 999999999)

    return maximum_traders <= reported_traders_num

def from_config(
    config: bots.config.types.BotsConfig,
    wallet_cli: VegaWalletCli,
    scenario_wallets: dict[str, ScenarioWallet],
    tokens: list[str],
) -> Traders:
    return Traders(
        host=config.http_server.interface,
        port=config.http_server.port,
        scenarios=config.scenarios,
        api_endpoints=config.network_config.api.rest.hosts,
        wallet=wallet_cli,
        wallet_name=config.wallet.wallet_name,
        scenario_wallets=scenario_wallets,
        tokens=[token for token in tokens if len(token) > 1],
    )
