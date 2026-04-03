from __future__ import annotations

import base64
import mimetypes
import platform
import re
import tempfile
import unicodedata
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote_to_bytes

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    SessionNotCreatedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from whatsapp_recruiter.config import Settings
from whatsapp_recruiter.models import MessageBundle


class WhatsAppWebClient:
    SIDEBAR_SELECTOR = "#pane-side"
    MAIN_PANEL_SELECTOR = "#main"

    def __init__(self, settings: Settings, wait_timeout: int = 60) -> None:
        self.settings = settings
        self.wait_timeout = wait_timeout
        self.driver = self._build_driver()
        self.wait = WebDriverWait(self.driver, wait_timeout)

    def _build_firefox_options(self, profile_dir: Path | None = None) -> FirefoxOptions:
        options = FirefoxOptions()
        download_dir = self.settings.download_dir.resolve()
        effective_profile_dir: Path | None = None
        if profile_dir:
            effective_profile_dir = profile_dir / self.settings.profile_name if self.settings.profile_name else profile_dir
            effective_profile_dir.mkdir(parents=True, exist_ok=True)

        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", str(download_dir))
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.download.manager.showWhenStarting", False)
        options.set_preference("browser.download.always_ask_before_handling_new_types", False)
        options.set_preference("browser.helperApps.alwaysAsk.force", False)
        options.set_preference(
            "browser.helperApps.neverAsk.saveToDisk",
            ",".join(
                [
                    "application/pdf",
                    "application/octet-stream",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "image/jpeg",
                    "image/png",
                    "text/plain",
                ]
            ),
        )
        options.set_preference("pdfjs.disabled", True)
        options.set_preference("browser.download.start_downloads_in_tmp_dir", False)
        options.set_preference("dom.webnotifications.enabled", False)
        options.set_preference("media.navigator.permission.disabled", True)
        options.add_argument("--disable-notifications")
        if effective_profile_dir:
            options.add_argument("-profile")
            options.add_argument(str(effective_profile_dir))
        if self.settings.headless:
            options.add_argument("-headless")
        return options

    def _build_chrome_options(self, profile_dir: Path | None = None) -> ChromeOptions:
        options = ChromeOptions()
        prefs = {
            "download.default_directory": str(self.settings.download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "download.restrictions": 0,
            "profile.default_content_settings.popups": 0,
            "profile.default_content_setting_values.automatic_downloads": 1,
            "safebrowsing.enabled": True,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--remote-allow-origins=*")
        if profile_dir:
            options.add_argument(f"--user-data-dir={profile_dir}")
        if self.settings.profile_name:
            options.add_argument(f"--profile-directory={self.settings.profile_name}")
        if self.settings.headless:
            options.add_argument("--headless=new")
        else:
            options.add_argument("--start-maximized")
        return options

    def _build_driver(self):
        browser = self.settings.browser
        if browser == "firefox":
            return self._build_firefox_driver()
        if browser == "chrome":
            return self._build_chrome_driver()
        if browser == "safari":
            return self._build_safari_driver()
        raise ValueError(
            f"Navegador invalido em BROWSER={browser!r}. Use firefox, chrome ou safari."
        )

    def _build_firefox_driver(self) -> webdriver.Firefox:
        service = FirefoxService(GeckoDriverManager().install())
        try:
            driver = webdriver.Firefox(service=service, options=self._build_firefox_options(self.settings.profile_dir))
        except SessionNotCreatedException:
            print("DEBUG: Firefox nao iniciou com o profile atual, tentando com perfil limpo...")
            temp_profile = Path(tempfile.mkdtemp(prefix="whatsapp-profile-"))
            driver = webdriver.Firefox(service=service, options=self._build_firefox_options(temp_profile))
        if not self.settings.headless:
            driver.set_window_size(1440, 1000)
        self._configure_download_behavior(driver)
        return driver

    def _build_chrome_driver(self) -> webdriver.Chrome:
        service = ChromeService(ChromeDriverManager().install())
        try:
            driver = webdriver.Chrome(service=service, options=self._build_chrome_options(self.settings.profile_dir))
        except SessionNotCreatedException:
            print("DEBUG: Chrome nao iniciou com o profile atual, tentando com perfil limpo...")
            temp_profile = Path(tempfile.mkdtemp(prefix="whatsapp-profile-"))
            driver = webdriver.Chrome(service=service, options=self._build_chrome_options(temp_profile))
        self._configure_download_behavior(driver)
        return driver

    def _build_safari_driver(self) -> webdriver.Safari:
        if platform.system() != "Darwin":
            raise RuntimeError("Safari so e suportado no macOS. Ajuste BROWSER para firefox ou chrome.")
        if self.settings.headless:
            raise RuntimeError("Safari nao suporta HEADLESS neste projeto. Use HEADLESS=false.")
        if self.settings.profile_name:
            print("DEBUG: Safari ignora WHATSAPP_PROFILE_NAME.")
        print("DEBUG: Safari usa o perfil padrao do sistema.")
        driver = webdriver.Safari()
        driver.set_window_size(1440, 1000)
        self._configure_download_behavior(driver)
        return driver

    def _configure_download_behavior(self, driver) -> None:
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.browser == "firefox":
            print("DEBUG: Download configurado via preferencias do Firefox")
            return
        if self.settings.browser == "chrome":
            commands = [
                (
                    "Browser.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": str(self.settings.download_dir),
                        "eventsEnabled": True,
                    },
                ),
                (
                    "Page.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": str(self.settings.download_dir),
                    },
                ),
            ]
            last_error: Exception | None = None
            for command, params in commands:
                try:
                    driver.execute_cdp_cmd(command, params)
                    print(f"DEBUG: Download behavior configurado via {command}")
                    return
                except Exception as exc:
                    last_error = exc
            if last_error is not None:
                print(f"DEBUG: Nao foi possivel configurar o download via CDP: {last_error}")
            return
        print("DEBUG: Safari usa comportamento padrao de download do sistema")

    def open(self) -> None:
        self.driver.get(self.settings.whatsapp_url)
        self.wait.until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, self.SIDEBAR_SELECTOR)),
                EC.presence_of_element_located((By.CSS_SELECTOR, "canvas[aria-label]")),
            )
        )
        if "web.whatsapp.com" in self.driver.current_url:
            self._wait_until_logged_in()

    def _wait_until_logged_in(self) -> None:
        try:
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, self.SIDEBAR_SELECTOR))
            )
        except TimeoutException as exc:
            raise RuntimeError(
                "Nao foi possivel concluir o login no WhatsApp Web. "
                "Escaneie o QR Code e tente novamente."
            ) from exc

    def _get_search_box(self):
        # Aumentamos o timeout para 180s (3 minutos) caso o WhatsApp demore
        # muito na tela de carregamento / "Baixando mensagens"
        wait_long = WebDriverWait(self.driver, 180)
        return wait_long.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 
                 "div[contenteditable='true'][data-tab='3'], #side [contenteditable='true'], #side [role='textbox'], #side input"
                )
            )
        )

    def _set_search_term(self, search_term: str, submit: bool = False) -> None:
        search_box = self._get_search_box()
        self.driver.execute_script("arguments[0].click();", search_box)
        time.sleep(0.5)
        search_box.send_keys(Keys.CONTROL, "a")
        search_box.send_keys(Keys.DELETE)
        if search_term:
            search_box.send_keys(search_term)
            time.sleep(0.5)
            if submit:
                search_box.send_keys(Keys.ENTER)
        time.sleep(2)

    def search_and_open_chat(self, search_term: str) -> str:
        self._set_search_term(search_term, submit=False)
        result = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div[role='listitem']"))
        )
        chat_name = result.text.split("\n")[0].strip() or search_term
        result.click()
        return chat_name

    def apply_search_filter(self, search_term: str) -> None:
        self._set_search_term(search_term, submit=False)
        time.sleep(3)  # Aguarda o carregamento dos resultados da busca

    def list_chat_names(self, max_chats: int = 100) -> list[str]:
        chat_panel = self._get_sidebar()
        discovered: list[str] = []
        seen = set()
        stable_rounds = 0

        while len(discovered) < max_chats and stable_rounds < 2:
            new_this_round = 0
            for chat_name in self._extract_chat_names_from_panel():
                if chat_name and chat_name not in seen:
                    seen.add(chat_name)
                    discovered.append(chat_name)
                    new_this_round += 1
                    if len(discovered) >= max_chats:
                        break

            stable_rounds = stable_rounds + 1 if new_this_round == 0 else 0
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollTop + arguments[0].clientHeight;",
                chat_panel,
            )
            time.sleep(1.5)

        return discovered

    def _get_sidebar(self):
        return self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, self.SIDEBAR_SELECTOR))
        )

    def _extract_chat_names_from_panel(self) -> Iterable[str]:
        for item in self._get_chat_cells():
            chat_name = self._extract_chat_name(item)
            if chat_name:
                yield chat_name

    def scan_chat_messages(
        self, max_chats: int, message_limit: int, keywords: list[str]
    ) -> list[tuple[str, list[MessageBundle]]]:
        sidebar = self._get_sidebar()
        processed_signatures: set[str] = set()
        processed: list[tuple[str, list[MessageBundle]]] = []
        stable_rounds = 0

        while len(processed) < max_chats and stable_rounds < 2:
            cells = self._get_chat_cells()
            new_this_round = 0

            for index in range(len(cells)):
                cells = self._get_chat_cells()
                if index >= len(cells):
                    break

                cell = cells[index]
                signature = self._chat_signature(cell)
                if not signature or signature in processed_signatures:
                    continue

                # Ignora cabeçalhos do resultado de busca (ex: "Mensagens", "Contatos")
                if "\n" not in cell.text:
                    processed_signatures.add(signature)
                    continue

                processed_signatures.add(signature)
                chat_name = self._extract_chat_name(cell) or f"Conversa {len(processed) + 1}"

                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});",
                        cell,
                    )
                    time.sleep(0.5)
                    self._activate_chat_cell(cell)
                    time.sleep(1)
                except Exception as e:
                    print(f"DEBUG: Falha ao ativar a conversa: {e}")
                    continue

                bundles = self.collect_chat_evidence(
                    chat_name=chat_name, limit=message_limit, keywords=keywords
                )
                processed.append((chat_name, bundles))
                new_this_round += 1

                if len(processed) >= max_chats:
                    break

            stable_rounds = stable_rounds + 1 if new_this_round == 0 else 0
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollTop + arguments[0].clientHeight;",
                sidebar,
            )
            time.sleep(1.5)

        return processed

    def iter_chat_messages(
        self, max_chats: int, message_limit: int, keywords: list[str]
    ) -> Iterable[tuple[str, list[MessageBundle]]]:
        if keywords:
            yield from self._iter_chat_messages_from_left_search(
                max_chats=max_chats,
                message_limit=message_limit,
                keywords=keywords,
            )
            return

        sidebar = self._get_sidebar()
        processed_signatures: set[str] = set()
        processed_count = 0
        stable_rounds = 0

        while processed_count < max_chats and stable_rounds < 2:
            cells = self._get_chat_cells()
            new_this_round = 0

            for index in range(len(cells)):
                cells = self._get_chat_cells()
                if index >= len(cells):
                    break

                cell = cells[index]
                signature = self._chat_signature(cell)
                if not signature or signature in processed_signatures:
                    continue

                if "\n" not in cell.text:
                    processed_signatures.add(signature)
                    continue

                processed_signatures.add(signature)
                chat_name = self._extract_chat_name(cell) or f"Conversa {processed_count + 1}"

                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});",
                        cell,
                    )
                    time.sleep(0.5)
                    self._activate_chat_cell(cell)
                    time.sleep(1)
                except Exception as e:
                    print(f"DEBUG: Falha ao ativar a conversa: {e}")
                    continue

                bundles = self.collect_chat_evidence(
                    chat_name=chat_name, limit=message_limit, keywords=keywords
                )
                processed_count += 1
                new_this_round += 1
                yield chat_name, bundles

                if processed_count >= max_chats:
                    break

            stable_rounds = stable_rounds + 1 if new_this_round == 0 else 0
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollTop + arguments[0].clientHeight;",
                sidebar,
            )
            time.sleep(1.5)

    def _iter_chat_messages_from_left_search(
        self,
        max_chats: int,
        message_limit: int,
        keywords: list[str],
    ) -> Iterable[tuple[str, list[MessageBundle]]]:
        processed_chats: set[str] = set()
        processed_signatures: set[str] = set()
        yielded = 0

        for keyword in keywords:
            if yielded >= max_chats:
                break
            self.apply_search_filter(keyword)
            sidebar = self._get_sidebar()
            stable_rounds = 0

            while yielded < max_chats and stable_rounds < 3:
                cells = self._get_chat_cells()
                new_this_round = 0

                for index in range(len(cells)):
                    cells = self._get_chat_cells()
                    if index >= len(cells):
                        break

                    cell = cells[index]
                    signature = self._chat_signature(cell)
                    if not signature or signature in processed_signatures:
                        continue
                    processed_signatures.add(signature)

                    if not self._looks_like_search_result(cell):
                        continue

                    chat_name = self._extract_chat_name(cell) or f"Conversa {yielded + 1}"
                    normalized_chat = self._normalize_search_text(chat_name)
                    if normalized_chat in processed_chats:
                        continue

                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cell)
                        time.sleep(0.4)
                        self._activate_chat_cell(cell)
                        time.sleep(1)
                    except Exception as e:
                        print(f"DEBUG: Falha ao abrir resultado da busca global: {e}")
                        continue

                    processed_chats.add(normalized_chat)
                    bundles = self.collect_chat_evidence(
                        chat_name=chat_name,
                        limit=message_limit,
                        keywords=keywords,
                    )
                    yielded += 1
                    new_this_round += 1
                    yield chat_name, bundles

                    if yielded >= max_chats:
                        break

                    self.apply_search_filter(keyword)
                    sidebar = self._get_sidebar()

                moved = self._scroll_search_results_sidebar(sidebar)
                if new_this_round == 0 and not moved:
                    stable_rounds += 1
                else:
                    stable_rounds = 0

        self.apply_search_filter("")

    def _get_chat_cells(self):
        sidebar = self._get_sidebar()
        return sidebar.find_elements(By.CSS_SELECTOR, "[role='gridcell'][tabindex='0'], [role='listitem']")

    def _extract_chat_name(self, item) -> str | None:
        titles = [
            (node.get_attribute("title") or "").strip()
            for node in item.find_elements(By.CSS_SELECTOR, "[title]")
        ]
        candidates = [title for title in titles if self._looks_like_chat_name(title)]
        if candidates:
            return candidates[0]

        text_lines = [line.strip() for line in item.text.splitlines() if line.strip()]
        for line in text_lines:
            if self._looks_like_chat_name(line):
                return line
        return text_lines[0] if text_lines else None

    def _looks_like_search_result(self, item) -> bool:
        try:
            text = item.text.strip()
        except Exception:
            return False
        if not text or "\n" not in text:
            return False
        lowered = text.lower()
        if lowered in {"mensagens", "contatos", "grupos"}:
            return False
        return True

    def _scroll_search_results_sidebar(self, sidebar) -> bool:
        try:
            before = self.driver.execute_script(
                "return [arguments[0].scrollTop, arguments[0].scrollHeight, arguments[0].clientHeight];",
                sidebar,
            )
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollTop + Math.max(arguments[0].clientHeight * 0.9, 300);",
                sidebar,
            )
            time.sleep(1)
            after = self.driver.execute_script(
                "return [arguments[0].scrollTop, arguments[0].scrollHeight, arguments[0].clientHeight];",
                sidebar,
            )
            return before != after
        except Exception:
            return False

    def open_chat_by_name(self, chat_name: str) -> None:
        self._set_search_term(chat_name)
        sidebar = self._get_sidebar()
        result = self.wait.until(
            lambda driver: self._find_chat_list_item(sidebar, chat_name)
        )
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", result)
        self._activate_chat_cell(result)
        time.sleep(1)
        self._set_search_term("")

    def collect_chat_evidence(
        self, chat_name: str, limit: int = 30, keywords: list[str] | None = None
    ) -> list[MessageBundle]:
        bundles = self.search_messages_in_open_chat(chat_name=chat_name, keywords=keywords or [], limit=limit)
        if bundles:
            return bundles
        return self.collect_recent_messages(chat_name=chat_name, limit=max(limit * 3, 90), keywords=keywords)[:limit]

    def search_messages_in_open_chat(
        self, chat_name: str, keywords: list[str], limit: int = 30
    ) -> list[MessageBundle]:
        if not keywords:
            return []

        bundles: list[MessageBundle] = []
        seen_signatures: set[str] = set()

        for keyword in keywords:
            if len(bundles) >= limit:
                break
            if not self._open_in_chat_search():
                break
            try:
                if not self._set_in_chat_search_term(keyword):
                    continue
                time.sleep(1.2)
                bundles.extend(
                    self._collect_bundles_from_search_results(
                        chat_name=chat_name,
                        keywords=[keyword],
                        seen_signatures=seen_signatures,
                        limit=limit - len(bundles),
                        source="chat_search",
                        matched_term=keyword,
                    )
                )
            finally:
                self._close_in_chat_search()

        if len(bundles) < limit:
            bundles.extend(
                self.collect_recent_messages(
                    chat_name=chat_name,
                    limit=max(limit * 3, 90),
                    keywords=keywords,
                    seen_signatures=seen_signatures,
                    source="history_scan",
                )[: limit - len(bundles)]
            )

        return bundles[:limit]

    def _collect_bundles_from_search_results(
        self,
        chat_name: str,
        keywords: list[str],
        seen_signatures: set[str],
        limit: int,
        source: str,
        matched_term: str,
    ) -> list[MessageBundle]:
        bundles: list[MessageBundle] = []
        results_panel = self._get_in_chat_search_panel(optional=True)
        if results_panel is None:
            return bundles

        stable_rounds = 0
        seen_result_signatures: set[str] = set()

        while len(bundles) < limit and stable_rounds < 3:
            result_items = self._get_in_chat_search_result_items(results_panel)
            new_this_round = 0

            for item in result_items:
                if len(bundles) >= limit:
                    break
                try:
                    item_text = item.text.strip()
                except StaleElementReferenceException:
                    continue
                if not item_text:
                    continue

                item_signature = self._message_signature(item_text, matched_term)
                if item_signature in seen_result_signatures:
                    continue
                seen_result_signatures.add(item_signature)

                if not self._click_search_result_item(item):
                    continue
                time.sleep(0.8)

                clicked_bundles = self._collect_visible_matching_bundles(
                    chat_name=chat_name,
                    keywords=keywords,
                    seen_signatures=seen_signatures,
                    limit=limit - len(bundles),
                    source=source,
                    matched_term=matched_term,
                )
                if clicked_bundles:
                    bundles.extend(clicked_bundles)
                    new_this_round += len(clicked_bundles)

            moved = self._scroll_in_chat_search_results(results_panel)
            if new_this_round == 0 and not moved:
                stable_rounds += 1
            else:
                stable_rounds = 0

        return bundles

    def collect_recent_messages(
        self,
        chat_name: str,
        limit: int = 30,
        keywords: list[str] | None = None,
        seen_signatures: set[str] | None = None,
        source: str = "recent_messages",
    ) -> list[MessageBundle]:
        self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, f"{self.MAIN_PANEL_SELECTOR}"))
        )
        bundles: list[MessageBundle] = []
        keywords = keywords or []
        seen_signatures = seen_signatures or set()
        main_panel = self.driver.find_element(By.CSS_SELECTOR, self.MAIN_PANEL_SELECTOR)
        total_messages = len(main_panel.find_elements(By.CSS_SELECTOR, "div[role='row']"))
        start_index = max(0, total_messages - limit)

        for index in range(start_index, total_messages):
            node = self._get_message_node(index)
            if node is None:
                continue

            try:
                text = node.text.strip()
            except StaleElementReferenceException:
                node = self._get_message_node(index)
                text = node.text.strip() if node is not None else ""

            if not text:
                continue

            attachment_path = None
            attachment_context = self._extract_attachment_context(node)
            keyword_context = "\n".join(part for part in [text, attachment_context] if part.strip())
            has_keyword = self._matches_keywords(keyword_context, keywords)
            if keywords and not has_keyword and not self.has_attachment(node):
                continue

            signature = self._message_signature(text, attachment_context)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            try:
                if self.has_attachment(node) and has_keyword:
                    print(f"DEBUG: Tentando baixar anexo da mensagem: {text[:60]}...")
                    attachment_path = self.download_any_attachment(node, chat_name)
            except StaleElementReferenceException:
                refreshed_node = self._get_message_node(index)
                if refreshed_node is not None and self.has_attachment(refreshed_node) and has_keyword:
                    print(f"DEBUG: Retry do download apos stale element: {text[:60]}...")
                    attachment_path = self.download_any_attachment(refreshed_node, chat_name)
            except Exception as e:
                print(f"DEBUG: Falha ao processar mensagem com anexo: {e}")

            bundles.append(
                MessageBundle(
                    chat_name=chat_name,
                    message_text=text,
                    pdf_path=attachment_path,
                    attachment_context=attachment_context,
                    source=source,
                )
            )

        return bundles

    def _collect_visible_matching_bundles(
        self,
        chat_name: str,
        keywords: list[str],
        seen_signatures: set[str],
        limit: int,
        source: str,
        matched_term: str,
    ) -> list[MessageBundle]:
        bundles: list[MessageBundle] = []
        main_panel = self.driver.find_element(By.CSS_SELECTOR, self.MAIN_PANEL_SELECTOR)
        message_nodes = main_panel.find_elements(By.CSS_SELECTOR, "div[role='row']")

        for node in message_nodes:
            if len(bundles) >= limit:
                break
            try:
                text = node.text.strip()
            except StaleElementReferenceException:
                continue
            if not text:
                continue
            attachment_context = self._extract_attachment_context(node)
            combined_text = "\n".join(part for part in [text, attachment_context] if part.strip())
            if not self._matches_keywords(combined_text, keywords):
                continue

            signature = self._message_signature(text, attachment_context)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            attachment_path = None
            try:
                if self.has_attachment(node):
                    attachment_path = self.download_any_attachment(node, chat_name)
            except Exception as e:
                print(f"DEBUG: Falha ao baixar anexo localizado na busca da conversa: {e}")

            bundles.append(
                MessageBundle(
                    chat_name=chat_name,
                    message_text=text,
                    pdf_path=attachment_path,
                    attachment_context=attachment_context,
                    matched_term=matched_term,
                    source=source,
                )
            )

        return bundles

    def _get_in_chat_search_result_items(self, panel) -> list:
        selectors = [
            "[role='listitem']",
            "[role='button']",
            "[tabindex='0']",
        ]
        candidates: list = []
        for selector in selectors:
            try:
                for element in panel.find_elements(By.CSS_SELECTOR, selector):
                    if not element.is_displayed():
                        continue
                    text = (element.text or "").strip()
                    if not text:
                        continue
                    lowered = text.lower()
                    if lowered == "pesquisar" or "pesquisar mensagens" in lowered:
                        continue
                    candidates.append(element)
            except Exception:
                continue

        filtered: list = []
        seen: set[str] = set()
        for element in candidates:
            try:
                text = element.text.strip()
            except StaleElementReferenceException:
                continue
            key = text[:250]
            if key in seen:
                continue
            seen.add(key)
            filtered.append(element)
        return filtered

    def _click_search_result_item(self, item) -> bool:
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
            self._safe_click(item)
            return True
        except Exception:
            try:
                ActionChains(self.driver).move_to_element(item).click(item).perform()
                return True
            except Exception:
                return False

    def _scroll_in_chat_search_results(self, panel) -> bool:
        try:
            before = self.driver.execute_script(
                """
                const panel = arguments[0];
                const candidates = [panel, ...panel.querySelectorAll('div, section')];
                let best = panel;
                for (const node of candidates) {
                    const style = window.getComputedStyle(node);
                    const canScroll = /(auto|scroll)/.test(style.overflowY || '') && node.scrollHeight > node.clientHeight + 20;
                    if (!canScroll) continue;
                    if (node.clientHeight > best.clientHeight) best = node;
                }
                return [best.scrollTop, best.scrollHeight, best.clientHeight];
                """,
                panel,
            )
            self.driver.execute_script(
                """
                const panel = arguments[0];
                const candidates = [panel, ...panel.querySelectorAll('div, section')];
                let best = panel;
                for (const node of candidates) {
                    const style = window.getComputedStyle(node);
                    const canScroll = /(auto|scroll)/.test(style.overflowY || '') && node.scrollHeight > node.clientHeight + 20;
                    if (!canScroll) continue;
                    if (node.clientHeight > best.clientHeight) best = node;
                }
                best.scrollTop = best.scrollTop + Math.max(best.clientHeight * 0.9, 300);
                """,
                panel,
            )
            time.sleep(0.8)
            after = self.driver.execute_script(
                """
                const panel = arguments[0];
                const candidates = [panel, ...panel.querySelectorAll('div, section')];
                let best = panel;
                for (const node of candidates) {
                    const style = window.getComputedStyle(node);
                    const canScroll = /(auto|scroll)/.test(style.overflowY || '') && node.scrollHeight > node.clientHeight + 20;
                    if (!canScroll) continue;
                    if (node.clientHeight > best.clientHeight) best = node;
                }
                return [best.scrollTop, best.scrollHeight, best.clientHeight];
                """,
                panel,
            )
            return before != after
        except Exception:
            return False

    def _open_in_chat_search(self) -> bool:
        selectors = [
            "header [aria-label*='Pesquisar']",
            "header [aria-label*='Buscar']",
            "header [aria-label*='Search']",
            "header [title*='Pesquisar']",
            "header [title*='Buscar']",
            "header [title*='Search']",
            "header [data-icon='search']",
        ]
        for selector in selectors:
            try:
                for button in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    if not button.is_displayed():
                        continue
                    self._safe_click(button)
                    time.sleep(0.8)
                    if self._get_in_chat_search_box(optional=True) is not None:
                        return True
            except Exception:
                continue
        return False

    def _get_in_chat_search_box(self, optional: bool = False):
        panel = self._get_in_chat_search_panel(optional=True)
        if panel is not None:
            selectors = [
                "div[contenteditable='true'][role='textbox']",
                "div[contenteditable='true']",
                "input",
            ]
            for selector in selectors:
                try:
                    for element in panel.find_elements(By.CSS_SELECTOR, selector):
                        if element.is_displayed():
                            return element
                except Exception:
                    continue
        if optional:
            return None
        raise NoSuchElementException("Campo de busca da conversa nao encontrado")

    def _get_in_chat_search_panel(self, optional: bool = False):
        try:
            panel = self.driver.execute_script(
                """
                const labels = ["Pesquisar mensagens", "Search messages", "Buscar mensagens"];
                const minLeft = window.innerWidth * 0.55;
                const nodes = Array.from(document.querySelectorAll("div, section, aside"));
                for (const node of nodes) {
                    const text = (node.innerText || "").trim();
                    if (!text) continue;
                    if (!labels.some(label => text.includes(label))) continue;
                    const rect = node.getBoundingClientRect();
                    if (rect.width < 220 || rect.height < 120) continue;
                    if (rect.left < minLeft) continue;
                    const field = node.querySelector("div[contenteditable='true'], input");
                    if (field) return node;
                }
                return null;
                """
            )
            if panel is not None:
                return panel
        except Exception:
            pass
        if optional:
            return None
        raise NoSuchElementException("Painel de busca da conversa nao encontrado")

    def _set_in_chat_search_term(self, keyword: str) -> bool:
        try:
            search_box = self._get_in_chat_search_box()
        except NoSuchElementException:
            return False
        focused = False
        try:
            self.driver.execute_script(
                """
                const el = arguments[0];
                el.scrollIntoView({block: 'center', inline: 'nearest'});
                el.click();
                el.focus();
                """,
                search_box,
            )
            time.sleep(0.2)
            focused = bool(
                self.driver.execute_script(
                    """
                    const el = arguments[0];
                    return document.activeElement === el || el.contains(document.activeElement);
                    """,
                    search_box,
                )
            )
        except Exception:
            focused = False

        if not focused:
            try:
                ActionChains(self.driver).move_to_element(search_box).click(search_box).perform()
                time.sleep(0.2)
                focused = bool(
                    self.driver.execute_script(
                        """
                        const el = arguments[0];
                        return document.activeElement === el || el.contains(document.activeElement);
                        """,
                        search_box,
                    )
                )
            except Exception:
                focused = False

        if not focused:
            print("DEBUG: Campo 'Pesquisar mensagens' nao recebeu foco; pulando keyword para evitar digitar na conversa.")
            return False

        try:
            is_contenteditable = bool(
                self.driver.execute_script(
                    "return arguments[0].isContentEditable || arguments[0].getAttribute('contenteditable') === 'true';",
                    search_box,
                )
            )
            if is_contenteditable:
                self.driver.execute_script(
                    """
                    const el = arguments[0];
                    const value = arguments[1];
                    el.focus();
                    const selection = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    document.execCommand('insertText', false, value);
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, data: value, inputType: 'insertText'}));
                    """,
                    search_box,
                    keyword,
                )
            else:
                search_box.send_keys(Keys.CONTROL, "a")
                search_box.send_keys(Keys.DELETE)
                search_box.send_keys(keyword)
        except Exception:
            return False

        time.sleep(0.3)
        typed_value = self.driver.execute_script(
            """
            const el = arguments[0];
            return (el.value || el.innerText || el.textContent || '').trim();
            """,
            search_box,
        ) or ""
        if keyword.lower() not in typed_value.lower():
            print("DEBUG: Keyword nao apareceu no campo 'Pesquisar mensagens'; ignorando esta tentativa.")
            return False
        return True

    def _close_in_chat_search(self) -> None:
        try:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
        except Exception:
            pass

    def _get_message_node(self, index: int):
        try:
            main_panel = self.driver.find_element(By.CSS_SELECTOR, self.MAIN_PANEL_SELECTOR)
            message_nodes = main_panel.find_elements(By.CSS_SELECTOR, "div[role='row']")
            if 0 <= index < len(message_nodes):
                return message_nodes[index]
        except Exception:
            return None
        return None

    def _extract_attachment_context(self, node) -> str:
        parts: list[str] = []
        selectors = [
            "[title]",
            "[aria-label]",
            "[data-testid]",
        ]
        for selector in selectors:
            try:
                for element in node.find_elements(By.CSS_SELECTOR, selector):
                    for value in (
                        element.get_attribute("title"),
                        element.get_attribute("aria-label"),
                        element.get_attribute("data-testid"),
                    ):
                        if value and value.strip():
                            parts.append(value.strip())
            except Exception:
                continue
        return "\n".join(dict.fromkeys(parts))

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        # Separa camelCase/PascalCase antes de normalizar.
        value = re.sub(r"(?<=[a-z\u00e0-\u00ff])(?=[A-Z\u00c0-\u00dd])", " ", value)
        normalized = "".join(
            c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn"
        )
        normalized = re.sub(r"[_.\-/]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _matches_keywords(self, text: str, keywords: list[str]) -> bool:
        normalized_text = self._normalize_search_text(text)
        if not normalized_text:
            return False

        for keyword in keywords:
            normalized_keyword = self._normalize_search_text(keyword)
            if not normalized_keyword:
                continue
            if " " in normalized_keyword or len(normalized_keyword) >= 4:
                if normalized_keyword in normalized_text:
                    return True
            else:
                if re.search(rf"\b{re.escape(normalized_keyword)}\b", normalized_text):
                    return True
        return False

    @staticmethod
    def _message_signature(text: str, attachment_context: str | None) -> str:
        combined = "\n".join(part for part in [text, attachment_context or ""] if part.strip())
        return combined.strip()[:500]

    def has_attachment(self, node) -> bool:
        """Detect any kind of document, media icon, or download button."""
        text_lower = node.text.lower()
        if any(ext in text_lower for ext in ['.pdf', '.doc', '.docx', '.zip']):
            return True
        media_xpaths = [
            ".//*[contains(@aria-label, 'Pressione para baixar') or contains(@aria-label, 'baixar') or contains(@aria-label, 'Download')]",
            ".//*[@data-icon='msg-image' or @data-icon='msg-video' or @data-icon='msg-document' or @data-icon='msg-pdf' or @data-icon='document']",
            ".//span[contains(@data-icon, 'download') or contains(@data-icon, 'pdf')]",
            ".//*[contains(@aria-label, 'imagem') or contains(@aria-label, 'foto') or contains(@aria-label, 'arquivo') or contains(@aria-label, '.pdf')]",
            ".//*[contains(@title, 'baixar') or contains(@title, 'download')]",
            ".//a[contains(@href, 'blob:') or @download]",
        ]
        for xpath in media_xpaths:
            if node.find_elements(By.XPATH, xpath):
                return True
        return False

    def download_any_attachment(self, node, chat_name: str = "") -> Path | None:
        "Download any attachment with enhanced robustness."
        print(f"DEBUG: Download dir before: {list(self.settings.download_dir.glob('*'))}")
        before = self._snapshot_download_dir()

        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", node)
        ActionChains(self.driver).move_to_element(node).pause(0.05).perform()
        time.sleep(0.1)

        def click_element(element):
            target = self._resolve_click_target(element)
            print(f"DEBUG: Click target resolved to {self._describe_element(target)}")
            self._safe_click(target)

        def find_first_element(root, xpaths: list[str], label: str):
            for xpath in xpaths:
                targets = root.find_elements(By.XPATH, xpath)
                if targets:
                    target = self._resolve_click_target(targets[0])
                    print(f"DEBUG: Found {label} with {xpath}: {self._describe_element(target)}")
                    return target
            return None

        def find_direct_download_button():
            xpaths = [
                ".//button[.//*[@data-icon='download' or contains(@data-icon, 'download')] or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar')]",
                ".//*[@role='button' and .//*[@data-icon='download' or contains(@data-icon, 'download')]]",
                ".//*[@data-testid='media-download' or contains(@data-testid, 'download')]",
                ".//button[contains(@data-testid, 'download') or @data-icon='download']",
                ".//*[@role='button' and (contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download'))]",
                ".//*[@data-icon='download' or contains(@data-icon, 'download')]",
                ".//a[@download or contains(@href, 'blob:') or contains(@href, 'data:') or contains(@href, '.pdf')]",
            ]
            return find_first_element(node, xpaths, "direct download target")

        def find_attachment_open_target():
            xpaths = [
                ".//*[@role='button' and (contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'arquivo') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'documento') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '.pdf') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '.pdf'))]",
                ".//*[@data-icon='msg-pdf' or @data-icon='msg-document' or @data-icon='document' or contains(@data-icon, 'document') or contains(@data-icon, 'pdf')]",
                ".//a[@download or contains(@href, 'blob:') or contains(@href, 'data:')]",
                ".//img",
            ]
            return find_first_element(node, xpaths, "attachment open target") or node

        def find_preview_download_button():
            xpaths = [
                "//button[.//*[@data-icon='download' or contains(@data-icon, 'download')] or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar')]",
                "//*[@role='button' and .//*[@data-icon='download' or contains(@data-icon, 'download')]]",
                "//button[@data-testid='media-download' or contains(@data-testid, 'download') or contains(@aria-label, 'Download') or contains(@aria-label, 'Baixar') or contains(@title, 'download') or contains(@title, 'baixar')]",
                "//*[@role='button' and (@data-testid='media-download' or contains(@data-testid, 'download') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') or contains(translate(@title, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar'))]",
                "//*[@data-icon='download' or contains(@data-icon, 'download')]",
                "//div[@role='button' and (contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') or contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'baixar'))]",
            ]
            return find_first_element(self.driver, xpaths, "preview download button")

        try:
            if downloaded := self._attempt_click_and_wait(
                before,
                click_fn=lambda: self._click_attachment_download_hotspot(node),
                timeout=4,
                label="hotspot do card",
            ):
                renamed = self._rename_downloaded_file(downloaded, chat_name)
                self._close_attachment_preview()
                return renamed

            direct_button = find_direct_download_button()
            if direct_button:
                if downloaded := self._attempt_click_and_wait(
                    before,
                    click_fn=lambda: click_element(direct_button),
                    timeout=4,
                    label="clique direto",
                ):
                    renamed = self._rename_downloaded_file(downloaded, chat_name)
                    self._close_attachment_preview()
                    return renamed
                print("DEBUG: Clique direto nao iniciou download, tentando abrir preview")

            print("DEBUG: Abrindo preview do anexo")
            click_element(find_attachment_open_target())
            time.sleep(0.35)

            if downloaded := self._attempt_click_and_wait(
                before,
                click_fn=self._click_preview_download_hotspot,
                timeout=5,
                label="hotspot do preview",
            ):
                renamed = self._rename_downloaded_file(downloaded, chat_name)
                self._close_attachment_preview()
                return renamed

            preview_button = find_preview_download_button()
            if preview_button:
                if downloaded := self._attempt_click_and_wait(
                    before,
                    click_fn=lambda: click_element(preview_button),
                    timeout=5,
                    label="botao do preview",
                ):
                    renamed = self._rename_downloaded_file(downloaded, chat_name)
                    self._close_attachment_preview()
                    return renamed
                print("DEBUG: Preview aberto, mas nao houve download")
            else:
                print("DEBUG: Botao de download no preview nao encontrado")

            preview_resource = self._download_resource_from_dom(None, chat_name, scope_label="preview")
            if preview_resource:
                print(f"DEBUG: Arquivo salvo a partir do DOM do preview: {preview_resource.name}")
                self._close_attachment_preview()
                return preview_resource

        except Exception as e:
            print(f"DEBUG: Falha ao baixar anexo: {e}")

        print(f"DEBUG: Download dir after (no new files): {list(self.settings.download_dir.glob('*'))}")
        self._close_attachment_preview()
        return None

    def _attempt_click_and_wait(self, before, click_fn, timeout: float, label: str) -> Path | None:
        print(f"DEBUG: Tentando {label}")
        clicked = click_fn()
        if clicked is False:
            print(f"DEBUG: {label} nao foi executado")
            return None
        downloaded = self._wait_for_new_attachment(before, timeout=timeout, poll_interval=0.2)
        if downloaded:
            print(f"DEBUG: Arquivo baixado via {label}: {downloaded.name}")
            return downloaded
        print(f"DEBUG: {label} nao iniciou download")
        return None

    def _download_resource_from_dom(self, root, chat_name: str, scope_label: str) -> Path | None:
        urls = self._collect_candidate_resource_urls(root)
        if not urls:
            print(f"DEBUG: Nenhuma URL de recurso encontrada no DOM ({scope_label})")
            return None

        print(f"DEBUG: URLs candidatas no DOM ({scope_label}): {urls[:5]}")
        hinted_name = self._extract_attachment_name(root)
        for url in urls:
            saved = self._save_resource_url(url, chat_name, hinted_name)
            if saved:
                return saved
        return None

    def _collect_candidate_resource_urls(self, root) -> list[str]:
        try:
            urls = self.driver.execute_script(
                """
                const root = arguments[0] || document;
                const scope = root.querySelectorAll ? root : document;
                const elements = scope.querySelectorAll(
                    "a[href], img[src], source[src], video[src], iframe[src], embed[src], object[data]"
                );
                const values = new Set();
                for (const el of elements) {
                    const candidates = [
                        el.getAttribute("href"),
                        el.getAttribute("src"),
                        el.getAttribute("data"),
                        el.currentSrc || "",
                    ];
                    for (const value of candidates) {
                        if (!value) continue;
                        const lower = value.toLowerCase();
                        if (
                            lower.startsWith("blob:") ||
                            lower.startsWith("data:") ||
                            lower.includes(".pdf") ||
                            lower.includes("document") ||
                            lower.includes("media")
                        ) {
                            values.add(value);
                        }
                    }
                }
                return Array.from(values);
                """,
                root,
            )
        except Exception as exc:
            print(f"DEBUG: Falha ao coletar URLs do DOM: {exc}")
            return []
        return [url for url in urls or [] if isinstance(url, str) and url.strip()]

    def _extract_attachment_name(self, root) -> str | None:
        try:
            text = (root.text if root is not None else self.driver.find_element(By.TAG_NAME, "body").text) or ""
        except Exception:
            text = ""

        match = re.search(
            r"([A-Za-z0-9 _.-]+\.(?:pdf|doc|docx|png|jpg|jpeg|webp|bmp|tif|tiff))",
            text,
            re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    def _save_resource_url(self, url: str, chat_name: str, hinted_name: str | None = None) -> Path | None:
        try:
            payload = self.driver.execute_async_script(
                """
                const url = arguments[0];
                const done = arguments[arguments.length - 1];
                function finish(blob, mimeType) {
                    const reader = new FileReader();
                    reader.onloadend = () => done({
                        ok: true,
                        dataUrl: reader.result,
                        mimeType: mimeType || blob.type || "",
                        size: blob.size || 0,
                    });
                    reader.readAsDataURL(blob);
                }
                if (url.startsWith("data:")) {
                    return done({ ok: true, dataUrl: url, mimeType: "", size: 0 });
                }
                fetch(url)
                    .then(response => response.blob().then(blob => ({ blob, mimeType: response.headers.get("content-type") || "" })))
                    .then(({ blob, mimeType }) => finish(blob, mimeType))
                    .catch(error => done({ ok: false, error: String(error) }));
                """,
                url,
            )
        except Exception as exc:
            print(f"DEBUG: Falha ao buscar recurso '{url}': {exc}")
            return None

        if not payload or not payload.get("ok") or not payload.get("dataUrl"):
            print(f"DEBUG: Nao foi possivel salvar recurso '{url}': {payload}")
            return None

        data_url = payload["dataUrl"]
        try:
            content = self._decode_data_url(data_url)
        except Exception as exc:
            print(f"DEBUG: Falha ao decodificar recurso '{url}': {exc}")
            return None

        extension = self._guess_attachment_extension(url, payload.get("mimeType"), hinted_name)
        if not self._is_valid_attachment_payload(
            content=content,
            extension=extension,
            mime_type=payload.get("mimeType"),
            url=url,
            hinted_name=hinted_name,
        ):
            print(
                "DEBUG: Recurso do DOM ignorado por assinatura invalida:",
                f"url={url}",
                f"mime={payload.get('mimeType')}",
                f"extension={extension}",
                f"size={len(content)}",
            )
            return None
        base_name = Path(hinted_name).stem if hinted_name else "attachment"
        safe_chat = re.sub(r"[^\w\s-]", "_", chat_name)[:30] or "chat"
        safe_base = re.sub(r"[^\w\s-]", "_", base_name).strip() or "attachment"
        file_path = self.settings.download_dir / f"{safe_chat}_{int(time.time())}_{safe_base}{extension}"
        try:
            file_path.write_bytes(content)
            return file_path
        except Exception as exc:
            print(f"DEBUG: Falha ao gravar recurso em disco: {exc}")
            return None

    def _guess_attachment_extension(self, url: str, mime_type: str | None, hinted_name: str | None) -> str:
        if hinted_name and Path(hinted_name).suffix:
            return Path(hinted_name).suffix.lower()
        if mime_type:
            if mime_type.lower() == "image/jpeg":
                return ".jpg"
            guessed = mimetypes.guess_extension(mime_type.split(";")[0].strip(), strict=False)
            if guessed:
                return guessed
        url_match = re.search(r"\.(pdf|doc|docx|png|jpg|jpeg|webp|bmp|tif|tiff)\b", url, re.IGNORECASE)
        if url_match:
            ext = url_match.group(0).lower()
            return ".jpg" if ext == ".jpeg" else ext
        return ".bin"

    @staticmethod
    def _decode_data_url(data_url: str) -> bytes:
        header, encoded = data_url.split(",", 1)
        if ";base64" in header.lower():
            return base64.b64decode(encoded)
        return unquote_to_bytes(encoded)

    def _is_valid_attachment_payload(
        self,
        content: bytes,
        extension: str,
        mime_type: str | None,
        url: str,
        hinted_name: str | None,
    ) -> bool:
        if not content:
            return False

        if self._looks_like_html_payload(content):
            return False

        expects_pdf = self._resource_looks_like_pdf(
            url=url,
            extension=extension,
            mime_type=mime_type,
            hinted_name=hinted_name,
        )
        if expects_pdf:
            return self._looks_like_pdf_content(content)

        return True

    @staticmethod
    def _resource_looks_like_pdf(
        url: str,
        extension: str,
        mime_type: str | None,
        hinted_name: str | None,
    ) -> bool:
        if extension.lower() == ".pdf":
            return True
        if hinted_name and Path(hinted_name).suffix.lower() == ".pdf":
            return True
        if mime_type and "pdf" in mime_type.lower():
            return True
        return ".pdf" in url.lower()

    @staticmethod
    def _looks_like_pdf_content(content: bytes) -> bool:
        return content.lstrip().startswith(b"%PDF-")

    @staticmethod
    def _looks_like_html_payload(content: bytes) -> bool:
        prefix = content[:512].lstrip().lower()
        return (
            prefix.startswith(b"<!doctype html")
            or prefix.startswith(b"<html")
            or prefix.startswith(b"<?xml")
        )

    def _click_attachment_download_hotspot(self, node) -> bool:
        hotspot = self._get_attachment_download_hotspot(node)
        if not hotspot:
            print("DEBUG: Hotspot de download do card nao encontrado")
            return False
        print(
            "DEBUG: Clicando no hotspot do card:",
            f"x={hotspot['x']:.1f}",
            f"y={hotspot['y']:.1f}",
            hotspot.get("target", ""),
        )
        return self._click_viewport_point(hotspot["x"], hotspot["y"])

    def _click_preview_download_hotspot(self) -> bool:
        hotspot = self._get_preview_download_hotspot()
        if not hotspot:
            print("DEBUG: Hotspot de download do preview nao encontrado")
            return False
        print(
            "DEBUG: Clicando no hotspot do preview:",
            f"x={hotspot['x']:.1f}",
            f"y={hotspot['y']:.1f}",
            hotspot.get("target", ""),
        )
        return self._click_viewport_point(hotspot["x"], hotspot["y"])

    def _get_attachment_download_hotspot(self, node) -> dict | None:
        try:
            hotspot = self.driver.execute_script(
                """
                const root = arguments[0];
                if (!root) return null;

                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                }

                function describe(el) {
                    if (!el) return "";
                    return [
                        el.tagName ? el.tagName.toLowerCase() : "",
                        el.getAttribute("role") || "",
                        el.getAttribute("aria-label") || "",
                        el.getAttribute("title") || "",
                        el.getAttribute("data-testid") || "",
                        el.getAttribute("data-icon") || "",
                    ].filter(Boolean).join(" | ");
                }

                const textMatchers = [/\\.pdf\\b/i, /\\.docx?\\b/i, /curriculum/i, /curriculo/i];
                let anchor = Array.from(root.querySelectorAll("*")).find(el => {
                    const text = (el.textContent || "").trim();
                    return text && textMatchers.some(pattern => pattern.test(text));
                });

                if (!anchor) {
                    anchor = root.querySelector("[data-icon='msg-pdf'], [data-icon='msg-document'], [data-icon='document']");
                }
                if (!anchor) return null;

                let card = anchor;
                while (card && card !== root) {
                    const rect = card.getBoundingClientRect();
                    if (isVisible(card) && rect.width >= 180 && rect.height >= 40) break;
                    card = card.parentElement;
                }
                card = card || root;
                const rect = card.getBoundingClientRect();
                if (!rect.width || !rect.height) return null;

                const x = rect.right - Math.min(28, Math.max(22, rect.width * 0.09));
                const y = rect.top + rect.height * 0.58;
                const target = document.elementFromPoint(x, y) || card;

                return {
                    x,
                    y,
                    target: describe(target),
                    card: describe(card),
                    width: rect.width,
                    height: rect.height,
                };
                """,
                node,
            )
        except Exception as exc:
            print(f"DEBUG: Falha ao calcular hotspot do card: {exc}")
            return None
        return hotspot

    def _get_preview_download_hotspot(self) -> dict | None:
        try:
            hotspot = self.driver.execute_script(
                """
                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                }

                function describe(el) {
                    if (!el) return "";
                    return [
                        el.tagName ? el.tagName.toLowerCase() : "",
                        el.getAttribute("role") || "",
                        el.getAttribute("aria-label") || "",
                        el.getAttribute("title") || "",
                        el.getAttribute("data-testid") || "",
                        el.getAttribute("data-icon") || "",
                    ].filter(Boolean).join(" | ");
                }

                const candidates = Array.from(document.querySelectorAll("button, [role='button'], a"))
                    .filter(isVisible)
                    .filter(el => {
                        const label = [
                            el.getAttribute("aria-label") || "",
                            el.getAttribute("title") || "",
                            el.getAttribute("data-testid") || "",
                            el.getAttribute("data-icon") || "",
                            el.textContent || "",
                        ].join(" ").toLowerCase();
                        return label.includes("baixar") || label.includes("download");
                    })
                    .sort((a, b) => {
                        const rectA = a.getBoundingClientRect();
                        const rectB = b.getBoundingClientRect();
                        return (rectA.top + rectA.left) - (rectB.top + rectB.left);
                    });

                const button = candidates[0];
                if (!button) return null;
                const rect = button.getBoundingClientRect();
                return {
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    target: describe(button),
                    width: rect.width,
                    height: rect.height,
                };
                """,
            )
        except Exception as exc:
            print(f"DEBUG: Falha ao calcular hotspot do preview: {exc}")
            return None
        return hotspot

    def _click_viewport_point(self, x: float, y: float) -> bool:
        try:
            self.driver.execute_script(
                """
                const x = arguments[0];
                const y = arguments[1];
                const target = document.elementFromPoint(x, y);
                if (!target) return false;
                const clickable =
                    target.closest("button") ||
                    target.closest("a") ||
                    target.closest("[role='button']") ||
                    target;
                const options = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y };
                ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(type => {
                    const EventCtor = type.startsWith("pointer") ? PointerEvent : MouseEvent;
                    clickable.dispatchEvent(new EventCtor(type, options));
                });
                if (clickable.click) clickable.click();
                return true;
                """,
                x,
                y,
            )
            time.sleep(0.1)
            return True
        except Exception as exc:
            print(f"DEBUG: Falha no clique por coordenada via JS: {exc}")
            return False

    def _resolve_click_target(self, element):
        try:
            resolved = self.driver.execute_script(
                """
                let node = arguments[0];
                if (!node) return null;
                if (node.nodeType !== 1 && node.parentElement) node = node.parentElement;
                const preferred =
                    node.closest("button") ||
                    node.closest("a[download]") ||
                    node.closest("a") ||
                    node.closest("[role='button'][aria-label]") ||
                    node.closest("[role='button'][title]") ||
                    node.closest("[data-testid]") ||
                    node.closest("[role='button']") ||
                    node.closest("[tabindex]");
                return preferred || node;
                """,
                element,
            )
            return resolved or element
        except Exception:
            return element

    def _describe_element(self, element) -> str:
        try:
            return self.driver.execute_script(
                """
                const el = arguments[0];
                if (!el) return "<null>";
                const attrs = [
                    ["tag", el.tagName ? el.tagName.toLowerCase() : ""],
                    ["role", el.getAttribute("role") || ""],
                    ["data-testid", el.getAttribute("data-testid") || ""],
                    ["data-icon", el.getAttribute("data-icon") || ""],
                    ["aria-label", el.getAttribute("aria-label") || ""],
                    ["title", el.getAttribute("title") || ""],
                    ["class", (el.className || "").toString().slice(0, 120)],
                ];
                return attrs.filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(" | ");
                """,
                element,
            ) or "<unknown>"
        except Exception:
            return "<unavailable>"

    def _safe_click(self, element) -> None:
        last_error: Exception | None = None
        strategies = [
            self._click_topmost_at_center,
            self._click_with_action_chain,
            self._click_with_javascript,
            self._click_with_dispatched_events,
            self._click_with_keyboard,
        ]
        for strategy in strategies:
            try:
                strategy(element)
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    def _click_topmost_at_center(self, element) -> None:
        self.driver.execute_script(
            """
            const original = arguments[0];
            original.scrollIntoView({block: 'center'});
            const rect = original.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            let target = document.elementFromPoint(x, y) || original;
            const clickable =
                target.closest("button") ||
                target.closest("a") ||
                target.closest("[role='button']") ||
                original.closest?.("button") ||
                original;
            target = clickable || target;
            const options = {
                bubbles: true,
                cancelable: true,
                composed: true,
                clientX: x,
                clientY: y,
            };
            ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(type => {
                const Ctor = type.startsWith("pointer") ? PointerEvent : MouseEvent;
                target.dispatchEvent(new Ctor(type, options));
            });
            if (target.click) target.click();
            """,
            element,
        )

    def _click_with_action_chain(self, element) -> None:
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        ActionChains(self.driver).move_to_element(element).pause(0.2).click(element).perform()

    def _click_with_javascript(self, element) -> None:
        self.driver.execute_script(
            """
            arguments[0].scrollIntoView({block: 'center'});
            arguments[0].focus();
            arguments[0].click();
            """,
            element,
        )

    def _click_with_dispatched_events(self, element) -> None:
        self.driver.execute_script(
            """
            const el = arguments[0];
            el.scrollIntoView({block: 'center'});
            const rect = el.getBoundingClientRect();
            const options = {
                bubbles: true,
                cancelable: true,
                composed: true,
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2,
            };
            ["mouseover", "mousemove", "mousedown", "mouseup", "click"].forEach(type => {
                el.dispatchEvent(new MouseEvent(type, options));
            });
            """,
            element,
        )

    def _click_with_keyboard(self, element) -> None:
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].focus();", element)
        try:
            element.send_keys(Keys.ENTER)
        except Exception:
            element.send_keys(Keys.SPACE)

    def _snapshot_download_dir(self) -> dict[Path, tuple[float, int]]:
        snapshot: dict[Path, tuple[float, int]] = {}
        for file_path in self.settings.download_dir.glob("*"):
            if not file_path.is_file():
                continue
            try:
                stat = file_path.stat()
            except FileNotFoundError:
                continue
            snapshot[file_path.resolve()] = (stat.st_mtime, stat.st_size)
        return snapshot

    @staticmethod
    def _is_temporary_download(file_path: Path) -> bool:
        return file_path.name.endswith((".crdownload", ".part", ".tmp", ".download"))

    def _wait_for_new_attachment(
        self,
        before: dict[Path, tuple[float, int]],
        timeout: float = 30,
        poll_interval: float = 1.0,
    ) -> Path | None:
        "Wait for any new attachment with more types."

        deadline = time.time() + timeout
        while time.time() < deadline:
            current = self._snapshot_download_dir()
            changed_files = [
                path
                for path, stats in current.items()
                if path.exists() and not self._is_temporary_download(path) and before.get(path) != stats
            ]
            if changed_files:
                candidates = [p for p in changed_files if p.exists()]
                if candidates:
                    latest = max(candidates, key=lambda p: p.stat().st_mtime)
                    print(f"DEBUG: New attachment candidate: {latest.name} (mtime: {time.ctime(latest.stat().st_mtime)})")
                    return self._wait_for_file_to_stabilize(latest, timeout=min(3, max(1.5, timeout)))
            time.sleep(poll_interval)
        return None

    def _wait_for_file_to_stabilize(self, file_path: Path, timeout: float = 3) -> Path | None:
        deadline = time.time() + timeout
        last_size = -1
        stable_since: float | None = None

        while time.time() < deadline:
            if not file_path.exists():
                time.sleep(0.1)
                continue

            try:
                size = file_path.stat().st_size
            except FileNotFoundError:
                time.sleep(0.1)
                continue

            if size > 0 and size == last_size:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= 0.4:
                    return file_path
            else:
                stable_since = None
                last_size = size
            time.sleep(0.15)

        return file_path if file_path.exists() else None

    def _rename_downloaded_file(self, file_path: Path, chat_name: str) -> Path:
        "Rename to avoid conflicts: chat_timestamp_original.ext"
        timestamp = int(time.time())
        name_no_ext = file_path.stem
        ext = file_path.suffix
        safe_chat = re.sub(r'[^\w\s-]', '_', chat_name)[:30]
        new_name = f"{safe_chat}_{timestamp}_{name_no_ext}{ext}"
        new_path = file_path.parent / new_name
        try:
            file_path.rename(new_path)
            print(f"DEBUG: Renamed {file_path.name} -> {new_name}")
            return new_path
        except Exception as e:
            print(f"DEBUG: Rename failed: {e}")
            return file_path

    def _close_attachment_preview(self) -> None:
        for _ in range(2):
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.5)
            except Exception:
                break
        try:
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f"{self.MAIN_PANEL_SELECTOR} div[role='row']"))
            )
        except TimeoutException:
            pass

    def _activate_chat_cell(self, cell) -> None:
        clickable = self._get_clickable_chat_target(cell)
        try:
            ActionChains(self.driver).move_to_element(clickable).click().perform()
        except Exception:
            try:
                self.driver.execute_script("arguments[0].click();", clickable)
            except Exception:
                pass

        try:
            self.wait.until(lambda driver: self._is_chat_cell_selected(cell))
        except TimeoutException:
            pass

    @staticmethod
    def _get_clickable_chat_target(cell):
        try:
            return cell.find_element(By.CSS_SELECTOR, "[aria-selected]")
        except NoSuchElementException:
            return cell

    @staticmethod
    def _is_chat_cell_selected(cell) -> bool:
        try:
            selected_node = cell.find_element(By.CSS_SELECTOR, "[aria-selected]")
            return (selected_node.get_attribute("aria-selected") or "").lower() == "true"
        except NoSuchElementException:
            return False

    @staticmethod
    def _chat_signature(item) -> str:
        return " ".join(
            part.strip()
            for part in item.text.splitlines()
            if part.strip()
        )[:300]

    @staticmethod
    def _looks_like_chat_name(value: str) -> bool:
        cleaned = value.strip()
        if not cleaned:
            return False
        lowered = cleaned.lower()
        preview_tokens = [
            ".pdf",
            "página",
            "voce",
            "você",
            "http://",
            "https://",
            "ontem",
            "document-refreshed",
        ]
        if any(token in lowered for token in preview_tokens):
            return False
        if len(cleaned) == 1 and not cleaned.isalnum():
            return False
        if not re.search(r"[\w\u00c0-\u00ff]", cleaned):
            return False
        return True

    def _find_chat_list_item(self, sidebar, chat_name: str):
        items = self._get_chat_cells()
        normalized_target = chat_name.strip().lower()

        for item in items:
            title = self._extract_chat_name(item) or ""

            if title.lower() == normalized_target:
                return item

        return False

    def close(self) -> None:
        self.driver.quit()
