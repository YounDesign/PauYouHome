import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
import re
import base64

try:
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False

DB_PATH = "immo_projet.db"

st.set_page_config(page_title="Gestion Achat Immo & Devis", layout="wide", page_icon="🏠")

# ----------------------------------------------------------------------------
# BASE DE DONNÉES & MIGRATIONS
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
    c.execute("""CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        nom_entreprise TEXT,
        adresse TEXT,
        telephone TEXT,
        email TEXT,
        siret TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS devis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        contact_id INTEGER,
        categorie TEXT,
        description TEXT,
        montant_ht REAL DEFAULT 0,
        montant_ttc REAL DEFAULT 0,
        taux_tva REAL DEFAULT 20.0,
        statut TEXT,
        valeur_ajoutee REAL DEFAULT 0,
        inclus INTEGER DEFAULT 1,
        pdf_nom TEXT,
        pdf_data BLOB,
        date_ajout TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS devis_lignes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        devis_id INTEGER,
        designation TEXT,
        quantite REAL,
        prix_unitaire_ht REAL DEFAULT 0,
        prix_unitaire_ttc REAL DEFAULT 0,
        montant_ht REAL DEFAULT 0,
        montant_ttc REAL DEFAULT 0,
        taux_tva REAL DEFAULT 20.0,
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
    
    existing_columns = [col["name"] for col in c.execute("PRAGMA table_info(devis)").fetchall()]
    if "project_id" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN project_id INTEGER")
    if "contact_id" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN contact_id INTEGER")
    if "valeur_ajoutee" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN valeur_ajoutee REAL DEFAULT 0")
    if "pdf_nom" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN pdf_nom TEXT")
    if "pdf_data" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN pdf_data BLOB")
    if "montant_ht" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN montant_ht REAL DEFAULT 0")
    if "montant_ttc" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN montant_ttc REAL DEFAULT 0")
    if "taux_tva" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN taux_tva REAL DEFAULT 20.0")
    if "inclus" not in existing_columns:
        c.execute("ALTER TABLE devis ADD COLUMN inclus INTEGER DEFAULT 1")

    existing_lignes_cols = [col["name"] for col in c.execute("PRAGMA table_info(devis_lignes)").fetchall()]
    if "prix_unitaire_ht" not in existing_lignes_cols:
        c.execute("ALTER TABLE devis_lignes ADD COLUMN prix_unitaire_ht REAL DEFAULT 0")
    if "prix_unitaire_ttc" not in existing_lignes_cols:
        c.execute("ALTER TABLE devis_lignes ADD COLUMN prix_unitaire_ttc REAL DEFAULT 0")
    if "montant_ht" not in existing_lignes_cols:
        c.execute("ALTER TABLE devis_lignes ADD COLUMN montant_ht REAL DEFAULT 0")
    if "montant_ttc" not in existing_lignes_cols:
        c.execute("ALTER TABLE devis_lignes ADD COLUMN montant_ttc REAL DEFAULT 0")
    if "taux_tva" not in existing_lignes_cols:
        c.execute("ALTER TABLE devis_lignes ADD COLUMN taux_tva REAL DEFAULT 20.0")

    conn.commit()
    conn.close()


init_db()

# ----------------------------------------------------------------------------
# HELPERS PROJETS & CONTACTS
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


def update_project(pid, prix_achat=None, taux_notaire=None):
    conn = get_conn()
    if prix_achat is not None and taux_notaire is not None:
        conn.execute("UPDATE projects SET prix_achat=?, taux_notaire=? WHERE id=?", (prix_achat, taux_notaire, pid))
    conn.commit()
    conn.close()


def delete_project(pid):
    conn = get_conn()
    conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    conn.execute("DELETE FROM contacts WHERE project_id=?", (pid,))
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


def save_or_get_contact(project_id, nom_entreprise, adresse, telephone, email, siret):
    conn = get_conn()
    cursor = conn.cursor()
    existing = cursor.execute(
        "SELECT id FROM contacts WHERE project_id=? AND nom_entreprise=?", 
        (project_id, nom_entreprise or "Artisan / Fournisseur")
    ).fetchone()
    
    if existing:
        cid = existing["id"]
        cursor.execute(
            "UPDATE contacts SET adresse=?, telephone=?, email=?, siret=? WHERE id=?",
            (adresse, telephone, email, siret, cid)
        )
    else:
        cursor.execute(
            """INSERT INTO contacts (project_id, nom_entreprise, adresse, telephone, email, siret)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, nom_entreprise or "Artisan / Fournisseur", adresse, telephone, email, siret)
        )
        cid = cursor.lastrowid
    conn.commit()
    conn.close()
    return cid


