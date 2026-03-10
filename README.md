# 🏛️ Bonifácio Clube de Investidores – Agente IA WhatsApp + CRM

Sistema completo de pré-atendimento automático via WhatsApp com integração ao CRM Agendor e dashboard de controle.

---

## 🗂️ Estrutura do Projeto

```
bonifacio-agent/
├── main.py              # Servidor FastAPI (API + webhook + dashboard)
├── agent.py             # Lógica da Júlia (agente IA)
├── agendor.py           # Cliente da API do Agendor CRM
├── whatsapp.py          # Cliente da WhatsApp Business Cloud API
├── database.py          # Modelos SQLite (SQLAlchemy async)
├── config.py            # Configurações (env vars)
├── requirements.txt
├── .env.example         # Exemplo de variáveis de ambiente
└── frontend/
    └── index.html       # Dashboard completo (single-file)
```

---

## ⚡ Instalação e Execução

### 1. Instalar dependências

```bash
cd bonifacio-agent
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite o .env com suas credenciais
```

### 3. Iniciar o servidor

```bash
python main.py
# Ou com reload automático:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Acessar o dashboard

Abra no navegador: `http://localhost:8000`

---

## 🔧 Configuração Passo a Passo

### WhatsApp Business API (Meta)

1. Crie um app no [Meta for Developers](https://developers.facebook.com)
2. Adicione o produto "WhatsApp"
3. Configure o webhook apontando para: `https://seudominio.com/webhook`
4. Copie o **Phone Number ID** e o **Access Token** para o dashboard
5. Use o **Verify Token** definido nas configurações

### Agendor CRM

1. Acesse [Agendor](https://app.agendor.com.br) → Integrações → API
2. Gere o token da API
3. No dashboard, vá em **Configurações** e:
   - Cole o token do Agendor
   - Clique em "Recarregar funis" para carregar seus funis
   - Selecione o funil onde os leads serão criados
   - Selecione a **Etapa Inicial** (Ex: "Novo Lead")
   - Selecione a **Etapa Qualificado** (Ex: "Qualificado")
   - Carregue os vendedores e selecione Lívia e Luiza para o rodízio

### Anthropic (Claude)

1. Acesse [console.anthropic.com](https://console.anthropic.com)
2. Crie uma API Key
3. Cole no campo **Anthropic API Key** no dashboard

---

## 🌊 Fluxo do Sistema

```
Lead manda mensagem no WhatsApp
         ↓
Webhook recebe na rota POST /webhook
         ↓
Sistema verifica se IA está ativa (global + por conversa)
         ↓
         ├── IA ativa → Júlia processa e responde
         └── IA pausada → ignora (operador responde pelo dashboard)
         
Estágios da Júlia:
  0 → Envia saudação e pede nome
  1 → Recebe nome, pergunta sobre investimentos
  2 → Recebe resposta, mostra enquete de valor
  3 → Recebe faixa de valor, envia mensagem de encerramento
  4 → Qualificação concluída → sincroniza no Agendor

Sync Agendor (background):
  1. Cria pessoa (nome + telefone)
  2. Cria negócio no funil configurado
  3. Assign vendedor (rodízio)
  4. Move para etapa "Qualificado"
  5. Adiciona nota com histórico da conversa
```

---

## 🎛️ Dashboard – Funcionalidades

### Aba Conversas
- Lista todos os leads em tempo real (atualiza a cada 5s)
- Badge de status (Iniciado / Em andamento / ✅ Qualificado)
- Clique em um lead para ver o histórico de mensagens
- **Parar IA**: pausa a Júlia para aquele contato (operador assume)
- **Retomar IA**: reativa a Júlia para o contato
- Painel lateral com detalhes do lead (nome, valor, CRM link, etapa)
- Campo de resposta manual (disponível quando IA pausada)

### Botão "IA Global" (cabeçalho)
- Liga/desliga a Júlia para TODOS os novos contatos simultaneamente

### Aba Disparo em Massa
- Cole lista de telefones (um por linha ou separados por vírgula)
- Escreva a mensagem com preview em tempo real
- Envio com rate limiting básico

### Aba Configurações
- Configure todas as integrações via interface
- Carregue funis e etapas do Agendor dinamicamente
- Selecione vendedores para o rodízio
- Copie a URL do webhook com 1 clique

---

## 🔄 Rodízio de Vendedores

O sistema faz rodízio **consecutivo** entre os vendedores configurados.

Exemplo com Lívia (ID: 5) e Luiza (ID: 8):
```
Lead 1 → Lívia
Lead 2 → Luiza
Lead 3 → Lívia
...
```

A ordem é mantida no banco de dados, garantindo consistência mesmo após reiniciar o servidor.

Para configurar, vá em **Configurações → Rodízio de Vendedores** e selecione os vendedores carregados do Agendor.

---

## 🚀 Deploy em Produção

### Com ngrok (teste rápido)
```bash
ngrok http 8000
# Use a URL gerada como webhook na Meta
```

### Com servidor VPS (produção)
```bash
# Com Nginx como proxy reverso + SSL
# Instale o certificado SSL (Let's Encrypt) para HTTPS
# A Meta exige HTTPS para webhooks
```

### Variáveis de ambiente em produção
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export WA_PHONE_NUMBER_ID="..."
export WA_ACCESS_TOKEN="..."
# etc.
```

---

## 📝 Notas Importantes

- O banco de dados `bonifacio.db` é criado automaticamente na primeira execução
- Todas as configurações salvas no dashboard persistem no banco
- As configurações do `.env` são usadas como fallback quando não há valor no banco
- Mensagens de mídia (foto, áudio, vídeo) são ignoradas — apenas texto
- A Júlia nunca responde fora do escopo de pré-atendimento
