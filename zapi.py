"""
zapi.py – Cliente Z-API para notificações de grupo
Documentação: https://developer.z-api.io
"""
import httpx
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("zapi")

ZAPI_BASE = "https://api.z-api.io/instances"


class ZAPIClient:
    def __init__(self, instance_id: str, token: str):
        self.instance_id = instance_id
        self.token = token

    async def send_text(self, phone: str, message: str) -> bool:
        """Envia mensagem de texto para número ou grupo."""
        url = f"{ZAPI_BASE}/{self.instance_id}/token/{self.token}/send-text"
        body = {"phone": phone, "message": message}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json=body)
                if r.status_code == 200:
                    log.info(f"[ZAPI] Notificação enviada para {phone}")
                    return True
                else:
                    log.error(f"[ZAPI] Erro {r.status_code}: {r.text[:300]}")
                    return False
        except Exception as e:
            log.error(f"[ZAPI] Exceção ao enviar: {e}")
            return False


def build_notification(name: str, phone: str, last_message: str) -> str:
    """Monta a mensagem de notificação do novo lead qualificado."""
    tz = timezone(timedelta(hours=-3))
    now = datetime.now(tz)
    date_str = now.strftime("%d/%m/%Y às %H:%M")

    # Limpa o telefone para exibição
    display_phone = phone
    if phone.startswith("55") and len(phone) >= 12:
        ddd = phone[2:4]
        num = phone[4:]
        display_phone = f"+55 ({ddd}) {num[:5]}-{num[5:]}" if len(num) >= 9 else phone

    return (
        f"📅 *{date_str}*\n"
        f"🔔 *Novo lead qualificado!*\n\n"
        f"👤 *Nome:* {name}\n"
        f"📱 *Telefone:* {display_phone}\n"
        f"💬 *Resposta:* {last_message}"
    )
