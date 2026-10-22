# -*- coding: utf-8 -*-
"""
GYM TRACKER PRO — App personal de seguimiento de gimnasio (Streamlit + SQLite)
==============================================================================
Ejecutar:   streamlit run app.py
Diseño:     mobile-first, tema oscuro con acentos lima (#c3f400) y cian (#00e3fd),
            basado en el HTML de referencia "Gym Tracker Pro".

Estructura del archivo
----------------------
1. Configuración y constantes
2. Capa de datos (SQLite)
3. Utilidades (formato, 1RM, sugerencias, calorías)
4. Estilos (CSS) y componentes HTML
5. Pestaña 1: Registrar serie
6. Pestaña 2: Progreso y analítica
7. Pestaña 3: Historial y referencia previa
8. Pestaña 4: Peso corporal y cardio
9. main()
"""

import html
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# 1. CONFIGURACIÓN Y CONSTANTES
# ---------------------------------------------------------------------------
# set_page_config debe ser el primer comando de Streamlit del script.
st.set_page_config(
    page_title="Gym Tracker",
    page_icon="🏋️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

DB_PATH = "gym_tracker.db"

# Paleta (tomada del HTML de referencia)
LIMA = "#c3f400"
CIAN = "#00e3fd"

GRUPOS = ["Pecho", "Espalda", "Pierna", "Hombro", "Brazos", "Core"]
NUEVO_EJERCICIO = "➕ Nuevo ejercicio…"

# Catálogo base de ejercicios por grupo (se complementa con lo que registres)
EJERCICIOS_BASE = {
    "Pecho": [
        "Press de Banca con Barra",
        "Press de Banca con Mancuernas",
        "Press Inclinado con Mancuernas",
        "Aperturas en Polea",
        "Fondos en Paralelas",
    ],
    "Espalda": [
        "Peso Muerto Convencional",
        "Dominadas",
        "Remo con Barra",
        "Jalón al Pecho",
        "Remo en Polea Baja",
    ],
    "Pierna": [
        "Sentadilla Trasera con Barra",
        "Prensa de Piernas",
        "Peso Muerto Rumano",
        "Extensión de Cuádriceps",
        "Curl Femoral",
        "Elevación de Talones",
    ],
    "Hombro": [
        "Press Militar Overhead",
        "Elevaciones Laterales",
        "Pájaro (Deltoide Posterior)",
        "Face Pull",
    ],
    "Brazos": [
        "Curl con Barra",
        "Curl Martillo",
        "Extensión de Tríceps en Polea",
        "Press Francés",
    ],
    "Core": [
        "Plancha",
        "Crunch en Polea",
        "Elevación de Piernas",
        "Rueda Abdominal",
    ],
}

TIPOS_CARDIO = [
    "Caminadora inclinada LISS",
    "Caminadora (plana)",
    "Correr",
    "Bicicleta",
    "Elíptica",
    "Remo",
    "Escaladora",
    "Otro",
]
# MET aproximado para el cardio que no es caminadora
MET_CARDIO = {"Bicicleta": 7.0, "Elíptica": 5.0, "Remo": 7.0, "Escaladora": 9.0, "Otro": 5.0}

TABLAS_VALIDAS = ("entrenamientos", "cardio", "metricas_corporales")
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ---------------------------------------------------------------------------
# 2. CAPA DE DATOS (SQLite)
# ---------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    """Abre una conexión nueva a la base de datos local."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db() -> None:
    """Crea las tablas e índices si no existen (se llama en cada ejecución; es barato)."""
    with closing(get_conn()) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entrenamientos (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha           TEXT    NOT NULL,
                    grupo_muscular  TEXT    NOT NULL,
                    ejercicio       TEXT    NOT NULL,
                    serie_num       INTEGER NOT NULL,
                    peso_kg         REAL    NOT NULL,
                    repeticiones    INTEGER NOT NULL,
                    rir_rpe         REAL,
                    volumen_total   REAL    NOT NULL,
                    "1rm_estimado"  REAL    NOT NULL,
                    notas           TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_entrenos_ejercicio
                    ON entrenamientos (ejercicio, fecha);

                CREATE TABLE IF NOT EXISTS cardio (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha         TEXT NOT NULL,
                    tipo          TEXT NOT NULL,
                    duracion_min  REAL NOT NULL,
                    inclinacion   REAL,
                    velocidad     REAL,
                    calorias_est  REAL
                );

                CREATE TABLE IF NOT EXISTS metricas_corporales (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha               TEXT NOT NULL,
                    peso_corporal_kg    REAL NOT NULL,
                    grasa_corporal_pct  REAL,
                    notas               TEXT
                );
                """
            )


def ejecutar(sql: str, params: tuple = ()) -> None:
    """Ejecuta una sentencia de escritura con commit automático."""
    with closing(get_conn()) as conn:
        with conn:
            conn.execute(sql, params)


def consultar(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame."""
    with closing(get_conn()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def leer_tabla(nombre: str) -> pd.DataFrame:
    """Lee una tabla completa (solo nombres de la lista blanca)."""
    if nombre not in TABLAS_VALIDAS:
        raise ValueError("Tabla no válida")
    return consultar(f"SELECT * FROM {nombre} ORDER BY fecha, id")


def eliminar_registro(tabla: str, registro_id: int) -> None:
    """Elimina un registro por id (solo tablas de la lista blanca)."""
    if tabla not in TABLAS_VALIDAS:
        raise ValueError("Tabla no válida")
    ejecutar(f"DELETE FROM {tabla} WHERE id = ?", (int(registro_id),))


def cargar_entrenamientos() -> pd.DataFrame:
    """Devuelve todos los entrenamientos con 'fecha' como datetime y '1rm_estimado' → 'rm_estimado'."""
    df = consultar("SELECT * FROM entrenamientos ORDER BY fecha, id")
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df.rename(columns={"1rm_estimado": "rm_estimado"})


def guardar_serie(fecha, grupo, ejercicio, serie, peso, reps, rir, notas) -> float:
    """Guarda una serie calculando volumen y 1RM (Epley). Devuelve el 1RM estimado."""
    volumen = round(peso * reps, 2)
    rm = round(peso * (1 + reps / 30), 2)  # Fórmula de Epley
    ejecutar(
        """INSERT INTO entrenamientos
           (fecha, grupo_muscular, ejercicio, serie_num, peso_kg, repeticiones,
            rir_rpe, volumen_total, "1rm_estimado", notas)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fecha.isoformat(), grupo, ejercicio, int(serie), float(peso), int(reps),
         float(rir), volumen, rm, notas or None),
    )
    return rm


def ejercicios_de_grupo(grupo: str) -> list:
    """Ejercicios base del grupo + los que ya registraste en ese grupo."""
    base = EJERCICIOS_BASE.get(grupo, [])
    en_db = consultar(
        "SELECT DISTINCT ejercicio FROM entrenamientos WHERE grupo_muscular = ? ORDER BY ejercicio",
        (grupo,),
    )["ejercicio"].tolist()
    return base + [e for e in en_db if e not in base]


def ultima_sesion(ejercicio: str, antes_de: date):
    """Última sesión de un ejercicio con fecha anterior a `antes_de`. Devuelve (fecha_str, df)."""
    res = consultar(
        "SELECT MAX(fecha) AS f FROM entrenamientos WHERE ejercicio = ? AND fecha < ?",
        (ejercicio, antes_de.isoformat()),
    )["f"].iloc[0]
    if res is None or pd.isna(res):
        return None, pd.DataFrame()
    df = consultar(
        "SELECT * FROM entrenamientos WHERE ejercicio = ? AND fecha = ? ORDER BY serie_num, id",
        (ejercicio, res),
    ).rename(columns={"1rm_estimado": "rm_estimado"})
    return res, df


# ---------------------------------------------------------------------------
# 3. UTILIDADES
# ---------------------------------------------------------------------------
def fmt_fecha(d) -> str:
    """18 Oct 2024"""
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]} {d.year}"


def rir_equivalente(valor):
    """
    Normaliza lo escrito en 'RIR/RPE' a RIR. Si el valor es > 5 se asume RPE
    (RIR = 10 - RPE); si no, se asume que ya es RIR.
    """
    if valor is None or pd.isna(valor):
        return None
    return 10 - valor if valor > 5 else valor


def fmt_serie(row) -> str:
    """'100 kg × 8 · RIR 2'"""
    txt = f"{row['peso_kg']:g} kg × {int(row['repeticiones'])}"
    if pd.notna(row["rir_rpe"]):
        txt += f" · RIR/RPE {row['rir_rpe']:g}"
    return txt


def sugerencia_progresion(df_sesion: pd.DataFrame, incremento: float = 2.5) -> str:
    """Heurística simple de sobrecarga progresiva a partir de la mejor serie de la última sesión."""
    if df_sesion.empty:
        return ""
    peso_top = df_sesion["peso_kg"].max()
    top = df_sesion[df_sesion["peso_kg"] == peso_top]
    rirs = [r for r in (rir_equivalente(v) for v in top["rir_rpe"]) if r is not None]
    if not rirs:
        return f"Intenta superar {peso_top:g} kg o sumar 1 repetición."
    promedio = sum(rirs) / len(rirs)
    if promedio >= 2:
        return (f"Terminaste con 2 o más repeticiones en reserva: prueba "
                f"{peso_top + incremento:g} kg (+{incremento:g} kg).")
    if promedio >= 1:
        return f"Estabas cerca del límite: mantén {peso_top:g} kg e intenta +1 repetición por serie."
    return f"Llegaste al fallo: repite {peso_top:g} kg hasta recuperar 1–2 repeticiones en reserva."


def estimar_calorias(tipo, minutos, inclinacion, velocidad, peso_corporal) -> float:
    """
    Estimación de calorías.
    - Caminadora/correr: ecuaciones metabólicas ACSM (velocidad en km/h, inclinación en %).
    - Resto: MET aproximado × peso × tiempo.
    """
    if tipo in ("Caminadora inclinada LISS", "Caminadora (plana)", "Correr"):
        v = velocidad * 1000 / 60  # m/min
        g = inclinacion / 100
        if tipo == "Correr" or velocidad > 8:
            vo2 = 0.2 * v + 0.9 * v * g + 3.5
        else:
            vo2 = 0.1 * v + 1.8 * v * g + 3.5
        return vo2 * peso_corporal / 1000 * 5 * minutos
    met = MET_CARDIO.get(tipo, 5.0)
    return met * 3.5 * peso_corporal / 200 * minutos


def agrupar_sesiones(df: pd.DataFrame) -> pd.DataFrame:
    """Resume un ejercicio por sesión (fecha): peso máx, 1RM máx, volumen total, nº de series."""
    return (
        df.groupby("fecha")
        .agg(peso_max=("peso_kg", "max"), rm_est=("rm_estimado", "max"),
             volumen=("volumen_total", "sum"), series=("id", "count"))
        .reset_index()
        .sort_values("fecha")
        .reset_index(drop=True)
    )


def aplicar_rango(df: pd.DataFrame, rango: str, personalizado=None) -> pd.DataFrame:
    """Filtra un DataFrame con columna 'fecha' según 1M/3M/6M/Todo/Personalizado."""
    dias = {"1M": 30, "3M": 90, "6M": 180}
    hoy = pd.Timestamp(date.today())
    if rango in dias:
        return df[df["fecha"] >= hoy - pd.Timedelta(days=dias[rango])]
    if rango == "Personalizado" and personalizado and len(personalizado) == 2:
        ini, fin = pd.Timestamp(personalizado[0]), pd.Timestamp(personalizado[1])
        return df[(df["fecha"] >= ini) & (df["fecha"] <= fin)]
    return df


def formato_delta(valor: float, unidad: str):
    """Devuelve (texto_delta, color) para st.metric; sin color si no hubo cambio."""
    if abs(valor) < 1e-9:
        return f"0 {unidad}", "off"
    return f"{valor:+,.1f} {unidad}", "normal"


def exportar_excel() -> bytes:
    """Genera un .xlsx con las tres tablas completas."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for tabla in TABLAS_VALIDAS:
            leer_tabla(tabla).to_excel(writer, sheet_name=tabla, index=False)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 4. ESTILOS (CSS) Y COMPONENTES
# ---------------------------------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap');

:root{
  --bg:#131313; --surface:#1c1b1b; --surface-hi:#2a2a2a; --surface-top:#353534;
  --lime:#c3f400; --cyan:#00e3fd; --on:#e5e2e1; --on-var:#c4c9ac; --on-lime:#161e00;
}

/* Base */
html, body, .stApp, [data-testid="stAppViewContainer"]{
  background:var(--bg)!important; color:var(--on); font-family:'Plus Jakarta Sans',sans-serif;
}
[data-testid="stHeader"]{background:transparent;}
#MainMenu, footer{visibility:hidden;}
.block-container{max-width:640px; padding:1rem 1rem 4rem 1rem;}
h1,h2,h3,h4{font-family:'Barlow Condensed',sans-serif!important; letter-spacing:.03em;}

/* Iconos Material */
.material-symbols-outlined{
  font-family:'Material Symbols Outlined'; font-weight:normal; font-style:normal; font-size:22px;
  line-height:1; display:inline-block; font-feature-settings:'liga'; -webkit-font-feature-settings:'liga';
}

/* Pestañas superiores (accesibles con el pulgar) */
.stTabs [data-baseweb="tab-list"]{
  gap:4px; background:var(--surface); border-radius:999px; padding:4px; overflow-x:auto;
}
.stTabs [data-baseweb="tab"]{
  height:44px; border-radius:999px; padding:0 14px; font-weight:700; font-size:13px;
  color:var(--on-var); background:transparent; white-space:nowrap;
}
.stTabs [aria-selected="true"]{
  background:rgba(195,244,0,.15); color:var(--lime)!important; box-shadow:0 0 12px rgba(195,244,0,.25);
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"]{display:none;}

/* Tarjetas st.metric */
[data-testid="stMetric"]{
  background:var(--surface); border-radius:12px; padding:12px 14px; box-shadow:0 2px 6px rgba(0,0,0,.4);
}
[data-testid="stMetricLabel"] p{
  font-size:11px; letter-spacing:.08em; text-transform:uppercase; font-weight:700; color:var(--on-var);
}
[data-testid="stMetricValue"]{font-family:'Barlow Condensed',sans-serif; font-size:30px; font-weight:700;}

/* Columnas: 2 por fila incluso en celular */
[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important; gap:.5rem!important;}
[data-testid="stColumn"], [data-testid="column"]{
  min-width:calc(50% - .5rem)!important; flex:1 1 calc(50% - .5rem)!important;
}

/* Controles táctiles grandes (16px evita el zoom automático de iOS) */
input, textarea{font-size:16px!important;}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div, [data-baseweb="textarea"]{
  background:var(--surface-hi)!important; border-radius:10px!important;
}
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input, [data-testid="stDateInput"] input{min-height:48px;}
[data-testid="stNumberInput"] button{min-width:46px;}
[data-baseweb="select"] *{color:var(--on);}
[data-baseweb="popover"] ul{background:var(--surface-hi)!important;}
[data-baseweb="popover"] li{color:var(--on)!important;}

/* Botones */
.stButton > button, [data-testid="stFormSubmitButton"] > button, .stDownloadButton > button{
  min-height:52px; border-radius:12px; font-weight:700; background:var(--surface-hi); color:var(--on); border:none;
}
button[kind="primary"], button[kind="primaryFormSubmit"],
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"]{
  background:var(--lime)!important; color:var(--on-lime)!important; border:none!important;
  font-family:'Barlow Condensed',sans-serif; font-size:18px; letter-spacing:.06em; text-transform:uppercase;
}
button[kind="primary"] p, button[kind="primaryFormSubmit"] p,
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p{
  color:var(--on-lime)!important; font-size:18px; font-weight:700;
}
[data-testid="stBaseButton-segmented_controlActive"]{
  background:var(--lime)!important; color:var(--on-lime)!important;
}
[data-testid="stBaseButton-segmented_controlActive"] p{color:var(--on-lime)!important; font-weight:700;}

/* Formularios, expanders y alertas */
[data-testid="stForm"]{background:var(--surface); border:none; border-radius:14px; padding:14px;}
[data-testid="stExpander"]{background:var(--surface); border:none; border-radius:12px;}
[data-testid="stAlert"]{border-radius:12px;}

/* Componentes propios */
.gt-header{display:flex; align-items:center; gap:12px; padding:4px 2px 14px;}
.gt-logo{width:40px; height:40px; border-radius:10px; background:var(--surface-top); color:var(--lime);
  display:flex; align-items:center; justify-content:center;}
.gt-title{font-family:'Barlow Condensed',sans-serif; font-weight:600; font-size:22px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--lime); line-height:1;}
.gt-sub{font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--on-var); font-weight:700; margin-top:3px;}
.gt-section{font-family:'Barlow Condensed',sans-serif; font-size:22px; font-weight:600; letter-spacing:.03em; margin:.6rem 0 .2rem;}
.gt-stats{display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:.75rem 0;}
.gt-stat{background:var(--surface); border-radius:12px; padding:10px 6px; text-align:center;}
.gt-stat .v{font-family:'Barlow Condensed',sans-serif; font-size:24px; font-weight:600; color:var(--on);}
.gt-stat .l{font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--on-var); font-weight:700;}
.gt-insight{display:flex; gap:12px; align-items:center; background:var(--surface); border-radius:12px; padding:12px; margin-top:.75rem;}
.gt-insight .ic{width:40px; height:40px; border-radius:50%; background:rgba(0,227,253,.18); color:var(--cyan);
  display:flex; align-items:center; justify-content:center; flex-shrink:0;}
.gt-insight .k{font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--cyan); font-weight:700;}
.gt-insight .t{font-size:13px; line-height:18px; color:var(--on-var);}
</style>
"""


def inyectar_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def cabecera() -> None:
    st.markdown(
        '<div class="gt-header"><div class="gt-logo"><span class="material-symbols-outlined">fitness_center</span></div>'
        '<div><div class="gt-title">Gym Tracker Pro</div><div class="gt-sub">Sobrecarga progresiva</div></div></div>',
        unsafe_allow_html=True,
    )


def seccion(titulo: str) -> None:
    st.markdown(f'<div class="gt-section">{html.escape(titulo)}</div>', unsafe_allow_html=True)


def mini_stats(items: list) -> None:
    """items: lista de (valor, etiqueta). Cuadrícula de 3 tarjetas que no se apila en móvil."""
    celdas = "".join(
        f'<div class="gt-stat"><div class="v">{html.escape(str(v))}</div><div class="l">{html.escape(l)}</div></div>'
        for v, l in items
    )
    st.markdown(f'<div class="gt-stats">{celdas}</div>', unsafe_allow_html=True)


def tarjeta_recomendacion(texto: str) -> None:
    st.markdown(
        '<div class="gt-insight"><div class="ic"><span class="material-symbols-outlined">auto_graph</span></div>'
        f'<div><div class="k">Sugerencia de progresión</div><div class="t">{html.escape(texto)}</div></div></div>',
        unsafe_allow_html=True,
    )


def selector_pills(etiqueta, opciones, defecto, key, format_func=str):
    """Control segmentado (pastillas). Usa st.segmented_control o, si no existe, st.radio horizontal."""
    if hasattr(st, "segmented_control"):
        valor = st.segmented_control(
            etiqueta, opciones, default=defecto, key=key,
            format_func=format_func, label_visibility="collapsed",
        )
        return defecto if valor is None else valor
    return st.radio(
        etiqueta, opciones, index=opciones.index(defecto), key=key,
        format_func=format_func, horizontal=True, label_visibility="collapsed",
    )


def estilo_plotly(fig, alto: int = 320):
    """Aplica el tema oscuro y márgenes compactos a una figura de Plotly."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=alto,
        margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(orientation="h", y=1.18, x=0, title=None),
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#c4c9ac", size=12),
        hovermode="x unified",
        dragmode=False,  # permite hacer scroll de la página con el dedo sobre el gráfico
    )
    fig.update_xaxes(gridcolor="#2a2a2a", title=None, tickformat="%d %b")
    fig.update_yaxes(gridcolor="#2a2a2a", title=None, zeroline=False)
    return fig


