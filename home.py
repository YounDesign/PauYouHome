"""
Gestionnaire d'achat immobilier & travaux
===========================================
Application Streamlit pour piloter l'achat d'une maison (ou une extension/rénovation) :
- suivi des devis (PDF joints, montants ajoutés au budget global)
- simulation de financement (mensualité, taux d'endettement français, reste à vivre)
- estimation de la plus-value à la revente (avec fiscalité simplifiée)
- tableau de bord

Lancer avec : streamlit run app.py
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
import re
import plotly.express as px
import plotly.graph_objects as go

try:
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False

DB_PATH = "immo_projet.db"

st.set_page_config(page_title="Gestion Achat Immo & Travaux", layout="wide", page_icon="🏠")

# ----------------------------------------------------------------------------
# BASE DE DONNÉES
# ----------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT,
        type TEXT,
        prix_achat REAL DEFAULT 0,
        taux_notaire REAL DEFAULT 7.5,
        date_creation TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS devis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        categorie TEXT,
        description TEXT,
        montant REAL,
        statut TEXT,
        valeur_ajoutee REAL DEFAULT 0,
        pdf_nom TEXT,
        pdf_data BLOB,
        date_ajout TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS financement (
        project_id INTEGER PRIMARY KEY,
        apport REAL DEFAULT 0,
        duree_annees INTEGER DEFAULT 20,
        taux_interet REAL DEFAULT 3.5,
        taux_assurance REAL DEFAULT 0.34,
        revenus_mensuels REAL DEFAULT 0,
        charges_mensuelles REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS revente (
        project_id INTEGER PRIMARY KEY,
        prix_revente_estime REAL DEFAULT 0,
        residence_principale INTEGER DEFAULT 1,
        duree_detention_annees REAL DEFAULT 5,
        frais_divers REAL DEFAULT 0
    )""")
    conn.commit()
    conn.close()


init_db()

# ----------------------------------------------------------------------------
# HELPERS PROJETS
# ----------------------------------------------------------------------------

def list_projects():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def create_project(nom, type_, prix_achat, taux_notaire):
    conn = get_conn()
    conn.execute(
        "INSERT INTO projects (nom, type, prix_achat, taux_notaire, date_creation) VALUES (?,?,?,?,?)",
        (nom, type_, prix_achat, taux_notaire, datetime.now().isoformat()),
    )
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    conn.close()
    return pid


