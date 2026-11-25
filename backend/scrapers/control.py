"""Cooperative cancellation and cleanup of one search's owned Chrome tree."""

import shutil
import threading

import psutil
from selenium.webdriver import Chrome
from selenium.webdriver.remote.command import Command
from selenium.webdriver.support.ui import WebDriverWait


class SearchCancelled(Exception):
    pass


class BrowserLease:
    def __init__(self, service, profile_dir):
        self.service = service
        self.profile_dir = profile_dir
        self.driver = None
        self._lock = threading.Lock()
        self._closing = False
        self.closed = threading.Event()

    def close(self):
        with self._lock:
            if not self._closing:
                self._closing = True
                threading.Thread(target=self._cleanup, daemon=True).start()

    def _cleanup(self):
        # psutil Process objects retain creation time, so a reused PID is never killed.
        owned = []
        process = getattr(self.service, "process", None)
        if process is not None:
            try:
                parent = psutil.Process(process.pid)
                owned = parent.children(recursive=True) + [parent]
                for child in owned:
                    child.create_time()
            except psutil.Error:
                pass
        quit_done = threading.Event()

        def quit_driver():
            try:
                if self.driver is not None:
                    self.driver.quit()
                else:
                    self.service.stop()
            except Exception:
                pass
            finally:
                quit_done.set()

        threading.Thread(target=quit_driver, daemon=True).start()
        quit_done.wait(3)
        try:
            alive = [p for p in owned if p.is_running()]
            for p in alive:
                try:
                    p.terminate()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs(alive, timeout=2)
            for p in alive:
                try:
                    p.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(alive, timeout=2)
        finally:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            self.closed.set()


class SearchControl:
    def __init__(self):
        self.event = threading.Event()
        self._lock = threading.RLock()
        self.reason = None
        self.lease = None

    def request(self, reason):
        with self._lock:
            if self.reason != "stopped":
                self.reason = reason
            self.event.set()
            if self.lease:
                self.lease.close()

    def checkpoint(self):
        if self.event.is_set():
            raise SearchCancelled()

    def sleep(self, seconds):
        self.event.wait(seconds)
        self.checkpoint()

    def attach(self, driver, service, profile_dir):
        lease = BrowserLease(service, profile_dir)
        lease.driver = driver
        with self._lock:
            self.lease = lease
            if self.event.is_set():
                lease.close()
        self.checkpoint()

    def close_browser(self):
        if self.lease:
            self.lease.close()
            self.lease.closed.wait(8)


class CancellableWait(WebDriverWait):
    def __init__(self, driver, timeout, control):
        super().__init__(driver, timeout)
        self.control = control

    def until(self, method, message=""):
        def checked(driver):
            self.control.checkpoint()
            return method(driver)
        return super().until(checked, message)


class CancellableChrome(Chrome):
    def __init__(self, control, **kwargs):
        self._search_control = control
        super().__init__(**kwargs)

    def execute(self, driver_command, params=None):
        if driver_command != Command.QUIT:
            self._search_control.checkpoint()
        # Selenium 4.43's Chromium transport defaults to 120 seconds, including
        # session creation. Keep a stuck local driver bounded during cancellation.
        self.command_executor._client_config.timeout = 20
        return super().execute(driver_command, params)