def mostrar_grafico(fig) -> None:
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# --- Mensajes "flash" (toasts que sobreviven a st.rerun / callbacks) --------
def flash(msg: str, icono: str = "✅") -> None:
    st.session_state["flash"] = (msg, icono)


def mostrar_flash() -> None:
    datos = st.session_state.pop("flash", None)
    if datos:
        st.toast(datos[0], icon=datos[1])


# --- Bloque reutilizable para eliminar registros ----------------------------
def cb_eliminar(tabla: str, key: str) -> None:
    """Callback del botón eliminar: borra el registro seleccionado si se confirmó."""
    rid = st.session_state.get(f"{key}_id")
    if rid is None or not st.session_state.get(f"{key}_ok"):
        return
    eliminar_registro(tabla, int(rid))
    flash(f"Registro #{int(rid)} eliminado", "🗑️")
    st.session_state[f"{key}_ok"] = False
    st.session_state.pop(f"{key}_id", None)


def bloque_borrado(tabla: str, etiquetas: dict, key: str) -> None:
    """etiquetas: {id: texto_descriptivo}. Muestra selector + confirmación + botón."""
    if not etiquetas:
        return
    k_id, k_ok = f"{key}_id", f"{key}_ok"
    # Si el id guardado ya no existe (por filtros o borrados), se descarta antes de crear el widget
    if st.session_state.get(k_id) not in etiquetas:
        st.session_state.pop(k_id, None)
    with st.expander("🗑️ Eliminar un registro por ID"):
        st.selectbox("Registro a eliminar", list(etiquetas.keys()),
                     format_func=lambda i: etiquetas[i], key=k_id)
        st.checkbox("Confirmo que quiero eliminarlo (no se puede deshacer)", key=k_ok)
        st.button("Eliminar registro", key=f"{key}_btn", use_container_width=True,
                  disabled=not st.session_state.get(k_ok, False),
                  on_click=cb_eliminar, args=(tabla, key))


