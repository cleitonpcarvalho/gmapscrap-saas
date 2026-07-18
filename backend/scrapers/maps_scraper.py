import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

import phonenumbers
from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from backend.config import get_settings


PHONE_XPATH_FALLBACK = "/html/body/div[1]/div[2]/div[9]/div[9]/div/div/div[1]/div[3]/div/div[1]/div/div/div[2]/div[7]/div[6]/button/div/div[2]/div[1]"
DOMAIN_REGEX = re.compile(
    r"(?<!@)\b(?:https?://)?(?:www\.)?"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
    r"\.[a-z]{2,}(?::\d{2,5})?(?:/[^\s,]*)?",
    re.IGNORECASE,
)
PHONE_SHAPE_REGEX = re.compile(r"(\+\d|\(?\d{2,3}\)?[\s.-]\d{3,5}[\s.-]\d{4}|tel:)", re.IGNORECASE)
ADDRESS_HINT_REGEX = re.compile(
    r"(\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|"
    r"\b(estados unidos|united states|brasil|brazil|eua)\b|"
    r"\d{1,6}\s+[\w .'-]+"
    r"\b(st|street|ave|avenue|road|rd|drive|dr|blvd|lane|ln|way|hwy|highway|ct|court)\b)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class MapLead:
    name: str
    address: str
    phone: str
    website: str


@dataclass(slots=True)
class ScrapeEvent:
    kind: str
    scanned: int
    message: str
    lead: MapLead | None = None


def _create_driver() -> WebDriver:
    settings = get_settings()
    options = Options()
    profile_dir = tempfile.mkdtemp(prefix="gmapscrap-chrome-")

    if settings.selenium_headless:
        options.add_argument("--headless=new")

    if settings.chrome_bin:
        options.binary_location = settings.chrome_bin

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--window-size=1365,900")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--accept-lang=pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("prefs", {"intl.accept_languages": "pt-BR,pt,en-US,en"})
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    service = Service(executable_path=settings.chromedriver_bin) if settings.chromedriver_bin else Service()
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        shutil.rmtree(profile_dir, ignore_errors=True)
        raise

    setattr(driver, "_gmapscrap_profile_dir", profile_dir)
    return driver


def _quit_driver(driver: WebDriver) -> None:
    profile_dir = getattr(driver, "_gmapscrap_profile_dir", "")
    try:
        driver.quit()
    except WebDriverException:
        pass
    finally:
        if profile_dir:
            shutil.rmtree(profile_dir, ignore_errors=True)


def _click_google_consent_if_present(driver: WebDriver) -> None:
    labels = (
        "Aceitar tudo",
        "Concordo",
        "Accept all",
        "I agree",
        "Reject all",
        "Rejeitar tudo",
    )

    for label in labels:
        xpath = f"//button[.//*[contains(normalize-space(), '{label}')] or contains(normalize-space(), '{label}')]"
        try:
            buttons = driver.find_elements(By.XPATH, xpath)
            if buttons:
                buttons[0].click()
                time.sleep(1.5)
                return
        except WebDriverException:
            continue


def _diagnose_maps_page(driver: WebDriver) -> str:
    try:
        title = driver.title
        current_url = driver.current_url
        body = driver.find_element(By.TAG_NAME, "body").text
    except WebDriverException:
        return "Google Maps não respondeu corretamente no Chrome headless."

    page_text = f"{title}\n{current_url}\n{body}".lower()
    if any(
        marker in page_text
        for marker in (
            "unusual traffic",
            "not a robot",
            "não sou um robô",
            "captcha",
            "/sorry/",
            "our systems have detected",
        )
    ):
        return "Google bloqueou a busca no servidor e pediu verificação/CAPTCHA."

    if any(marker in page_text for marker in ("before you continue", "antes de continuar", "privacy", "privacidade")):
        return "Google exibiu tela de consentimento/privacidade e não abriu os resultados do Maps."

    if "maps" not in current_url.lower():
        return f"Google Maps redirecionou para outra página: {title or current_url}."

    return "Google Maps não carregou a lista de resultados no servidor dentro do tempo limite."


def _wait_for_results_panel(driver: WebDriver, wait: WebDriverWait):
    selectors = (
        "//div[contains(@aria-label, 'Resultados') or contains(@aria-label, 'Results')]",
        "//div[@role='feed']",
        "//div[contains(@class, 'm6QErb') and .//a[contains(@href, '/maps/place/')]]",
    )

    for selector in selectors:
        try:
            return wait.until(EC.presence_of_element_located((By.XPATH, selector)))
        except TimeoutException:
            continue

    raise RuntimeError(_diagnose_maps_page(driver))


def _infer_region(address: str) -> str:
    normalized = (address or "").lower()
    if any(value in normalized for value in ("estados unidos", "united states", "eua", " usa")):
        return "US"
    if any(value in normalized for value in ("brasil", "brazil")):
        return "BR"
    return "US"


def _format_phone_number(raw: str, address: str) -> str:
    if not raw:
        return ""

    candidate = raw.strip()
    candidate = re.sub(r"^(phone:tel:|tel:)", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.replace("\u202a", "").replace("\u202c", "")

    region = None if candidate.startswith("+") else _infer_region(address)

    try:
        parsed = phonenumbers.parse(candidate, region)
    except phonenumbers.NumberParseException:
        matches = list(phonenumbers.PhoneNumberMatcher(candidate, region or "US"))
        if not matches:
            return candidate
        parsed = matches[0].number

    if not phonenumbers.is_possible_number(parsed):
        return candidate

    if parsed.country_code == 55:
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def _has_phone_shape(text: str) -> bool:
    return bool(PHONE_SHAPE_REGEX.search(text or ""))


def _extract_phone(driver: WebDriver, info_elements: list, address: str) -> str:
    candidates: list[str] = []

    for element in info_elements:
        text = element.text
        if _has_phone_shape(text):
            candidates.append(text)

    phone_targets = [
        (By.XPATH, "//button[contains(@data-item-id, 'phone:tel:')]"),
        (By.XPATH, "//button[contains(@aria-label, 'Telefone') or contains(@aria-label, 'phone') or contains(@aria-label, 'Phone')]"),
        (By.XPATH, PHONE_XPATH_FALLBACK),
    ]

    for by, selector in phone_targets:
        for element in driver.find_elements(by, selector):
            candidates.extend(
                [
                    element.text,
                    element.get_attribute("aria-label") or "",
                    element.get_attribute("data-item-id") or "",
                    element.get_attribute("href") or "",
                ]
            )

    for candidate in candidates:
        phone = _format_phone_number(candidate, address)
        if phone and re.search(r"\d", phone):
            return phone

    return ""


def _normalize_website(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    match = DOMAIN_REGEX.search(raw)
    if not match:
        return ""

    site = match.group(0).strip().strip(".,;:()[]{}<>")
    if not site or " " in site or "," in site or "%" in site:
        return ""

    if not re.match(r"^https?://", site, re.IGNORECASE):
        site = f"https://{site}"

    parsed = urlparse(site)
    host = (parsed.netloc or "").lower()
    if not host or "." not in host or "%" in host or "," in host:
        return ""

    if any(blocked in host for blocked in ("google.", "gstatic.", "ggpht.", "googleusercontent.")):
        return ""

    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def _extract_website(driver: WebDriver, info_elements: list) -> str:
    candidates: list[str] = []

    for selector in (
        "//a[contains(@data-item-id, 'authority')]",
        "//a[contains(@aria-label, 'Website') or contains(@aria-label, 'Site')]",
    ):
        for element in driver.find_elements(By.XPATH, selector):
            candidates.extend([element.get_attribute("href") or "", element.text])

    for element in info_elements:
        candidates.append(element.text)

    for candidate in candidates:
        website = _normalize_website(candidate)
        if website:
            return website

    return ""


def _clean_address_text(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^(endereço|address)\s*:\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_address(text: str) -> bool:
    clean = _clean_address_text(text)
    if not clean or len(clean) > 260:
        return False

    if _normalize_website(clean) or _has_phone_shape(clean):
        return False

    return bool(ADDRESS_HINT_REGEX.search(clean))


def _extract_address(driver: WebDriver, info_elements: list) -> str:
    candidates: list[str] = []

    for selector in (
        "//*[contains(@data-item-id, 'address')]",
        "//*[contains(@aria-label, 'Endereço') or contains(@aria-label, 'Address')]",
    ):
        for element in driver.find_elements(By.XPATH, selector):
            candidates.extend([element.get_attribute("aria-label") or "", element.text])

    for element in info_elements:
        candidates.append(element.text)

    fallback = ""
    for candidate in candidates:
        address = _clean_address_text(candidate)
        if not address:
            continue

        if _looks_like_address(address):
            return address

        if not fallback and not _normalize_website(address) and not _has_phone_shape(address):
            fallback = address

    return fallback or "Não encontrado"


def _safe_text(wait: WebDriverWait, by: str, selector: str) -> str:
    try:
        return wait.until(EC.presence_of_element_located((by, selector))).text.strip()
    except TimeoutException:
        return ""


def _extract_current_place(driver: WebDriver, wait: WebDriverWait) -> MapLead:
    name = _safe_text(wait, By.CLASS_NAME, "DUwDvf") or "Não encontrado"

    try:
        info_elements = driver.find_elements(By.CLASS_NAME, "Io6YTe")
    except WebDriverException:
        info_elements = []

    address = _extract_address(driver, info_elements)
    website = _extract_website(driver, info_elements)
    phone = _extract_phone(driver, info_elements, address)

    return MapLead(name=name, address=address, phone=phone, website=website)


def scrape_google_maps(niche: str, location: str, start_index: int = 1):
    driver = _create_driver()
    wait = WebDriverWait(driver, 15)

    try:
        query = quote_plus(f"{niche} {location}")
        driver.get(f"https://www.google.com/maps/search/{query}?hl=pt-BR")
        time.sleep(5)
        _click_google_consent_if_present(driver)

        results_panel = _wait_for_results_panel(driver, wait)

        def scroll_list() -> bool:
            previous_height = driver.execute_script("return arguments[0].scrollHeight", results_panel)
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", results_panel)
            time.sleep(2)
            new_height = driver.execute_script("return arguments[0].scrollHeight", results_panel)
            return new_height != previous_height

        def find_result_element(index: int):
            attempts = 0

            while attempts < 15:
                elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/maps/place/')]")

                if len(elements) < index:
                    attempts += 1
                    if not scroll_list():
                        return None
                    continue

                element = elements[index - 1]
                driver.execute_script("arguments[0].scrollIntoView();", element)
                time.sleep(0.8)
                return element

            return None

        index = max(1, start_index)

        while True:
            element = find_result_element(index)
            if element is None:
                yield ScrapeEvent(kind="done", scanned=index - 1, message="Não há mais resultados.")
                break

            try:
                element.click()
            except ElementClickInterceptedException:
                time.sleep(1)
                try:
                    element.click()
                except ElementClickInterceptedException:
                    yield ScrapeEvent(kind="skip", scanned=index, message="Não conseguiu clicar no resultado.")
                    index += 1
                    continue

            time.sleep(2.5)
            lead = _extract_current_place(driver, wait)

            if not lead.website:
                yield ScrapeEvent(kind="skip", scanned=index, message=f"{lead.name} ignorado: sem site.")
            else:
                yield ScrapeEvent(kind="lead", scanned=index, message=f"{lead.name} encontrado.", lead=lead)

            index += 1
    finally:
        _quit_driver(driver)
