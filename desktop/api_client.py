from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE_URL = "https://api.automasoluct.com.br"


class ApiClientError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


STOPPED_ERROR = "DESKTOP_STOPPED"


def search_status(run):
    if run.get("status") == "failed" and str(run.get("error") or "").startswith(STOPPED_ERROR):
        return "stopped"
    return run.get("status")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if key:
            values[key] = value

    return values


def _desktop_env_paths() -> tuple[Path, ...]:
    paths = [PROJECT_ROOT / ".env", Path.cwd() / ".env", Path.home() / ".gmapscrap-desktop.env"]
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        bundle_root = executable.parents[2] if len(executable.parents) > 2 else executable.parent
        paths.extend((bundle_root.parent / ".gmapscrap-desktop.env", bundle_root / "Contents" / "Resources" / ".env"))
    return tuple(dict.fromkeys(paths))


def load_local_environment() -> None:
    for path in _desktop_env_paths():
        for key, value in _read_env_file(path).items():
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    username: str
    password: str


def load_api_config() -> ApiConfig:
    load_local_environment()

    base_url = os.getenv("GMAPSCRAP_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
    username = os.getenv("GMAPSCRAP_API_USERNAME") or os.getenv("APP_USERNAME", "")
    password = os.getenv("GMAPSCRAP_API_PASSWORD") or os.getenv("APP_PASSWORD", "")

    if not username or not password:
        raise ApiClientError("Credenciais da API não encontradas no ambiente local.")

    return ApiConfig(base_url=base_url, username=username, password=password)


class GmapScrapApiClient:
    def __init__(self, config: ApiConfig):
        self.config = config
        self.session = requests.Session()
        self._authenticated = False
        self.control = None
        self.request_key = None

    @classmethod
    def from_environment(cls) -> "GmapScrapApiClient":
        return cls(load_api_config())

    def login(self) -> None:
        response = self._send_with_retries(
            "POST",
            "/api/auth/login",
            json={"username": self.config.username, "password": self.config.password},
            timeout=20,
        )

        if not response.ok:
            raise ApiClientError(self._error_message(response, "Login na API falhou."))

        self._authenticated = True

    def create_search(
        self,
        niche: str,
        location: str,
        quantity: int | None,
        max_results: bool,
        skip_without_website: bool,
        validate_whatsapp: bool,
        enrich_site_insights: bool = False,
        only_without_website: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/desktop/searches",
            attempts=1,  # Legacy production has no idempotency support; never retry creation blindly.
            headers={"Idempotency-Key": self.request_key} if self.request_key else {},
            json={
                "niche": niche,
                "location": location,
                "quantity": quantity,
                "max_results": max_results,
                "skip_without_website": skip_without_website,
                "only_without_website": only_without_website,
                "validate_whatsapp": validate_whatsapp,
                "enrich_site_insights": enrich_site_insights,
            },
        )

    def update_search(
        self,
        run_id: int,
        *,
        status: str | None = None,
        message: str | None = None,
        scanned_count: int | None = None,
        skipped_delta: int = 0,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "status": status,
            "message": message,
            "scanned_count": scanned_count,
            "skipped_delta": skipped_delta,
            "error": error,
        }
        return self._request("PATCH", f"/api/desktop/searches/{run_id}", json=payload,
                             attempts=1 if skipped_delta else 4)

    def stop_search(self, run_id: int, *, scanned_count=0):
        message = "Busca parada definitivamente. Leads salvos foram preservados."
        try:
            return self.update_search(run_id, status="stopped", message=message, scanned_count=scanned_count)
        except ApiClientError as exc:
            if exc.status_code != 422:
                raise
            # Old production accepts 'failed' as a terminal state and rejects further ingestion.
            return self.update_search(run_id, status="failed", message=message,
                                      scanned_count=scanned_count, error=STOPPED_ERROR)

    def ingest_lead(
        self,
        run_id: int,
        *,
        scanned: int,
        name: str,
        address: str,
        phone: str,
        website: str,
        email: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/desktop/searches/{run_id}/leads",
            json={
                "scanned": scanned,
                "name": name,
                "address": address,
                "phone": phone,
                "website": website,
                "email": email,
            },
            timeout=60,
        )

    def list_searches(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/searches", timeout=20)

    def get_search(self, run_id):
        return self._request("GET", f"/api/searches/{run_id}", timeout=20)

    def get_created_search(self, request_key):
        return self._request("GET", f"/api/desktop/searches/by-request/{request_key}", timeout=20)

    def list_niches(self, query: str = "") -> list[dict[str, Any]]:
        return self._request("GET", "/api/niches", params={"q": query}, timeout=20)

    def create_niche(self, name: str) -> dict[str, Any]:
        # Creating a registry entry is explicit and separate from starting a search.
        return self._request("POST", "/api/niches", json={"name": name}, timeout=20)

    def _request(self, method: str, path: str, *, timeout: int = 30, retry: bool = True, **kwargs: Any) -> Any:
        if not self._authenticated:
            self.login()

        response = self._send_with_retries(method, path, timeout=timeout, **kwargs)

        if response.status_code == 401 and retry:
            self._authenticated = False
            self.login()
            return self._request(method, path, timeout=timeout, retry=False, **kwargs)

        if not response.ok:
            raise ApiClientError(self._error_message(response, "A API recusou a operação."), response.status_code)

        if not response.content:
            return None
        return response.json()

    def _send_with_retries(self, method: str, path: str, *, timeout: int, attempts=4, **kwargs: Any) -> requests.Response:
        transient_statuses = {502, 503, 504}
        last_error: requests.RequestException | None = None

        for attempt in range(attempts):
            if self.control:
                self.control.checkpoint()
            try:
                response = self.session.request(method, f"{self.config.base_url}{path}", timeout=timeout, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                self._reset_connections()
                if attempt == attempts - 1:
                    break
                self._retry_sleep(1.5 * (attempt + 1))
                continue

            if response.status_code not in transient_statuses or attempt == attempts - 1:
                return response

            response.close()
            self._reset_connections()
            self._retry_sleep(1.5 * (attempt + 1))

        raise ApiClientError(f"Falha ao chamar a API: {last_error}") from None

    def _retry_sleep(self, seconds):
        if self.control:
            self.control.sleep(seconds)
        else:
            time.sleep(seconds)

    def _reset_connections(self) -> None:
        self.session.close()

    @staticmethod
    def _error_message(response: requests.Response, fallback: str) -> str:
        try:
            data = response.json()
        except ValueError:
            return f"{fallback} HTTP {response.status_code}"

        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, str) and detail:
            return detail
        return f"{fallback} HTTP {response.status_code}"