# ---------------------------------------------------------------------------
# 5. PESTAÑA 1 — REGISTRAR SERIE
# ---------------------------------------------------------------------------
def tab_registrar() -> None:
    seccion("Registro rápido")

    # Si se acaba de guardar un ejercicio nuevo, se selecciona en la lista (antes de crear el widget)
    pendiente = st.session_state.pop("_ejercicio_pendiente", None)
    if pendiente:
        st.session_state[f"reg_ej_{pendiente[0]}"] = pendiente[1]

    # --- Selectores dinámicos (fuera del formulario para que reaccionen al instante)
    fecha = st.date_input("Fecha", value=date.today(), key="reg_fecha", format="DD/MM/YYYY")
    grupo = st.selectbox("Grupo muscular", GRUPOS, key="reg_grupo")
    opciones = ejercicios_de_grupo(grupo) + [NUEVO_EJERCICIO]
    seleccion = st.selectbox("Ejercicio", opciones, key=f"reg_ej_{grupo}")  # key por grupo: evita estados obsoletos

    if seleccion == NUEVO_EJERCICIO:
        ejercicio = st.text_input("Nombre del nuevo ejercicio", key=f"reg_nuevo_{grupo}",
                                  placeholder="Ej.: Press Arnold").strip()
    else:
        ejercicio = seleccion

    if not ejercicio:
        st.info("Escribe el nombre del ejercicio para ver tu referencia previa y registrar series.")
        return

    # --- Referencia inmediata: última sesión de este ejercicio
    f_prev, df_prev = ultima_sesion(ejercicio, fecha)
    if df_prev.empty:
        st.info("📌 Sin sesiones previas de este ejercicio: esta será tu primera referencia.")
    else:
        dias = (fecha - pd.to_datetime(f_prev).date()).days
        lineas = [f"**Serie {int(r['serie_num'])}:** {fmt_serie(r)}" for _, r in df_prev.iterrows()]
        cuerpo = f"**Última sesión · {fmt_fecha(f_prev)}** (hace {dias} d)  \n" + "  \n".join(lineas)
        cuerpo += f"  \n💡 {sugerencia_progresion(df_prev)}"
        st.info(cuerpo)

    # --- Valores por defecto inteligentes (agilizan el registro en el gimnasio)
    sets_dia = consultar(
        "SELECT * FROM entrenamientos WHERE ejercicio = ? AND fecha = ? ORDER BY serie_num, id",
        (ejercicio, fecha.isoformat()),
    )
    if not sets_dia.empty:
        ult = sets_dia.iloc[-1]
        serie0 = int(sets_dia["serie_num"].max()) + 1
        peso0, reps0 = float(ult["peso_kg"]), int(ult["repeticiones"])
        rir0 = float(ult["rir_rpe"]) if pd.notna(ult["rir_rpe"]) else 2.0
    elif not df_prev.empty:
        top = df_prev.sort_values(["peso_kg", "repeticiones"]).iloc[-1]
        serie0, peso0, reps0 = 1, float(top["peso_kg"]), int(top["repeticiones"])
        rir0 = float(top["rir_rpe"]) if pd.notna(top["rir_rpe"]) else 2.0
    else:
        serie0, peso0, reps0, rir0 = 1, 20.0, 10, 2.0

    # --- Incremento del peso (0.5 o 2.5 kg)
    st.caption("Incremento de peso (botones + / −)")
    paso = selector_pills("Incremento", [0.5, 2.5], 2.5, "reg_paso", format_func=lambda x: f"{x:g} kg")

    # --- Formulario de la serie
    with st.form("form_serie", clear_on_submit=False):
        c1, c2 = st.columns(2)
        serie = c1.number_input("Serie Nº", min_value=1, max_value=50, value=serie0, step=1)
        peso = c2.number_input("Peso (kg)", min_value=0.0, max_value=1000.0, value=peso0,
                               step=float(paso), format="%.1f")
        c3, c4 = st.columns(2)
        reps = c3.number_input("Repeticiones", min_value=1, max_value=100, value=reps0, step=1)
        rir = c4.number_input("RIR / RPE", min_value=0.0, max_value=10.0, value=rir0,
                              step=0.5, format="%.1f")
        notas = st.text_input("Notas (opcional)", placeholder="Ej.: pausa en el pecho, sin ayuda")
        guardar = st.form_submit_button("💾 Guardar serie", type="primary", use_container_width=True)

    if guardar:
        rm = guardar_serie(fecha, grupo, ejercicio, serie, peso, reps, rir, notas.strip())
        if seleccion == NUEVO_EJERCICIO:
            st.session_state["_ejercicio_pendiente"] = (grupo, ejercicio)
        flash(f"Serie {int(serie)} guardada: {peso:g} kg × {int(reps)} (1RM est. {rm:.1f} kg)")
        st.rerun()

    # --- Series ya registradas ese día para este ejercicio
    if not sets_dia.empty:
        seccion(f"Series de {fmt_fecha(fecha)}")
        vista = sets_dia[["serie_num", "peso_kg", "repeticiones", "rir_rpe", "volumen_total", "1rm_estimado"]].rename(
            columns={"serie_num": "Serie", "peso_kg": "Peso (kg)", "repeticiones": "Reps",
                     "rir_rpe": "RIR/RPE", "volumen_total": "Volumen", "1rm_estimado": "1RM est."})
        st.dataframe(vista, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# 6. PESTAÑA 2 — PROGRESO Y ANALÍTICA
# ---------------------------------------------------------------------------
def tab_progreso() -> None:
    df_all = cargar_entrenamientos()
    if df_all.empty:
        st.info("Aún no hay series registradas. Guarda tu primera serie en la pestaña «Registrar Serie».")
        return

    seccion("Evolución de fuerza")

    # Ejercicios ordenados por uso más reciente
    ejercicios = (df_all.groupby("ejercicio")["fecha"].max()
                  .sort_values(ascending=False).index.tolist())
    ej = st.selectbox("Ejercicio", ejercicios, key="prog_ej")
    rango = selector_pills("Rango", ["1M", "3M", "6M", "Todo", "Personalizado"], "3M", "prog_rango")

    df_ej = df_all[df_all["ejercicio"] == ej]
    personalizado = None
    if rango == "Personalizado":
        personalizado = st.date_input(
            "Rango de fechas",
            value=(df_ej["fecha"].min().date(), df_ej["fecha"].max().date()),
            key=f"prog_fechas_{ej}", format="DD/MM/YYYY",
        )

    # --- Tarjetas de resumen (históricas, no dependen del rango)
    ses_all = agrupar_sesiones(df_ej)
    pr = df_ej["peso_kg"].max()
    fecha_pr = df_ej.loc[df_ej["peso_kg"] == pr, "fecha"].min()
    rm_mejor = df_ej["rm_estimado"].max()
    ultima = ses_all.iloc[-1]
    previa = ses_all.iloc[-2] if len(ses_all) > 1 else None

    m1, m2 = st.columns(2)
    m1.metric("🏆 PR histórico", f"{pr:g} kg", help=f"Logrado el {fmt_fecha(fecha_pr)}")
    m2.metric("1RM estimado (mejor)", f"{rm_mejor:.1f} kg", help="Fórmula de Epley: peso × (1 + reps / 30)")

    m3, m4 = st.columns(2)
    if previa is not None:
        d_peso, c_peso = formato_delta(ultima["peso_max"] - previa["peso_max"], "kg")
        d_vol, c_vol = formato_delta(ultima["volumen"] - previa["volumen"], "kg")
    else:
        d_peso = d_vol = None
        c_peso = c_vol = "off"
    m3.metric("Peso máx. última sesión", f"{ultima['peso_max']:g} kg", delta=d_peso, delta_color=c_peso,
              help="Variación frente a la sesión anterior")
    m4.metric("Volumen última sesión", f"{ultima['volumen']:,.0f} kg", delta=d_vol, delta_color=c_vol,
              help="Variación frente a la sesión anterior")
    st.caption(f"Última sesión: {fmt_fecha(ultima['fecha'])} · Los deltas comparan contra la sesión anterior.")

    # --- Datos filtrados por rango
    df_r = aplicar_rango(df_ej, rango, personalizado)
    if df_r.empty:
        st.warning("No hay datos de este ejercicio en el rango seleccionado.")
        return
    ses = agrupar_sesiones(df_r)

    mini_stats([
        (len(ses), "Sesiones"),
        (len(df_r), "Series tot."),
        (f"{ses['volumen'].mean():,.0f}", "Vol. prom. (kg)"),
    ])

    # --- Gráfico 1: peso máximo y 1RM estimado por sesión
    seccion("Peso máximo y 1RM estimado")
    largo = (ses.rename(columns={"rm_est": "1RM estimado (kg)", "peso_max": "Peso máx (kg)"})
             .melt(id_vars="fecha", value_vars=["1RM estimado (kg)", "Peso máx (kg)"],
                   var_name="Métrica", value_name="kg"))
    fig1 = px.line(largo, x="fecha", y="kg", color="Métrica", markers=True,
                   color_discrete_map={"1RM estimado (kg)": LIMA, "Peso máx (kg)": CIAN})
    fig1.update_traces(line=dict(width=3), marker=dict(size=8))
    mostrar_grafico(estilo_plotly(fig1))

    # --- Gráfico 2: volumen por sesión y volumen acumulado
    seccion("Volumen por sesión")
    ses = ses.assign(acumulado=ses["volumen"].cumsum())
    fig2 = px.bar(ses, x="fecha", y="volumen", color_discrete_sequence=[CIAN])
    fig2.update_traces(name="Volumen de la sesión", showlegend=True)
    fig2.add_scatter(x=ses["fecha"], y=ses["acumulado"], mode="lines+markers", name="Acumulado",
                     yaxis="y2", line=dict(color=LIMA, width=3), marker=dict(size=7))
    estilo_plotly(fig2)
    fig2.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False))
    mostrar_grafico(fig2)
    mejor = ses.loc[ses["volumen"].idxmax()]
    st.caption(f"Sesión con mayor tonelaje: {mejor['volumen']:,.0f} kg ({fmt_fecha(mejor['fecha'])}). "
               f"Volumen acumulado en el rango: {ses['volumen'].sum():,.0f} kg.")

    # --- Sugerencia de progresión basada en la última sesión
    ultima_df = df_ej[df_ej["fecha"] == ultima["fecha"]]
    tarjeta_recomendacion(sugerencia_progresion(ultima_df))


