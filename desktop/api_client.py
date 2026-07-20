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
    pass


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
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/desktop/searches",
            json={
                "niche": niche,
                "location": location,
                "quantity": quantity,
                "max_results": max_results,
                "skip_without_website": skip_without_website,
                "validate_whatsapp": validate_whatsapp,
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
        return self._request("PATCH", f"/api/desktop/searches/{run_id}", json=payload)

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

    def _request(self, method: str, path: str, *, timeout: int = 30, retry: bool = True, **kwargs: Any) -> Any:
        if not self._authenticated:
            self.login()

        response = self._send_with_retries(method, path, timeout=timeout, **kwargs)

        if response.status_code == 401 and retry:
            self._authenticated = False
            self.login()
            return self._request(method, path, timeout=timeout, retry=False, **kwargs)

        if not response.ok:
            raise ApiClientError(self._error_message(response, "A API recusou a operação."))

        if not response.content:
            return None
        return response.json()

    def _send_with_retries(self, method: str, path: str, *, timeout: int, **kwargs: Any) -> requests.Response:
        transient_statuses = {502, 503, 504}
        last_error: requests.RequestException | None = None

        for attempt in range(4):
            try:
                response = self.session.request(method, f"{self.config.base_url}{path}", timeout=timeout, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(1.5 * (attempt + 1))
                continue

            if response.status_code not in transient_statuses or attempt == 3:
                return response

            time.sleep(1.5 * (attempt + 1))

        raise ApiClientError(f"Falha ao chamar a API: {last_error}") from None

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
