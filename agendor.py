"""
Agendor CRM – cliente assíncrono
Endpoints 100% confirmados via cURL testado em produção:

  POST /people                       → cria pessoa (NÃO usar /upsert)
  GET  /people?q=<phone>             → busca pessoa por telefone
  POST /people/{person_id}/deals     → cria negócio vinculado à pessoa
  PUT  /deals/{deal_id}/stage        → move negócio para outra etapa/funil
  POST /deals/{deal_id}/tasks        → cria nota no histórico (só {"text": "..."})
  GET  /funnels                      → lista funis (etapas em 'dealStages')
  GET  /users                        → lista usuários/vendedores
"""
import httpx
import logging
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
    async def find_person_by_phone(self, phone: str) -> Optional[int]:
        """
        Busca pessoa existente pelo telefone.
        IMPORTANTE: valida que o telefone da pessoa encontrada realmente
        corresponde ao buscado — o Agendor retorna matches parciais por nome/email também.
        """
        try:
            phone_clean = "".join(c for c in phone if c.isdigit())
            data = await self._get("/people", {"q": phone_clean})
            people = data.get("data", [])
            log.info(f"[Agendor] Busca por {phone_clean} → {len(people)} resultado(s)")

            for person in people:
                pid = person.get("id")
                contact = person.get("contact") or {}

                # Extrair todos os telefones cadastrados na pessoa
                person_phones = []
                for field in ("mobile", "work", "whatsapp", "phone"):
                    val = contact.get(field) or ""
                    # Normaliza: só dígitos
                    digits = "".join(c for c in str(val) if c.isdigit())
                    if digits:
                        person_phones.append(digits)

                log.info(f"[Agendor] Candidato ID={pid} | telefones={person_phones}")

                # Verifica se algum telefone da pessoa termina com os mesmos dígitos
                # (cobre diferenças de DDI: 5527... vs 27...)
                for p in person_phones:
                    # Compara os últimos 9 dígitos (número local sem DDI/DDD)
                    if phone_clean[-9:] == p[-9:]:
                        log.info(f"[Agendor] ✅ Pessoa confirmada pelo telefone: ID {pid}")
                        return pid

            log.info(f"[Agendor] Nenhuma pessoa com telefone {phone_clean} encontrada — será criada")
        except Exception as e:
            log.error(f"[Agendor] Erro ao buscar pessoa: {e}")
        return None

    async def create_person(self, name: str, phone: str) -> Optional[int]:
        """
        Cria pessoa no Agendor.
        Endpoint: POST /people  (NÃO /people/upsert – retorna 400)
        Campos confirmados: contact.mobile, contact.work, contact.whatsapp
        """
        try:
            phone_clean = "".join(c for c in phone if c.isdigit())
            phone_ddi = f"+{phone_clean}"
            body: Dict[str, Any] = {
                "name": name,
                "allowToAllUsers": True,
                "contact": {
                    "work": phone_clean,
                    "mobile": phone_clean,
                    "whatsapp": phone_ddi,
                },
            }
            data = await self._post("/people", body)
            person_id = data.get("data", {}).get("id")
            log.info(f"[Agendor] Pessoa criada: {name} → ID {person_id}")
            return person_id
        except Exception as e:
            log.error(f"[Agendor] Erro ao criar pessoa: {e}")
            return None

    async def get_or_create_person(self, name: str, phone: str) -> Optional[int]:
        """Busca pessoa pelo telefone; se não encontrar, cria."""
        person_id = await self.find_person_by_phone(phone)
        if person_id:
            return person_id
        return await self.create_person(name, phone)

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
        Cria negócio vinculado à pessoa.
        Endpoint: POST /people/{person_id}/deals
        Campos confirmados via cURL: title, dealStatusText, funnel, dealStage, allowToAllUsers
        """
        try:
            body: Dict[str, Any] = {
                "title": title,
                "dealStatusText": "ongoing",
                "funnel": funnel_id,
                "dealStage": stage_id,
                "allowToAllUsers": True,
            }
            if value_tier:
                body["description"] = f"Faixa de investimento: {value_tier}"

            data = await self._post(f"/people/{person_id}/deals", body)
            deal_id = data.get("data", {}).get("id")
            log.info(f"[Agendor] Negócio criado: {title} → ID {deal_id}")
            return deal_id
        except Exception as e:
            log.error(f"[Agendor] Erro ao criar negócio: {e}")
            return None

    async def move_deal_stage(self, deal_id: int, stage_id: int, funnel_id: Optional[int] = None) -> bool:
        """
        Move negócio para outra etapa.
        Endpoint CORRETO: PUT /deals/{id}/stage
        """
        try:
            body: Dict[str, Any] = {"dealStage": stage_id}
            if funnel_id:
                body["funnel"] = funnel_id
            await self._put(f"/deals/{deal_id}/stage", body)
            log.info(f"[Agendor] Negócio {deal_id} movido para etapa {stage_id}")
            return True
        except Exception as e:
            log.error(f"[Agendor] Erro ao mover etapa: {e}")
            return False

    async def add_note(self, deal_id: int, text: str) -> bool:
        """
        Adiciona nota ao histórico do negócio.
        Endpoint: POST /deals/{id}/tasks
        Body: apenas {"text": "..."} – sem type nem due_date.
        """
        try:
            note_text = text[:2000] if len(text) > 2000 else text
            await self._post(f"/deals/{deal_id}/tasks", {"text": note_text})
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
        """Etapas vêm dentro do funil, chave 'dealStages'."""
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
