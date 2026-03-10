"""
WhatsApp Business Cloud API – cliente assíncrono
Documentação: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import httpx
import logging
from typing import Optional

log = logging.getLogger("whatsapp")

WA_BASE = "https://graph.facebook.com/v19.0"


class WhatsAppClient:
    def __init__(self, phone_number_id: str, access_token: str):
        self.phone_number_id = phone_number_id
        self.access_token = access_token

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def send_text(self, to: str, text: str) -> Optional[str]:
        """Envia mensagem de texto simples. Retorna wa_message_id ou None."""
        phone = self._normalize_phone(to)
        body = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{WA_BASE}/{self.phone_number_id}/messages",
                    headers=self._headers,
                    json=body,
                )
                r.raise_for_status()
                data = r.json()
                msg_id = data.get("messages", [{}])[0].get("id")
                log.info(f"[WA] Mensagem enviada para {phone}: {msg_id}")
                return msg_id
        except Exception as e:
            log.error(f"[WA] Erro ao enviar mensagem: {e}")
            return None

    async def send_text_bulk(self, to: str, text: str) -> Optional[str]:
        """Alias para disparos em massa."""
        return await self.send_text(to, text)

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Remove formatação, garante código de país (55 Brasil)."""
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) <= 11:
            digits = "55" + digits
        return digits


# ─── Parser de payload recebido pelo webhook ────────────────────────────────
def parse_incoming_message(payload: dict) -> Optional[dict]:
    """
    Extrai dados relevantes de um webhook da Meta.
    Retorna dict com: phone, name, text, wa_message_id | None se não for mensagem.
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})

        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        if msg.get("type") != "text":
            # ignora mídia, sticker etc.
            return None

        contacts = value.get("contacts", [{}])
        contact = contacts[0] if contacts else {}

        return {
            "phone": msg["from"],
            "name": contact.get("profile", {}).get("name", ""),
            "text": msg["text"]["body"],
            "wa_message_id": msg.get("id", ""),
        }
    except (IndexError, KeyError, TypeError):
        return None
