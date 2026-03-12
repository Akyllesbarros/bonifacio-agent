"""
Bonifácio – Agente IA WhatsApp + CRM Agendor
FastAPI application
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, desc

from config import settings
from database import (
    init_db, get_db, Conversation, Message,
    AppSetting, SalespersonRotation
)
from agendor import AgendorClient
from whatsapp import WhatsAppClient, parse_incoming_message
from agent import JuliaAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


# ─── Lifespan ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from database import AsyncSessionLocal, _DB_BACKEND
    async with AsyncSessionLocal() as db:
        total = (await db.execute(select(func.count(Conversation.id)))).scalar()
        log.info(f"✅ Banco inicializado [{_DB_BACKEND.upper()}] — {total} conversa(s) existente(s)")
    yield


app = FastAPI(title="Bonifácio AI Agent", lifespan=lifespan)

# ─── Serve frontend ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ─── Helper: get runtime setting (DB overrides env) ─────────────────────────
async def get_setting(key: str, db: AsyncSession, default: str = "") -> str:
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = r.scalar_one_or_none()
    if row:
        return row.value
    # fallback to env/config
    env_map = {
        "anthropic_api_key": settings.anthropic_api_key,
        "wa_phone_number_id": settings.wa_phone_number_id,
        "wa_access_token": settings.wa_access_token,
        "wa_verify_token": settings.wa_verify_token,
        "agendor_api_token": settings.agendor_api_token,
        "agendor_funnel_id": str(settings.agendor_funnel_id),
        "agendor_stage_initial": str(settings.agendor_stage_initial),
        "agendor_stage_qualified": str(settings.agendor_stage_qualified),
        "agendor_salespeople_ids": settings.agendor_salespeople_ids,
        "ai_global_active": "true",
    }
    return env_map.get(key, default)


async def set_setting(key: str, value: str, db: AsyncSession):
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = r.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()


# ─── Round-robin salesperson ─────────────────────────────────────────────────
async def get_next_salesperson(value_tier: Optional[str], db: AsyncSession) -> Optional[int]:
    ids_str = await get_setting("agendor_salespeople_ids", db)
    ids = [int(x.strip()) for x in ids_str.split(",") if x.strip()]
    if not ids:
        return None

    tier_key = value_tier or "default"
    r = await db.execute(select(SalespersonRotation).where(SalespersonRotation.tier == tier_key))
    rot = r.scalar_one_or_none()
    if not rot:
        rot = SalespersonRotation(tier=tier_key, next_index=0)
        db.add(rot)

    idx = rot.next_index % len(ids)
    salesperson_id = ids[idx]
    rot.next_index = (idx + 1) % len(ids)
    await db.commit()
    return salesperson_id


# ─── WhatsApp Webhook ────────────────────────────────────────────────────────
@app.get("/webhook")
async def wa_verify(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    verify_token = await get_setting("wa_verify_token", db, "bonifacio_verify")
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == verify_token):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(403, "Token inválido")


@app.post("/webhook")
async def wa_receive(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()
    msg_data = parse_incoming_message(payload)
    if not msg_data:
        return JSONResponse({"status": "ignored"})

    phone = msg_data["phone"]
    wa_name = msg_data["name"]
    text = msg_data["text"]
    wa_msg_id = msg_data["wa_message_id"]

    # ── Get or create conversation ──────────────────────────────────────────
    r = await db.execute(select(Conversation).where(Conversation.phone == phone))
    conv = r.scalar_one_or_none()
    if not conv:
        conv = Conversation(phone=phone, name=wa_name or None, stage=0, ai_active=True)
        db.add(conv)
        await db.flush()

    # ── Store incoming message ──────────────────────────────────────────────
    db.add(Message(
        conversation_id=conv.id,
        direction="in",
        content=text,
        wa_message_id=wa_msg_id,
    ))
    await db.commit()
    await db.refresh(conv)

    # ── Check global AI switch ──────────────────────────────────────────────
    global_ai = await get_setting("ai_global_active", db, "true")
    if global_ai.lower() != "true" or not conv.ai_active:
        return JSONResponse({"status": "ai_paused"})

    # ── Get conversation history ────────────────────────────────────────────
    r2 = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(40)
    )
    history = [{"direction": m.direction, "content": m.content} for m in r2.scalars().all()]

    # ── Run agent ──────────────────────────────────────────────────────────
    api_key = await get_setting("anthropic_api_key", db)
    agent = JuliaAgent(api_key)

    reply, new_stage, new_name, new_tier = await agent.process_message(
        conversation_stage=conv.stage,
        user_name=conv.name,
        wa_display_name=wa_name,
        history=history[:-1],   # exclude last (just added)
        user_message=text,
    )

    log.info(f"[STAGE] phone={phone} | stage {conv.stage} → {new_stage} | name={new_name!r} | tier={new_tier!r} | msg={text!r}")

    # ── Update conversation ────────────────────────────────────────────────
    if new_name:
        conv.name = new_name
    if new_tier:
        conv.value_tier = new_tier
    if conv.stage == 2 and new_stage > 2:
        conv.investment_answer = text  # save investment status reply

    conv.stage = new_stage
    conv.updated_at = datetime.utcnow()

    # ── Send reply via WhatsApp ────────────────────────────────────────────
    wa_phone_id = await get_setting("wa_phone_number_id", db)
    wa_token = await get_setting("wa_access_token", db)
    wa_client = WhatsAppClient(wa_phone_id, wa_token)

    out_msg_id = await wa_client.send_text(phone, reply)

    db.add(Message(
        conversation_id=conv.id,
        direction="out",
        content=reply,
        wa_message_id=out_msg_id,
    ))
    await db.commit()

    # ── CRM sync when qualification completes ──────────────────────────────
    if new_stage == 4 and conv.agendor_deal_id is None:
        log.info(f"[CRM] 🚀 Disparando sync para conv_id={conv.id} phone={phone} tier={conv.value_tier!r}")
        task = asyncio.create_task(_sync_to_agendor(conv.id))
        task.add_done_callback(lambda t: log.error(f"[CRM] Task falhou: {t.exception()}") if not t.cancelled() and t.exception() else None)
    else:
        log.info(f"[CRM] Sync NÃO disparado — new_stage={new_stage}, deal_id={conv.agendor_deal_id}")

    return JSONResponse({"status": "ok"})


async def _sync_to_agendor(conv_id: int):
    """Background task: cria pessoa + negócio no Agendor, move etapa, adiciona nota."""
    from database import AsyncSessionLocal
    log.info(f"[CRM] ── Iniciando sync para conv_id={conv_id}")
    try:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Conversation).where(Conversation.id == conv_id))
            conv = r.scalar_one_or_none()
            if not conv:
                log.error(f"[CRM] conv_id={conv_id} não encontrado no banco")
                return

            agendor_token = await get_setting("agendor_api_token", db)
            funnel_id_str = await get_setting("agendor_funnel_id", db)
            stage_initial_str = await get_setting("agendor_stage_initial", db)
            stage_qualified_str = await get_setting("agendor_stage_qualified", db)

            log.info(f"[CRM] Config → token={'✅' if agendor_token else '❌ VAZIO'} | funnel={funnel_id_str!r} | stage_initial={stage_initial_str!r} | stage_qualified={stage_qualified_str!r}")

            funnel_id = int(funnel_id_str) if funnel_id_str else 0
            stage_initial = int(stage_initial_str) if stage_initial_str else 0
            stage_qualified = int(stage_qualified_str) if stage_qualified_str else 0

            if not agendor_token:
                log.warning("[CRM] ❌ Token do Agendor não configurado — abortando sync")
                return
            if not funnel_id:
                log.warning("[CRM] ❌ Funil do Agendor não configurado — abortando sync")
                return

            crm = AgendorClient(agendor_token)
            name = conv.name or conv.phone
            log.info(f"[CRM] Lead: {name} | phone: {conv.phone} | tier: {conv.value_tier}")

            # 1. Buscar ou criar pessoa
            log.info("[CRM] Passo 1 → get_or_create_person")
            person_id = await crm.get_or_create_person(name, conv.phone)
            if not person_id:
                log.error("[CRM] ❌ Falha ao obter/criar pessoa no Agendor")
                return
            log.info(f"[CRM] ✅ Pessoa: ID {person_id}")

            # 2. Atribuir vendedor
            salesperson_id = await get_next_salesperson(conv.value_tier, db)
            log.info(f"[CRM] Vendedor atribuído: {salesperson_id}")

            # 3. Criar negócio
            deal_title = f"Lead WhatsApp – {name}"
            log.info(f"[CRM] Passo 3 → create_deal: {deal_title!r} | funnel={funnel_id} | stage={stage_initial}")
            deal_id = await crm.create_deal(
                title=deal_title,
                person_id=person_id,
                funnel_id=funnel_id,
                stage_id=stage_initial,
                owner_id=salesperson_id,
                value_tier=conv.value_tier,
            )
            if not deal_id:
                log.error("[CRM] ❌ Falha ao criar negócio")
                return
            log.info(f"[CRM] ✅ Negócio criado: ID {deal_id}")

            # 4. Mover para etapa qualificado
            if stage_qualified:
                log.info(f"[CRM] Passo 4 → move_deal_stage: deal={deal_id} stage={stage_qualified}")
                await crm.move_deal_stage(deal_id, stage_qualified, funnel_id=funnel_id)

            # 5. Adicionar nota com histórico
            r2 = await db.execute(
                select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
            )
            messages = [{"direction": m.direction, "content": m.content} for m in r2.scalars().all()]
            agent = JuliaAgent("")
            note = agent.build_crm_note(name, conv.investment_answer, conv.value_tier, messages)
            log.info(f"[CRM] Passo 5 → add_note ({len(note)} chars)")
            await crm.add_note(deal_id, note)

            # 6. Salvar IDs no banco
            conv.agendor_person_id = person_id
            conv.agendor_deal_id = deal_id
            conv.agendor_salesperson_id = salesperson_id
            await db.commit()
            log.info(f"[CRM] ✅ SYNC COMPLETO — person={person_id} deal={deal_id} seller={salesperson_id}")

    except Exception as e:
        log.exception(f"[CRM] ❌ Exceção inesperada no sync: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# REST API – Dashboard
# ═══════════════════════════════════════════════════════════════════════════

# ─── Conversations ─────────────────────────────────────────────────────────
@app.get("/api/conversations")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at))
    )
    convs = r.scalars().all()
    result = []
    for c in convs:
        # last message
        r2 = await db.execute(
            select(Message)
            .where(Message.conversation_id == c.id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        last = r2.scalar_one_or_none()
        result.append({
            "id": c.id,
            "phone": c.phone,
            "name": c.name or c.phone,
            "stage": c.stage,
            "ai_active": c.ai_active,
            "value_tier": c.value_tier,
            "agendor_deal_id": c.agendor_deal_id,
            "agendor_salesperson_id": c.agendor_salesperson_id,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat() if c.updated_at else c.created_at.isoformat(),
            "last_message": last.content[:80] if last else "",
            "last_message_direction": last.direction if last else "",
        })
    return result


@app.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    msgs = r.scalars().all()
    return [{"id": m.id, "direction": m.direction, "content": m.content,
             "created_at": m.created_at.isoformat()} for m in msgs]


@app.post("/api/conversations/{conv_id}/toggle-ai")
async def toggle_ai(conv_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = r.scalar_one_or_none()
    if not conv:
        raise HTTPException(404)
    conv.ai_active = not conv.ai_active
    await db.commit()
    return {"ai_active": conv.ai_active}


@app.post("/api/conversations/{conv_id}/send")
async def send_manual_message(conv_id: int, request: Request,
                               db: AsyncSession = Depends(get_db)):
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "Texto vazio")
    r = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = r.scalar_one_or_none()
    if not conv:
        raise HTTPException(404)

    wa_phone_id = await get_setting("wa_phone_number_id", db)
    wa_token = await get_setting("wa_access_token", db)
    wa_client = WhatsAppClient(wa_phone_id, wa_token)
    msg_id = await wa_client.send_text(conv.phone, text)

    db.add(Message(conversation_id=conv_id, direction="out", content=text, wa_message_id=msg_id))
    conv.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "sent"}


# ─── Global AI switch ───────────────────────────────────────────────────────
@app.get("/api/settings/ai-status")
async def ai_status(db: AsyncSession = Depends(get_db)):
    val = await get_setting("ai_global_active", db, "true")
    return {"ai_global_active": val == "true"}


@app.post("/api/settings/ai-toggle")
async def ai_toggle(db: AsyncSession = Depends(get_db)):
    current = await get_setting("ai_global_active", db, "true")
    new_val = "false" if current == "true" else "true"
    await set_setting("ai_global_active", new_val, db)
    return {"ai_global_active": new_val == "true"}


# ─── Settings CRUD ──────────────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    keys = [
        "anthropic_api_key", "wa_phone_number_id", "wa_access_token",
        "wa_verify_token", "agendor_api_token", "agendor_funnel_id",
        "agendor_stage_initial", "agendor_stage_qualified", "agendor_salespeople_ids",
    ]
    result = {}
    for key in keys:
        val = await get_setting(key, db)
        # Mask sensitive keys
        if "token" in key or "key" in key:
            result[key] = ("*" * 8 + val[-4:]) if len(val) > 4 else ("*" * len(val))
        else:
            result[key] = val
    return result


@app.post("/api/settings")
async def save_settings(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    allowed = [
        "anthropic_api_key", "wa_phone_number_id", "wa_access_token",
        "wa_verify_token", "agendor_api_token", "agendor_funnel_id",
        "agendor_stage_initial", "agendor_stage_qualified", "agendor_salespeople_ids",
    ]
    for key, val in body.items():
        if key in allowed and val and not val.startswith("****"):
            await set_setting(key, str(val), db)
    return {"status": "saved"}


# ─── Agendor helpers (for settings UI) ─────────────────────────────────────
@app.get("/api/agendor/funnels")
async def agendor_funnels(db: AsyncSession = Depends(get_db)):
    token = await get_setting("agendor_api_token", db)
    if not token:
        return []
    crm = AgendorClient(token)
    return await crm.list_funnels()


@app.get("/api/agendor/funnels/{funnel_id}/stages")
async def agendor_stages(funnel_id: int, db: AsyncSession = Depends(get_db)):
    token = await get_setting("agendor_api_token", db)
    if not token:
        return []
    crm = AgendorClient(token)
    return await crm.list_stages(funnel_id)


@app.get("/api/agendor/users")
async def agendor_users(db: AsyncSession = Depends(get_db)):
    token = await get_setting("agendor_api_token", db)
    if not token:
        return []
    crm = AgendorClient(token)
    return await crm.list_users()


# ─── Contact Management (reset / delete / notes) ───────────────────────────

@app.get("/api/contacts")
async def list_contacts(db: AsyncSession = Depends(get_db)):
    """Lists all contacts with message count. Used by the Contacts panel."""
    from sqlalchemy import func as sqlfunc
    r = await db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at))
    )
    convs = r.scalars().all()
    result = []
    for c in convs:
        count_r = await db.execute(
            select(sqlfunc.count(Message.id)).where(Message.conversation_id == c.id)
        )
        msg_count = count_r.scalar() or 0
        result.append({
            "id": c.id,
            "phone": c.phone,
            "name": c.name or c.phone,
            "stage": c.stage,
            "ai_active": c.ai_active,
            "value_tier": c.value_tier,
            "agendor_person_id": c.agendor_person_id,
            "agendor_deal_id": c.agendor_deal_id,
            "agendor_salesperson_id": c.agendor_salesperson_id,
            "contact_notes": c.contact_notes or "",
            "reset_count": c.reset_count or 0,
            "message_count": msg_count,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat() if c.updated_at else c.created_at.isoformat(),
        })
    return result


@app.post("/api/conversations/{conv_id}/reset")
async def reset_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    """
    Resets the conversation state for testing:
    - Deletes all messages
    - Resets: stage, investment_answer, value_tier, agendor_deal_id, agendor_salesperson_id
    - Keeps: phone, name, agendor_person_id (person already exists in Agendor – avoid duplicate)
    - Increments: reset_count (audit trail)
    """
    r = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = r.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversa não encontrada")

    # Count messages before deletion
    from sqlalchemy import func as sqlfunc, delete as sqla_delete
    count_r = await db.execute(
        select(sqlfunc.count(Message.id)).where(Message.conversation_id == conv_id)
    )
    msg_count = count_r.scalar() or 0

    # Delete all messages
    await db.execute(sqla_delete(Message).where(Message.conversation_id == conv_id))

    # Reset session state, keep contact identity
    conv.stage = 0
    conv.ai_active = True
    conv.investment_answer = None
    conv.value_tier = None
    conv.agendor_deal_id = None
    conv.agendor_salesperson_id = None
    conv.reset_count = (conv.reset_count or 0) + 1
    conv.updated_at = datetime.utcnow()

    await db.commit()
    log.info(f"[Contact] Conversa {conv_id} ({conv.phone}) resetada. {msg_count} msgs apagadas. Reset #{conv.reset_count}")
    return {"status": "reset", "messages_deleted": msg_count, "reset_count": conv.reset_count}


@app.delete("/api/contacts/{conv_id}")
async def delete_contact(conv_id: int, db: AsyncSession = Depends(get_db)):
    """
    Permanently deletes a contact and ALL associated data (messages cascade).
    The Agendor record is NOT affected.
    """
    r = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = r.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Contato não encontrado")

    phone = conv.phone
    name = conv.name or conv.phone

    # cascade="all, delete-orphan" on the relationship handles messages automatically
    await db.delete(conv)
    await db.commit()
    log.info(f"[Contact] Contato apagado: {name} ({phone})")
    return {"status": "deleted", "phone": phone, "name": name}


@app.patch("/api/contacts/{conv_id}/notes")
async def update_contact_notes(conv_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Save operator notes for a contact."""
    body = await request.json()
    notes = body.get("notes", "").strip()

    r = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = r.scalar_one_or_none()
    if not conv:
        raise HTTPException(404)

    conv.contact_notes = notes
    await db.commit()
    return {"status": "saved"}


