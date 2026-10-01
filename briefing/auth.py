from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

import msal


class AuthError(RuntimeError):
    pass


class GraphAuth:
    """Delegated OAuth 2.0 via MSAL device code flow with a persistent token cache."""

    def __init__(self, client_id: str, authority: str, scopes: Sequence[str], cache_path: Path):
        self._scopes = list(scopes)
        self._cache_path = cache_path
        self._cache = msal.SerializableTokenCache()
        if cache_path.exists():
            self._cache.deserialize(cache_path.read_text())
        self._app = msal.PublicClientApplication(
            client_id, authority=authority, token_cache=self._cache
        )

    def get_token(self, interactive: bool = True) -> str:
        result = None
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(self._scopes, account=accounts[0])

        if not result:
            if not interactive:
                raise AuthError("No cached token. Run once interactively to sign in.")
            flow = self._app.initiate_device_flow(scopes=self._scopes)
            if "user_code" not in flow:
                raise AuthError(f"Could not start device flow: {flow.get('error_description')}")
            print(flow["message"], file=sys.stderr, flush=True)
            result = self._app.acquire_token_by_device_flow(flow)

        self._persist()
        if "access_token" not in result:
            raise AuthError(result.get("error_description") or str(result.get("error")))
        return result["access_token"]

    def sign_out(self) -> None:
        for account in self._app.get_accounts():
            self._app.remove_account(account)
        if self._cache_path.exists():
            self._cache_path.unlink()

    def _persist(self) -> None:
        if not self._cache.has_state_changed:
            return
        self._cache_path.write_text(self._cache.serialize())
        try:
            os.chmod(self._cache_path, 0o600)
        except OSError:
            pass