def list_contacts(project_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM contacts WHERE project_id=?", (project_id,)).fetchall()
    conn.close()
    return rows

def get_project_categories(project_id):
    defaults = ["Gros œuvre", "Extension", "Cuisine", "Salle de bain", "Électricité", "Plomberie", "Toiture", "Isolation", "Menuiserie", "Peinture / finitions", "Autre"]
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT categorie FROM devis WHERE project_id=? AND categorie IS NOT NULL", (project_id,)).fetchall()
    conn.close()
    cats = list(defaults)
    for r in rows:
        if r["categorie"] and r["categorie"] not in cats:
            cats.append(r["categorie"])
    return cats

# ----------------------------------------------------------------------------
# ANALYSE ET EXTRACTION INTELLIGENTE DU FICHIER
# ----------------------------------------------------------------------------

def parse_file_data(file_bytes, file_name):
    text_all = ""
    lignes = []
    amount_ttc = None
    amount_ht = None
    taux_tva_detecte = 20.0
    contact_info = {"nom": "Artisan / Fournisseur", "adresse": "", "tel": "", "email": "", "siret": ""}

    if file_name.endswith('.pdf') and PDF_OK:
        import io as _io
        try:
            with pdfplumber.open(_io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            cells = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
                            if len(cells) >= 2:
                                last_cell = cells[-1].replace(" ", "").replace("\xa0", "").replace("€", "").replace(",", ".")
                                try:
                                    val_prix = float(last_cell)
                                    if val_prix > 0 and val_prix < 500000:
                                        desc = " - ".join(cells[:-1])
                                        if len(desc) > 2 and not any(kw in desc.lower() for kw in ["total", "tva", "net à payer"]):
                                            lignes.append({
                                                "designation": desc,
                                                "quantite": 1.0,
                                                "prix_unitaire_ttc": val_prix,
                                                "montant_ttc": val_prix,
                                                "taux_tva": 20.0
                                            })
                                except ValueError:
                                    pass
                    t = page.extract_text() or ""
                    text_all += t + "\n"
        except Exception:
            pass
    elif file_name.endswith(('.xlsx', '.xls')):
        import io as _io
        try:
            df_excel = pd.read_excel(_io.BytesIO(file_bytes))
            for col in df_excel.columns:
                for val in df_excel[col].dropna():
                    text_all += str(val) + "\n"
            
            for idx, row in df_excel.iterrows():
                desc = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
                prix = None
                for val in row.values:
                    if isinstance(val, (int, float)) and val > 0 and val < 1000000:
                        prix = float(val)
                if desc and desc != "nan" and len(desc) > 3 and prix:
                    lignes.append({
                        "designation": desc,
                        "quantite": 1.0,
                        "prix_unitaire_ttc": prix,
                        "montant_ttc": prix,
                        "taux_tva": 20.0
                    })
        except Exception:
            pass

    if not lignes and text_all:
        for ligne in text_all.split("\n"):
            ligne_str = ligne.strip()
            matches = re.findall(r"(\d{1,3}(?:[ \xA0]\d{3})*[.,]\d{2})\s*(?:€)?$", ligne_str)
            if matches:
                prix_str = matches[-1].replace(" ", "").replace("\xa0", "").replace(",", ".")
                try:
                    p_val = float(prix_str)
                    if not any(kw in ligne_str.lower() for kw in ["total", "tva", "net à payer", "acompte", "solde"]):
                        designation = ligne_str[:ligne_str.rfind(matches[-1])].strip()
                        designation = re.sub(r"^[-\u2010-\u2015\d\.\)]+\s*", "", designation).strip()
                        if len(designation) > 3:
                            lignes.append({
                                "designation": designation,
                                "quantite": 1.0,
                                "prix_unitaire_ttc": p_val,
                                "montant_ttc": p_val,
                                "taux_tva": 20.0
                            })
                except ValueError:
                    pass

    match_tva = re.search(r"tva\D{0,5}(20|10|5\.5|5|2\.1|0)[,%]?", text_all, re.IGNORECASE)
    if match_tva:
        t_val = match_tva.group(1).replace(",", ".")
        try:
            taux_tva_detecte = float(t_val)
            if taux_tva_detecte == 5:
                taux_tva_detecte = 5.5
        except ValueError:
            pass

    candidates_ttc = re.findall(
        r"(?:total\s*t\.?t\.?c\.?|net\s*à\s*payer)\D{0,15}([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})",
        text_all, flags=re.IGNORECASE,
    )
    if not candidates_ttc:
        candidates_ttc = re.findall(r"([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})\s*€", text_all)
    if candidates_ttc:
        raw = candidates_ttc[-1].replace(" ", "").replace("\xa0", "").replace(",", ".")
        try:
            amount_ttc = float(raw)
        except ValueError:
            amount_ttc = None

    candidates_ht = re.findall(
        r"total\s*h\.?t\.?\D{0,15}([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})",
        text_all, flags=re.IGNORECASE,
    )
    if candidates_ht:
        raw_ht = candidates_ht[-1].replace(" ", "").replace("\xa0", "").replace(",", ".")
        try:
            amount_ht = float(raw_ht)
        except ValueError:
            amount_ht = None

    if amount_ttc and not amount_ht:
        amount_ht = amount_ttc / (1 + taux_tva_detecte / 100.0)
    elif amount_ht and not amount_ttc:
        amount_ttc = amount_ht * (1 + taux_tva_detecte / 100.0)

    match_tel = re.search(r"(?:tel|tél|t[ée]l\s*[:\.]?)\s*([\d\s\.\-\/\+]{8,})", text_all, re.IGNORECASE)
    if match_tel:
        contact_info["tel"] = match_tel.group(1).strip()

    match_email = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text_all)
    if match_email:
        contact_info["email"] = match_email.group(0).strip()

    match_siret = re.search(r"siret\s*[:\.]?\s*([\d\s]{9,14})", text_all, re.IGNORECASE)
    if match_siret:
        contact_info["siret"] = match_siret.group(1).strip()

    match_nom = re.search(r"([A-Z\s]{4,}\s(?:MACONNERIE|BTP|ENTREPRISE|SARL|SAS))", text_all)
    if match_nom:
        contact_info["nom"] = match_nom.group(1).strip()

    for l in lignes:
        l["taux_tva"] = taux_tva_detecte
        l["prix_unitaire_ht"] = l["prix_unitaire_ttc"] / (1 + taux_tva_detecte / 100.0)
        l["montant_ht"] = l["montant_ttc"] / (1 + taux_tva_detecte / 100.0)

    return amount_ht, amount_ttc, taux_tva_detecte, text_all, lignes, contact_info

# ----------------------------------------------------------------------------
# HELPERS DEVIS & LIGNES
# ----------------------------------------------------------------------------

def add_devis(project_id, contact_id, categorie, description, montant_ht, montant_ttc, taux_tva, statut, valeur_ajoutee, pdf_nom, pdf_data, lignes=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO devis (project_id, contact_id, categorie, description, montant_ht, montant_ttc, taux_tva, statut,
           valeur_ajoutee, inclus, pdf_nom, pdf_data, date_ajout) VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?)""",
        (project_id, contact_id, categorie, description, montant_ht, montant_ttc, taux_tva, statut, valeur_ajoutee,
         pdf_nom, pdf_data, date.today().isoformat()),
    )
    devis_id = cursor.lastrowid
    if lignes:
        for l in lignes:
            cursor.execute(
                """INSERT INTO devis_lignes (devis_id, designation, quantite, prix_unitaire_ht, prix_unitaire_ttc, montant_ht, montant_ttc, taux_tva, inclus)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (devis_id, l["designation"], l["quantite"], l["prix_unitaire_ht"], l["prix_unitaire_ttc"], l["montant_ht"], l["montant_ttc"], l["taux_tva"])
            )
    conn.commit()
    conn.close()