def update_project(pid, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    cols = ", ".join([f"{k}=?" for k in kwargs])
    conn.execute(f"UPDATE projects SET {cols} WHERE id=?", (*kwargs.values(), pid))
    conn.commit()
    conn.close()


def delete_project(pid):
    conn = get_conn()
    conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    conn.execute("DELETE FROM devis WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM financement WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM revente WHERE project_id=?", (pid,))
    conn.commit()
    conn.close()


def get_project(pid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    return row

# ----------------------------------------------------------------------------
# HELPERS DEVIS
# ----------------------------------------------------------------------------

def add_devis(project_id, categorie, description, montant, statut, valeur_ajoutee, pdf_nom, pdf_data):
    conn = get_conn()
    conn.execute(
        """INSERT INTO devis (project_id, categorie, description, montant, statut,
           valeur_ajoutee, pdf_nom, pdf_data, date_ajout) VALUES (?,?,?,?,?,?,?,?,?)""",
        (project_id, categorie, description, montant, statut, valeur_ajoutee,
         pdf_nom, pdf_data, date.today().isoformat()),
    )
    conn.commit()
    conn.close()


def list_devis(project_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM devis WHERE project_id=? ORDER BY id DESC", (project_id,)).fetchall()
    conn.close()
    return rows


def delete_devis(devis_id):
    conn = get_conn()
    conn.execute("DELETE FROM devis WHERE id=?", (devis_id,))
    conn.commit()
    conn.close()


def update_devis_statut(devis_id, statut):
    conn = get_conn()
    conn.execute("UPDATE devis SET statut=? WHERE id=?", (statut, devis_id))
    conn.commit()
    conn.close()


def extract_amount_from_pdf(file_bytes):
    """Essaie de deviner un montant total dans un PDF de devis (best-effort)."""
    if not PDF_OK:
        return None, ""
    try:
        import io as _io
        text_all = ""
        with pdfplumber.open(_io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_all += t + "\n"
        candidates = re.findall(
            r"(?:total\s*ttc|montant\s*ttc|total\s*t\.t\.c\.?|net\s*à\s*payer)\D{0,15}([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})",
            text_all, flags=re.IGNORECASE,
        )
        if not candidates:
            candidates = re.findall(r"([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})\s*€", text_all)
        amount = None
        if candidates:
            raw = candidates[-1].replace(" ", "").replace("\xa0", "").replace(",", ".")
            try:
                amount = float(raw)
            except ValueError:
                amount = None
        return amount, text_all
    except Exception:
        return None, ""

# ----------------------------------------------------------------------------
# HELPERS FINANCEMENT / REVENTE
# ----------------------------------------------------------------------------

def get_financement(pid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM financement WHERE project_id=?", (pid,)).fetchone()
    conn.close()
    return row


def save_financement(pid, apport, duree, taux, assurance, revenus, charges):
    conn = get_conn()
    conn.execute("""INSERT INTO financement (project_id, apport, duree_annees, taux_interet,
        taux_assurance, revenus_mensuels, charges_mensuelles) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(project_id) DO UPDATE SET apport=excluded.apport, duree_annees=excluded.duree_annees,
        taux_interet=excluded.taux_interet, taux_assurance=excluded.taux_assurance,
        revenus_mensuels=excluded.revenus_mensuels, charges_mensuelles=excluded.charges_mensuelles""",
        (pid, apport, duree, taux, assurance, revenus, charges))
    conn.commit()
    conn.close()


def get_revente(pid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM revente WHERE project_id=?", (pid,)).fetchone()
    conn.close()
    return row


def save_revente(pid, prix_revente, residence_principale, duree_detention, frais_divers):
    conn = get_conn()
    conn.execute("""INSERT INTO revente (project_id, prix_revente_estime, residence_principale,
        duree_detention_annees, frais_divers) VALUES (?,?,?,?,?)
        ON CONFLICT(project_id) DO UPDATE SET prix_revente_estime=excluded.prix_revente_estime,
        residence_principale=excluded.residence_principale,
        duree_detention_annees=excluded.duree_detention_annees, frais_divers=excluded.frais_divers""",
        (pid, prix_revente, residence_principale, duree_detention, frais_divers))
    conn.commit()
    conn.close()

# ----------------------------------------------------------------------------
# CALCULS FINANCIERS
# ----------------------------------------------------------------------------

def mensualite_credit(capital, taux_annuel_pct, duree_annees, taux_assurance_pct=0.0):
    """Mensualité hors assurance, mensualité assurance, mensualité totale."""
    if capital <= 0 or duree_annees <= 0:
        return 0.0, 0.0, 0.0
    n = duree_annees * 12
    taux_mensuel = (taux_annuel_pct / 100) / 12
    if taux_mensuel == 0:
        mensualite_hors_assurance = capital / n
    else:
        mensualite_hors_assurance = capital * taux_mensuel / (1 - (1 + taux_mensuel) ** (-n))
    mensualite_assurance = capital * (taux_assurance_pct / 100) / 12
    return mensualite_hors_assurance, mensualite_assurance, mensualite_hors_assurance + mensualite_assurance


def taux_endettement(mensualite_totale, autres_charges, revenus_mensuels):
    if revenus_mensuels <= 0:
        return 0.0
    return (mensualite_totale + autres_charges) / revenus_mensuels * 100


def reste_a_vivre(revenus_mensuels, charges_mensuelles, mensualite_totale):
    return revenus_mensuels - charges_mensuelles - mensualite_totale


def cout_total_credit(mensualite_totale, duree_annees, capital):
    return mensualite_totale * duree_annees * 12 - capital


ABATTEMENT_IR = {  # % d'exonération cumulée impôt sur le revenu (19%) selon années de détention
    # (années_min, taux exonération par année entre années_min et années_max, ...)
}

def abattement_plus_value(duree_annees):
    """Retourne (pct_exonere_IR, pct_exonere_PS) pour une durée de détention donnée.
    Barème applicable aux résidences secondaires / biens locatifs (hors résidence principale).
    """
    d = duree_annees
    # Impôt sur le revenu (19%) : exonération totale à partir de 22 ans
    if d <= 5:
        exo_ir = 0.0
    elif d < 22:
        exo_ir = (d - 5) * 6.0
    else:
        exo_ir = 100.0
    exo_ir = min(exo_ir, 100.0)

    # Prélèvements sociaux (17.2%) : exonération totale à partir de 30 ans
    if d <= 5:
        exo_ps = 0.0
    elif d < 22:
        exo_ps = (d - 5) * 1.65
    elif d < 30:
        exo_ps = 16.5 + (d - 21) * 1.60
    else:
        exo_ps = 100.0
    exo_ps = min(exo_ps, 100.0)

    return exo_ir, exo_ps


def calcul_plus_value(prix_achat, frais_notaire, total_travaux, frais_divers, prix_revente,
                       residence_principale, duree_detention):
    cout_acquisition = prix_achat + frais_notaire + total_travaux + frais_divers
    plus_value_brute = prix_revente - cout_acquisition

    if residence_principale:
        return {
            "cout_acquisition": cout_acquisition,
            "plus_value_brute": plus_value_brute,
            "impot_ir": 0.0,
            "impot_ps": 0.0,
            "surtaxe": 0.0,
            "impot_total": 0.0,
            "plus_value_nette": plus_value_brute,
            "note": "Résidence principale : plus-value exonérée d'impôt en France.",
        }

    if plus_value_brute <= 0:
        return {
            "cout_acquisition": cout_acquisition,
            "plus_value_brute": plus_value_brute,
            "impot_ir": 0.0,
            "impot_ps": 0.0,
            "surtaxe": 0.0,
            "impot_total": 0.0,
            "plus_value_nette": plus_value_brute,
            "note": "Pas de plus-value imposable (moins-value ou nulle).",
        }

    exo_ir, exo_ps = abattement_plus_value(duree_detention)
    base_ir = plus_value_brute * (1 - exo_ir / 100)
    base_ps = plus_value_brute * (1 - exo_ps / 100)
    impot_ir = base_ir * 0.19
    impot_ps = base_ps * 0.172

    # Surtaxe sur les plus-values > 50 000 € (barème simplifié, taux moyen appliqué au-delà du seuil)
    surtaxe = 0.0
    if base_ir > 50000:
        if base_ir <= 60000:
            taux_s = 0.02
        elif base_ir <= 100000:
            taux_s = 0.03
        elif base_ir <= 150000:
            taux_s = 0.04
        elif base_ir <= 200000:
            taux_s = 0.05
        else:
            taux_s = 0.06
        surtaxe = base_ir * taux_s

    impot_total = impot_ir + impot_ps + surtaxe
    plus_value_nette = plus_value_brute - impot_total

    return {
        "cout_acquisition": cout_acquisition,
        "plus_value_brute": plus_value_brute,
        "impot_ir": impot_ir,
        "impot_ps": impot_ps,
        "surtaxe": surtaxe,
        "impot_total": impot_total,
        "plus_value_nette": plus_value_nette,
        "note": f"Exonération IR: {exo_ir:.0f}% · Exonération prélèvements sociaux: {exo_ps:.0f}% "
                f"(barème indicatif, hors cas particuliers).",
    }


def fmt_eur(x):
    try:
        return f"{x:,.0f} €".replace(",", " ")
    except Exception:
        return str(x)

# ----------------------------------------------------------------------------
# UI - SIDEBAR : sélection / création de projet
# ----------------------------------------------------------------------------

st.title("🏠 Gestion d'achat immobilier & travaux")

with st.sidebar:
    st.header("Projets")
    projects = list_projects()
    options = {f"{p['nom']} ({p['type']})": p["id"] for p in projects}

    if options:
        choix = st.selectbox("Projet actif", list(options.keys()))
        current_pid = options[choix]
    else:
        current_pid = None
        st.info("Crée un premier projet ci-dessous.")

    with st.expander("➕ Nouveau projet"):
        nom = st.text_input("Nom du projet", key="new_nom")
        type_ = st.selectbox("Type", ["Achat maison", "Extension / travaux seuls"], key="new_type")
        prix_achat = st.number_input("Prix d'achat (€)", min_value=0.0, step=1000.0, key="new_prix")
        taux_notaire = st.number_input(
            "Frais de notaire (%)", min_value=0.0, max_value=15.0, value=7.5, step=0.1,
            help="≈ 7 à 8% dans l'ancien, ≈ 2 à 3% dans le neuf.", key="new_notaire"
        )
        if st.button("Créer le projet"):
            if nom:
                new_id = create_project(nom, type_, prix_achat, taux_notaire)
                st.success("Projet créé.")
                st.rerun()
            else:
                st.warning("Donne un nom au projet.")

    if current_pid:
        with st.expander("🗑️ Supprimer ce projet"):
            st.warning("Action irréversible (devis, financement, revente inclus).")
            if st.button("Confirmer la suppression"):
                delete_project(current_pid)
                st.rerun()

if not current_pid:
    st.stop()

project = get_project(current_pid)

# ----------------------------------------------------------------------------
# TABS
# ----------------------------------------------------------------------------

tab_achat, tab_devis, tab_financement, tab_revente, tab_dashboard = st.tabs(
    ["🏡 Achat", "🧾 Devis & Travaux", "💶 Financement", "📈 Revente / Plus-value", "📊 Tableau de bord"]
)

# ---- ACHAT ----
with tab_achat:
    st.subheader("Informations sur l'achat")
    col1, col2 = st.columns(2)
    with col1:
        prix_achat = st.number_input("Prix d'achat (€)", min_value=0.0, step=1000.0, value=float(project["prix_achat"]))
    with col2:
        taux_notaire = st.number_input(
            "Frais de notaire (%)", min_value=0.0, max_value=15.0, value=float(project["taux_notaire"]), step=0.1
        )
    if st.button("💾 Enregistrer", key="save_achat"):
        update_project(current_pid, prix_achat=prix_achat, taux_notaire=taux_notaire)
        st.success("Mis à jour.")
        st.rerun()

    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100
    devis_rows = list_devis(current_pid)
    total_travaux = sum(d["montant"] or 0 for d in devis_rows)
    cout_total = project["prix_achat"] + frais_notaire_eur + total_travaux

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prix d'achat", fmt_eur(project["prix_achat"]))
    c2.metric("Frais de notaire", fmt_eur(frais_notaire_eur))
    c3.metric("Total travaux (devis)", fmt_eur(total_travaux))
    c4.metric("Coût total du projet", fmt_eur(cout_total))

# ---- DEVIS & TRAVAUX ----
with tab_devis:
    st.subheader("Ajouter un devis / une dépense de travaux")
    if not PDF_OK:
        st.warning(
            "Le module `pdfplumber` n'est pas installé : les PDF pourront être joints et stockés, "
            "mais le montant ne sera pas pré-rempli automatiquement. Installe-le avec "
            "`pip install pdfplumber` pour activer la détection automatique."
        )

    with st.form("form_devis", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            categorie = st.selectbox(
                "Catégorie",
                ["Gros œuvre", "Extension", "Cuisine", "Salle de bain", "Électricité", "Plomberie",
                 "Toiture", "Isolation", "Menuiserie", "Peinture / finitions", "Aménagement extérieur",
                 "Étude / architecte", "Autre"],
            )
            description = st.text_input("Description")
        with col2:
            statut = st.selectbox("Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"])
            valeur_ajoutee = st.number_input(
                "Valeur ajoutée estimée à la revente (€)", min_value=0.0, step=500.0,
                help="Optionnel : estimation de la plus-value que ce poste de travaux devrait apporter au bien."
            )

        pdf_file = st.file_uploader("Devis (PDF)", type=["pdf"])
        montant_detecte = None
        if pdf_file is not None and PDF_OK:
            montant_detecte, _ = extract_amount_from_pdf(pdf_file.getvalue())
            if montant_detecte:
                st.info(f"Montant détecté dans le PDF : {fmt_eur(montant_detecte)} (vérifie avant de valider)")

        montant = st.number_input(
            "Montant TTC (€)", min_value=0.0, step=100.0,
            value=float(montant_detecte) if montant_detecte else 0.0,
        )

        submitted = st.form_submit_button("Ajouter au budget")
        if submitted:
            pdf_bytes = pdf_file.getvalue() if pdf_file is not None else None
            pdf_nom = pdf_file.name if pdf_file is not None else None
            add_devis(current_pid, categorie, description, montant, statut, valeur_ajoutee, pdf_nom, pdf_bytes)
            st.success("Devis ajouté et intégré au budget.")
            st.rerun()

    st.divider()
    st.subheader("Devis enregistrés")
    devis_rows = list_devis(current_pid)
    if not devis_rows:
        st.caption("Aucun devis pour l'instant.")
    else:
        for d in devis_rows:
            with st.container(border=True):
                cols = st.columns([3, 2, 2, 2, 2, 1])
                cols[0].write(f"**{d['categorie']}** — {d['description'] or ''}")
                cols[1].write(fmt_eur(d["montant"]))
                nouveau_statut = cols[2].selectbox(
                    "Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"],
                    index=["Devis reçu", "Devis signé", "En cours", "Terminé / payé"].index(d["statut"])
                    if d["statut"] in ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"] else 0,
                    key=f"statut_{d['id']}", label_visibility="collapsed",
                )
                if nouveau_statut != d["statut"]:
                    update_devis_statut(d["id"], nouveau_statut)
                    st.rerun()
                if d["pdf_data"]:
                    cols[3].download_button(
                        "📄 PDF", data=d["pdf_data"], file_name=d["pdf_nom"] or "devis.pdf",
                        key=f"dl_{d['id']}",
                    )
                else:
                    cols[3].caption("Pas de PDF")
                cols[4].caption(f"+VA: {fmt_eur(d['valeur_ajoutee'])}")
                if cols[5].button("🗑️", key=f"del_{d['id']}"):
                    delete_devis(d["id"])
                    st.rerun()

        df_devis = pd.DataFrame([dict(d) for d in devis_rows])
        st.divider()
        st.caption(f"**Total travaux : {fmt_eur(df_devis['montant'].sum())}**")
        fig = px.pie(df_devis, values="montant", names="categorie", title="Répartition du budget travaux")
        st.plotly_chart(fig, use_container_width=True)

# ---- FINANCEMENT ----
with tab_financement:
    st.subheader("Simulation de financement")
    fin = get_financement(current_pid)
    devis_rows = list_devis(current_pid)
    total_travaux = sum(d["montant"] or 0 for d in devis_rows)
    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100
    cout_total_projet = project["prix_achat"] + frais_notaire_eur + total_travaux

    col1, col2 = st.columns(2)
    with col1:
        apport = st.number_input(
            "Apport personnel (€)", min_value=0.0, step=1000.0,
            value=float(fin["apport"]) if fin else 0.0,
        )
        duree = st.slider(
            "Durée du prêt (années)", min_value=5, max_value=30,
            value=int(fin["duree_annees"]) if fin else 20,
        )
        taux_interet = st.number_input(
            "Taux d'intérêt annuel (%)", min_value=0.0, max_value=15.0, step=0.05,
            value=float(fin["taux_interet"]) if fin else 3.5,
        )
        taux_assurance = st.number_input(
            "Taux d'assurance emprunteur (%/an du capital)", min_value=0.0, max_value=3.0, step=0.01,
            value=float(fin["taux_assurance"]) if fin else 0.34,
        )
    with col2:
        revenus_mensuels = st.number_input(
            "Revenus mensuels nets du foyer (€)", min_value=0.0, step=100.0,
            value=float(fin["revenus_mensuels"]) if fin else 0.0,
        )
        charges_mensuelles = st.number_input(
            "Autres charges mensuelles récurrentes (€)", min_value=0.0, step=50.0,
            value=float(fin["charges_mensuelles"]) if fin else 0.0,
            help="Autres crédits, pensions alimentaires versées, etc. (hors futur crédit immo).",
        )

    if st.button("💾 Enregistrer les paramètres de financement"):
        save_financement(current_pid, apport, duree, taux_interet, taux_assurance, revenus_mensuels, charges_mensuelles)
        st.success("Enregistré.")
        st.rerun()

    capital_emprunte = max(cout_total_projet - apport, 0)
    m_hors_assurance, m_assurance, m_totale = mensualite_credit(capital_emprunte, taux_interet, duree, taux_assurance)
    taux_end = taux_endettement(m_totale, charges_mensuelles, revenus_mensuels)
    rav = reste_a_vivre(revenus_mensuels, charges_mensuelles, m_totale)
    cout_credit = cout_total_credit(m_totale, duree, capital_emprunte)

    st.divider()
    st.markdown("### Résultat de la simulation")
    c1, c2, c3 = st.columns(3)
    c1.metric("Coût total du projet", fmt_eur(cout_total_projet))
    c2.metric("Capital à emprunter", fmt_eur(capital_emprunte))
    c3.metric("Mensualité totale (avec assurance)", fmt_eur(m_totale))

    c4, c5, c6 = st.columns(3)
    c4.metric(
        "Taux d'endettement", f"{taux_end:.1f} %",
        delta=f"{taux_end - 35:.1f} pts vs plafond HCSF (35%)", delta_color="inverse",
    )
    c5.metric("Reste à vivre estimé / mois", fmt_eur(rav))
    c6.metric("Coût total du crédit (intérêts + assurance)", fmt_eur(cout_credit))

    if taux_end > 35:
        st.error(
            "⚠️ Le taux d'endettement dépasse le plafond de 35% recommandé par le HCSF "
            "(Haut Conseil de Stabilité Financière) pour les crédits immobiliers en France. "
            "Les banques dérogent parfois à cette règle pour une partie de leurs dossiers, "
            "mais ce n'est pas garanti."
        )
    else:
        st.success("✅ Le taux d'endettement reste sous le plafond indicatif de 35%.")

    st.caption(
        "Ceci est une simulation indicative. Le calcul réel d'une banque intègre aussi le "
        "'reste à vivre', le profil emprunteur, l'apport, la stabilité des revenus, etc."
    )

    st.divider()
    st.markdown("### Comparateur de scénarios (durée × taux)")
    durees_cmp = [15, 20, 25, 30]
    taux_cmp = [taux_interet - 0.5, taux_interet, taux_interet + 0.5]
    taux_cmp = [max(t, 0) for t in taux_cmp]
    rows = []
    for d in durees_cmp:
        row = {"Durée (ans)": d}
        for t in taux_cmp:
            _, _, mt = mensualite_credit(capital_emprunte, t, d, taux_assurance)
            row[f"Taux {t:.2f}%"] = round(mt)
        rows.append(row)
    st.dataframe(pd.DataFrame(rows).set_index("Durée (ans)"), use_container_width=True)

    fig2 = go.Figure()
    for t in taux_cmp:
        mensualites = []
        for d in range(5, 31):
            _, _, mt = mensualite_credit(capital_emprunte, t, d, taux_assurance)
            mensualites.append(mt)
        fig2.add_trace(go.Scatter(x=list(range(5, 31)), y=mensualites, mode="lines", name=f"Taux {t:.2f}%"))
    fig2.update_layout(title="Mensualité selon la durée du prêt", xaxis_title="Durée (années)", yaxis_title="Mensualité (€)")
    st.plotly_chart(fig2, use_container_width=True)

# ---- REVENTE / PLUS-VALUE ----
with tab_revente:
    st.subheader("Estimation de la plus-value à la revente")
    rev = get_revente(current_pid)
    devis_rows = list_devis(current_pid)
    total_travaux = sum(d["montant"] or 0 for d in devis_rows)
    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100

    col1, col2 = st.columns(2)
    with col1:
        prix_revente = st.number_input(
            "Prix de revente estimé (€)", min_value=0.0, step=1000.0,
            value=float(rev["prix_revente_estime"]) if rev else 0.0,
        )
        residence_principale = st.checkbox(
            "Il s'agit de ma résidence principale",
            value=bool(rev["residence_principale"]) if rev else True,
            help="En France, la plus-value sur la résidence principale est exonérée d'impôt.",
        )
    with col2:
        duree_detention = st.number_input(
            "Durée de détention prévue (années)", min_value=0.0, step=1.0,
            value=float(rev["duree_detention_annees"]) if rev else 5.0,
        )
        frais_divers = st.number_input(
            "Frais divers (agence à la revente, diagnostics...) (€)", min_value=0.0, step=500.0,
            value=float(rev["frais_divers"]) if rev else 0.0,
        )

    if st.button("💾 Enregistrer", key="save_revente"):
        save_revente(current_pid, prix_revente, residence_principale, duree_detention, frais_divers)
        st.success("Enregistré.")
        st.rerun()

    resultat = calcul_plus_value(
        project["prix_achat"], frais_notaire_eur, total_travaux, frais_divers,
        prix_revente, residence_principale, duree_detention,
    )

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Coût total d'acquisition", fmt_eur(resultat["cout_acquisition"]))
    c2.metric("Plus-value brute", fmt_eur(resultat["plus_value_brute"]))
    c3.metric("Plus-value nette (après impôt)", fmt_eur(resultat["plus_value_nette"]))

    if not residence_principale and resultat["plus_value_brute"] > 0:
        c4, c5, c6 = st.columns(3)
        c4.metric("Impôt sur le revenu (19%)", fmt_eur(resultat["impot_ir"]))
        c5.metric("Prélèvements sociaux (17.2%)", fmt_eur(resultat["impot_ps"]))
        c6.metric("Surtaxe (si > 50k€)", fmt_eur(resultat["surtaxe"]))

    st.info(resultat["note"])
    st.caption(
        "⚠️ Simulation indicative basée sur le barème général des plus-values immobilières en France. "
        "Ne tient pas compte de cas particuliers (donation, indivision, usufruit, travaux déductibles "
        "sur justificatifs après 5 ans, etc.). Ceci n'est pas un conseil fiscal — vérifie ta situation "
        "avec un notaire ou un conseiller fiscal avant toute décision."
    )

    st.divider()
    st.markdown("### Valeur ajoutée par poste de travaux")
    if devis_rows:
        df = pd.DataFrame([dict(d) for d in devis_rows])
        df_va = df[["categorie", "description", "montant", "valeur_ajoutee"]].copy()
        df_va["ROI (%)"] = (df_va["valeur_ajoutee"] / df_va["montant"].replace(0, pd.NA) * 100).round(0)
        st.dataframe(df_va, use_container_width=True)
        st.caption(
            f"Valeur ajoutée totale estimée par les travaux : {fmt_eur(df['valeur_ajoutee'].sum())} "
            f"pour {fmt_eur(df['montant'].sum())} dépensés."
        )
    else:
        st.caption("Ajoute des devis avec une valeur ajoutée estimée pour voir le ROI par poste.")

# ---- DASHBOARD ----
with tab_dashboard:
    st.subheader("Tableau de bord global")
    devis_rows = list_devis(current_pid)
    total_travaux = sum(d["montant"] or 0 for d in devis_rows)
    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100
    cout_total_projet = project["prix_achat"] + frais_notaire_eur + total_travaux
    fin = get_financement(current_pid)
    rev = get_revente(current_pid)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prix d'achat", fmt_eur(project["prix_achat"]))
    c2.metric("Coût total projet", fmt_eur(cout_total_projet))
    if fin:
        capital_emprunte = max(cout_total_projet - fin["apport"], 0)
        _, _, m_totale = mensualite_credit(capital_emprunte, fin["taux_interet"], fin["duree_annees"], fin["taux_assurance"])
        c3.metric("Mensualité prévue", fmt_eur(m_totale))
    else:
        c3.metric("Mensualité prévue", "—")
    if rev and rev["prix_revente_estime"]:
        resultat = calcul_plus_value(
            project["prix_achat"], frais_notaire_eur, total_travaux, rev["frais_divers"],
            rev["prix_revente_estime"], rev["residence_principale"], rev["duree_detention_annees"],
        )
        c4.metric("Plus-value nette estimée", fmt_eur(resultat["plus_value_nette"]))
    else:
        c4.metric("Plus-value nette estimée", "—")

    st.divider()
    colA, colB = st.columns(2)
    with colA:
        st.markdown("#### Répartition du coût total")
        fig = go.Figure(data=[go.Pie(
            labels=["Prix d'achat", "Frais de notaire", "Travaux"],
            values=[project["prix_achat"], frais_notaire_eur, total_travaux],
        )])
        st.plotly_chart(fig, use_container_width=True)
    with colB:
        st.markdown("#### Avancement des devis")
        if devis_rows:
            df = pd.DataFrame([dict(d) for d in devis_rows])
            counts = df["statut"].value_counts().reset_index()
            counts.columns = ["Statut", "Nombre"]
            fig2 = px.bar(counts, x="Statut", y="Nombre")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.caption("Pas encore de devis.")

    st.divider()
    st.markdown("#### Checklist / idées à ne pas oublier")
    st.markdown(
        """
- [ ] Vérifier le DPE et les diagnostics obligatoires
- [ ] Demander au moins 2-3 devis par corps de métier pour comparer
- [ ] Vérifier les assurances (dommages-ouvrage si gros travaux/extension)
- [ ] Anticiper le délai d'obtention du permis de construire / déclaration préalable pour une extension
- [ ] Vérifier le PLU (règles d'urbanisme) avant de chiffrer une extension
- [ ] Prévoir une marge de sécurité de 10-15% sur le budget travaux (imprévus)
- [ ] Comparer plusieurs offres de prêt (courtier vs banques directes)
- [ ] Vérifier la taxe foncière actuelle et son évolution prévisible
        """
    )

