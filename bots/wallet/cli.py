import bots.config.types
import bots.wallet.state
import subprocess
import json
import logging
import os.path


class VegaWalletCli:
    def __init__(self, wallet_config: bots.config.types.WalletConfig):
        self._wallet_config = wallet_config
        self._state = bots.wallet.state.WalletStateService(wallet_config.state_file)

    @property
    def state(self) -> bots.wallet.state.VegaWalletStateType:
        return self._state.state_as_struct()

    def _exec(self, args) -> dict:
        if len(self._wallet_config.home) > 0:
            args = args + [
                "--home",
                self._wallet_config.home,
            ]

        args = args + ["--output", "json"]

        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            err = proc.stderr.read()
            out = proc.stdout.read()
            if len(err) > 0:
                logging.error(err)
                raise RuntimeError(err)

            if len(out) < 1:
                return {}

            return json.loads(out)

    def _update_token_file(self, wallet_name: str, token: str):
        tokens = {}
        if os.path.exists(self._wallet_config.tokens_file):
            with open(self._wallet_config.tokens_file, "r") as file:
                tokens = json.load(file)

        tokens[wallet_name] = token

        json_object = json.dumps(tokens, indent=4)

        with open(self._wallet_config.tokens_file, "w+") as outfile:
            outfile.write(json_object)

    def is_initialized(self) -> bool:
        wallets = self.list_wallets()

        return len(wallets) > 0

    def init(self):
        args = [
            self._wallet_config.binary,
            "wallet",
            "init",
        ]

        self._exec(args)

        args = [
            self._wallet_config.binary,
            "wallet",
            "api-token",
            "init",
            "--passphrase-file",
            self._wallet_config.passphrase_file,
        ]

        self._exec(args)

        self.create_wallet("default")

    def generate_api_token(self, wallet_name: str) -> str:
        args = [
            self._wallet_config.binary,
            "wallet",
            "api-token",
            "generate",
            "--description",
            wallet_name,
            "--wallet-name",
            wallet_name,
            "--wallet-passphrase-file",
            self._wallet_config.passphrase_file,
            "--tokens-passphrase-file",
            self._wallet_config.passphrase_file,
        ]

        resp = self._exec(args)

        if not "token" in resp:
            raise RuntimeError("Invalid api-token generate response")

        self._update_token_file(wallet_name, resp["token"])

        return resp

    def list_wallets(self) -> list:
        args = [self._wallet_config.binary, "wallet", "list"]

        resp = self._exec(args)
        if not "wallets" in resp:
            return []

        return [wallet for wallet in resp["wallets"]]

    def wallet_exists(self, wallet_name: str) -> bool:
        wallets = self.list_wallets()

        return wallet_name in wallets

    def list_keys(self, wallet_name: str) -> dict[str, str]:
        wallets = self.list_wallets()

        if not wallet_name in wallets:
            raise RuntimeError(f"Wallet {wallet_name} does not exist")

        args = [
            self._wallet_config.binary,
            "wallet",
            "key",
            "list",
            "--wallet",
            wallet_name,
            "--passphrase-file",
            self._wallet_config.passphrase_file,
        ]

        resp = self._exec(args)

        if "keys" not in resp:
            return {}

        return {key["name"]: key["publicKey"] for key in resp["keys"]}

    def create_wallet(self, wallet_name: str):
        wallets = self.list_wallets()

        if wallet_name in wallets:
            raise RuntimeError(f"Wallet {wallet_name} already exists")

        args = [
            self._wallet_config.binary,
            "wallet",
            "create",
            "--wallet",
            wallet_name,
            "--passphrase-file",
            self._wallet_config.passphrase_file,
        ]

        resp = self._exec(args)

        if not "wallet" in resp:
            raise RuntimeError("Invalid response from create_wallet command")
        if not "key" in resp:
            raise RuntimeError("Invalid response from create_wallet command")
        # wallet_name: str, public_key: str, recovery_phrase: str
        self._state.add_wallet(
            wallet_name,
            resp["key"]["publicKey"],
            resp["wallet"]["recoveryPhrase"],
        )

        return resp["wallet"]

    def generate_key(self, wallet_name: str, key_name: str):
        wallets = self.list_wallets()

        if not wallet_name in wallets:
            raise RuntimeError(f"Wallet {wallet_name} does not exist")

        keys = self.list_keys(wallet_name)

        if key_name in keys:
            raise RuntimeError(f"Key {key_name} already exists for wallet {wallet_name}")

        args = [
            self._wallet_config.binary,
            "wallet",
            "key",
            "generate",
            "--meta",
            f"name:{key_name}",
            "--wallet",
            wallet_name,
            "--passphrase-file",
            self._wallet_config.passphrase_file,
        ]

        resp = self._exec(args)

        if not "publicKey" in resp:
            raise RuntimeError("Invalid response from generate_key command")

        self._state.add_key(
            wallet_name,
            key_name,
            resp["publicKey"],
            len(keys),
        )

        return resp

    def import_internal_networks(self):
        networks = [
            "https://raw.githubusercontent.com/vegaprotocol/networks-internal/main/stagnet1/vegawallet-stagnet1.toml",
            "https://raw.githubusercontent.com/vegaprotocol/networks-internal/main/mainnet-mirror/vegawallet-mainnet-mirror.toml",
            "https://raw.githubusercontent.com/vegaprotocol/networks-internal/main/fairground/vegawallet-fairground.toml",
            "https://raw.githubusercontent.com/vegaprotocol/networks-internal/main/devnet1/vegawallet-devnet1.toml",
        ]

        for network in networks:
            args = [
                self._wallet_config.binary,
                "wallet",
                "network",
                "import",
                "--from-url",
                network,
            ]

            self._exec(args)