def list_devis(project_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.*, c.nom_entreprise, c.telephone, c.email FROM devis d 
        LEFT JOIN contacts c ON d.contact_id = c.id 
        WHERE d.project_id=? ORDER BY d.id DESC
    """, (project_id,)).fetchall()
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


def update_devis_categorie(devis_id, categorie):
    conn = get_conn()
    conn.execute("UPDATE devis SET categorie=? WHERE id=?", (categorie, devis_id))
    conn.commit()
    conn.close()


def update_devis_inclus(devis_id, inclus):
    conn = get_conn()
    conn.execute("UPDATE devis SET inclus=? WHERE id=?", (1 if inclus else 0, devis_id))
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


def add_ligne_devis(devis_id, designation, quantite, prix_saisi, mode_saisi, taux_tva):
    conn = get_conn()
    if mode_saisi == "HT":
        prix_ht = prix_saisi
        prix_ttc = prix_saisi * (1 + taux_tva / 100.0)
    else:
        prix_ttc = prix_saisi
        prix_ht = prix_saisi / (1 + taux_tva / 100.0)

    montant_ht = quantite * prix_ht
    montant_ttc = quantite * prix_ttc

    conn.execute(
        """INSERT INTO devis_lignes (devis_id, designation, quantite, prix_unitaire_ht, prix_unitaire_ttc, montant_ht, montant_ttc, taux_tva, inclus)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (devis_id, designation, quantite, prix_ht, prix_ttc, montant_ht, montant_ttc, taux_tva)
    )
    conn.commit()
    conn.close()


