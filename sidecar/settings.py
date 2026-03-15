import os
from dataclasses import dataclass
@dataclass
class ArgSchema:
    name: str
    type: str
    description: str
    required: bool


@dataclass
class Settings:
    agent_command: str
    capability: str
    agent_name: str
    agent_description: str
    agent_price: int
    agent_endpoint: str
    agent_wallet: str
    agent_wallet_pk: str
    agent_wallet_seed: str | None
    registry_address: str
    port: int
    payment_timeout: int
    sync_timeout: int
    final_timeout: int
    jobs_ttl: int
    toncenter_base_url: str
    toncenter_api_key: str | None
    state_path: str
    tx_db_path: str
    docs_path: str
    ton_storage_base_url: str
    ton_storage_session: str | None
    enforce_comment_nonce: bool
    refund_fee_nanoton: int
    storage_extend_threshold_days: int
    args_schema: list[ArgSchema]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _parse_args_schema() -> list[ArgSchema]:
    result: list[ArgSchema] = []
    prefix = "AGENT_ARG_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        arg_name = key[len(prefix) :].strip().lower()
        chunks = value.split(":")
        if len(chunks) < 2:
            raise ValueError(f"Invalid {key} format; expected type:description[:optional]")

        arg_type = chunks[0].strip().lower()
        description = chunks[1].strip()
        optional = len(chunks) > 2 and chunks[2].strip().lower() == "optional"

        if arg_type not in {"string", "number", "boolean"}:
            raise ValueError(f"Invalid type for {key}: {arg_type}")

        result.append(
            ArgSchema(
                name=arg_name,
                type=arg_type,
                description=description,
                required=not optional,
            )
        )

    result.sort(key=lambda item: item.name)
    return result


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
        "AGENT_WALLET",
        "AGENT_WALLET_PK",
        "REGISTRY_ADDRESS",
    ]
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return Settings(
        agent_command=os.environ["AGENT_COMMAND"],
        capability=os.environ["AGENT_CAPABILITY"],
        agent_name=os.environ["AGENT_NAME"],
        agent_description=os.environ["AGENT_DESCRIPTION"],
        agent_price=int(os.environ["AGENT_PRICE"]),
        agent_endpoint=os.environ["AGENT_ENDPOINT"],
        agent_wallet=os.environ["AGENT_WALLET"],
        agent_wallet_pk=os.environ["AGENT_WALLET_PK"],
        agent_wallet_seed=os.getenv("AGENT_WALLET_SEED"),
        registry_address=os.environ["REGISTRY_ADDRESS"],
        port=int(os.getenv("PORT", "8080")),
        payment_timeout=int(os.getenv("PAYMENT_TIMEOUT", "300")),
        sync_timeout=int(os.getenv("AGENT_SYNC_TIMEOUT", "30")),
        final_timeout=int(os.getenv("AGENT_FINAL_TIMEOUT", "1200")),
        jobs_ttl=int(os.getenv("JOBS_TTL_SECONDS", "3600")),
        toncenter_base_url=os.getenv("TONCENTER_BASE_URL", "https://toncenter.com/api/v3"),
        toncenter_api_key=os.getenv("TONCENTER_API_KEY"),
        state_path=os.getenv("SIDECAR_STATE_PATH", ".sidecar_state.json"),
        tx_db_path=os.getenv("SIDECAR_TX_DB_PATH", "processed_txs.db"),
        docs_path=os.getenv("DOCS_PATH", "docs.json"),
        ton_storage_base_url=os.getenv("TON_STORAGE_BASE_URL", "https://mytonstorage.org"),
        ton_storage_session=os.getenv("TON_STORAGE_SESSION"),
        enforce_comment_nonce=_env_bool("ENFORCE_COMMENT_NONCE", True),
        refund_fee_nanoton=int(os.getenv("REFUND_FEE_NANOTON", "500000")),
        storage_extend_threshold_days=int(os.getenv("STORAGE_EXTEND_THRESHOLD_DAYS", "7")),
        args_schema=_parse_args_schema(),
    )