# ---------------------------------------------------------------------------
# 7. PESTAÑA 3 — HISTORIAL Y REFERENCIA PREVIA
# ---------------------------------------------------------------------------
def tab_historial() -> None:
    df = cargar_entrenamientos()
    seccion("Historial de entrenamientos")
    if df.empty:
        st.info("Todavía no hay registros. Cuando guardes series aparecerán aquí.")
        return

    # --- Filtros
    f_min, f_max = df["fecha"].min().date(), df["fecha"].max().date()
    with st.expander("🔎 Filtros", expanded=True):
        rango = st.date_input("Rango de fechas", value=(f_min, f_max), format="DD/MM/YYYY", key="hist_fechas")
        grupos = st.multiselect("Grupo muscular", sorted(df["grupo_muscular"].unique()),
                                placeholder="Todos", key="hist_grupos")
        base_ej = df[df["grupo_muscular"].isin(grupos)] if grupos else df
        ejercicios = st.multiselect("Ejercicio", sorted(base_ej["ejercicio"].unique()),
                                    placeholder="Todos", key="hist_ejercicios")

    filtrado = df.copy()
    if isinstance(rango, (tuple, list)) and len(rango) == 2:
        filtrado = filtrado[(filtrado["fecha"] >= pd.Timestamp(rango[0])) &
                            (filtrado["fecha"] <= pd.Timestamp(rango[1]))]
    if grupos:
        filtrado = filtrado[filtrado["grupo_muscular"].isin(grupos)]
    if ejercicios:
        filtrado = filtrado[filtrado["ejercicio"].isin(ejercicios)]
    filtrado = filtrado.sort_values(["fecha", "id"], ascending=False)

    if filtrado.empty:
        st.warning("No hay registros con los filtros seleccionados.")
    else:
        st.caption(f"{len(filtrado)} series · {filtrado['fecha'].nunique()} días · "
                   f"volumen total {filtrado['volumen_total'].sum():,.0f} kg")
        vista = filtrado[["id", "fecha", "grupo_muscular", "ejercicio", "serie_num", "peso_kg",
                          "repeticiones", "rir_rpe", "volumen_total", "rm_estimado", "notas"]].copy()
        vista["fecha"] = vista["fecha"].dt.date
        st.dataframe(
            vista, hide_index=True, use_container_width=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", format="%d"),
                "fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"),
                "grupo_muscular": "Grupo",
                "ejercicio": "Ejercicio",
                "serie_num": st.column_config.NumberColumn("Serie", format="%d"),
                "peso_kg": st.column_config.NumberColumn("Peso (kg)", format="%.1f"),
                "repeticiones": st.column_config.NumberColumn("Reps", format="%d"),
                "rir_rpe": st.column_config.NumberColumn("RIR/RPE", format="%.1f"),
                "volumen_total": st.column_config.NumberColumn("Volumen", format="%.0f"),
                "rm_estimado": st.column_config.NumberColumn("1RM est.", format="%.1f"),
                "notas": "Notas",
            },
        )

        # --- Eliminar un registro por ID (se muestran los 200 más recientes del filtro)
        etiquetas = {
            int(r.id): f"#{int(r.id)} · {fmt_fecha(r.fecha)} · {r.ejercicio} · S{int(r.serie_num)}: {r.peso_kg:g}×{int(r.repeticiones)}"
            for r in filtrado.head(200).itertuples()
        }
        bloque_borrado("entrenamientos", etiquetas, "del_entreno")

    # --- Referencia previa: última sesión de cada ejercicio
    with st.expander("📌 Última sesión por ejercicio (referencia rápida)"):
        filas = []
        for ejercicio, g in df.groupby("ejercicio"):
            f = g["fecha"].max()
            s = g[g["fecha"] == f].sort_values(["serie_num", "id"])
            resumen = " · ".join(
                f"{p:g}×{int(r)}" + (f" (RIR {x:g})" if pd.notna(x) else "")
                for p, r, x in zip(s["peso_kg"], s["repeticiones"], s["rir_rpe"])
            )
            filas.append({"Ejercicio": ejercicio, "Fecha": f.date(), "Series (kg×reps)": resumen})
        resumen_df = pd.DataFrame(filas).sort_values("Fecha", ascending=False)
        st.dataframe(resumen_df, hide_index=True, use_container_width=True,
                     column_config={"Fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY")})

    # --- Exportación
    seccion("Exportar historial")
    hoy = date.today().isoformat()
    e1, e2 = st.columns(2)
    e1.download_button(
        "⬇️ CSV (entrenos)", data=leer_tabla("entrenamientos").to_csv(index=False).encode("utf-8-sig"),
        file_name=f"gym_tracker_entrenamientos_{hoy}.csv", mime="text/csv", use_container_width=True,
    )
    e2.download_button(
        "⬇️ Excel (todo)", data=exportar_excel(),
        file_name=f"gym_tracker_{hoy}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True,
    )