def delete_ligne_devis(ligne_id):
    conn = get_conn()
    conn.execute("DELETE FROM devis_lignes WHERE id=?", (ligne_id,))
    conn.commit()
    conn.close()


def get_total_travaux_valides(pid):
    devis_rows = list_devis(pid)
    total_ht = 0.0
    total_ttc = 0.0
    for d in devis_rows:
        if d["inclus"] == 1:
            lignes = list_lignes_devis(d["id"])
            if lignes:
                for l in lignes:
                    if l["inclus"] == 1:
                        total_ht += l["montant_ht"] or 0
                        total_ttc += l["montant_ttc"] or 0
            else:
                total_ht += d["montant_ht"] or 0
                total_ttc += d["montant_ttc"] or 0
    return total_ht, total_ttc

# ----------------------------------------------------------------------------
# INTERFACE PRINCIPALE
# ----------------------------------------------------------------------------

st.title("🏠 Gestion de Projets Immobiliers & Devis")

with st.sidebar:
    st.header("Projets")
    projects = list_projects()
    options = {f"{p['nom']} ({p['type']})": p["id"] for p in projects}

    if options:
        choix = st.selectbox("Projet actif", list(options.keys()))
        current_pid = options[choix]
    else:
        current_pid = None
        st.info("Créez un projet.")

    with st.expander("➕ Nouveau projet"):
        nom = st.text_input("Nom", key="new_nom")
        type_ = st.selectbox("Type", ["Achat maison", "Extension / travaux seuls"], key="new_type")
        prix_achat = st.number_input("Prix d'achat (€)", min_value=0.0, step=1000.0, key="new_prix")
        taux_notaire = st.number_input("Frais de notaire (%)", min_value=0.0, max_value=15.0, value=7.5, step=0.1, key="new_notaire")
        if st.button("Créer"):
            if nom:
                create_project(nom, type_, prix_achat, taux_notaire)
                st.success("Créé.")
                st.rerun()

    if current_pid:
        if st.button("🗑️ Supprimer le projet"):
            delete_project(current_pid)
            st.rerun()

if not current_pid:
    st.stop()

project = get_project(current_pid)
available_categories = get_project_categories(current_pid)

tab_achat, tab_devis, tab_contacts, tab_dashboard = st.tabs(["🏡 Achat", "🧾 Devis & Lignes", "📇 Contacts", "📊 Dashboard"])

with tab_achat:
    st.subheader("Paramètres d'achat")
    c1, c2 = st.columns(2)
    with c1:
        prix_achat = st.number_input("Prix d'achat (€)", min_value=0.0, step=1000.0, value=float(project["prix_achat"]))
    with c2:
        taux_notaire = st.number_input("Frais de notaire (%)", min_value=0.0, max_value=15.0, value=float(project["taux_notaire"]), step=0.1)
    if st.button("Enregistrer l'achat"):
        update_project(current_pid, prix_achat=prix_achat, taux_notaire=taux_notaire)
        st.success("Mis à jour.")
        st.rerun()

