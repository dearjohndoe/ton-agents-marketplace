import os
from dataclasses import dataclass


@dataclass
class Settings:
    agent_command: str
    capability: str
    agent_name: str
    agent_description: str
    agent_price: int
    agent_endpoint: str
    agent_wallet_pk: str
    agent_wallet_seed: str | None
    agent_wallet: str
    registry_address: str
    port: int
    payment_timeout: int
    sync_timeout: int
    final_timeout: int
    jobs_ttl: int
    testnet: bool
    state_path: str
    tx_db_path: str
    enforce_comment_nonce: bool
    refund_fee_nanoton: int
    has_quote: bool
    rate_limit_requests: int
    rate_limit_window: int
    file_store_dir: str
    file_store_ttl: int


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _derive_wallet_address(pk_hex: str, testnet: bool) -> str:
    from tonutils.contracts.wallet import WalletV4R2
    from tonutils.types import PrivateKey
    pk = PrivateKey(bytes.fromhex(pk_hex.removeprefix("0x")))
    wallet = WalletV4R2.from_private_key(None, pk)  # type: ignore[arg-type]
    return wallet.address.to_str(
        is_user_friendly=True,
        is_bounceable=False,
        is_url_safe=True,
        is_test_only=testnet,
    )


def load_settings(env_file: str | None = None) -> Settings:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=env_file)

    required_keys = [
        "AGENT_COMMAND",
        "AGENT_CAPABILITY",
        "AGENT_NAME",
        "AGENT_DESCRIPTION",
        "AGENT_PRICE",
        "AGENT_ENDPOINT",
        "AGENT_WALLET_PK",
        "REGISTRY_ADDRESS",
    ]
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    agent_wallet_pk = os.environ["AGENT_WALLET_PK"]
    testnet = _env_bool("TESTNET", False)

    return Settings(
        agent_command=os.environ["AGENT_COMMAND"],
        capability=os.environ["AGENT_CAPABILITY"],
        agent_name=os.environ["AGENT_NAME"],
        agent_description=os.environ["AGENT_DESCRIPTION"],
        agent_price=int(os.environ["AGENT_PRICE"]),
        agent_endpoint=os.environ["AGENT_ENDPOINT"],
        agent_wallet=_derive_wallet_address(agent_wallet_pk, testnet),
        agent_wallet_pk=agent_wallet_pk,
        agent_wallet_seed=os.getenv("AGENT_WALLET_SEED"),
        registry_address=os.environ["REGISTRY_ADDRESS"],
        port=int(os.getenv("PORT", "8080")),
        payment_timeout=int(os.getenv("PAYMENT_TIMEOUT", "300")),
        sync_timeout=int(os.getenv("AGENT_SYNC_TIMEOUT", "30")),
        final_timeout=int(os.getenv("AGENT_FINAL_TIMEOUT", "1200")),
        jobs_ttl=int(os.getenv("JOBS_TTL_SECONDS", "3600")),
        testnet=testnet,
        state_path=os.getenv("SIDECAR_STATE_PATH", ".sidecar_state.json"),
        tx_db_path=os.getenv("SIDECAR_TX_DB_PATH", "processed_txs.db"),
        enforce_comment_nonce=_env_bool("ENFORCE_COMMENT_NONCE", True),
        refund_fee_nanoton=int(os.getenv("REFUND_FEE_NANOTON", "500000")),
        has_quote=_env_bool("AGENT_HAS_QUOTE", False),
        rate_limit_requests=int(os.getenv("RATE_LIMIT_REQUESTS", "60")),
        rate_limit_window=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
        file_store_dir=os.getenv("FILE_STORE_DIR", "file_store"),
        file_store_ttl=int(os.getenv("FILE_STORE_TTL", "900")),
    )
