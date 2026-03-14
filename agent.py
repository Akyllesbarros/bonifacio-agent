"""
agent.py – Motor de IA da Júlia
================================
Responsável por:
  1. Interpretar a resposta do lead usando o Claude (quando advance="ai")
  2. Decidir se a resposta é suficiente para avançar de etapa
  3. Gerar a resposta de texto quando necessário
  4. Construir notas de CRM

Você NÃO edita este arquivo para mudar o fluxo.
Edite flow.py.
"""
import json
import logging
from typing import Optional
from anthropic import AsyncAnthropic

log = logging.getLogger("agent")


class JuliaAgent:
    def __init__(self, api_key: str):
        self.client = AsyncAnthropic(api_key=api_key) if api_key else None

    async def interpret(
        self,
        stage_config: dict,
        user_message: str,
        user_name: Optional[str],
        history: list,
    ) -> dict:
        """
        Interpreta a mensagem do lead dentro do contexto da etapa atual.

        Retorna:
          {
            "advance": bool,        # deve avançar de etapa?
            "reply": str | None,    # resposta a enviar (None = silêncio)
            "save_value": str | None  # valor a salvar no campo save_to
          }
        """
        advance_mode = stage_config.get("advance", "any")

        # ── "any": qualquer resposta avança, sem usar IA ──────────────────
        if advance_mode == "any":
            return {"advance": True, "reply": None, "save_value": None}

        # ── "ai": Claude decide ───────────────────────────────────────────
        if advance_mode == "ai":
            return await self._ai_decide(stage_config, user_message, user_name, history)

        return {"advance": False, "reply": None, "save_value": None}

    async def _ai_decide(
        self,
        stage_config: dict,
        user_message: str,
        user_name: Optional[str],
        history: list,
    ) -> dict:
        """
        Chama o Claude para:
          1. Verificar se o lead respondeu o suficiente para avançar
          2. Gerar resposta de texto (se necessário)
          3. Extrair o valor a salvar (se save_to estiver configurado)
        """
        from flow import JULIA_PERSONA

        if not self.client:
            log.warning("[Agent] API key não configurada — avançando sem IA")
            return {"advance": True, "reply": None, "save_value": None}

        first_name = user_name.split()[0] if user_name else "lead"
        label = stage_config.get("label", "")
        save_to = stage_config.get("save_to", "")

        # Monta histórico
        messages = []
        for h in history[-10:]:
            role = "user" if h["direction"] == "in" else "assistant"
            messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        # Instrução para o Claude responder em JSON
        stage_instruction = f"""
ETAPA ATUAL: {label}
NOME DO LEAD: {first_name}

Você deve analisar a resposta do lead e retornar SOMENTE um JSON válido com:
{{
  "advance": true/false,
  "reply": "sua resposta de texto aqui ou null se não precisar responder",
  "save_value": "valor extraído da resposta do lead para salvar, ou null"
}}

- "advance": true se o lead respondeu o suficiente para ir para a próxima etapa
- "advance": false se ainda precisar de mais informação (envie "reply" com nova pergunta)
- "reply": null significa silêncio (não enviar mensagem)
- "save_value": extraia o valor relevante da resposta{f' para o campo {save_to}' if save_to else ''}

RETORNE APENAS O JSON. Sem explicações, sem markdown, sem texto extra.
"""

        try:
            resp = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                system=JULIA_PERSONA + "\n\n" + stage_instruction,
                messages=messages,
            )
            raw = resp.content[0].text.strip()
            # Remove possíveis marcadores de código
            raw = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            return {
                "advance": bool(result.get("advance", False)),
                "reply": result.get("reply") or None,
                "save_value": result.get("save_value") or None,
            }
        except Exception as e:
            log.error(f"[Agent] Erro ao chamar Claude: {e}")
            # Fallback: avança sem responder
            return {"advance": True, "reply": None, "save_value": None}

    def build_crm_note(
        self,
        name: str,
        messages: list,
        extra_fields: dict = None,
    ) -> str:
        """Gera nota para o Agendor com histórico da conversa."""
        lines = [
            "📱 CONTATO WhatsApp – Júlia IA",
            f"👤 Lead: {name}",
        ]
        if extra_fields:
            for k, v in extra_fields.items():
                if v:
                    lines.append(f"   {k}: {v}")
        lines += ["", "📝 Histórico:"]
        for m in messages[-20:]:
            direction = "Cliente" if m["direction"] == "in" else "Júlia"
            lines.append(f"  [{direction}] {m['content'][:200]}")
        return "\n".join(lines)

    @staticmethod
    def extract_name(raw: str) -> Optional[str]:
        if not raw or len(raw.strip()) < 2:
            return None
        generic = {"user", "lead", "cliente", "test", "teste", "undefined", "null"}
        if raw.lower().strip() in generic:
            return None
        if any(ord(c) > 9000 for c in raw):
            return None
        return raw.strip().title()
