from __future__ import annotations

import os
import re
import sqlite3
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus
from typing import Any

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

from core import build_overpass_query, make_message, normalize, score_business

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SDR_DB_PATH", str(APP_DIR / "data" / "sdr_prospect.db")))
OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SDR-Propect/1.0 (internal B2B prospecting; contact: configure-local-admin)"
STATES = {"São Paulo": "SP", "Rio de Janeiro": "RJ"}
SEGMENTS = {
    "Drywall / construção a seco": "drywall",
    "Impermeabilização": "impermeabilizacao",
}
STATUSES = ["Novo", "Revisar", "Pronto para contato", "Contatado", "Sem interesse", "Não prospectar"]

st.set_page_config(page_title="SDR Prospect | Construcril", page_icon="◈", layout="wide")

st.markdown("""
<style>
    .stApp { background: #f7f8fa; color: #20242b; }
    [data-testid="stHeader"] { background: rgba(247,248,250,.9); }
    [data-testid="stSidebar"] { background: #f0f2f5; }
    .block-container { padding-top: 1.7rem; padding-bottom: 2.5rem; max-width: 1440px; }
    .hero { padding: 1.25rem 1.5rem; border: 1px solid #e2e5e9; border-radius: 16px; background: #fff; margin-bottom: 1.1rem; }
    .hero-kicker { color: #c52b32; font-size: .76rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
    .hero h1 { font-size: 1.8rem; line-height: 1.2; margin: .35rem 0 .45rem 0; color: #20242b; }
    .hero p { color: #626a75; margin: 0; }
    [data-testid="stMetric"] { background: white; padding: 14px 16px; border: 1px solid #e4e7eb; border-radius: 12px; }
    div.stButton > button[kind="primary"] { background: #c52b32; border-color: #c52b32; }
    div.stButton > button[kind="primary"]:hover { background: #a92229; border-color: #a92229; }
    .note { color: #6b7280; font-size: .85rem; }
    div[data-testid="stTabs"] button { font-weight: 600; }
</style>
""", unsafe_allow_html=True)


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osm_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            segment TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            score_reason TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            website TEXT NOT NULL DEFAULT '',
            cnpj TEXT NOT NULL DEFAULT '',
            buyer_contact TEXT NOT NULL DEFAULT '',
            street_address TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_name TEXT NOT NULL DEFAULT 'OpenStreetMap',
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Novo',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            search_day TEXT NOT NULL,
            UNIQUE(name COLLATE NOCASE, city COLLATE NOCASE, state COLLATE NOCASE)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")
        defaults = {
            "daily_limit": "20",
            "default_state": "São Paulo",
            "default_city": "Campinas",
            "default_segment": "Drywall / construção a seco",
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))


def get_setting(key: str, default: str = "") -> str:
    with connect_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect_db() as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))




