from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..config import AppConfig


class SecretStoreError(RuntimeError):
    pass


class SecretStore(Protocol):
    def save_secret(self, reference: str, secret: str) -> None:
        ...

    def has_secret(self, reference: str) -> bool:
        ...


class LocalSecretStore:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(self.path)
        self.path.chmod(0o600)

    def save_secret(self, reference: str, secret: str) -> None:
        values = self._read()
        values[reference] = secret
        self._write(values)

    def has_secret(self, reference: str) -> bool:
        values = self._read()
        return reference in values and values[reference] != ""


class AwsSecretsManagerStore:
    def __init__(self, region_name: str | None = None):
        self.region_name = region_name

    def _client(self):
        try:
            import boto3  # type: ignore
            from botocore.exceptions import ClientError  # type: ignore
        except ImportError as exc:
            raise SecretStoreError("boto3 is required to update AWS Secrets Manager secrets") from exc
        return boto3.client("secretsmanager", region_name=self.region_name), ClientError

    def save_secret(self, reference: str, secret: str) -> None:
        client, client_error = self._client()
        try:
            client.put_secret_value(SecretId=reference, SecretString=secret)
        except client_error as exc:
            raise SecretStoreError(f"Unable to update AWS secret '{reference}'") from exc

    def has_secret(self, reference: str) -> bool:
        client, client_error = self._client()
        try:
            client.describe_secret(SecretId=reference)
        except client_error:
            return False
        return True


def secret_store_for_config(config: AppConfig, provider: str) -> SecretStore:
    if provider == "aws":
        return AwsSecretsManagerStore()
    if provider == "local":
        return LocalSecretStore(config.config_path.parent / ".gpmpe-secrets.json")
    raise SecretStoreError(f"Unsupported secret provider '{provider}'")
