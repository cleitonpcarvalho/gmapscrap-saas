from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.api_client import ApiClientError, GmapScrapApiClient
from desktop.worker import SearchWorker


def asset_path(filename: str) -> str:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = base_dir / "assets" / filename
    if bundled.exists():
        return str(bundled)
    return str(Path(__file__).resolve().parent / "assets" / filename)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: SearchWorker | None = None
        self.current_run: dict | None = None

        self.setWindowTitle("GmapScrap Desktop")
        self.setWindowIcon(QIcon(asset_path("gmapscrap-favicon.png")))
        self.resize(1180, 760)
        self.setMinimumSize(980, 680)

        self._build_ui()
        self._apply_style()
        QTimer.singleShot(300, self.refresh_history)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("rootPage")
        page = QVBoxLayout(root)
        page.setContentsMargins(28, 24, 28, 28)
        page.setSpacing(22)

        header = QHBoxLayout()
        header.setSpacing(14)

        logo = QLabel()
        logo.setObjectName("logoImage")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(154, 124)
        brand_logo = QPixmap(asset_path("gmapscrap-logo.png"))
        logo.setPixmap(
            brand_logo.scaled(
                154,
                124,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Desktop")
        title.setObjectName("title")
        subtitle = QLabel("Busca local com Selenium headless")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_box.addStretch()

        self.connection_label = QLabel("Pronto")
        self.connection_label.setObjectName("connection")
        self.connection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_label.setFixedHeight(52)

        header.addWidget(logo)
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(self.connection_label, 0, Qt.AlignmentFlag.AlignTop)

        body = QHBoxLayout()
        body.setSpacing(18)

        form_card = self._card()
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(24, 22, 24, 24)
        form_layout.setSpacing(16)

        form_heading = QLabel("Nova busca")
        form_heading.setObjectName("eyebrow")
        form_title = QLabel("Google Maps headless")
        form_title.setObjectName("sectionTitle")
        form_layout.addWidget(form_heading)
        form_layout.addWidget(form_title)

        self.niche_input = QLineEdit()
        self.niche_input.setPlaceholderText("Ex.: pressure washing")
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("Ex.: Anchorage, AK")
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 500)
        self.quantity_input.setValue(10)
        self.max_checkbox = QCheckBox("Máximo possível")
        self.max_checkbox.toggled.connect(self._toggle_quantity)

        form_layout.addWidget(self._field("Nicho", self.niche_input))
        form_layout.addWidget(self._field("Cidade, estado ou país", self.location_input))

        quantity_row = QHBoxLayout()
        quantity_row.setSpacing(12)
        quantity_row.addWidget(self._field("Quantidade", self.quantity_input), 1)
        quantity_box = QFrame()
        quantity_box.setObjectName("checkBoxFrame")
        quantity_box_layout = QVBoxLayout(quantity_box)
        quantity_box_layout.setContentsMargins(14, 13, 14, 13)
        quantity_box_layout.addWidget(self.max_checkbox)
        quantity_row.addWidget(quantity_box)
        form_layout.addLayout(quantity_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.start_button = QPushButton("Iniciar busca")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_search)
        self.stop_button = QPushButton("Pausar")
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.handle_secondary_action)
        button_row.addWidget(self.start_button, 1)
        button_row.addWidget(self.stop_button)
        form_layout.addLayout(button_row)
        form_layout.addStretch()

        right = QVBoxLayout()
        right.setSpacing(18)

        execution_card = self._card()
        execution_layout = QVBoxLayout(execution_card)
        execution_layout.setContentsMargins(24, 22, 24, 24)
        execution_layout.setSpacing(14)

        execution_top = QHBoxLayout()
        execution_title_box = QVBoxLayout()
        execution_heading = QLabel("Execução atual")
        execution_heading.setObjectName("eyebrow")
        self.current_title = QLabel("Nenhuma busca em andamento")
        self.current_title.setObjectName("sectionTitle")
        execution_title_box.addWidget(execution_heading)
        execution_title_box.addWidget(self.current_title)
        self.status_badge = QLabel("Aguardando")
        self.status_badge.setObjectName("badge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        execution_top.addLayout(execution_title_box)
        execution_top.addStretch()
        execution_top.addWidget(self.status_badge)
        execution_layout.addLayout(execution_top)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(10)
        stats_grid.setVerticalSpacing(10)
        self.scanned_value = self._metric("0", "Escaneados")
        self.saved_value = self._metric("0", "Salvos")
        self.skipped_value = self._metric("0", "Pulados")
        stats_grid.addWidget(self.scanned_value, 0, 0)
        stats_grid.addWidget(self.saved_value, 0, 1)
        stats_grid.addWidget(self.skipped_value, 0, 2)
        execution_layout.addLayout(stats_grid)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Aguardando")
        execution_layout.addWidget(self.progress_bar)

        self.current_message = QLabel("Aguardando uma nova busca.")
        self.current_message.setObjectName("runMessage")
        self.current_message.setWordWrap(True)
        execution_layout.addWidget(self.current_message)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Os logs da busca aparecem aqui.")
        execution_layout.addWidget(self.log_view, 1)

        history_card = self._card()
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(24, 22, 24, 24)
        history_layout.setSpacing(12)

        history_top = QHBoxLayout()
        history_heading_box = QVBoxLayout()
        history_heading = QLabel("Histórico recente")
        history_heading.setObjectName("eyebrow")
        history_title = QLabel("Últimas execuções")
        history_title.setObjectName("sectionTitle")
        history_heading_box.addWidget(history_heading)
        history_heading_box.addWidget(history_title)
        refresh_button = QPushButton("Atualizar")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.refresh_history)
        history_top.addLayout(history_heading_box)
        history_top.addStretch()
        history_top.addWidget(refresh_button)
        history_layout.addLayout(history_top)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Busca", "Status", "Salvos", "Criada em"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        history_layout.addWidget(self.history_table)

        right.addWidget(execution_card, 3)
        right.addWidget(history_card, 2)

        body.addWidget(form_card, 2)
        body.addLayout(right, 3)

        page.addLayout(header)
        page.addLayout(body, 1)
        self.setCentralWidget(root)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#rootPage {
                background: #f2f7f5;
                color: #13201d;
                font-family: Inter, Arial, sans-serif;
                font-size: 14px;
            }
            QLabel {
                background: transparent;
            }
            QFrame#card {
                background: #ffffff;
                border: 1px solid #dce8e4;
                border-radius: 8px;
            }
            QLabel#logoImage {
                background: transparent;
                border: none;
            }
            QLabel#title {
                font-size: 28px;
                font-weight: 850;
                color: #10211d;
            }
            QLabel#subtitle {
                color: #60706b;
                font-weight: 650;
            }
            QLabel#connection, QLabel#badge {
                background: #e9f5ef;
                border: 1px solid #d6e8df;
                border-radius: 15px;
                color: #08705e;
                font-weight: 800;
                padding: 7px 14px;
            }
            QLabel#eyebrow {
                color: #006879;
                font-size: 12px;
                font-weight: 850;
                text-transform: uppercase;
            }
            QLabel#sectionTitle {
                font-size: 22px;
                font-weight: 850;
            }
            QLabel#fieldLabel {
                color: #5d6d68;
                font-weight: 800;
            }
            QLabel#metricValue {
                background: #f7faf9;
                border: 1px solid #dce8e4;
                border-radius: 8px;
                color: #10211d;
                padding: 12px;
                font-size: 22px;
                font-weight: 900;
            }
            QLabel#runMessage {
                color: #52635f;
                font-weight: 750;
            }
            QLineEdit, QSpinBox {
                min-height: 42px;
                background: #ffffff;
                border: 1px solid #d8e4df;
                border-radius: 8px;
                color: #10211d;
                padding: 0 12px;
                font-weight: 700;
                selection-background-color: #cceee8;
                selection-color: #10211d;
                placeholder-text-color: #84958f;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #008996;
            }
            QFrame#checkBoxFrame {
                background: #f0f7f4;
                border: 1px solid #d8e4df;
                border-radius: 8px;
            }
            QCheckBox {
                color: #10211d;
                background: transparent;
                font-weight: 800;
                spacing: 10px;
            }
            QCheckBox:disabled {
                color: #6f807a;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                background: #ffffff;
                border: 1px solid #a8b9b4;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background: #008996;
                border: 1px solid #008996;
            }
            QCheckBox::indicator:disabled {
                background: #edf4f2;
                border: 1px solid #cbdad5;
            }
            QPushButton {
                min-height: 44px;
                border-radius: 8px;
                padding: 0 18px;
                font-size: 15px;
                font-weight: 850;
            }
            QPushButton#primaryButton {
                background: #008996;
                color: white;
                border: 1px solid #008996;
            }
            QPushButton#primaryButton:disabled {
                background: #9cb8b6;
                border: 1px solid #9cb8b6;
                color: #f5fbfa;
            }
            QPushButton#secondaryButton {
                background: #ffffff;
                color: #006879;
                border: 1px solid #d8e4df;
            }
            QPushButton#secondaryButton:disabled {
                color: #9aa9a5;
                background: #f4f7f6;
            }
            QProgressBar {
                height: 18px;
                border: 1px solid #d8e4df;
                border-radius: 8px;
                background: #edf4f2;
                color: #13201d;
                font-weight: 800;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: #3ab795;
            }
            QPlainTextEdit {
                background: #101c1a;
                color: #d7f4ed;
                border: 1px solid #20342f;
                border-radius: 8px;
                padding: 10px;
                font-family: Menlo, Monaco, Consolas, monospace;
                font-size: 12px;
            }
            QTableWidget {
                background: white;
                alternate-background-color: #f7faf9;
                border: 1px solid #dce8e4;
                border-radius: 8px;
                color: #13201d;
                gridline-color: #e6efeb;
                selection-background-color: #d7f3ee;
                selection-color: #10211d;
            }
            QTableWidget::item {
                color: #13201d;
                padding: 6px;
            }
            QTableWidget::item:alternate {
                background: #f7faf9;
            }
            QHeaderView::section {
                background: #edf4f2;
                color: #52635f;
                border: none;
                padding: 9px;
                font-weight: 850;
            }
            """
        )

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return frame

    def _field(self, label: str, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        text = QLabel(label)
        text.setObjectName("fieldLabel")
        layout.addWidget(text)
        layout.addWidget(widget)
        return wrapper

    def _metric(self, value: str, label: str) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label_widget = QLabel(label)
        label_widget.setObjectName("fieldLabel")
        label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label)
        layout.addWidget(label_widget)
        wrapper.value_label = value_label  # type: ignore[attr-defined]
        return wrapper

    def _toggle_quantity(self, checked: bool) -> None:
        self.quantity_input.setEnabled(not checked)

    def start_search(self) -> None:
        niche = self.niche_input.text().strip()
        location = self.location_input.text().strip()
        max_results = self.max_checkbox.isChecked()
        quantity = None if max_results else self.quantity_input.value()

        if len(niche) < 2 or len(location) < 2:
            self._append_log("Informe nicho e cidade antes de iniciar.")
            return

        self._set_running(True)
        self._reset_current()
        self.current_title.setText(f"{niche} · {location}")
        self._set_status("Rodando", "#fff4d7", "#916400")
        self._start_worker(niche, location, quantity, max_results)

    def _start_worker(
        self,
        niche: str,
        location: str,
        quantity: int | None,
        max_results: bool,
        *,
        run_id: int | None = None,
        start_index: int = 1,
    ) -> None:
        self.thread = QThread(self)
        self.worker = SearchWorker(niche, location, quantity, max_results, run_id=run_id, start_index=start_index)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._update_run)
        self.worker.finished.connect(self._finish_search)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._clear_worker_refs)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def handle_secondary_action(self) -> None:
        if self.thread and self.thread.isRunning():
            self.pause_search()
            return

        if self.current_run and self.current_run.get("status") == "paused":
            self.resume_search()

    def pause_search(self) -> None:
        if self.worker:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def resume_search(self) -> None:
        if not self.current_run:
            return

        run_id = int(self.current_run["id"])
        niche = str(self.current_run.get("niche") or self.niche_input.text().strip())
        location = str(self.current_run.get("location") or self.location_input.text().strip())
        max_results = bool(self.current_run.get("max_results"))
        target_quantity = self.current_run.get("target_quantity")
        quantity = None if max_results else int(target_quantity or self.quantity_input.value())
        start_index = int(self.current_run.get("scanned_count") or 0) + 1

        self._append_log(f"Retomando do resultado #{start_index}.")
        self.current_message.setText("Retomando busca local...")
        self._set_status("Rodando", "#fff4d7", "#916400")
        self._set_running(True)
        self._start_worker(niche, location, quantity, max_results, run_id=run_id, start_index=start_index)

    def refresh_history(self) -> None:
        try:
            client = GmapScrapApiClient.from_environment()
            searches = client.list_searches()
        except ApiClientError as exc:
            self.connection_label.setText("Offline")
            self._append_log(f"Histórico indisponível: {exc}")
            return

        self.connection_label.setText("Online")
        self._fill_history(searches[:8])

    def _set_running(self, running: bool) -> None:
        paused = bool(self.current_run and self.current_run.get("status") == "paused")
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running or paused)
        self.stop_button.setText("Pausar" if running else ("Retomar" if paused else "Pausar"))
        if paused and not running:
            self.start_button.setEnabled(False)
        fields_enabled = not running and not paused
        self.niche_input.setEnabled(fields_enabled)
        self.location_input.setEnabled(fields_enabled)
        self.quantity_input.setEnabled(fields_enabled and not self.max_checkbox.isChecked())
        self.max_checkbox.setEnabled(fields_enabled)

    def _reset_current(self) -> None:
        self.current_run = None
        self.log_view.clear()
        self.current_message.setText("Preparando busca local...")
        self._set_metric(self.scanned_value, 0)
        self._set_metric(self.saved_value, 0)
        self._set_metric(self.skipped_value, 0)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Rodando")

    def _update_run(self, run: dict) -> None:
        self.current_run = run
        niche = run.get("niche", "")
        location = run.get("location", "")
        self.current_title.setText(f"{niche} · {location}")

        scanned = int(run.get("scanned_count") or 0)
        saved = int(run.get("saved_count") or 0)
        skipped = int(run.get("skipped_count") or 0)
        message = str(run.get("message") or "")
        self._set_metric(self.scanned_value, scanned)
        self._set_metric(self.saved_value, saved)
        self._set_metric(self.skipped_value, skipped)
        self.current_message.setText(message or "Busca em andamento...")

        status = str(run.get("status") or "running")
        if status == "completed":
            self._set_status("Concluída", "#dff8e9", "#16834a")
        elif status == "failed":
            self._set_status("Falhou", "#ffe0df", "#ba2624")
        elif status == "paused":
            self._set_status("Pausada", "#eef0f3", "#5f6872")
        else:
            self._set_status("Rodando", "#fff4d7", "#916400")

        target = run.get("target_quantity")
        if target:
            target_value = int(target)
            self.progress_bar.setRange(0, target_value)
            self.progress_bar.setValue(min(saved, target_value))
            if status == "completed":
                self.progress_bar.setFormat(f"Concluída: {saved}/{target_value} salvos")
            elif status == "failed":
                self.progress_bar.setFormat(f"Falhou: {saved}/{target_value} salvos")
            elif status == "paused":
                self.progress_bar.setFormat(f"Pausada: {saved}/{target_value} salvos")
            else:
                self.progress_bar.setFormat(f"{saved}/{target_value} salvos")
        elif status in {"completed", "failed", "paused"}:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat(_status_label(status))
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("Máximo possível")

    def _finish_search(self, ok: bool, message: str) -> None:
        self._append_log(message)
        self.current_message.setText(message)
        self._set_running(False)
        if ok:
            self._set_status("Concluída", "#dff8e9", "#16834a")
        elif self.current_run and self.current_run.get("status") == "paused":
            self._set_status("Pausada", "#eef0f3", "#5f6872")
        else:
            self._set_status("Falhou", "#ffe0df", "#ba2624")
        self.refresh_history()

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {message}")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_metric(self, metric: QWidget, value: int) -> None:
        metric.value_label.setText(str(value))  # type: ignore[attr-defined]

    def _set_status(self, text: str, background: str, color: str) -> None:
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(
            f"background: {background}; color: {color}; border: 1px solid {background}; border-radius: 15px; "
            "font-weight: 850; padding: 7px 14px;"
        )

    def _fill_history(self, searches: list[dict]) -> None:
        self.history_table.setRowCount(len(searches))
        for row, item in enumerate(searches):
            query = f"{item.get('niche', '')} · {item.get('location', '')}"
            status = str(item.get("status") or "")
            saved = str(item.get("saved_count") or 0)
            created = _format_date(str(item.get("created_at") or ""))

            for column, value in enumerate((query, _status_label(status), saved, created)):
                cell = QTableWidgetItem(value)
                cell.setForeground(QBrush(QColor("#13201d")))
                cell.setToolTip(value)
                self.history_table.setItem(row, column, cell)

    def _clear_worker_refs(self) -> None:
        self.thread = None
        self.worker = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker and self.thread and self.thread.isRunning():
            self.worker.stop()
            self.thread.quit()
            self.thread.wait(2500)
        event.accept()


def _status_label(status: str) -> str:
    labels = {
        "queued": "Na fila",
        "running": "Rodando",
        "paused": "Pausada",
        "completed": "Concluída",
        "failed": "Falhou",
    }
    return labels.get(status, status or "-")


def _format_date(raw: str) -> str:
    if not raw:
        return "-"

    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:16]
    return value.strftime("%d/%m %H:%M")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