def clean_tag(tags: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if value and str(value).strip() not in {"yes", "no", "unknown"}:
            return str(value).strip()
    return ""






def resolve_city_area(city: str, state: str) -> tuple[int, str]:
    """Resolve a cidade para uma relação administrativa OSM dentro do estado escolhido."""
    response = requests.get(
        NOMINATIM_URL,
        params={"q": f"{city}, {state}, Brasil", "format": "jsonv2", "addressdetails": 1, "limit": 10},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    matches = response.json()
    state_expected = normalize(state)
    city_expected = normalize(city)
    for item in matches:
        address = item.get("address", {})
        address_state = normalize(address.get("state", ""))
        display = normalize(item.get("display_name", ""))
        name_match = normalize(item.get("name", "")) == city_expected or city_expected in display
        state_match = address_state == state_expected or state_expected in display
        if item.get("osm_type") == "relation" and name_match and state_match:
            return int(item["osm_id"]), str(item.get("name", city))
    raise ValueError(
        f"Não foi possível localizar com segurança a área administrativa de {city}/{state}. "
        "Confira a grafia ou tente uma cidade maior próxima."
    )





def search_osm(city: str, state: str, segment_label: str) -> list[dict[str, Any]]:
    segment_key = SEGMENTS[segment_label]
    area_relation_id, resolved_city = resolve_city_area(city, state)
    query = build_overpass_query(area_relation_id, segment_key)

    # Faz até duas tentativas de consulta ao Overpass.

    for attempt in range(2):
        try:
            response = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=(10, 60),
            )
            response.raise_for_status()
            payload = response.json()
            break

        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None

            if status not in (429, 502, 503, 504):
                raise

            if attempt == 1:
                raise RuntimeError(
                    f"O serviço de pesquisa retornou HTTP {status} "
                    "após duas tentativas. Aguarde alguns minutos "
                    "e tente novamente."
                ) from exc

            time.sleep(5)

        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == 1:
                raise RuntimeError(
                    "O serviço OpenStreetMap não respondeu após "
                    "duas tentativas. Aguarde um pouco e tente novamente."
                ) from exc

            time.sleep(3)


    results: list[dict[str, Any]] = []

    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = clean_tag(tags, "name", "brand", "operator")
        if not name:
            continue

        score, reason = score_business(name, tags, segment_key)
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        osm_type = element.get("type", "element")
        osm_id = element.get("id", "")
        osm_key = f"{osm_type}/{osm_id}"

        address_parts = [
            clean_tag(tags, "addr:street"),
            clean_tag(tags, "addr:housenumber"),
        ]
        address = ", ".join(part for part in address_parts if part)

        website = clean_tag(tags, "website", "contact:website")
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website

        phone = clean_tag(
            tags, "contact:phone", "phone", "contact:mobile", "mobile"
        )
        email = clean_tag(tags, "contact:email", "email")

        results.append({
            "osm_key": osm_key,
            "name": name,
            "segment": segment_label,
            "score": score,
            "score_reason": reason,
            "phone": phone,
            "email": email,
            "website": website,
            "cnpj": "",
            "buyer_contact": "",
            "street_address": address,
            "city": resolved_city,
            "state": STATES[state],
            "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "source_name": "OpenStreetMap",
            "message": make_message(name, segment_label, resolved_city),
            "lat": lat,
            "lon": lon,
        })

    # Ordena pela relevância e remove duplicados.
    unique: dict[str, dict[str, Any]] = {}

    for item in sorted(results, key=lambda x: x["score"], reverse=True):
        key = (
            normalize(item["name"])
            + "|"
            + normalize(city)
            + "|"
            + item["state"]
        )
        unique.setdefault(key, item)

    return list(unique.values())



def daily_added_count(day: str | None = None) -> int:
    day = day or date.today().isoformat()
    with connect_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM leads WHERE search_day = ?", (day,)).fetchone()
    return int(row["n"])


def save_leads(candidates: list[dict[str, Any]], limit: int, batch_limit: int) -> tuple[int, int]:
    saved = 0
    duplicates = 0
    today = date.today().isoformat()
    with connect_db() as conn:
        already = conn.execute("SELECT COUNT(*) AS n FROM leads WHERE search_day = ?", (today,)).fetchone()["n"]
        remaining = min(max(0, limit - int(already)), max(0, batch_limit))
        for lead in candidates:
            if saved >= remaining:
                break
            try:
                conn.execute("""INSERT INTO leads (
                    osm_key, name, segment, score, score_reason, phone, email, website,
                    cnpj, buyer_contact, street_address, city, state, source_url,
                    source_name, message, status, notes, created_at, search_day
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Novo', '', ?, ?)""", (
                    lead["osm_key"], lead["name"], lead["segment"], lead["score"], lead["score_reason"],
                    lead["phone"], lead["email"], lead["website"], lead["cnpj"], lead["buyer_contact"],
                    lead["street_address"], lead["city"], lead["state"], lead["source_url"],
                    lead["source_name"], lead["message"], datetime.now().isoformat(timespec="seconds"), today,
                ))
                saved += 1
            except sqlite3.IntegrityError:
                duplicates += 1
    return saved, duplicates


def get_leads() -> pd.DataFrame:
    with connect_db() as conn:
        
        df = pd.read_sql_query("""
                SELECT
        id,
        name AS "Empresa",
        segment AS "Segmento",
        score AS "Pontuação",
        score_reason AS "Motivo da pontuação",
        phone AS "Telefone",
        email AS "E-mail",
        buyer_contact AS "Contato do comprador",
        website AS "Site",
        cnpj AS "CNPJ",
        street_address AS "Endereço",
        city AS "Cidade",
        state AS "UF",
        source_url AS "Fonte",
        message AS "Mensagem sugerida",
        status AS "Status",
        notes AS "Observações",
        created_at AS "Adicionado em"
    FROM leads
    ORDER BY score DESC, id DESC
""", conn)

    if not df.empty:
        df["Google Maps"] = df.apply(
            lambda row: "https://www.google.com/maps/search/?api=1&query=" + quote_plus(
                f"{row['Empresa']}, {row['Cidade']}, {row['UF']}, Brasil"
            ), axis=1
        )
    return df


def update_lead(lead_id: int, status: str, notes: str, phone: str, email: str,
                website: str, cnpj: str, buyer_contact: str, message: str) -> None:
    with connect_db() as conn:
        conn.execute("""UPDATE leads SET status = ?, notes = ?, phone = ?, email = ?, website = ?,
            cnpj = ?, buyer_contact = ?, message = ? WHERE id = ?""",
            (status, notes, phone.strip(), email.strip(), website.strip(), cnpj.strip(),
             buyer_contact.strip(), message.strip(), lead_id))


def excel_bytes(df: pd.DataFrame) -> bytes:
    from io import BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.drop(columns=["id"], errors="ignore").to_excel(writer, index=False, sheet_name="Prospecção")
    return output.getvalue()


init_db()

st.markdown("""
<div class="hero">
  <div class="hero-kicker">Construcril · Inteligência comercial</div>
  <h1>SDR Prospect</h1>
  <p>Encontre empresas, priorize oportunidades e prepare abordagens comerciais em um só lugar.</p>
</div>
""", unsafe_allow_html=True)

all_leads = get_leads()
today_count = daily_added_count()
daily_limit = int(get_setting("daily_limit", "20"))
col1, col2, col3, col4 = st.columns(4)
col1.metric("Empresas na planilha", len(all_leads))
col2.metric("Adicionadas hoje", today_count)
col3.metric("Limite diário", daily_limit)
col4.metric("Restantes hoje", max(0, daily_limit - today_count))

search_tab, sheet_tab, settings_tab = st.tabs(["⌕  Nova prospecção", "▤  Planilha de leads", "⚙  Configurações"])

with search_tab:
    st.subheader("Configurar pesquisa")
    st.caption("A busca usa OpenStreetMap/Overpass para manter o protótipo sem chave de API paga. Os resultados dependem dos dados mapeados na cidade selecionada.")
    with st.form("search_form"):
        c1, c2 = st.columns(2)
        state = c1.selectbox("Estado", list(STATES.keys()), index=0 if get_setting("default_state", "São Paulo") == "São Paulo" else 1)
        city = c2.text_input("Cidade", value=get_setting("default_city", "Campinas"), placeholder="Ex.: Campinas")
        segment = st.selectbox("Segmento", list(SEGMENTS.keys()), index=list(SEGMENTS.keys()).index(get_setting("default_segment", "Drywall / construção a seco")) if get_setting("default_segment", "Drywall / construção a seco") in SEGMENTS else 0)
        remaining = max(0, int(get_setting("daily_limit", "20")) - daily_added_count())
        st.caption(f"Ainda é possível adicionar até {remaining} empresas hoje, conforme o limite diário configurado.")
        max_per_search = st.number_input("Máximo de novas empresas nesta pesquisa", min_value=1, max_value=100, value=min(10, max(1, remaining)), step=1)
        run_search = st.form_submit_button("Pesquisar empresas", type="primary", use_container_width=True)
    if run_search:
        if not city.strip():
            st.error("Informe uma cidade para iniciar a pesquisa.")
        elif remaining <= 0:
            st.warning("O limite diário foi atingido. Aumente o limite em Configurações ou continue amanhã.")
        else:
            st.session_state["search_state_code"] = STATES[state]
            with st.spinner(f"Pesquisando empresas de {segment.lower()} em {city.strip()}..."):
                try:
                    found = search_osm(city.strip(), state, segment)
                    saved, duplicates = save_leads(found, int(get_setting("daily_limit", "20")), int(max_per_search))
                    st.success(f"Pesquisa concluída. {saved} novas empresas adicionadas; {duplicates} duplicidades ignoradas.")
                    if not found:
                        st.info("Nenhuma empresa foi encontrada nesta consulta. Tente uma cidade vizinha ou outro segmento. Isso não significa que não existam empresas no local.")
                    elif saved == 0:
                        st.info("Os resultados encontrados já estavam na planilha ou o limite diário foi atingido.")
                    st.dataframe(pd.DataFrame([
                        {"Empresa": item["name"], "Segmento": item["segment"], "Pontuação": item["score"],
                         "Telefone": item["phone"] or "Não disponível", "Site": item["website"] or "Não disponível",
                         "Cidade": item["city"], "UF": item["state"]}
                        for item in found[:20]
                    ]), use_container_width=True, hide_index=True)
                    st.caption("O resultado temporário da pesquisa não significa que todos os campos estejam completos. Revise os dados antes de abordar.")
                except requests.HTTPError as exc:
                    st.error(f"O serviço de pesquisa respondeu com erro HTTP: {exc}. Tente novamente mais tarde.")
                except requests.RequestException as exc:
                    st.error(f"Não foi possível acessar o serviço de pesquisa: {exc}. Verifique a conexão e tente novamente.")
                except (ValueError, KeyError) as exc:
                    st.error(f"Não foi possível interpretar os resultados: {exc}")
    st.markdown("<p class='note'>Fonte dos dados: OpenStreetMap, sob a licença ODbL. A disponibilidade de telefones, sites e endereços depende do mapeamento. Contato de comprador e CNPJ não são inferidos nem inventados.</p>", unsafe_allow_html=True)

with sheet_tab:
    st.subheader("Planilha de prospecção")
    st.caption("Os registros ficam salvos localmente em SQLite e permanecem disponíveis ao reiniciar a aplicação neste computador.")
    if all_leads.empty:
        st.info("Sua planilha ainda está vazia. Faça uma pesquisa na aba Nova prospecção para adicionar empresas.")
    else:
        f1, f2, f3 = st.columns(3)
        filter_state = f1.selectbox("Filtrar UF", ["Todas", "SP", "RJ"])
        filter_segment = f2.selectbox("Filtrar segmento", ["Todos"] + list(SEGMENTS.keys()))
        filter_status = f3.selectbox("Filtrar status", ["Todos"] + STATUSES)
        view = all_leads.copy()
        if filter_state != "Todas":
            view = view[view["UF"] == filter_state]
        if filter_segment != "Todos":
            view = view[view["Segmento"] == filter_segment]
        if filter_status != "Todos":
            view = view[view["Status"] == filter_status]
        st.dataframe(view.drop(columns=["id"], errors="ignore"), use_container_width=True, hide_index=True, height=420,
                     column_config={
                         "Pontuação": st.column_config.ProgressColumn("Pontuação", min_value=0, max_value=100, format="%d"),
                         "Site": st.column_config.LinkColumn("Site", display_text="Abrir site"),
                         "Fonte": st.column_config.LinkColumn("Fonte", display_text="Ver fonte"),
                         "Google Maps": st.column_config.LinkColumn("Google Maps", display_text="Ver no Maps"),
                         "Mensagem sugerida": st.column_config.TextColumn("Mensagem sugerida", width="large"),
                     })
        st.download_button("Baixar Excel (.xlsx)", data=excel_bytes(view), file_name=f"sdr_prospect_{date.today().isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        st.download_button("Baixar CSV", data=view.drop(columns=["id"], errors="ignore").to_csv(index=False, sep=";", encoding="utf-8-sig"), file_name=f"sdr_prospect_{date.today().isoformat()}.csv", mime="text/csv")
        st.divider()
        st.subheader("Atualizar acompanhamento")
        ids = all_leads["id"].tolist()
        lead_names = {int(row["id"]): f'{row["Empresa"]} — {row["Cidade"]}/{row["UF"]}' for _, row in all_leads.iterrows()}
        with st.form("update_lead_form"):
            selected_id = st.selectbox("Empresa", ids, format_func=lambda x: lead_names[int(x)])
            selected_row = all_leads[all_leads["id"] == selected_id].iloc[0]
            current_status = selected_row["Status"] if selected_row["Status"] in STATUSES else "Novo"
            new_status = st.selectbox("Status", STATUSES, index=STATUSES.index(current_status))
            edit1, edit2 = st.columns(2)
            new_phone = edit1.text_input("Telefone verificado", value=str(selected_row["Telefone"] or ""))
            new_email = edit2.text_input("E-mail verificado", value=str(selected_row["E-mail"] or ""))
            edit3, edit4 = st.columns(2)
            new_website = edit3.text_input("Site verificado", value=str(selected_row["Site"] or ""))
            new_cnpj = edit4.text_input("CNPJ verificado", value=str(selected_row["CNPJ"] or ""))
            new_buyer = st.text_input("Contato do comprador (somente se verificado)", value=str(selected_row["Contato do comprador"] or ""))
            new_message = st.text_area("Mensagem sugerida (editável)", value=str(selected_row["Mensagem sugerida"] or ""), height=150)
            new_notes = st.text_area("Observações", value=str(selected_row["Observações"] or ""), placeholder="Ex.: pedir contato do setor de compras")
            save_update = st.form_submit_button("Salvar alterações", type="primary")
        if save_update:
            update_lead(int(selected_id), new_status, new_notes, new_phone, new_email,
                        new_website, new_cnpj, new_buyer, new_message)
            st.success("Dados e acompanhamento atualizados.")
            st.rerun()

with settings_tab:
    st.subheader("Configurações da prospecção")
    st.caption("Essas configurações são salvas no banco local desta instalação.")
    with st.form("settings_form"):
        saved_limit = int(get_setting("daily_limit", "20"))
        new_limit = st.number_input("Limite de novas empresas por dia", min_value=1, max_value=500, value=saved_limit, step=5)
        saved_state = get_setting("default_state", "São Paulo")
        new_state = st.selectbox("Estado padrão", list(STATES.keys()), index=0 if saved_state == "São Paulo" else 1)
        new_city = st.text_input("Cidade padrão", value=get_setting("default_city", "Campinas"))
        saved_segment = get_setting("default_segment", "Drywall / construção a seco")
        new_segment = st.selectbox("Segmento padrão", list(SEGMENTS.keys()), index=list(SEGMENTS.keys()).index(saved_segment) if saved_segment in SEGMENTS else 0)
        save_settings = st.form_submit_button("Salvar configurações", type="primary")
    if save_settings:
        set_setting("daily_limit", str(int(new_limit)))
        set_setting("default_state", new_state)
        set_setting("default_city", new_city.strip())
        set_setting("default_segment", new_segment)
        st.success("Configurações salvas.")
        st.rerun()
    st.divider()
    st.subheader("Limitações conhecidas")
    st.markdown("""
    - Esta versão usa OpenStreetMap, não Google Maps. O Google Maps oficial não é uma opção com gratuidade garantida.
    - A pesquisa é feita por cidade para evitar consultas excessivas ao serviço público; não executa varredura de um estado inteiro de uma só vez.
    - Telefone e site só aparecem se estiverem mapeados. O CNPJ e o contato do comprador ficam vazios até serem verificados em fonte confiável.
    - A pontuação é heurística e serve para triagem, não comprova intenção de compra.
    - Não há envio automático de WhatsApp, enriquecimento por scraping ou consulta automática de CNPJ nesta versão.
    """)
    st.markdown("**Fonte e atribuição:** © OpenStreetMap contributors · [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright)")
