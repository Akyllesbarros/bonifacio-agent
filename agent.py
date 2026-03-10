"""
Agente Júlia – Pré-atendimento Bonifácio Clube de Investidores
State machine:
  0 = início (envia saudação e pergunta nome)
  1 = aguardando nome
  2 = aguardando status de investimento
  3 = aguardando faixa de valor
  4 = concluído (transferido)
"""
import logging
import re
from typing import List, Optional, Tuple
from anthropic import AsyncAnthropic

log = logging.getLogger("agent")

# ─── VALUE TIER MAP ─────────────────────────────────────────────────────────
VALUE_TIERS = {
    "1": "Abaixo de R$35.000",
    "2": "Acima de R$35.000",
    "3": "Acima de R$100.000",
    "4": "Acima de R$250.000",
}

# ─── SYSTEM PROMPT ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é a Júlia, assistente virtual do Bonifácio Clube de Investidores.

IDENTIDADE E TOM:
- Fui treinada para oferecer um atendimento ágil, acolhedor e à altura do padrão de excelência do Clube.
- Minha função é conduzir o primeiro contato com exclusividade, entender o essencial e encaminhar para um consultor.
- Uso linguagem leve, elegante e confiante.
- Faço UMA ÚNICA pergunta por vez, mantendo respostas com no máximo uma frase + uma pergunta.
- Sou o mais humanizada possível.
- Nunca me apresento mais de uma vez.
- Uso emojis 🌎 ✨ 🤝 apenas em momentos sutis e estratégicos — não em toda mensagem.

REGRAS ABSOLUTAS (NUNCA QUEBRAR):
- Nunca fornecerei números, juros, rentabilidade, promessas ou porcentagens.
- Evito as palavras: investir, lucro, retorno, seguro, aplicação, dividendos.
- Nunca invento informações.
- Não respondo nada fora do escopo do pré-atendimento.
- Não respondo perguntas sobre o investimento, riscos ou valores — digo que somente o consultor conseguirá responder.
- Uso o nome do lead apenas em pontos-chave, não em toda mensagem.

SOBRE O CLUBE (caso perguntem):
O Bonifácio Clube de Investidores é um círculo privado que dá acesso a operações e estratégias institucionais, estruturadas para quem busca segurança e alta performance com acompanhamento profissional.

TRATAMENTO DE OBJEÇÕES:
- Se pedirem rentabilidade/números/porcentagens: "Esses detalhes são apresentados diretamente pelo consultor na reunião, com total transparência."
- Se não quiserem informar valores: "Sem problema! Pode ser uma faixa aproximada, é só pra direcionar melhor o consultor certo pro seu perfil."
- Se insistirem em rentabilidade: "Esses detalhes são apresentados diretamente pelo consultor, durante a reunião. Ele vai te mostrar o modelo completo de acesso institucional, com total transparência."

FLUXO DE QUALIFICAÇÃO:
1. Verificar nome (se parecer genérico, emoji ou incompleto, perguntar de forma natural)
2. Perguntar: "Hoje você já investe em algo ou está buscando dar o primeiro passo?"
3. Perguntar sobre faixa de patrimônio com as opções numeradas:
   "1. Abaixo de R$35.000 (Reais)
    2. Acima de R$35.000 (Reais)
    3. Acima de R$100.000 (Reais)
    4. Acima de R$250.000 (Reais)"
4. Mensagem de encerramento e transferência

MENSAGEM DE ENCERRAMENTO (usar exatamente quando qualificação concluída):
"Excelente, muito obrigado por compartilhar essas informações.
A partir desse momento uma das assistentes do Maik vai continuar seu atendimento. O fluxo de atendimento pode estar um pouco alto, mas fique tranquilo(a) em breve será atendido(a).
Agradeço pela confiança e pelo interesse.
Seja bem-vindo(a) a um novo nível de acesso e inteligência financeira. ✨"

