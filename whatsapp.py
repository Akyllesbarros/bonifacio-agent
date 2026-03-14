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

    async def upload_media(self, file_path: str, mime_type: str = "audio/ogg") -> Optional[str]:
        """Faz upload de mídia para o WhatsApp e retorna o media_id."""
        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            with open(file_path, "rb") as f:
                file_data = f.read()
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{WA_BASE}/{self.phone_number_id}/media",
                    headers=headers,
                    data={"messaging_product": "whatsapp"},
                    files={"file": (file_path.split("/")[-1], file_data, mime_type)},
                )
                r.raise_for_status()
                media_id = r.json().get("id")
                log.info(f"[WA] Mídia enviada: {file_path} → media_id={media_id}")
                return media_id
        except Exception as e:
            log.error(f"[WA] Erro ao fazer upload de mídia: {e}")
            return None

    async def send_audio(self, to: str, media_id: str) -> Optional[str]:
        """Envia áudio como mensagem de voz (voice note) usando media_id já uploadado."""
        phone = self._normalize_phone(to)
        body = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "audio",
            "audio": {"id": media_id},
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
                log.info(f"[WA] Áudio enviado para {phone}: {msg_id}")
                return msg_id
        except Exception as e:
            log.error(f"[WA] Erro ao enviar áudio: {e}")
            return None

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
        msg_type = msg.get("type", "")

        # Extrai texto (text, button reply, ou descrição do tipo para outros)
        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type == "interactive":
            text = (msg.get("interactive", {}).get("button_reply", {}).get("title")
                    or msg.get("interactive", {}).get("list_reply", {}).get("title", ""))
        elif msg_type in ("audio", "voice"):
            text = "[áudio]"
        elif msg_type == "image":
            text = "[imagem]"
        elif msg_type == "video":
            text = "[vídeo]"
        elif msg_type == "document":
            text = "[documento]"
        elif msg_type == "sticker":
            text = "[sticker]"
        else:
            text = f"[{msg_type}]"

        contacts = value.get("contacts", [{}])
        contact = contacts[0] if contacts else {}

        return {
            "phone": msg["from"],
            "name": contact.get("profile", {}).get("name", ""),
            "text": text,
            "wa_message_id": msg.get("id", ""),
        }
    except (IndexError, KeyError, TypeError):
        return None
