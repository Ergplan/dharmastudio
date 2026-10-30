"""Studio settings: keys and model names from `.env` only (never the DB, never the UI).

Every provider has a dry-run mode when its key is missing, so the whole app runs end to end without keys.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    topaz_api_key: str | None = None
    # motion, voice and publishing (keys follow each provider's own env names)
    fal_api_key: str | None = Field(default=None, validation_alias=AliasChoices("FAL_KEY", "FAL_API_KEY"))
    byteplus_api_key: str | None = Field(default=None, validation_alias=AliasChoices("BYTEPLUS_API_KEY", "ARK_API_KEY"))
    elevenlabs_api_key: str | None = Field(default=None, validation_alias=AliasChoices("ELEVENLABS_API_KEY"))
    blob_read_write_token: str | None = Field(default=None, validation_alias=AliasChoices("BLOB_READ_WRITE_TOKEN"))
    revalidate_secret: str | None = Field(default=None, validation_alias=AliasChoices("REVALIDATE_SECRET"))
    site_url: str = Field(default="https://cycleofdharma.world", validation_alias=AliasChoices("SITE_URL"))
    # Seedance model ids (they change; override in .env)
    seedance_fal_model: str | None = Field(default=None, validation_alias=AliasChoices("SEEDANCE_FAL_MODEL"))
    seedance_byteplus_model: str | None = Field(default=None, validation_alias=AliasChoices("SEEDANCE_BYTEPLUS_MODEL"))

    topaz_model: str = "Wonder 3.5"
    gemini_image_model: str = "gemini-nano-banana-2.1"
    gemini_pro_image_model: str = "gemini-3-pro-image"
    sunburst_model: str = "gpt-image-2.5-sunburst"
    agent_model: str = "claude-sonnet-4-5"

    data_dir: Path = Field(default=REPO_ROOT / "data")
    port: int = 8787

    # Sunburst token prices (USD per million tokens)
    sunburst_text_in_per_m: float = 5.0
    sunburst_image_in_per_m: float = 8.0
    sunburst_image_out_per_m: float = 30.0
    # Gemini and Topaz bill per image; these are flat estimates used for the ledger
    gemini_cost_per_image: float = 0.04
    gemini_pro_cost_per_image: float = 0.13
    topaz_cost_per_image: float = 0.05

    @property
    def dry_run_sunburst(self) -> bool:
        return not self.openai_api_key

    @property
    def dry_run_gemini(self) -> bool:
        return not self.gemini_api_key

    @property
    def dry_run_topaz(self) -> bool:
        return not self.topaz_api_key

    @property
    def dry_run_agents(self) -> bool:
        return not self.anthropic_api_key

    def key_status(self) -> dict[str, bool]:
        """Which keys are present — booleans only, the values never leave this process."""
        return {
            "openai": bool(self.openai_api_key),
            "anthropic": bool(self.anthropic_api_key),
            "gemini": bool(self.gemini_api_key),
            "topaz": bool(self.topaz_api_key),
        }

    def motion_key_status(self) -> dict[str, bool]:
        """Motion / publishing keys — booleans only."""
        return {"fal": bool(self.fal_api_key), "byteplus": bool(self.byteplus_api_key), "elevenlabs": bool(self.elevenlabs_api_key),
                "blob": bool(self.blob_read_write_token), "revalidate": bool(self.revalidate_secret)}

    def resolve_data_dir(self) -> Path:
        d = self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir
        d.mkdir(parents=True, exist_ok=True)
        return d


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
