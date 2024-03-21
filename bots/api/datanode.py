import requests
import logging
import bots.api.types


from typing import Optional
from bots.api.http import get_call


def get_markets(endpoints: list[str]) -> any:
    for endpoint in endpoints:
        try:
            json_resp = get_call(f"{endpoint}/api/v2/markets")
        except:
            continue

        if not "markets" in json_resp:
            continue

        return [market["node"] for market in json_resp["markets"]["edges"]]

    raise requests.RequestException("all endpoints for /api/v2/markets did not return a valid response")


def check_market_exists(endpoints: list[str], market_names: list[str]):
    all_markets = get_markets(endpoints)
    all_markets_names = [market["tradableInstrument"]["instrument"]["name"] for market in all_markets]

    for required_market_name in market_names:
        if not required_market_name in all_markets_names:
            raise EnvironmentError(
                f'The market "{required_market_name}" is missing, it is required to exist on the network. Modify the config.toml file to correct the data.'
            )


def get_statistics(endpoints: list[str]) -> dict[str, any]:
    for endpoint in endpoints:
        try:
            json_resp = get_call(f"{endpoint}/statistics")
        except:
            continue

        if not "statistics" in json_resp:
            continue

        return json_resp["statistics"]

    raise requests.RequestException("all endpoints for /statistics did not return a valid response")


def get_assets(endpoints: list[str]) -> dict[str, any]:
    for endpoint in endpoints:
        try:
            json_resp = get_call(f"{endpoint}/api/v2/assets")
        except:
            continue

        if not "assets" in json_resp:
            continue

        return [asset["node"] for asset in json_resp["assets"]["edges"]]

    raise requests.RequestException("all endpoints for /statistics did not return a valid response")


def get_accounts(
    endpoints: list[str],
    asset_id: Optional[str] = None,
    parties: Optional[list[str]] = None,
    market_ids: Optional[list[str]] = None,
    afterCursor: Optional[str] = None,
) -> list[bots.api.types.Account]:
    query = []

    if not asset_id is None:
        query = query + [f"filter.assetId={asset_id}"]

    if not parties is None:
        parties_list = ",".join(parties)
        query = query + [f"filter.partyIds={parties_list}"]

    if not market_ids is None:
        markets_list = ",".join(market_ids)
        query = query + [f"filter.marketIds={markets_list}"]

    if not afterCursor is None:
        query = query + [f"pagination.after={afterCursor}"]

    url = "api/v2/accounts"

    if len(query) > 0:
        query_str = "&".join(query)
        url = f"{url}?{query_str}"

    for endpoint in endpoints:
        try:
            json_resp = get_call(f"{endpoint}/{url}")
        except:
            continue

        if not "accounts" in json_resp:
            continue

        response = []
        for edge in json_resp["accounts"]["edges"]:
            if not "node" in edge:
                continue
            response.append(
                bots.api.types.Account(
                    owner=edge["node"]["owner"],
                    balance=int(edge["node"]["balance"]),
                    asset=edge["node"]["asset"],
                    market_id=edge["node"]["marketId"],
                    type=edge["node"]["type"],
                )
            )

        if "pageInfo" in json_resp["accounts"] and "hasNextPage" in json_resp["accounts"]["pageInfo"] and json_resp["accounts"]["pageInfo"]["hasNextPage"]:
            return response + get_accounts(endpoints, asset_id, parties, market_ids, json_resp["accounts"]["pageInfo"]["endCursor"])

        return response

    raise requests.RequestException("all endpoints for /api/v2/assets did not return a valid response")
