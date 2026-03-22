"""Generate a new WalletV4R2 keypair for use as AGENT_WALLET_PK / AGENT_WALLET_SEED.
The wallet address is derived automatically from the private key at runtime."""
from pytoniq_core.crypto.keys import mnemonic_new, mnemonic_to_private_key
from tonutils.contracts.wallet import WalletV4R2
from tonutils.types import PrivateKey

words = mnemonic_new(24)
_, priv_bytes = mnemonic_to_private_key(words)
pk = PrivateKey(bytes(priv_bytes))

wallet = WalletV4R2.from_private_key(None, pk)  # type: ignore[arg-type]
address = wallet.address.to_str(is_user_friendly=True, is_bounceable=False, is_url_safe=True)

print(f"# Wallet address (for reference): {address}")
print(f"AGENT_WALLET_PK={priv_bytes.hex()}")
print(f"AGENT_WALLET_SEED={' '.join(words)}")
