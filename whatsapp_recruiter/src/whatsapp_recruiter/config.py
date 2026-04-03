from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    whatsapp_url: str
    browser: str
    profile_dir: Path
    profile_name: str | None
    download_dir: Path
    template_xlsx_path: Path | None
    tesseract_cmd: str | None
    poppler_path: str | None
    headless: bool

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        browser = os.getenv("BROWSER", "firefox").strip().lower() or "firefox"
        default_profile_dir = {
            "firefox": Path.cwd() / ".firefox-profile",
            "chrome": Path.cwd() / ".chrome-profile",
            "safari": Path.cwd() / ".safari-profile",
        }.get(browser, Path.cwd() / ".firefox-profile")
        profile_dir = Path(
            os.getenv(
                "WHATSAPP_PROFILE_DIR",
                str(default_profile_dir),
            )
        )
        profile_name_raw = os.getenv("WHATSAPP_PROFILE_NAME", "").strip()
        download_dir = Path(
            os.getenv(
                "WHATSAPP_DOWNLOAD_DIR",
                str(Path.cwd() / "downloads"),
            )
        )
        profile_dir.mkdir(parents=True, exist_ok=True)
        download_dir.mkdir(parents=True, exist_ok=True)
        template_xlsx_raw = os.getenv(
            "TEMPLATE_XLSX_PATH",
            r"C:\Users\USER\Downloads\CORPO CLINICO BP -VP.xlsx",
        )
        template_xlsx_path = Path(template_xlsx_raw) if template_xlsx_raw else None

        return cls(
            whatsapp_url="https://web.whatsapp.com/",
            browser=browser,
            profile_dir=profile_dir,
            profile_name=profile_name_raw or None,
            download_dir=download_dir,
            template_xlsx_path=template_xlsx_path if template_xlsx_path and template_xlsx_path.exists() else None,
            tesseract_cmd=os.getenv("TESSERACT_CMD"),
            poppler_path=os.getenv("POPPLER_PATH"),
            headless=os.getenv("HEADLESS", "true").lower() == "true",
        )