with tab_devis:
    st.subheader("Importation de devis et gestion des choix")
    uploaded_file = st.file_uploader("Importer un devis (PDF ou Excel)", type=["pdf", "xlsx", "xls"])
    
    montant_ht_detecte = None
    montant_ttc_detecte = None
    taux_tva_detecte = 20.0
    lignes_extraites = []
    contact_detecte = {}

    if uploaded_file is not None:
        montant_ht_detecte, montant_ttc_detecte, taux_tva_detecte, _, lignes_extraites, contact_detecte = parse_file_data(uploaded_file.getvalue(), uploaded_file.name)
        if montant_ttc_detecte:
            st.info(f"Détecté - HT : {montant_ht_detecte:,.2f} € | TVA : {taux_tva_detecte}% | TTC : {montant_ttc_detecte:,.2f} €")
        if lignes_extraites:
            st.success(f"🔍 {len(lignes_extraites)} ligne(s) détectée(s) automatiquement.")
        else:
            st.warning("⚠️ Aucune ligne détectée automatiquement. Ajoutez-les manuellement.")

    with st.form("form_devis", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            choix_cat = st.selectbox("Catégorie", available_categories + ["➕ Ajouter une nouvelle catégorie..."])
            nouvelle_cat = ""
            if choix_cat == "➕ Ajouter une nouvelle catégorie...":
                nouvelle_cat = st.text_input("Nom de la nouvelle catégorie")
            
            description = st.text_input("Description générale", value=uploaded_file.name if uploaded_file else "")
            nom_artisan = st.text_input("Nom de l'entreprise", value=contact_detecte.get("nom", ""))
        with col2:
            statut = st.selectbox("Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"])
            valeur_ajoutee = st.number_input("Plus-value estimée (€)", min_value=0.0, step=500.0)
            taux_tva_global = st.selectbox("Taux de TVA par défaut", [20.0, 10.0, 5.5, 0.0], index=[20.0, 10.0, 5.5, 0.0].index(taux_tva_detecte) if taux_tva_detecte in [20.0, 10.0, 5.5, 0.0] else 0)

        col_m1, col_m2 = st.columns(2)
        montant_ht_saisi = col_m1.number_input("Montant HT global (€)", min_value=0.0, step=100.0, value=float(montant_ht_detecte) if montant_ht_detecte else 0.0)
        montant_ttc_saisi = col_m2.number_input("Montant TTC global (€)", min_value=0.0, step=100.0, value=float(montant_ttc_detecte) if montant_ttc_detecte else 0.0)

        if st.form_submit_button("Enregistrer le devis"):
            cat_finale = nouvelle_cat.strip() if choix_cat == "➕ Ajouter une nouvelle catégorie..." and nouvelle_cat.strip() else choix_cat
            if cat_finale == "➕ Ajouter une nouvelle catégorie...":
                cat_finale = "Autre"

            pdf_bytes = uploaded_file.getvalue() if uploaded_file is not None else None
            pdf_nom = uploaded_file.name if uploaded_file is not None else None
            
            if montant_ttc_saisi > 0 and montant_ht_saisi == 0:
                montant_ht_saisi = montant_ttc_saisi / (1 + taux_tva_global / 100.0)
            elif montant_ht_saisi > 0 and montant_ttc_saisi == 0:
                montant_ttc_saisi = montant_ht_saisi * (1 + taux_tva_global / 100.0)

            cid = save_or_get_contact(current_pid, nom_artisan, contact_detecte.get("adresse", ""), contact_detecte.get("tel", ""), contact_detecte.get("email", ""), contact_detecte.get("siret", ""))
            
            lignes_a_sauver = []
            if lignes_extraites:
                lignes_a_sauver = lignes_extraites
            else:
                lignes_a_sauver = [{
                    "designation": description or "Global", 
                    "quantite": 1.0, 
                    "prix_unitaire_ht": montant_ht_saisi, 
                    "prix_unitaire_ttc": montant_ttc_saisi,
                    "montant_ht": montant_ht_saisi,
                    "montant_ttc": montant_ttc_saisi,
                    "taux_tva": taux_tva_global
                }]
            
            add_devis(current_pid, cid, cat_finale, description, montant_ht_saisi, montant_ttc_saisi, taux_tva_global, statut, valeur_ajoutee, pdf_nom, pdf_bytes, lignes_a_sauver)
            st.success("Enregistré avec succès !")
            st.rerun()

    st.divider()
    st.subheader("Sélection des devis et des lignes")
    devis_rows = list_devis(current_pid)
    
    if not devis_rows:
        st.caption("Aucun devis.")
    else:
        for d in devis_rows:
            with st.container(border=True):
                c_inc, c1, c2, c3, c4 = st.columns([1, 3, 2, 2, 1])
                
                inclus_devis = c_inc.checkbox("Actif", value=bool(d["inclus"]), key=f"inc_devis_{d['id']}")
                if inclus_devis != bool(d["inclus"]):
                    update_devis_inclus(d["id"], inclus_devis)
                    st.rerun()

                # Modification de la catégorie en direct
                all_cats = get_project_categories(current_pid)
                current_cat_idx = all_cats.index(d["categorie"]) if d["categorie"] in all_cats else 0
                
                selected_cat = c1.selectbox(
                    "Catégorie", 
                    all_cats + ["➕ Autre..."], 
                    index=current_cat_idx if d["categorie"] in all_cats else 0, 
                    key=f"cat_select_{d['id']}",
                    label_visibility="collapsed"
                )
                if selected_cat == "➕ Autre...":
                    new_c_input = c1.text_input("Nouvelle catégorie", key=f"new_cat_input_{d['id']}")
                    if new_c_input and new_c_input != d["categorie"]:
                        update_devis_categorie(d["id"], new_c_input)
                        st.rerun()
                elif selected_cat != d["categorie"]:
                    update_devis_categorie(d["id"], selected_cat)
                    st.rerun()

                c1.write(f"🏢 **{d['nom_entreprise']}** \n\n*({d['pdf_nom'] or 'Sans fichier'})*")
                
                lignes = list_lignes_devis(d["id"])
                tot_ht_devis = sum(l["montant_ht"] for l in lignes if l["inclus"] == 1) if lignes else (d["montant_ht"] if d["inclus"]==1 else 0)
                tot_ttc_devis = sum(l["montant_ttc"] for l in lignes if l["inclus"] == 1) if lignes else (d["montant_ttc"] if d["inclus"]==1 else 0)
                
                c2.markdown(f"**Sous-total Devis**\n- HT : **{tot_ht_devis:,.2f} €**\n- TTC : **{tot_ttc_devis:,.2f} €**")
                
                nouveau_statut = c3.selectbox("Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"], index=["Devis reçu", "Devis signé", "En cours", "Terminé / payé"].index(d["statut"]) if d["statut"] in ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"] else 0, key=f"statut_{d['id']}", label_visibility="collapsed")
                if nouveau_statut != d["statut"]:
                    update_devis_statut(d["id"], nouveau_statut)
                    st.rerun()

                if c4.button("🗑️", key=f"del_{d['id']}"):
                    delete_devis(d["id"])
                    st.rerun()

                pdf_key = f"show_pdf_{d['id']}"
                if pdf_key not in st.session_state:
                    st.session_state[pdf_key] = False

                col_btn1, _ = st.columns([2, 5])
                if d["pdf_data"]:
                    if col_btn1.button("👁️ Afficher PDF & Gérer les lignes", key=f"btn_toggle_{d['id']}"):
                        st.session_state[pdf_key] = not st.session_state[pdf_key]
                        st.rerun()
                else:
                    col_btn1.caption("Aucun PDF joint")
                    if col_btn1.button("✍️ Gérer les lignes", key=f"btn_toggle_nopdf_{d['id']}"):
                        st.session_state[pdf_key] = not st.session_state[pdf_key]
                        st.rerun()

                if st.session_state[pdf_key]:
                    st.markdown("---")
                    col_pdf, col_form = st.columns(2)
                    
                    with col_pdf:
                        st.markdown("#### 📄 Document original")
                        if d["pdf_data"]:
                            base64_pdf = base64.b64encode(d["pdf_data"]).decode('utf-8')
                            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="500px" type="application/pdf"></iframe>'
                            st.markdown(pdf_display, unsafe_allow_html=True)
                            st.download_button("📥 Télécharger le PDF", data=d["pdf_data"], file_name=d["pdf_nom"] or "devis.pdf", key=f"dl_side_{d['id']}")
                        else:
                            st.info("Aucun PDF associé.")

                    with col_form:
                        st.markdown(f"#### ✍️ Lignes du devis : {d['nom_entreprise']}")
                        if lignes:
                            for l in lignes:
                                cols_l = st.columns([1, 3, 2, 1, 1])
                                inclus_actuel = cols_l[0].checkbox("Inc.", value=bool(l["inclus"]), key=f"ligne_{l['id']}")
                                if inclus_actuel != bool(l["inclus"]):
                                    update_ligne_inclus(l["id"], inclus_actuel)
                                    st.rerun()
                                cols_l[1].write(l["designation"])
                                cols_l[2].write(f"HT:{l['montant_ht']:,.2f}€\nTTC:{l['montant_ttc']:,.2f}€")
                                cols_l[3].write(f"{l['taux_tva']}%")
                                if cols_l[4].button("❌", key=f"delligne_{l['id']}"):
                                    delete_ligne_devis(l["id"])
                                    st.rerun()

                        with st.form(key=f"form_add_ligne_side_{d['id']}"):
                            st.markdown("**Ajouter une ligne manuellement**")
                            des_manuelle = st.text_input("Désignation", key=f"desc_{d['id']}")
                            
                            col_q, col_p, col_mode, col_tva = st.columns(4)
                            qte_manuelle = col_q.number_input("Qté", min_value=0.1, value=1.0, step=1.0, key=f"qte_{d['id']}")
                            prix_manuelle = col_p.number_input("Prix", min_value=0.0, step=10.0, key=f"prix_{d['id']}")
                            mode_saisi = col_mode.selectbox("Type", ["TTC", "HT"], key=f"mode_{d['id']}")
                            taux_ligne = col_tva.selectbox("TVA", [20.0, 10.0, 5.5, 0.0], key=f"tva_{d['id']}")
                            
                            if st.form_submit_button("Ajouter la ligne"):
                                if des_manuelle and prix_manuelle > 0:
                                    add_ligne_devis(d["id"], des_manuelle, qte_manuelle, prix_manuelle, mode_saisi, taux_ligne)
                                    st.success("Ligne ajoutée !")
                                    st.rerun()
                                else:
                                    st.error("Renseignez la désignation et le prix.")
                    st.markdown("---")
                else:
                    if lignes:
                        st.markdown("*Lignes rattachées :*")
                        for l in lignes:
                            cols_l = st.columns([1, 4, 2, 1, 1])
                            inclus_actuel = cols_l[0].checkbox("Inc.", value=bool(l["inclus"]), key=f"ligne_normal_{l['id']}")
                            if inclus_actuel != bool(l["inclus"]):
                                update_ligne_inclus(l["id"], inclus_actuel)
                                st.rerun()
                            cols_l[1].write(l["designation"])
                            cols_l[2].write(f"HT: {l['montant_ht']:,.2f} € | TTC: {l['montant_ttc']:,.2f} €")
                            cols_l[3].write(f"{l['taux_tva']}%")
                            if cols_l[4].button("❌", key=f"delligne_normal_{l['id']}"):
                                delete_ligne_devis(l["id"])
                                st.rerun()

        tot_g_ht, tot_g_ttc = get_total_travaux_valides(current_pid)
        st.divider()
        st.metric("Total cumulé des travaux (selon devis et lignes cochés)", f"HT : {tot_g_ht:,.2f} €  |  TTC : {tot_g_ttc:,.2f} €")

