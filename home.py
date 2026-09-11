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
    c.execute("""CREATE TABLE IF NOT EXISTS devis_lignes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        devis_id INTEGER,
        designation TEXT,
        quantite REAL,
        prix_unitaire REAL,
        montant_total REAL,
        inclus INTEGER DEFAULT 1
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
# HELPERS DEVIS & LIGNES
# ----------------------------------------------------------------------------

def add_devis(project_id, categorie, description, montant, statut, valeur_ajoutee, pdf_nom, pdf_data, lignes=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO devis (project_id, categorie, description, montant, statut,
           valeur_ajoutee, pdf_nom, pdf_data, date_ajout) VALUES (?,?,?,?,?,?,?,?,?)""",
        (project_id, categorie, description, montant, statut, valeur_ajoutee,
         pdf_nom, pdf_data, date.today().isoformat()),
    )
    devis_id = cursor.lastrowid
    if lignes:
        for l in lignes:
            cursor.execute(
                """INSERT INTO devis_lignes (devis_id, designation, quantite, prix_unitaire, montant_total, inclus)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (devis_id, l["designation"], l["quantite"], l["prix_unitaire"], l["montant_total"])
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
    conn.execute("DELETE FROM devis_lignes WHERE devis_id=?", (devis_id,))
    conn.commit()
    conn.close()


def update_devis_statut(devis_id, statut):
    conn = get_conn()
    conn.execute("UPDATE devis SET statut=? WHERE id=?", (statut, devis_id))
    conn.commit()
    conn.close()


def list_lignes_devis(devis_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM devis_lignes WHERE devis_id=?", (devis_id,)).fetchall()
    conn.close()
    return rows


def update_ligne_inclus(ligne_id, inclus):
    conn = get_conn()
    conn.execute("UPDATE devis_lignes SET inclus=? WHERE id=?", (1 if inclus else 0, ligne_id))
    conn.commit()
    conn.close()


def parse_devis_pdf(file_bytes):
    """Analyse intelligente du PDF pour extraire le texte, le montant global et les lignes de travaux."""
    if not PDF_OK:
        return None, "", []
    try:
        import io as _io
        text_all = ""
        with pdfplumber.open(_io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_all += t + "\n"
        
        # Extraction du montant TTC global
        candidates = re.findall(
            r"(?:total\s*t\.?t\.?c\.?|net\s*à\s*payer)\D{0,15}([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})",
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

        # Extraction heuristique des lignes de devis (ex: désignation, quantité, prix)
        lignes = []
        lignes_texte = text_all.split("\n")
        for ligne in lignes_texte:
            # Recherche de motifs de lignes chiffrées (ex: libellé ... prix)
            match_prix = re.search(r"([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})\s*(?:€)?$", ligne)
            if match_prix and len(ligne.strip()) > 10:
                prix_str = match_prix.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
                try:
                    p_val = float(prix_str)
                    if p_val < 50000: # éviter de prendre le total TTC global comme simple ligne
                        designation = ligne[:match_prix.start()].strip()
                        designation = re.sub(r"^[-\u2010\u2011\u2012\u2013\u2014\u2015]\s*", "", designation).strip()
                        if designation:
                            lignes.append({
                                "designation": designation,
                                "quantite": 1.0,
                                "prix_unitaire": p_val,
                                "montant_total": p_val
                            })
                except ValueError:
                    pass

        return amount, text_all, lignes
    except Exception:
        return None, "", []

# ----------------------------------------------------------------------------
# HELPERS FINANCEMENT / REVENTE / CALCULS
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


def mensualite_credit(capital, taux_annuel_pct, duree_annees, taux_assurance_pct=0.0):
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


def abattement_plus_value(duree_annees):
    d = duree_annees
    if d <= 5:
        exo_ir = 0.0
    elif d < 22:
        exo_ir = (d - 5) * 6.0
    else:
        exo_ir = 100.0
    exo_ir = min(exo_ir, 100.0)

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
        "note": f"Exonération IR: {exo_ir:.0f}% · Exonération prélèvements sociaux: {exo_ps:.0f}%",
    }


def fmt_eur(x):
    try:
        return f"{x:,.0f} €".replace(",", " ")
    except Exception:
        return str(x)

# ----------------------------------------------------------------------------
# UI - SIDEBAR : projets
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
        taux_notaire = st.number_input("Frais de notaire (%)", min_value=0.0, max_value=15.0, value=7.5, step=0.1, key="new_notaire")
        if st.button("Créer le projet"):
            if nom:
                create_project(nom, type_, prix_achat, taux_notaire)
                st.success("Projet créé.")
                st.rerun()
            else:
                st.warning("Donne un nom au projet.")

    if current_pid:
        with st.expander("🗑️ Supprimer ce projet"):
            if st.button("Confirmer la suppression"):
                delete_project(current_pid)
                st.rerun()

if not current_pid:
    st.stop()

project = get_project(current_pid)

# Calcul dynamique du total des travaux basé uniquement sur les lignes cochées
def get_total_travaux_valides(pid):
    devis_rows = list_devis(pid)
    total = 0.0
    for d in devis_rows:
        lignes = list_lignes_devis(d["id"])
        if lignes:
            for l in lignes:
                if l["inclus"] == 1:
                    total += l["montant_total"] or 0
        else:
            total += d["montant"] or 0
    return total

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
        taux_notaire = st.number_input("Frais de notaire (%)", min_value=0.0, max_value=15.0, value=float(project["taux_notaire"]), step=0.1)
    if st.button("💾 Enregistrer", key="save_achat"):
        update_project(current_pid, prix_achat=prix_achat, taux_notaire=taux_notaire)
        st.success("Mis à jour.")
        st.rerun()

    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100
    total_travaux = get_total_travaux_valides(current_pid)
    cout_total = project["prix_achat"] + frais_notaire_eur + total_travaux

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prix d'achat", fmt_eur(project["prix_achat"]))
    c2.metric("Frais de notaire", fmt_eur(frais_notaire_eur))
    c3.metric("Total travaux validés", fmt_eur(total_travaux))
    c4.metric("Coût total du projet", fmt_eur(cout_total))

# ---- DEVIS & TRAVAUX (avec analyse PDF & gestion fine des lignes) ----
with tab_devis:
    st.subheader("Ajouter un devis / une dépense de travaux")
    if not PDF_OK:
        st.warning("Le module `pdfplumber` n'est pas installé. Installe-le pour l'analyse automatique des PDF.")

    pdf_file = st.file_uploader("Importer un devis (PDF)", type=["pdf"])
    montant_detecte = None
    texte_brut = ""
    lignes_extraites = []

    if pdf_file is not None and PDF_OK:
        montant_detecte, texte_brut, lignes_extraites = parse_devis_pdf(pdf_file.getvalue())
        if montant_detecte:
            st.info(f"Montant TTC détecté automatiquement : {fmt_eur(montant_detecte)}")

    with st.form("form_devis", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            categorie = st.selectbox(
                "Catégorie",
                ["Gros œuvre", "Extension", "Cuisine", "Salle de bain", "Électricité", "Plomberie",
                 "Toiture", "Isolation", "Menuiserie", "Peinture / finitions", "Aménagement extérieur",
                 "Étude / architecte", "Autre"],
            )
            description = st.text_input("Description / Intitulé du devis")
        with col2:
            statut = st.selectbox("Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"])
            valeur_ajoutee = st.number_input("Valeur ajoutée estimée à la revente (€)", min_value=0.0, step=500.0)

        montant = st.number_input(
            "Montant total TTC (€)", min_value=0.0, step=100.0,
            value=float(montant_detecte) if montant_detecte else 0.0,
        )

        submitted = st.form_submit_button("Enregistrer le devis et ses lignes")
        if submitted:
            pdf_bytes = pdf_file.getvalue() if pdf_file is not None else None
            pdf_nom = pdf_file.name if pdf_file is not None else None
            
            # Si aucune ligne n'a été détectée automatiquement, on crée une ligne par défaut avec le montant global
            lignes_a_sauvegarder = lignes_extraites if lignes_extraites else [{
                "designation": description or "Prestation globale",
                "quantite": 1.0,
                "prix_unitaire": montant,
                "montant_total": montant
            }]
            
            add_devis(current_pid, categorie, description or (pdf_nom if pdf_file else "Devis manuel"), 
                      montant, statut, valeur_ajoutee, pdf_nom, pdf_bytes, lignes_a_sauvegarder)
            st.success("Devis ajouté avec succès.")
            st.rerun()

    st.divider()
    st.subheader("Validation détaillée des postes et lignes de devis")
    
    filtre_statut = st.selectbox("Filtrer par statut", ["Tous", "Devis reçu", "Devis signé", "En cours", "Terminé / payé"])
    devis_rows = list_devis(current_pid)
    
    if filtre_statut != "Tous":
        devis_rows = [d for d in devis_rows if d["statut"] == filtre_statut]

    if not devis_rows:
        st.caption("Aucun devis enregistré.")
    else:
        for d in devis_rows:
            with st.container(border=True):
                cols = st.columns([3, 2, 2, 1])
                cols[0].write(f"**{d['categorie']}** : {d['description'] or ''}")
                cols[1].write(f"Total devis : {fmt_eur(d['montant'])}")
                
                nouveau_statut = cols[2].selectbox(
                    "Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"],
                    index=["Devis reçu", "Devis signé", "En cours", "Terminé / payé"].index(d["statut"])
                    if d["statut"] in ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"] else 0,
                    key=f"statut_{d['id']}", label_visibility="collapsed"
                )
                if nouveau_statut != d["statut"]:
                    update_devis_statut(d["id"], nouveau_statut)
                    st.rerun()

                if cols[3].button("🗑️ Supprimer", key=f"del_{d['id']}_{d['categorie']}"):
                    delete_devis(d["id"])
                    st.rerun()

                # Gestion interactive des lignes de devis (cases à cocher individuelles)
                lignes = list_lignes_devis(d["id"])
                if lignes:
                    st.markdown("*Lignes du devis (décochez pour exclure du budget global) :*")
                    for l in lignes:
                        c_chk, c_desc, c_prix = st.columns([1, 6, 2])
                        inclus_actuel = c_chk.checkbox("Prendre en compte", value=bool(l["inclus"]), key=f"ligne_{l['id']}")
                        if inclus_actuel != bool(l["inclus"]):
                            update_ligne_inclus(l["id"], inclus_actuel)
                            st.rerun()
                        c_desc.write(l["designation"])
                        c_prix.write(fmt_eur(l["montant_total"]))

                if d["pdf_data"]:
                    st.download_button("📄 Télécharger le PDF original", data=d["pdf_data"], file_name=d["pdf_nom"] or "devis.pdf", key=f"dl_{d['id']}")

        total_travaux_global = get_total_travaux_valides(current_pid)
        st.divider()
        st.metric("Total cumulé des travaux validés (lignes cochées)", fmt_eur(total_travaux_global))

# ---- FINANCEMENT ----
with tab_financement:
    st.subheader("Simulation de financement")
    fin = get_financement(current_pid)
    total_travaux = get_total_travaux_valides(current_pid)
    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100
    cout_total_projet = project["prix_achat"] + frais_notaire_eur + total_travaux

    col1, col2 = st.columns(2)
    with col1:
        apport = st.number_input("Apport personnel (€)", min_value=0.0, step=1000.0, value=float(fin["apport"]) if fin else 0.0)
        duree = st.slider("Durée du prêt (années)", min_value=5, max_value=30, value=int(fin["duree_annees"]) if fin else 20)
        taux_interet = st.number_input("Taux d'intérêt annuel (%)", min_value=0.0, max_value=15.0, step=0.05, value=float(fin["taux_interet"]) if fin else 3.5)
        taux_assurance = st.number_input("Taux d'assurance (%/an)", min_value=0.0, max_value=3.0, step=0.01, value=float(fin["taux_assurance"]) if fin else 0.34)
    with col2:
        revenus_mensuels = st.number_input("Revenus mensuels nets du foyer (€)", min_value=0.0, step=100.0, value=float(fin["revenus_mensuels"]) if fin else 0.0)
        charges_mensuelles = st.number_input("Autres charges récurrentes (€)", min_value=0.0, step=50.0, value=float(fin["charges_mensuelles"]) if fin else 0.0)

    if st.button("💾 Enregistrer le financement"):
        save_financement(current_pid, apport, duree, taux_interet, taux_assurance, revenus_mensuels, charges_mensuelles)
        st.success("Financement enregistré.")
        st.rerun()

    capital_emprunte = max(cout_total_projet - apport, 0)
    m_hors_ass, m_ass, m_totale = mensualite_credit(capital_emprunte, taux_interet, duree, taux_assurance)
    taux_end = taux_endettement(m_totale, charges_mensuelles, revenus_mensuels)
    rav = reste_a_vivre(revenus_mensuels, charges_mensuelles, m_totale)
    cout_credit = cout_total_credit(m_totale, duree, capital_emprunte)

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Capital à emprunter", fmt_eur(capital_emprunte))
    c2.metric("Mensualité totale", fmt_eur(m_totale))
    c3.metric("Taux d'endettement", f"{taux_end:.1f} %")

    if taux_end > 35:
        st.error("⚠️ Attention : Le taux d'endettement dépasse le plafond recommandé de 35% (HCSF).")
    else:
        st.success("✅ Taux d'endettement conforme aux normes HCSF (<= 35%).")

# ---- REVENTE / PLUS-VALUE ----
with tab_revente:
    st.subheader("Estimation de la plus-value à la revente")
    rev = get_revente(current_pid)
    total_travaux = get_total_travaux_valides(current_pid)
    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100

    col1, col2 = st.columns(2)
    with col1:
        prix_revente = st.number_input("Prix de revente estimé (€)", min_value=0.0, step=1000.0, value=float(rev["prix_revente_estime"]) if rev else 0.0)
        residence_principale = st.checkbox("Résidence principale", value=bool(rev["residence_principale"]) if rev else True)
    with col2:
        duree_detention = st.number_input("Durée de détention (années)", min_value=0.0, step=1.0, value=float(rev["duree_detention_annees"]) if rev else 5.0)
        frais_divers = st.number_input("Frais divers revente (agence...) (€)", min_value=0.0, step=500.0, value=float(rev["frais_divers"]) if rev else 0.0)

    if st.button("💾 Enregistrer la revente"):
        save_revente(current_pid, prix_revente, residence_principale, duree_detention, frais_divers)
        st.success("Enregistré.")
        st.rerun()

    resultat = calcul_plus_value(project["prix_achat"], frais_notaire_eur, total_travaux, frais_divers, prix_revente, residence_principale, duree_detention)

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Coût total d'acquisition", fmt_eur(resultat["cout_acquisition"]))
    c2.metric("Plus-value brute", fmt_eur(resultat["plus_value_brute"]))
    c3.metric("Plus-value nette", fmt_eur(resultat["plus_value_nette"]))
    st.info(resultat["note"])

# ---- DASHBOARD ----
with tab_dashboard:
    st.subheader("Tableau de bord global")
    total_travaux = get_total_travaux_valides(current_pid)
    frais_notaire_eur = project["prix_achat"] * project["taux_notaire"] / 100
    cout_total_projet = project["prix_achat"] + frais_notaire_eur + total_travaux

    c1, c2, c3 = st.cols(3) if False else st.columns(3)
    c1.metric("Prix d'achat", fmt_eur(project["prix_achat"]))
    c2.metric("Coût total projet", fmt_eur(cout_total_projet))
    c3.metric("Total travaux validés", fmt_eur(total_travaux))

    fig = go.Figure(data=[go.Pie(
        labels=["Prix d'achat", "Frais de notaire", "Travaux validés"],
        values=[project["prix_achat"], frais_notaire_eur, total_travaux],
    )])
    st.plotly_chart(fig, use_container_width=True)
