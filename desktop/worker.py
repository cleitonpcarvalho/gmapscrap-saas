from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from selenium.common.exceptions import TimeoutException, WebDriverException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scrapers.email_scraper import extract_email_from_site  # noqa: E402
from backend.scrapers.maps_scraper import scrape_google_maps  # noqa: E402
from desktop.api_client import ApiClientError, GmapScrapApiClient  # noqa: E402


class SearchWorker(QObject):
    log = Signal(str)
    progress = Signal(dict)
    finished = Signal(bool, str)

    def __init__(self, niche: str, location: str, quantity: int | None, max_results: bool):
        super().__init__()
        self.niche = niche
        self.location = location
        self.quantity = quantity
        self.max_results = max_results
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True
        self.log.emit("Parada solicitada. A busca será interrompida no próximo ponto seguro.")

    @Slot()
    def run(self) -> None:
        client: GmapScrapApiClient | None = None
        run_id: int | None = None
        last_run: dict | None = None
        finish_status = "completed"
        finish_message = "Busca concluída."
        scanned_count = 0

        try:
            client = GmapScrapApiClient.from_environment()
            self.log.emit("Conectando na API de produção...")
            client.login()
            self.log.emit("API conectada.")

            run = client.create_search(self.niche, self.location, self.quantity, self.max_results)
            last_run = run
            run_id = int(run["id"])
            self.progress.emit(run)
            self.log.emit(f"Execução #{run_id} criada.")
            self.log.emit("Abrindo Google Maps no Chrome headless local...")

            target_quantity = None if self.max_results else self.quantity

            for event in scrape_google_maps(self.niche, self.location):
                if self._stop_requested:
                    finish_status = "paused"
                    finish_message = "Busca interrompida no aplicativo desktop."
                    break

                scanned_count = max(scanned_count, event.scanned)

                if event.kind == "done":
                    finish_message = _completion_message(event.message, target_quantity, last_run)
                    self.log.emit(event.message)
                    break

                if event.kind == "skip" or event.lead is None:
                    run = client.update_search(
                        run_id,
                        status="running",
                        message=event.message,
                        scanned_count=scanned_count,
                        skipped_delta=1,
                    )
                    last_run = run
                    self.progress.emit(run)
                    self.log.emit(event.message)
                    continue

                self.log.emit(f"{event.lead.name} encontrado. Buscando e-mail em {event.lead.website}...")
                try:
                    email_result = extract_email_from_site(event.lead.website)
                except Exception:
                    run = client.update_search(
                        run_id,
                        status="running",
                        message=f"{event.lead.name} ignorado: erro ao buscar e-mail.",
                        scanned_count=scanned_count,
                        skipped_delta=1,
                    )
                    last_run = run
                    self.progress.emit(run)
                    self.log.emit(f"{event.lead.name} ignorado: erro ao buscar e-mail.")
                    continue

                if not email_result.email:
                    run = client.update_search(
                        run_id,
                        status="running",
                        message=f"{event.lead.name} ignorado: e-mail não encontrado.",
                        scanned_count=scanned_count,
                        skipped_delta=1,
                    )
                    last_run = run
                    self.progress.emit(run)
                    self.log.emit(f"{event.lead.name} ignorado: e-mail não encontrado.")
                    continue

                response = client.ingest_lead(
                    run_id,
                    scanned=scanned_count,
                    name=event.lead.name,
                    address=event.lead.address,
                    phone=event.lead.phone,
                    website=event.lead.website,
                    email=email_result.email,
                )
                run = response["run"]
                last_run = run
                self.progress.emit(run)
                self.log.emit(response["message"])

                if target_quantity and int(run["saved_count"]) >= target_quantity:
                    finish_message = "Quantidade solicitada concluída."
                    break

            if self._stop_requested:
                finish_status = "paused"
                finish_message = "Busca interrompida no aplicativo desktop."

            if run_id and client:
                run = client.update_search(
                    run_id,
                    status=finish_status,
                    message=finish_message,
                    scanned_count=scanned_count,
                )
                last_run = run
                self.progress.emit(run)

            self.finished.emit(finish_status == "completed", finish_message)
        except Exception as exc:
            message = _friendly_error(exc)
            self.log.emit(message)

            if run_id and client:
                try:
                    run = client.update_search(run_id, status="failed", message=message, error=message)
                    self.progress.emit(run)
                except ApiClientError as api_exc:
                    self.log.emit(f"Não foi possível atualizar a falha na API: {api_exc}")

            self.finished.emit(False, message)


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ApiClientError):
        return str(exc)

    if isinstance(exc, TimeoutException):
        return "Google Maps não carregou os resultados dentro do tempo limite."

    def clean(value: str) -> str:
        message = value.split("Stacktrace:", 1)[0]
        message = re.sub(r"^Message:\s*", "", message.strip(), flags=re.IGNORECASE)
        message = re.sub(r"\s+", " ", message).strip()
        return "" if message.lower() in {"message", "message:"} else message

    if isinstance(exc, WebDriverException):
        return clean(getattr(exc, "msg", "") or str(exc)) or "Google Maps não conseguiu completar a busca no Chrome local."

    return clean(str(exc)) or "Busca falhou por um erro inesperado."


def _completion_message(base_message: str, target_quantity: int | None, run: dict | None) -> str:
    message = base_message.strip() or "Busca concluída."
    if not target_quantity or not run:
        return message

    saved = int(run.get("saved_count") or 0)
    if saved >= target_quantity:
        return "Quantidade solicitada concluída."

    return f"{message} Foram salvos {saved} de {target_quantity} leads solicitados."