with tab_contacts:
    st.subheader("Contacts extraits des devis")
    contacts = list_contacts(current_pid)
    if not contacts:
        st.info("Aucun contact.")
    else:
        for c in contacts:
            with st.container(border=True):
                st.write(f"### 🏢 {c['nom_entreprise']}")
                st.write(f"**Tél** : {c['telephone']} | **Email** : {c['email']} | **SIRET** : {c['siret']}")
                st.write(f"**Adresse** : {c['adresse']}")

with tab_dashboard:
    st.subheader("Synthèse financière (basée sur vos sélections)")
    tot_travaux_ht, tot_travaux_ttc = get_total_travaux_valides(current_pid)
    frais_notaire = project["prix_achat"] * project["taux_notaire"] / 100
    cout_total_ht = project["prix_achat"] + frais_notaire + tot_travaux_ht
    cout_total_ttc = project["prix_achat"] + frais_notaire + tot_travaux_ttc

    c1, c2, c3 = st.columns(3)
    c1.metric("Prix d'achat", f"{project['prix_achat']:,.2f} €")
    c2.metric("Frais de notaire", f"{frais_notaire:,.2f} €")
    c3.metric("Coût total projet", f"HT : {cout_total_ht:,.2f} €\nTTC : {cout_total_ttc:,.2f} €")
