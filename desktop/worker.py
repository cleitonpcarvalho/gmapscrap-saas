from __future__ import annotations

import re
import sys
from pathlib import Path
from uuid import uuid4
from threading import RLock

from PySide6.QtCore import QObject, Signal, Slot
from selenium.common.exceptions import TimeoutException, WebDriverException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scrapers.control import SearchCancelled, SearchControl
from backend.scrapers.email_scraper import extract_email_from_site
from backend.scrapers.maps_scraper import scrape_google_maps
from desktop.api_client import ApiClientError, GmapScrapApiClient, search_status
from desktop.state import forget_search, remember_search


class SearchWorker(QObject):
    log = Signal(str)
    progress = Signal(dict)
    finished = Signal(bool, str)

    def __init__(self, niche, location, quantity, max_results,
                 skip_without_website=True, only_without_website=False,
                 validate_whatsapp=False, enrich_site_insights=False,
                 run_id=None, start_index=1, finalize_only=False, initial_run=None):
        super().__init__()
        self.niche = niche
        self.location = location
        self.quantity = quantity
        self.max_results = max_results
        self.skip_without_website = skip_without_website
        self.only_without_website = only_without_website
        self.validate_whatsapp = validate_whatsapp
        self.enrich_site_insights = enrich_site_insights
        self.resume_run_id = run_id
        self.start_index = max(1, start_index)
        self.finalize_only = finalize_only
        self.initial_run = initial_run
        self.control = SearchControl()
        self.request_key = str(uuid4())
        self._command_lock = RLock()
        self._accept_commands = True

    def pause(self):
        with self._command_lock:
            if not self._accept_commands:
                return False
            self.control.request("paused")
        self.log.emit("Pausa solicitada. Encerrando o navegador local...")
        return True

    def stop(self):
        with self._command_lock:
            if not self._accept_commands:
                return False
            self.control.request("stopped")
        self.log.emit("Parada definitiva solicitada. Encerrando o navegador local...")
        return True

    @Slot()
    def run(self):
        client = None
        events = None
        run_id = self.resume_run_id
        last_run = self.initial_run
        scanned = max(self.start_index - 1, int((last_run or {}).get("scanned_count") or 0))
        creation_attempted = bool((last_run or {}).get("creation_uncertain"))
        uncertain = {}
        if creation_attempted:
            self.request_key = last_run["request_key"]
        finish_status, message = "completed", "Busca concluída."
        try:
            client = GmapScrapApiClient.from_environment()
            client.control = self.control
            client.request_key = self.request_key
            if self.finalize_only and run_id is None and creation_attempted:
                client.control = None
                last_run = client.get_created_search(self.request_key)
                run_id = int(last_run["id"])
            if not self.finalize_only:
                self.control.checkpoint()
                client.login()
                self.control.checkpoint()
                if run_id is not None:
                    last_run = client.update_search(run_id, status="running", message="Retomando busca local no aplicativo desktop...")
                else:
                    uncertain = dict(niche=self.niche, location=self.location, request_key=self.request_key,
                                     creation_uncertain=True, sync_pending=True, status="failed",
                                     message="Criação ainda não confirmada. Use Tentar sincronizar antes de iniciar outra busca.")
                    remember_search(uncertain)
                    creation_attempted = True
                    last_run = client.create_search(
                        self.niche, self.location, self.quantity, self.max_results,
                        self.skip_without_website, self.validate_whatsapp, self.enrich_site_insights,
                        only_without_website=self.only_without_website)
                    run_id = int(last_run["id"])
                    forget_search()
                self.progress.emit(last_run)
                self.control.checkpoint()
                events = scrape_google_maps(
                    self.niche, self.location, start_index=self.start_index,
                    skip_without_website=self.skip_without_website and not self.only_without_website,
                    control=self.control)
                for event in events:
                    self.control.checkpoint()
                    # Do not advance the resume cursor until this result is handled.
                    if event.kind == "done":
                        scanned = max(scanned, event.scanned)
                        message = _completion_message(event.message, None if self.max_results else self.quantity, last_run)
                        break
                    skip_message = None
                    email = ""
                    if event.kind == "skip" or event.lead is None:
                        skip_message = event.message
                    elif self.only_without_website and event.lead.website:
                        skip_message = f"{event.lead.name} ignorado: tem site."
                    elif event.lead.website:
                        try:
                            result = extract_email_from_site(event.lead.website, control=self.control)
                            self.control.checkpoint()
                            email = result.email
                            if not email:
                                skip_message = f"{event.lead.name} ignorado: e-mail não encontrado ou inválido."
                        except SearchCancelled:
                            raise
                        except Exception:
                            self.control.checkpoint()
                            skip_message = f"{event.lead.name} ignorado: erro ao buscar e-mail."
                    self.control.checkpoint()
                    if skip_message:
                        last_run = client.update_search(run_id, message=skip_message,
                                                        scanned_count=event.scanned, skipped_delta=1)
                        self.log.emit(skip_message)
                    else:
                        response = client.ingest_lead(
                            run_id, scanned=event.scanned, name=event.lead.name,
                            address=event.lead.address, phone=event.lead.phone,
                            website=event.lead.website, email=email)
                        last_run = response["run"]
                        self.log.emit(response["message"])
                    scanned = max(scanned, event.scanned)
                    self.progress.emit(last_run)
                    self.control.checkpoint()
                    if not self.max_results and self.quantity and int(last_run["saved_count"]) >= self.quantity:
                        message = "Quantidade solicitada concluída."
                        break
        except SearchCancelled:
            pass
        except Exception as exc:
            finish_status, message = "failed", _friendly_error(exc)
            self.log.emit(message)
        finally:
            # Closing the generator explicitly runs Selenium's finally on early breaks.
            if events is not None:
                try:
                    events.close()
                except Exception as exc:
                    self.log.emit(f"Encerrando navegador: {_friendly_error(exc)}")
            self.control.close_browser()
            with self._command_lock:
                self._accept_commands = False
                if self.control.reason:
                    finish_status = self.control.reason
            if self.control.reason:
                message = {
                    "stopped": "Busca parada definitivamente. Leads salvos foram preservados.",
                    "paused": "Busca pausada. É possível retomar esta execução.",
                }.get(finish_status, (last_run or {}).get("message") or message)
            if client is not None:
                client.control = None  # Final status must be sent even after cancellation.
                if run_id is not None:
                    try:
                        pending = dict(last_run or {}, id=run_id, status=finish_status,
                                       message=message, scanned_count=scanned, sync_pending=True)
                        try:
                            remember_search(pending)
                        except OSError as exc:
                            self.log.emit(f"Não foi possível guardar a sincronização local: {exc}")
                        if finish_status == "stopped":
                            last_run = client.stop_search(run_id, scanned_count=scanned)
                        else:
                            last_run = client.update_search(
                                run_id, status=finish_status, message=message, scanned_count=scanned,
                                error=message if finish_status == "failed" else None)
                        forget_search()
                        self.progress.emit(last_run)
                    except Exception as exc:
                        authoritative = None
                        if isinstance(exc, ApiClientError) and exc.status_code == 409:
                            try:
                                current = client.get_search(run_id)
                                if search_status(current) in {"completed", "failed", "stopped"}:
                                    authoritative = current
                            except Exception:
                                pass
                        if authoritative:
                            finish_status = search_status(authoritative)
                            message = authoritative.get("message") or message
                            forget_search()
                            self.progress.emit(authoritative)
                        else:
                            message += f" Sincronização pendente: {_friendly_error(exc)} Use Tentar sincronizar."
                            last_run = dict(last_run or {}, id=run_id, status=finish_status,
                                            message=message, sync_pending=True)
                            self.progress.emit(last_run)
                    finally:
                        client.session.close()
                else:
                    if creation_attempted:
                        pending = dict(last_run or uncertain, status=finish_status, sync_pending=True,
                                       request_key=self.request_key, creation_uncertain=True,
                                       message=message + " Criação não confirmada. Não inicie outra busca antes de reconciliar esta execução.")
                        remember_search(pending)
                        self.progress.emit(pending)
                    client.session.close()
            self.finished.emit(finish_status == "completed", message)

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
