from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""

    # WhatsApp
    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_verify_token: str = "bonifacio_verify"

    # Agendor
    agendor_api_token: str = ""
    agendor_funnel_id: int = 0
    agendor_stage_initial: int = 0
    agendor_stage_qualified: int = 0
    agendor_salespeople_ids: str = ""   # "5,8" → parsed below

    # Server
    port: int = 8000

    @property
    def salespeople_ids(self) -> List[int]:
        if not self.agendor_salespeople_ids:
            return []
        return [int(x.strip()) for x in self.agendor_salespeople_ids.split(",") if x.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
