from __future__ import annotations


def _generate_wallet_keypair() -> tuple[str, str, str]:
    """Returns (pk_hex, seed_phrase_or_empty, wallet_address)."""
    try:
        from pytoniq_core.crypto.keys import mnemonic_new, mnemonic_to_private_key
        words = mnemonic_new(24)
        _, priv_bytes = mnemonic_to_private_key(words)
        pk_hex = bytes(priv_bytes).hex()
        seed = " ".join(words)
    except ImportError:
        import secrets
        pk_hex = secrets.token_bytes(32).hex()
        seed = ""

    from settings import _derive_wallet_address
    address = _derive_wallet_address(pk_hex, False)
    return pk_hex, seed, address
