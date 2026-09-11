import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
import re

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

# ----------------------------------------------------------------------------
# ANALYSE ET EXTRACTION INTELLIGENTE DU FICHIER (PDF / EXCEL)
# ----------------------------------------------------------------------------

def parse_file_data(file_bytes, file_name):
    text_all = ""
    lignes = []
    amount = None
    contact_info = {"nom": "Artisan / Fournisseur", "adresse": "", "tel": "", "email": "", "siret": ""}

    if file_name.endswith('.pdf') and PDF_OK:
        import io as _io
        try:
            with pdfplumber.open(_io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    # Extraction structurée par tableaux si possible
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            # Nettoyer les cellules vides
                            cells = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
                            if len(cells) >= 2:
                                # Chercher si l'une des cellules ressemble à un montant
                                last_cell = cells[-1].replace(" ", "").replace("\xa0", "").replace("€", "").replace(",", ".")
                                try:
                                    val_prix = float(last_cell)
                                    if val_prix > 0 and val_prix < 500000:
                                        desc = " - ".join(cells[:-1])
                                        if len(desc) > 2 and not any(kw in desc.lower() for kw in ["total", "tva", "net à payer"]):
                                            lignes.append({
                                                "designation": desc,
                                                "quantite": 1.0,
                                                "prix_unitaire": val_prix,
                                                "montant_total": val_prix
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
                        "prix_unitaire": prix,
                        "montant_total": prix
                    })
        except Exception:
            pass

    # Si aucune ligne n'a été trouvée via les tableaux, analyse textuelle améliorée ligne par ligne
    if not lignes and text_all:
        for ligne in text_all.split("\n"):
            ligne_str = ligne.strip()
            # Chercher un montant en fin de ligne (ex: 1 250,00 ou 450.00 €)
            matches = re.findall(r"(\d{1,3}(?:[ \xA0]\d{3})*[.,]\d{2})\s*(?:€)?$", ligne_str)
            if matches:
                prix_str = matches[-1].replace(" ", "").replace("\xa0", "").replace(",", ".")
                try:
                    p_val = float(prix_str)
                    # Exclure les lignes de totaux globaux
                    if not any(kw in ligne_str.lower() for kw in ["total", "tva", "net à payer", "acompte", "solde"]):
                        designation = ligne_str[:ligne_str.rfind(matches[-1])].strip()
                        designation = re.sub(r"^[-\u2010-\u2015\d\.\)]+\s*", "", designation).strip()
                        if len(designation) > 3:
                            lignes.append({
                                "designation": designation,
                                "quantite": 1.0,
                                "prix_unitaire": p_val,
                                "montant_total": p_val
                            })
                except ValueError:
                    pass

    # Extraction du montant TTC global
    candidates = re.findall(
        r"(?:total\s*t\.?t\.?c\.?|net\s*à\s*payer)\D{0,15}([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})",
        text_all, flags=re.IGNORECASE,
    )
    if not candidates:
        candidates = re.findall(r"([\d\s]{1,3}(?:[\d\s]{3})*[.,]\d{2})\s*€", text_all)
    if candidates:
        raw = candidates[-1].replace(" ", "").replace("\xa0", "").replace(",", ".")
        try:
            amount = float(raw)
        except ValueError:
            amount = None

    # Extraction des coordonnées
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

    return amount, text_all, lignes, contact_info

# ----------------------------------------------------------------------------
# HELPERS DEVIS & LIGNES
# ----------------------------------------------------------------------------

def add_devis(project_id, contact_id, categorie, description, montant, statut, valeur_ajoutee, pdf_nom, pdf_data, lignes=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO devis (project_id, contact_id, categorie, description, montant, statut,
           valeur_ajoutee, pdf_nom, pdf_data, date_ajout) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (project_id, contact_id, categorie, description, montant, statut, valeur_ajoutee,
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
    st.subheader("Importation de devis et gestion des lignes")
    uploaded_file = st.file_uploader("Importer un devis (PDF ou Excel)", type=["pdf", "xlsx", "xls"])
    
    montant_detecte = None
    lignes_extraites = []
    contact_detecte = {}

    if uploaded_file is not None:
        montant_detecte, _, lignes_extraites, contact_detecte = parse_file_data(uploaded_file.getvalue(), uploaded_file.name)
        if montant_detecte:
            st.info(f"Montant TTC détecté : {montant_detecte:,.2f} € | Entreprise : {contact_detecte.get('nom')}")
        if lignes_extraites:
            st.success(f"🔍 {len(lignes_extraites)} ligne(s) de travaux détectée(s) automatiquement !")
        else:
            st.warning("⚠️ Aucune ligne détaillée n'a pu être isolée automatiquement. Une ligne globale sera créée, vous pourrez l'ajuster.")

    with st.form("form_devis", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            categorie = st.selectbox("Catégorie", ["Gros œuvre", "Extension", "Cuisine", "Salle de bain", "Électricité", "Plomberie", "Toiture", "Isolation", "Menuiserie", "Peinture / finitions", "Autre"])
            description = st.text_input("Description générale", value=uploaded_file.name if uploaded_file else "")
            nom_artisan = st.text_input("Nom de l'entreprise", value=contact_detecte.get("nom", ""))
        with col2:
            statut = st.selectbox("Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"])
            valeur_ajoutee = st.number_input("Plus-value estimée (€)", min_value=0.0, step=500.0)
            tel_artisan = st.text_input("Téléphone", value=contact_detecte.get("tel", ""))
            email_artisan = st.text_input("Email", value=contact_detecte.get("email", ""))

        montant_saisi = st.number_input("Montant TTC global (€)", min_value=0.0, step=100.0, value=float(montant_detecte) if montant_detecte else 0.0)

        if st.form_submit_button("Enregistrer le devis"):
            pdf_bytes = uploaded_file.getvalue() if uploaded_file is not None else None
            pdf_nom = uploaded_file.name if uploaded_file is not None else None
            
            cid = save_or_get_contact(current_pid, nom_artisan, contact_detecte.get("adresse", ""), tel_artisan, email_artisan, contact_detecte.get("siret", ""))
            lignes_a_sauver = lignes_extraites if lignes_extraites else [{"designation": description or "Global", "quantite": 1.0, "prix_unitaire": montant_saisi, "montant_total": montant_saisi}]
            
            add_devis(current_pid, cid, categorie, description, montant_saisi, statut, valeur_ajoutee, pdf_nom, pdf_bytes, lignes_a_sauver)
            st.success("Enregistré avec succès dans la base de données.")
            st.rerun()

    st.divider()
    st.subheader("Liste des devis et sélection dynamique des lignes")
    devis_rows = list_devis(current_pid)
    
    if not devis_rows:
        st.caption("Aucun devis.")
    else:
        for d in devis_rows:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                c1.write(f"**{d['categorie']}** — {d['nom_entreprise']}")
                
                lignes = list_lignes_devis(d["id"])
                total_devis_actuel = sum(l["montant_total"] for l in lignes if l["inclus"] == 1) if lignes else d["montant"]
                
                c2.write(f"Total : {total_devis_actuel:,.2f} €")
                
                nouveau_statut = c3.selectbox("Statut", ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"], index=["Devis reçu", "Devis signé", "En cours", "Terminé / payé"].index(d["statut"]) if d["statut"] in ["Devis reçu", "Devis signé", "En cours", "Terminé / payé"] else 0, key=f"statut_{d['id']}", label_visibility="collapsed")
                if nouveau_statut != d["statut"]:
                    update_devis_statut(d["id"], nouveau_statut)
                    st.rerun()

                if c4.button("🗑️", key=f"del_{d['id']}"):
                    delete_devis(d["id"])
                    st.rerun()

                if lignes:
                    st.markdown("*Lignes du devis (Cochez pour inclure dans le calcul global) :*")
                    for l in lignes:
                        cols_l = st.columns([1, 6, 2])
                        inclus_actuel = cols_l[0].checkbox("Inclure", value=bool(l["inclus"]), key=f"ligne_{l['id']}")
                        if inclus_actuel != bool(l["inclus"]):
                            update_ligne_inclus(l["id"], inclus_actuel)
                            st.rerun()
                        cols_l[1].write(l["designation"])
                        cols_l[2].write(f"{l['montant_total']:,.2f} €")

                if d["pdf_data"]:
                    st.download_button("📄 Télécharger original", data=d["pdf_data"], file_name=d["pdf_nom"] or "devis.pdf", key=f"dl_{d['id']}")

        total_global = get_total_travaux_valides(current_pid)
        st.divider()
        st.metric("Total cumulé des travaux validés (tous devis confondus)", f"{total_global:,.2f} €")

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
    st.subheader("Synthèse financière")
    total_travaux = get_total_travaux_valides(current_pid)
    frais_notaire = project["prix_achat"] * project["taux_notaire"] / 100
    cout_total = project["prix_achat"] + frais_notaire + total_travaux

    c1, c2, c3 = st.columns(3)
    c1.metric("Prix d'achat", f"{project['prix_achat']:,.2f} €")
    c2.metric("Frais de notaire", f"{frais_notaire:,.2f} €")
    c3.metric("Coût total projet", f"{cout_total:,.2f} €")
