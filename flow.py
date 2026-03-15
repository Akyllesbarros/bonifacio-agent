"""
flow.py – Roteiro da Júlia
==========================
AQUI é o único lugar onde você define o fluxo de atendimento.

TIPOS DE ETAPA:
  "send"    → envia mensagens automáticas (áudios, textos). Não espera resposta do Claude.
  "listen"  → aguarda qualquer resposta do lead para avançar. Sem mensagem enviada.
  "ask"     → envia uma pergunta e aguarda resposta interpretada pelo Claude.
  "done"    → fluxo encerrado. Silêncio.

CAMPOS DE CADA ETAPA:
  id          (int)   → número do stage (0, 1, 2...)
  label       (str)   → nome descritivo para logs e dashboard
  type        (str)   → "send" | "listen" | "ask" | "done"
  messages    (list)  → lista de mensagens a enviar (apenas para type="send")
                         cada item: {"type": "audio", "file": "nome.opus"}
                                 ou {"type": "text",  "text": "mensagem aqui"}
  message     (str)   → mensagem a enviar ao entrar na etapa (apenas para type="ask")
  advance     (str)   → "any" = qualquer resposta avança
                         "ai"  = Claude decide se a resposta é suficiente para avançar
  save_to     (str)   → campo do banco onde salvar a resposta do lead (opcional)
                         campos disponíveis: "investment_answer", "value_tier"
  crm_sync    (bool)  → True = dispara sync no Agendor ao ENTRAR nesta etapa
  next        (int)   → próximo stage após avançar

PARA ADICIONAR UMA ETAPA:
  1. Adicione um bloco novo aqui com o "id" correto
  2. Ajuste o "next" da etapa anterior para apontar pro novo id
  3. Pronto. Não precisa mexer em main.py nem agent.py.

FLUXO ATUAL:
  Stage 0 → envia áudio1 + áudio2 + texto → Stage 1
  Stage 1 → aguarda qualquer resposta → sincroniza CRM → Stage 2
  Stage 2 → encerrado
"""

FLOW: list[dict] = [
    {
        "id": 0,
        "label": "Primeiro contato",
        "type": "send",
        "messages": [
            {
                "type": "greeting",   # "Bom dia, Antonio!" / "Boa tarde!" / "Boa noite!"
                "delay_before": 0,
            },
            {
                "type": "audio",
                "file": "audio1.mp3",
                "mime_type": "audio/mpeg",
                "delay_before": 10,   # aguarda 10s antes de enviar o 1º áudio
            },
            {
                "type": "audio",
                "file": "audio2.mp3",
                "mime_type": "audio/mpeg",
                "delay_before": 30,   # aguarda 30s após o 1º áudio
            },
            {
                "type": "text",
                "text": (
                    "Assim eu já consigo entender se faz sentido e se é a fase ideal "
                    "pra te explicar melhor como funciona o clube por dentro 🤝"
                ),
                "delay_before": 10,   # aguarda 10s após o 2º áudio
            },
        ],
        "next": 1,
    },
    {
        "id": 1,
        "label": "Aguardando resposta",
        "type": "listen",
        "advance": "any",
        "crm_sync": True,
        "next": 2,
    },
    {
        "id": 2,
        "label": "Concluído",
        "type": "done",
    },
]

# ── Persona da Júlia (usada quando advance="ai") ──────────────────────────
# Editável aqui sem tocar no agent.py
JULIA_PERSONA = """Você é a Júlia, assistente virtual do Bonifácio Clube de Investidores.

IDENTIDADE E TOM:
- Atendimento ágil, acolhedor e à altura do padrão de excelência do Clube.
- Linguagem leve, elegante e confiante.
- Faço UMA ÚNICA pergunta por vez. Respostas com no máximo uma frase + uma pergunta.
- Sou o mais humanizada possível. Nunca me apresento mais de uma vez.
- Uso emojis 🌎 ✨ 🤝 apenas em momentos sutis — não em toda mensagem.

REGRAS ABSOLUTAS:
- Nunca forneço números, juros, rentabilidade, promessas ou porcentagens.
- Evito as palavras: investir, lucro, retorno, seguro, aplicação, dividendos.
- Nunca invento informações.
- Não respondo perguntas fora do escopo do pré-atendimento.

TRATAMENTO DE OBJEÇÕES:
- Se pedirem rentabilidade/números: "Esses detalhes são apresentados diretamente pelo consultor na reunião."
- Se não quiserem informar valores: "Sem problema! Pode ser uma faixa aproximada."

RESPONDA SEMPRE em português brasileiro. Seja concisa e humanizada."""


# ── Helpers ───────────────────────────────────────────────────────────────
def get_stage(stage_id: int) -> dict | None:
    """Retorna a config da etapa pelo id."""
    for step in FLOW:
        if step["id"] == stage_id:
            return step
    return None
