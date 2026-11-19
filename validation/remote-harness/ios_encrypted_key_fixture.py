"""Disposable OpenSSH identity for the iOS public-key loopback fixture."""
import secrets

from tauri_ios_direct_ssh import SingleCommandFixture


class EncryptedKeyFixture(SingleCommandFixture):
    """Generate a one-time encrypted OpenSSH identity entirely in this process."""
    def __init__(self, **options):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        expected = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        super().__init__(client_public_key=expected.decode().split()[1], **options)
        self.passphrase = secrets.token_hex(16)
        self.wrong_passphrase = ('0' if self.passphrase[0] != '0' else '1') + self.passphrase[1:]
        self.private_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                             serialization.BestAvailableEncryption(self.passphrase.encode())).decode()

    def close(self):
        try:
            super().close()
        finally:
            self.private_key = self.passphrase = self.wrong_passphrase = ''