# ---------------------------------------------------------------------------
# 8. PESTAÑA 4 — PESO CORPORAL Y CARDIO
# ---------------------------------------------------------------------------
def tab_cuerpo_cardio() -> None:
    df_peso = leer_tabla("metricas_corporales")
    df_peso["fecha"] = pd.to_datetime(df_peso["fecha"])
    df_cardio = leer_tabla("cardio")
    df_cardio["fecha"] = pd.to_datetime(df_cardio["fecha"])

    peso_defecto = float(df_peso["peso_corporal_kg"].iloc[-1]) if not df_peso.empty else 70.0

    # ------------------------- Peso corporal -------------------------
    seccion("Peso corporal")
    with st.form("form_peso"):
        fecha_p = st.date_input("Fecha", value=date.today(), format="DD/MM/YYYY", key="peso_fecha")
        c1, c2 = st.columns(2)
        peso_c = c1.number_input("Peso (kg)", min_value=20.0, max_value=300.0, value=peso_defecto,
                                 step=0.1, format="%.1f")
        grasa = c2.number_input("Grasa corporal (%)", min_value=0.0, max_value=70.0, value=0.0,
                                step=0.1, format="%.1f", help="Déjalo en 0 si no lo mediste")
        notas_p = st.text_input("Notas (opcional)", key="peso_notas", placeholder="Ej.: en ayunas")
        guardar_peso = st.form_submit_button("💾 Guardar peso", type="primary", use_container_width=True)

    if guardar_peso:
        ejecutar(
            "INSERT INTO metricas_corporales (fecha, peso_corporal_kg, grasa_corporal_pct, notas) VALUES (?, ?, ?, ?)",
            (fecha_p.isoformat(), float(peso_c), float(grasa) if grasa > 0 else None, notas_p.strip() or None),
        )
        flash(f"Peso registrado: {peso_c:.1f} kg")
        st.rerun()

    if df_peso.empty:
        st.info("Registra tu peso varios días para ver la tendencia y la media móvil de 7 días.")
    else:
        # Un valor por día (promedio si hay varios) + media móvil de 7 días basada en fechas reales
        diario = (df_peso.groupby("fecha", as_index=False)
                  .agg(peso=("peso_corporal_kg", "mean"), grasa=("grasa_corporal_pct", "mean"))
                  .sort_values("fecha").reset_index(drop=True))
        diario["media7"] = diario.set_index("fecha")["peso"].rolling("7D", min_periods=1).mean().values

        actual, media_act = diario["peso"].iloc[-1], diario["media7"].iloc[-1]
        if len(diario) > 1:
            d_a, c_a = formato_delta(actual - diario["peso"].iloc[-2], "kg")
            d_m, c_m = formato_delta(media_act - diario["media7"].iloc[-2], "kg")
        else:
            d_a = d_m = None
            c_a = c_m = "off"
        k1, k2 = st.columns(2)
        k1.metric("Peso actual", f"{actual:.1f} kg", delta=d_a, delta_color="off" if c_a == "off" else "inverse")
        k2.metric("Media móvil 7 d", f"{media_act:.1f} kg", delta=d_m, delta_color="off" if c_m == "off" else "inverse",
                  help="Suaviza las fluctuaciones diarias de agua")

        rango_p = selector_pills("Rango peso", ["1M", "3M", "6M", "Todo"], "3M", "peso_rango")
        plot = aplicar_rango(diario, rango_p).rename(columns={"peso": "Peso diario", "media7": "Media móvil 7 d"})
        if plot.empty:
            st.warning("No hay registros de peso en este rango.")
        else:
            fig = px.line(plot, x="fecha", y=["Peso diario", "Media móvil 7 d"],
                          color_discrete_map={"Peso diario": CIAN, "Media móvil 7 d": LIMA})
            fig.for_each_trace(lambda t: t.update(
                mode="lines+markers", line=dict(width=1.5, dash="dot"), marker=dict(size=6))
                if t.name == "Peso diario" else t.update(mode="lines", line=dict(width=3.5)))
            mostrar_grafico(estilo_plotly(fig))

        if diario["grasa"].notna().any():
            g_plot = diario.dropna(subset=["grasa"]).rename(columns={"grasa": "Grasa corporal (%)"})
            fig_g = px.line(g_plot, x="fecha", y="Grasa corporal (%)", markers=True, color_discrete_sequence=[LIMA])
            st.caption("Grasa corporal (%)")
            mostrar_grafico(estilo_plotly(fig_g, 240))

    # ----------------------------- Cardio ----------------------------
    seccion("Cardio")
    with st.form("form_cardio"):
        fecha_c = st.date_input("Fecha", value=date.today(), format="DD/MM/YYYY", key="cardio_fecha")
        tipo = st.selectbox("Tipo de cardio", TIPOS_CARDIO)
        c1, c2 = st.columns(2)
        duracion = c1.number_input("Duración (min)", min_value=1, max_value=600, value=30, step=5)
        incl = c2.number_input("Inclinación (%)", min_value=0.0, max_value=40.0, value=0.0, step=0.5, format="%.1f")
        c3, c4 = st.columns(2)
        vel = c3.number_input("Velocidad (km/h)", min_value=0.0, max_value=40.0, value=5.0, step=0.1, format="%.1f")
        cal_manual = c4.number_input("Calorías (0 = estimar)", min_value=0, max_value=5000, value=0, step=10,
                                     help="Si lo dejas en 0 se estima con tu último peso corporal")
        guardar_cardio = st.form_submit_button("💾 Guardar cardio", type="primary", use_container_width=True)

    if guardar_cardio:
        calorias = float(cal_manual) if cal_manual > 0 else round(
            estimar_calorias(tipo, duracion, incl, vel, peso_defecto), 0)
        ejecutar(
            "INSERT INTO cardio (fecha, tipo, duracion_min, inclinacion, velocidad, calorias_est) VALUES (?, ?, ?, ?, ?, ?)",
            (fecha_c.isoformat(), tipo, float(duracion), float(incl), float(vel), calorias),
        )
        flash(f"Cardio guardado: {int(duracion)} min · ~{calorias:.0f} kcal", "🔥")
        st.rerun()

    if df_cardio.empty:
        st.info("Aún no hay sesiones de cardio registradas.")
    else:
        sem = df_cardio[df_cardio["fecha"] >= pd.Timestamp(date.today() - timedelta(days=6))]
        q1, q2 = st.columns(2)
        q1.metric("Cardio últimos 7 d", f"{sem['duracion_min'].sum():.0f} min")
        q2.metric("Calorías est. 7 d", f"{sem['calorias_est'].fillna(0).sum():,.0f} kcal")

        rango_c = selector_pills("Rango cardio", ["1M", "3M", "6M", "Todo"], "1M", "cardio_rango")
        c_plot = aplicar_rango(df_cardio, rango_c)
        if not c_plot.empty:
            fig_c = px.bar(c_plot, x="fecha", y="duracion_min", color="tipo",
                           color_discrete_sequence=[LIMA, CIAN, "#ffb4aa", "#abd600", "#9cf0ff", "#ffffff"])
            fig_c.update_layout(barmode="stack", legend=dict(title=None))
            estilo_plotly(fig_c, 280)
            fig_c.update_layout(legend=dict(orientation="h", y=-0.2, title=None))
            st.caption("Minutos de cardio por día")
            mostrar_grafico(fig_c)

    # ------------------- Registros recientes + borrado ----------------
    with st.expander("📋 Registros recientes de peso y cardio"):
        if not df_peso.empty:
            st.caption("Peso corporal (últimos 15)")
            rp = df_peso.sort_values(["fecha", "id"], ascending=False).head(15).copy()
            rp["fecha"] = rp["fecha"].dt.date
            st.dataframe(rp, hide_index=True, use_container_width=True)
            bloque_borrado(
                "metricas_corporales",
                {int(r.id): f"#{int(r.id)} · {fmt_fecha(r.fecha)} · {r.peso_corporal_kg:.1f} kg"
                 for r in df_peso.sort_values(["fecha", "id"], ascending=False).head(15).itertuples()},
                "del_peso",
            )
        if not df_cardio.empty:
            st.caption("Cardio (últimos 15)")
            rc = df_cardio.sort_values(["fecha", "id"], ascending=False).head(15).copy()
            rc["fecha"] = rc["fecha"].dt.date
            st.dataframe(rc, hide_index=True, use_container_width=True)
            bloque_borrado(
                "cardio",
                {int(r.id): f"#{int(r.id)} · {fmt_fecha(r.fecha)} · {r.tipo} · {r.duracion_min:.0f} min"
                 for r in df_cardio.sort_values(["fecha", "id"], ascending=False).head(15).itertuples()},
                "del_cardio",
            )


# ---------------------------------------------------------------------------
# 9. MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    init_db()
    inyectar_css()
    cabecera()
    mostrar_flash()

    t1, t2, t3, t4 = st.tabs([
        "🏋️‍♂️ Registrar Serie",
        "📈 Progreso",
        "📅 Historial",
        "⚖️ Peso y Cardio",
    ])
    with t1:
        tab_registrar()
    with t2:
        tab_progreso()
    with t3:
        tab_historial()
    with t4:
        tab_cuerpo_cardio()


main()