# ─── Stats ─────────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(Conversation.id)))).scalar()
    qualified = (await db.execute(
        select(func.count(Conversation.id)).where(Conversation.stage == 4)
    )).scalar()
    in_progress = (await db.execute(
        select(func.count(Conversation.id)).where(Conversation.stage < 4, Conversation.stage > 0)
    )).scalar()
    ai_on = await get_setting("ai_global_active", db, "true")
    return {
        "total_leads": total,
        "qualified": qualified,
        "in_progress": in_progress,
        "ai_global_active": ai_on == "true",
    }


# ─── Mass messaging ─────────────────────────────────────────────────────────
@app.post("/api/blast")
async def send_blast(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    phones: List[str] = body.get("phones", [])
    text: str = body.get("text", "").strip()
    if not phones or not text:
        raise HTTPException(400, "phones e text são obrigatórios")

    wa_phone_id = await get_setting("wa_phone_number_id", db)
    wa_token = await get_setting("wa_access_token", db)
    wa_client = WhatsAppClient(wa_phone_id, wa_token)

    results = {"sent": 0, "failed": 0}
    for phone in phones:
        phone = phone.strip()
        if not phone:
            continue
        msg_id = await wa_client.send_text_bulk(phone, text)
        if msg_id:
            results["sent"] += 1
        else:
            results["failed"] += 1
        await asyncio.sleep(0.5)  # rate limit básico

    return results


# ─── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
