"""Use the OS Secret Service (including KWallet's Secret Service), never plaintext fallbacks."""

import hashlib

from omnicore.text.types import TextError


class SystemVault:
    def __init__(self, data_dir):
        self.namespace = hashlib.sha256(str(data_dir.resolve()).encode()).hexdigest()

    def backend(self):
        try:
            from keyring.backends.SecretService import Keyring

            backend = Keyring()
            if backend.priority <= 0:
                raise RuntimeError("Secret Service unavailable")
            return backend
        except Exception:
            raise TextError("provider_secret_store_unavailable", 503) from None

    def get(self, reference):
        try:
            value = self.backend().get_password(
                "OmniCore AI providers", self.namespace + ":" + reference
            )
        except Exception:
            raise TextError("provider_secret_store_unavailable", 503) from None
        if not value:
            raise TextError("provider_key_missing", 409)
        return value

    def put(self, reference, value):
        try:
            self.backend().set_password(
                "OmniCore AI providers", self.namespace + ":" + reference, value
            )
        except Exception:
            raise TextError("provider_secret_store_unavailable", 503) from None

    def delete(self, reference):
        try:
            backend = self.backend()
            name = self.namespace + ":" + reference
            if backend.get_password("OmniCore AI providers", name) is not None:
                backend.delete_password("OmniCore AI providers", name)
        except Exception:
            raise TextError("provider_secret_store_unavailable", 503) from None