RESPONDA SEMPRE em português brasileiro. Seja concisa, elegante e humanizada."""


class JuliaAgent:
    def __init__(self, api_key: str):
        self.client = AsyncAnthropic(api_key=api_key)

    async def process_message(
        self,
        conversation_stage: int,
        user_name: Optional[str],
        wa_display_name: str,
        history: List[dict],
        user_message: str,
    ) -> Tuple[str, int, Optional[str], Optional[str]]:
        """
        Processa a mensagem e retorna:
          (resposta, novo_stage, nome_atualizado, value_tier)
        """

        # ── Stage 0: primeiro contato ──────────────────────────────────────
        if conversation_stage == 0:
            greeting = self._build_greeting(wa_display_name)
            new_stage = 1 if self._name_looks_valid(wa_display_name) else 1
            return greeting, new_stage, self._extract_name(wa_display_name), None

        # ── Monta histórico para o Claude ──────────────────────────────────
        messages = self._build_messages(history, user_message, conversation_stage, user_name)

        # ── Instrução de contexto de etapa ────────────────────────────────
        stage_context = self._stage_context(conversation_stage, user_name)

        response_text = await self._call_claude(messages, stage_context)

        # ── Detecta atualizações de estado ────────────────────────────────
        new_stage = conversation_stage
        new_name = user_name
        new_tier = None

        if conversation_stage == 1:
            # Esperando nome
            extracted = self._try_extract_name(user_message)
            if extracted:
                new_name = extracted
                new_stage = 2

        elif conversation_stage == 2:
            # Esperando status de investimento
            if len(user_message.strip()) > 2:
                new_stage = 3

        elif conversation_stage == 3:
            # Esperando faixa de valor
            tier = self._extract_value_tier(user_message)
            if tier:
                new_tier = tier
                new_stage = 4

        return response_text, new_stage, new_name, new_tier

    # ─── Mensagem de abertura ────────────────────────────────────────────────
    def _build_greeting(self, wa_name: str) -> str:
        if self._name_looks_valid(wa_name):
            return (
                "Olá! 👋\n"
                "Eu sou a Júlia, assistente do Bonifácio Clube de Investidores.\n"
                "Vou conduzir esse primeiro atendimento para que você seja atendido com mais agilidade e exclusividade por um de nossos consultores.\n\n"
                f"Como posso te chamar?"
            )
        return (
            "Olá! 👋\n"
            "Eu sou a Júlia, assistente do Bonifácio Clube de Investidores.\n"
            "Vou conduzir esse primeiro atendimento para que você seja atendido com mais agilidade e exclusividade por um de nossos consultores.\n\n"
            "Como posso te chamar?"
        )

    def _stage_context(self, stage: int, name: Optional[str]) -> str:
        first_name = name.split()[0] if name else ""
        contexts = {
            1: "O lead acabou de receber a saudação. Agora ele está respondendo com o nome dele. Confirme o nome de forma natural e pergunte sobre o status de investimento atual.",
            2: f"Você já sabe o nome do lead ({first_name}). Ele acabou de responder sobre investimentos. Agradeça de forma natural e pergunte sobre a faixa de patrimônio com as 4 opções numeradas.",
            3: f"O lead ({first_name}) está respondendo sobre a faixa de valor. Se ele escolheu uma opção válida (1, 2, 3 ou 4), agradeça e envie a mensagem de ENCERRAMENTO exata. Se não escolheu ainda, encoraje gentilmente.",
            4: "A qualificação foi concluída. Se o lead mandar mensagem, responda brevemente que o consultor já foi acionado e entrará em contato em breve.",
        }
        return contexts.get(stage, "")

    def _build_messages(self, history: List[dict], current_msg: str,
                         stage: int, name: Optional[str]) -> List[dict]:
        messages = []
        for h in history[-10:]:  # últimas 10 mensagens
            role = "user" if h["direction"] == "in" else "assistant"
            messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": current_msg})
        return messages

    async def _call_claude(self, messages: List[dict], stage_context: str) -> str:
        system = SYSTEM_PROMPT
        if stage_context:
            system += f"\n\nCONTEXTO DA ETAPA ATUAL: {stage_context}"
        try:
            resp = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                system=system,
                messages=messages,
            )
            return resp.content[0].text.strip()
        except Exception as e:
            log.error(f"[Agent] Erro Claude API: {e}")
            return "Desculpe, estou com uma instabilidade momentânea. Por favor, tente novamente em instantes. 🙏"

    # ─── Helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _name_looks_valid(name: str) -> bool:
        if not name:
            return False
        if any(c for c in name if ord(c) > 9000):  # emojis unicode
            return False
        words = name.strip().split()
        if len(words) < 1 or len(name.strip()) < 3:
            return False
        generic = {"user", "lead", "cliente", "test", "teste", "undefined", "null"}
        if name.lower().strip() in generic:
            return False
        return True

    @staticmethod
    def _extract_name(raw: str) -> Optional[str]:
        if not raw or not JuliaAgent._name_looks_valid(raw):
            return None
        return raw.strip().title()

    @staticmethod
    def _try_extract_name(text: str) -> Optional[str]:
        """Tenta extrair nome de uma resposta do usuário."""
        text = text.strip()
        if len(text) < 2:
            return None
        # Remove artigos comuns
        text = re.sub(r"^(me chamo|meu nome é|sou o|sou a|pode me chamar de)\s*", "",
                      text, flags=re.IGNORECASE).strip()
        if len(text) > 1 and not any(c.isdigit() for c in text):
            return text.title()
        return None

    @staticmethod
    def _extract_value_tier(text: str) -> Optional[str]:
        """Detecta qual opção de valor foi escolhida (1-4)."""
        text = text.strip()
        # Número direto
        for key, val in VALUE_TIERS.items():
            if text == key:
                return val
        # Número com ponto/parênteses
        m = re.search(r"\b([1-4])\b", text)
        if m:
            return VALUE_TIERS.get(m.group(1))
        # Texto com o valor
        if "35" in text and "abaixo" in text.lower():
            return VALUE_TIERS["1"]
        if "250" in text:
            return VALUE_TIERS["4"]
        if "100" in text:
            return VALUE_TIERS["3"]
        if "35" in text:
            return VALUE_TIERS["2"]
        # Qualquer resposta sobre não querer informar → marca como "Não informado"
        no_keywords = ["não", "nao", "prefiro", "quero", "depois", "privado", "sigilo"]
        if any(k in text.lower() for k in no_keywords):
            return "Não informado"
        return None

    def build_crm_note(self, name: str, investment_answer: Optional[str],
                        value_tier: Optional[str], messages: List[dict]) -> str:
        """Gera a nota resumida para o Agendor."""
        lines = [
            f"📱 PRÉ-ATENDIMENTO WhatsApp – Júlia IA",
            f"👤 Lead: {name}",
            f"💼 Investe atualmente: {investment_answer or 'Não informado'}",
            f"💰 Faixa de patrimônio: {value_tier or 'Não informado'}",
            "",
            "📝 Resumo da conversa:",
        ]
        for m in messages[-20:]:
            direction = "Cliente" if m["direction"] == "in" else "Júlia"
            lines.append(f"  [{direction}] {m['content'][:200]}")
        return "\n".join(lines)
