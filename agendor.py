"""
Agendor CRM – cliente assíncrono
Docs: https://api.agendor.com.br/docs/
Wiki: https://github.com/agendor/agendor-api-docs/wiki/Exemplos

Endpoints confirmados (v3):
  POST /people/upsert                → cria ou atualiza pessoa (sem duplicar)
  GET  /people?q=<phone>             → busca pessoa por telefone
  POST /people/{person_id}/deals     → cria negócio vinculado à pessoa
  PUT  /deals/{deal_id}              → atualiza negócio (etapa, responsável)
  POST /deals/{deal_id}/tasks        → cria tarefa/nota no negócio
  GET  /funnels                      → lista funis (etapas vêm em 'dealStages')
  GET  /users                        → lista usuários/vendedores
"""
import httpx
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

log = logging.getLogger("agendor")

AGENDOR_BASE = "https://api.agendor.com.br/v3"


class AgendorClient:
    def __init__(self, api_token: str):
        self.headers = {
            "Authorization": f"Token {api_token}",
            "Content-Type": "application/json",
        }

    # ─── helpers ────────────────────────────────────────────────────────────
    async def _get(self, path: str, params: Dict = None) -> Dict:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{AGENDOR_BASE}{path}", headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, body: Dict) -> Dict:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{AGENDOR_BASE}{path}", headers=self.headers, json=body)
            r.raise_for_status()
            return r.json()

    async def _put(self, path: str, body: Dict) -> Dict:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.put(f"{AGENDOR_BASE}{path}", headers=self.headers, json=body)
            r.raise_for_status()
            return r.json()

    # ─── People ─────────────────────────────────────────────────────────────
    async def upsert_person(self, name: str, phone: str) -> Optional[int]:
        """
        Cria ou atualiza uma pessoa no Agendor (sem duplicar).
        Endpoint: POST /people/upsert
        Telefone deve vir dentro de 'contact.mobilePhone'.
        """
        try:
            phone_clean = "".join(c for c in phone if c.isdigit())
            body = {
                "name": name,
                "contact": {
                    "mobilePhone": phone_clean,
                },
            }
            data = await self._post("/people/upsert", body)
            person_id = data.get("data", {}).get("id")
            log.info(f"[Agendor] Pessoa upsert: {name} → ID {person_id}")
            return person_id
        except Exception as e:
            log.error(f"[Agendor] Erro ao criar/atualizar pessoa: {e}")
            return None

    async def find_person_by_phone(self, phone: str) -> Optional[int]:
        """Busca pessoa existente pelo telefone."""
        try:
            phone_clean = "".join(c for c in phone if c.isdigit())
            data = await self._get("/people", {"q": phone_clean})
            people = data.get("data", [])
            if people:
                return people[0]["id"]
        except Exception as e:
            log.error(f"[Agendor] Erro ao buscar pessoa: {e}")
        return None

    # ─── Deals ──────────────────────────────────────────────────────────────
    async def create_deal(
        self,
        title: str,
        person_id: int,
        funnel_id: int,
        stage_id: int,
        owner_id: Optional[int] = None,
        value_tier: Optional[str] = None,
    ) -> Optional[int]:
        """
        Cria um negócio no Agendor vinculado à pessoa.
        Endpoint: POST /people/{person_id}/deals
        Campo da etapa: 'dealStage' (não 'stageId').
        Campo do funil: 'funnel' (não 'funnelId').
        """
        try:
            body: Dict[str, Any] = {
                "title": title,
                "dealStage": stage_id,
                "funnel": funnel_id,
            }
            if owner_id:
                body["allowedUsers"] = [owner_id]
            if value_tier:
                body["description"] = f"Faixa de investimento: {value_tier}"

            data = await self._post(f"/people/{person_id}/deals", body)
            deal_id = data.get("data", {}).get("id")
            log.info(f"[Agendor] Negócio criado: {title} → ID {deal_id}")
            return deal_id
        except Exception as e:
            log.error(f"[Agendor] Erro ao criar negócio: {e}")
            return None

    async def move_deal_stage(self, deal_id: int, stage_id: int) -> bool:
        """Move o negócio para outra etapa do funil."""
        try:
            await self._put(f"/deals/{deal_id}", {"dealStage": stage_id})
            log.info(f"[Agendor] Negócio {deal_id} movido para etapa {stage_id}")
            return True
        except Exception as e:
            log.error(f"[Agendor] Erro ao mover etapa: {e}")
            return False

    async def assign_deal_owner(self, deal_id: int, owner_id: int) -> bool:
        """Atribui responsável ao negócio."""
        try:
            await self._put(f"/deals/{deal_id}", {"allowedUsers": [owner_id]})
            log.info(f"[Agendor] Negócio {deal_id} atribuído ao vendedor {owner_id}")
            return True
        except Exception as e:
            log.error(f"[Agendor] Erro ao atribuir vendedor: {e}")
            return False

    async def add_note(self, deal_id: int, text: str) -> bool:
        """
        Adiciona uma nota/anotação ao negócio via tarefa do tipo NOTA.
        Endpoint: POST /deals/{deal_id}/tasks
        O endpoint /deals/{id}/annotations não existe na API v3.
        """
        try:
            note_text = text[:2000] if len(text) > 2000 else text
            due_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = {
                "text": note_text,
                "type": "NOTA",
                "due_date": due_date,
            }
            await self._post(f"/deals/{deal_id}/tasks", body)
            log.info(f"[Agendor] Nota adicionada ao negócio {deal_id}")
            return True
        except Exception as e:
            log.error(f"[Agendor] Erro ao adicionar nota: {e}")
            return False

    # ─── Utilities ──────────────────────────────────────────────────────────
    async def list_funnels(self) -> List[Dict]:
        try:
            data = await self._get("/funnels")
            return data.get("data", [])
        except Exception as e:
            log.error(f"[Agendor] Erro ao listar funis: {e}")
            return []

    async def list_stages(self, funnel_id: int) -> List[Dict]:
        """Extrai etapas do retorno de /funnels (etapas vêm em 'dealStages')."""
        try:
            data = await self._get("/funnels")
            funnels = data.get("data", [])
            for funnel in funnels:
                fid = funnel.get("id") or funnel.get("_id")
                if str(fid) == str(funnel_id):
                    for key in ("dealStages", "stages", "steps", "funnelSteps"):
                        stages = funnel.get(key, [])
                        if stages:
                            log.info(f"[Agendor] {len(stages)} etapas encontradas (chave: {key})")
                            return stages
            log.warning(f"[Agendor] Funil {funnel_id} não encontrado ou sem etapas")
        except Exception as e:
            log.error(f"[Agendor] Erro ao buscar etapas: {e}")
        return []

    async def list_users(self) -> List[Dict]:
        try:
            data = await self._get("/users")
            return data.get("data", [])
        except Exception as e:
            log.error(f"[Agendor] Erro ao listar usuários: {e}")
            return []
