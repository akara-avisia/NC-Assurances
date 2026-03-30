import pandas as pd
import re
import calendar
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path
from dateutil.relativedelta import relativedelta
from pandas.tseries.offsets import MonthEnd
import numpy as np

# ==========================================
# 1. CACHE ET API INSEE
# ==========================================
BASE_DIR = Path(r"C:\Users\Azad\Documents\NC Assurances")
DOSSIER_NVX = BASE_DIR / "NVX_fichier_evol"
FICHIER_CONCAT = BASE_DIR / "concatenation_DSN.edi"

cache_noms_entreprises = {} 

def recuperer_nom_entreprise(siren):
    if siren in cache_noms_entreprises: return cache_noms_entreprises[siren]
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}"
        reponse = requests.get(url, timeout=5) 
        if reponse.status_code == 200 and reponse.json().get('results'):
            nom = reponse.json()['results'][0].get('nom_complet', 'Nom introuvable')
            cache_noms_entreprises[siren] = nom
            time.sleep(0.1) 
            return nom
    except Exception: pass 
    cache_noms_entreprises[siren] = "Nom inconnu (API)"
    return "Nom inconnu (API)"

# ==========================================
# 2. UTILITAIRES DSN
# ==========================================
def analyser_nom_fichier(filename):
    try:
        parts = filename.replace('.edi', '').split('_')
        annee_mois = parts[2]
        siret = parts[3].replace('!', '')
        annee, mois = int(annee_mois[:4]), int(annee_mois[4:])
        return datetime(annee, mois, calendar.monthrange(annee, mois)[1]), siret
    except Exception: return None, None

def convertir_date_dsn(date_str):
    if not date_str: return None
    date_str = date_str.replace("'", "").strip()
    if len(date_str) == 8:
        try: return datetime.strptime(date_str, "%d%m%Y")
        except ValueError: return None
    return None

def est_actif(contrat, date_cible):
    if not contrat or not contrat.get('debut'): return False
    if contrat['debut'] > date_cible: return False
    if contrat.get('fin') and contrat['fin'] < date_cible: return False
    return True

def auto_classer_contrat(nom_contrat):
    if not nom_contrat: return "INCONNU"
    nom_propre = str(nom_contrat).upper()
    mots_sante = ['SANTE', 'SANTÉ', 'MUTUELLE', 'MUT', 'FRAIS DE SANTE', 'COMPLEMENTAIRE']
    mots_prev = ['PREVOYANCE', 'PRÉVOYANCE', 'PREV', 'PRV', 'INCAPACITE', 'INVALIDITE', 'DECES', 'RISO']
    if any(m in nom_propre for m in mots_sante): return "SANTE"
    elif any(m in nom_propre for m in mots_prev): return "PREVOYANCE"
    return "INCONNU"

def lister_sirets_dans_fichier(file_path):
    sirets = set()
    pattern = re.compile(r"^S21\.G00\.40\.019,'(.*)'$")
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = pattern.match(line.strip())
            if match: sirets.add(match.group(1))
    return list(sirets)

# ==========================================
# 3. LECTURE ET PARSING UNIFIÉ
# ==========================================
def parser_fichier_dsn(file_path, date_analyse, siret_attendu):
    mapping_ent = {'S21.G00.06.003': 'CODE_NAF', 'S21.G00.06.004': 'ADRESSE_ENTREPRISE', 'S21.G00.06.005': 'CP_ENTREPRISE', 'S21.G00.06.006': 'VILLE_ENTREPRISE'}
    pattern = re.compile(r"^(S\d{2}\.G\d{2}\.\d{2}\.\d{3}),'(.*)'$")
    codes_retraite = {"105", "106", "109", "110", "111", "112", "113", "131", "132", "915", "060", "061"}
    
    contrats_hist, salaires_hist = [], []
    infos_statiques = {}
    
    contrat_en_cours, absence_en_cours = {}, {}
    current_siret, current_siren_lecture = None, None
    statut_cadre, nature_contrat, temps_travail, sexe, date_naiss, type_rem = None, None, None, None, None, None
    
    sante_found, prev_found = False, False
    
    effectif, ms_totale, ms_primes, charges_pat = 0, 0.0, 0.0, 0.0
    nb_cadres, ms_cadre, nb_non_cadres, ms_non_cadre = 0, 0.0, 0, 0.0
    nb_h, nb_f, nb_tp_plein, nb_tp_partiel = 0, 0, 0, 0
    nb_cdi, nb_cdd, nb_alt, nb_stag = 0, 0, 0, 0
    nb_affilies_sante, nb_affilies_prev = 0, 0
    
    nb_femmes_cadres = 0 
    noms_mutuelles, noms_prevoyances = set(), set() 
    
    jours_absence, j_maladie, j_at, j_conges = 0, 0, 0, 0
    nb_arrets_total, nb_abs_longue_duree, nb_sini_at = 0, 0, 0
    demissions, fins_cdd, licenciements = 0, 0, 0
    anciennetes_cdi, anciennetes_depart = [], []
    
    adhesions_globales, affiliations_salarie = {}, {}
    current_ref_contrat, current_id_affil, current_base_affil, code_cotis = None, None, None, None
    cotis_sante, cotis_prev, cotis_retraite = 0.0, 0.0, 0.0
    
    debut_mois = date_analyse.replace(day=1)
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        for line in file:
            m = pattern.match(line.strip())
            if not m: continue 
            seg, val = m.groups()

            if seg == 'S21.G00.06.001': current_siren_lecture = val
            elif seg in mapping_ent and current_siren_lecture: infos_statiques[mapping_ent[seg]] = val
            elif seg == 'S21.G00.15.001': current_ref_contrat = val
            elif seg == 'S21.G00.15.005':
                if current_ref_contrat: adhesions_globales[val] = current_ref_contrat
                current_ref_contrat = None

            # --- CORRECTION SEXE ---
            elif seg == 'S21.G00.30.001': 
                nir = val.strip()
                if nir: sexe = nir[0] # Le 1er chiffre donne le sexe (1=H, 2=F)
            elif seg == 'S21.G00.30.006': date_naiss = convertir_date_dsn(val)

            elif seg == 'S21.G00.40.019': current_siret = val
            elif seg == 'S21.G00.40.001':
                if contrat_en_cours and current_siret == siret_attendu:
                    contrats_hist.append(contrat_en_cours)
                    if est_actif(contrat_en_cours, date_analyse):
                        effectif += 1
                        if statut_cadre == '01': 
                            nb_cadres += 1
                            if sexe == '2': nb_femmes_cadres += 1
                        elif statut_cadre == '04': nb_non_cadres += 1
                        
                        if sexe == '1': nb_h += 1
                        elif sexe == '2': nb_f += 1
                        
                        if temps_travail == '1': nb_tp_plein += 1
                        elif temps_travail == '2': nb_tp_partiel += 1
                        
                        if sante_found: nb_affilies_sante += 1
                        if prev_found: nb_affilies_prev += 1
                        
                        if nature_contrat == '01':
                            nb_cdi += 1
                            if contrat_en_cours.get('debut'): anciennetes_cdi.append((date_analyse - contrat_en_cours['debut']).days / 365.25)
                        elif nature_contrat == '02': nb_cdd += 1
                        elif nature_contrat in ('07','08','09'): nb_alt += 1
                        elif nature_contrat == '29': nb_stag += 1
                
                contrat_en_cours = {'SIRET': siret_attendu, 'debut': convertir_date_dsn(val), 'fin': None, 'statut': None, 'sexe': sexe, 'date_naissance': date_naiss}
                statut_cadre, nature_contrat, temps_travail = None, None, None
                sante_found, prev_found = False, False
                affiliations_salarie.clear()
                current_id_affil, current_base_affil, code_cotis = None, None, None
                
            elif seg == 'S21.G00.40.003':
                statut_cadre = val
                if contrat_en_cours: contrat_en_cours['statut'] = val
            elif seg == 'S21.G00.40.007': nature_contrat = val
            
            # --- CORRECTION TEMPS DE TRAVAIL ---
            elif seg == 'S21.G00.40.014': 
                if val.startswith('1'): temps_travail = '1' # ex: 10 = temps plein
                elif val.startswith('2'): temps_travail = '2' # ex: 20 = partiel
                
            elif seg in ('S21.G00.40.010', 'S21.G00.62.001'):
                fin_c = convertir_date_dsn(val)
                if contrat_en_cours: contrat_en_cours['fin'] = fin_c
                if seg == 'S21.G00.62.001' and current_siret == siret_attendu:
                    if val == '011': demissions += 1
                    elif val == '066': fins_cdd += 1
                    elif val.startswith('02'): licenciements += 1
                    if contrat_en_cours.get('debut') and fin_c: anciennetes_depart.append((fin_c - contrat_en_cours['debut']).days / 365.25)
            
            elif seg == 'S21.G00.51.011': type_rem = val 
            elif seg == 'S21.G00.51.013':
                if current_siret == siret_attendu and est_actif(contrat_en_cours, date_analyse):
                    try:
                        montant = float(val)
                        if type_rem == '010':
                            salaires_hist.append({'SIRET': siret_attendu, 'ANNEE_MOIS': date_analyse, 'MONTANT_BRUT': montant, 'STATUT': statut_cadre, 'SEXE': sexe})
                            ms_totale += montant
                            if statut_cadre == '01': ms_cadre += montant
                            elif statut_cadre == '04': ms_non_cadre += montant
                        else: ms_primes += montant
                    except ValueError: pass
                type_rem = None
            
            elif seg == 'S21.G00.60.001': motif_abs = val
            elif seg == 'S21.G00.60.002':
                djt = convertir_date_dsn(val)
                if djt: absence_en_cours = {'debut': djt + timedelta(days=1), 'motif': motif_abs}
            elif seg == 'S21.G00.60.003':
                if absence_en_cours and absence_en_cours.get('debut'):
                    fin_abs = convertir_date_dsn(val)
                    if fin_abs and current_siret == siret_attendu:
                        if (fin_abs - absence_en_cours['debut']).days > 90: nb_abs_longue_duree += 1
                        d_bornee, f_bornee = max(absence_en_cours['debut'], debut_mois), min(fin_abs, date_analyse)
                        if f_bornee >= d_bornee:
                            nb_arrets_total += 1
                            j_ouvres = ((f_bornee - d_bornee).days + 1) * (5/7)
                            jours_absence += j_ouvres
                            
                            m_abs = absence_en_cours.get('motif')
                            if m_abs == '01': j_maladie += j_ouvres
                            elif m_abs == '04':
                                j_at += j_ouvres
                                nb_sini_at += 1
                            elif m_abs in ('10', '13'): j_conges += j_ouvres
                    absence_en_cours = {}

            elif seg == 'S21.G00.70.012': current_id_affil = val
            elif seg == 'S21.G00.70.013':
                if current_id_affil: affiliations_salarie[current_id_affil] = val
                current_id_affil = None
            elif seg == 'S21.G00.78.001': current_base_affil = None 
            elif seg == 'S21.G00.78.005': current_base_affil = val 
            elif seg == 'S21.G00.81.001': code_cotis = val
            elif seg == 'S21.G00.81.004': 
                if current_siret == siret_attendu and code_cotis:
                    try:
                        m_val = float(val)
                        if code_cotis in codes_retraite: cotis_retraite += m_val
                        elif code_cotis == '059':
                            id_ad = affiliations_salarie.get(current_base_affil)
                            nom_c = adhesions_globales.get(id_ad)
                            cat = auto_classer_contrat(nom_c)
                            if cat == "SANTE": 
                                cotis_sante += m_val
                                sante_found = True
                                if nom_c: noms_mutuelles.add(nom_c)
                            elif cat == "PREVOYANCE": 
                                cotis_prev += m_val
                                prev_found = True
                                if nom_c: noms_prevoyances.add(nom_c)
                    except ValueError: pass
                code_cotis = None 
            elif seg == 'S21.G00.81.006' and current_siret == siret_attendu:
                try: charges_pat += float(val)
                except ValueError: pass

        if contrat_en_cours and current_siret == siret_attendu:
            contrats_hist.append(contrat_en_cours)
            if est_actif(contrat_en_cours, date_analyse):
                effectif += 1
                if statut_cadre == '01': 
                    nb_cadres += 1
                    if sexe == '2': nb_femmes_cadres += 1
                elif statut_cadre == '04': nb_non_cadres += 1
                
                if sexe == '1': nb_h += 1
                elif sexe == '2': nb_f += 1
                
                if temps_travail == '1': nb_tp_plein += 1
                elif temps_travail == '2': nb_tp_partiel += 1
                
                if sante_found: nb_affilies_sante += 1
                if prev_found: nb_affilies_prev += 1
                if nature_contrat == '01':
                    nb_cdi += 1
                    if contrat_en_cours.get('debut'): anciennetes_cdi.append((date_analyse - contrat_en_cours['debut']).days / 365.25)
                elif nature_contrat == '02': nb_cdd += 1

    kpi_base = {
        'SIRET': siret_attendu, 'DATE_ANALYSE': date_analyse,
        'NOMBRE_CONTRATS_ACTIFS': effectif,
        'NB_HOMMES': nb_h, 'NB_FEMMES': nb_f,
        'NB_CADRES': nb_cadres, 'NB_NON_CADRES': nb_non_cadres,
        'NB_FEMMES_CADRES': nb_femmes_cadres,
        'NB_CDI': nb_cdi, 'NB_CDD': nb_cdd, 'NB_ALTERNANTS': nb_alt, 'NB_STAGIAIRES': nb_stag,
        'NB_TEMPS_PLEIN': nb_tp_plein, 'NB_TEMPS_PARTIEL': nb_tp_partiel,
        'NB_AFFILIES_SANTE': nb_affilies_sante, 'NB_AFFILIES_PREVOYANCE': nb_affilies_prev,
        'NOM_MUTUELLE': " / ".join(noms_mutuelles), 
        'NOM_PREVOYANCE': " / ".join(noms_prevoyances),
        'DEMISSIONS': demissions, 'FINS_CDD': fins_cdd, 'LICENCIEMENTS': licenciements,
        
        'MASSE_SALARIALE_BRUTE_KE': int(round(ms_totale / 1000)),
        'MS_BASE_EUROS_BRUT': ms_totale,
        'MS_PRIMES_EUROS': ms_primes, 'CHARGES_PAT_EUROS': charges_pat,
        'MS_CADRE_KE': int(round(ms_cadre / 1000)), 'MS_NON_CADRE_KE': int(round(ms_non_cadre / 1000)),
        'PART_MS_CADRE_POURCENT': round((ms_cadre / ms_totale) * 100, 1) if ms_totale > 0 else 0.0,
        'PART_MS_NON_CADRE_POURCENT': round((ms_non_cadre / ms_totale) * 100, 1) if ms_totale > 0 else 0.0,
        'SALAIRE_MOYEN_TOTAL': int(round(ms_totale / effectif)) if effectif > 0 else 0,
        
        'TOTAL_JOURS_ABSENCES': jours_absence, 'J_MALADIE': j_maladie, 'J_AT': j_at, 'J_CONGES': j_conges, 
        'NB_ARRETS_TOTAL': nb_arrets_total, 'NB_SINI_AT': nb_sini_at, 'NB_ABS_LONGUE_DUREE': nb_abs_longue_duree,
        'TAUX_ABSENTEISME_POURCENT': round((jours_absence / (effectif * 21.67)) * 100, 2) if effectif > 0 else 0.0,
        
        'ANCIENNETE_MOYENNE_CDI_ANNEES': round(sum(anciennetes_cdi) / len(anciennetes_cdi), 1) if anciennetes_cdi else 0.0,
        'ANCIENNETE_MOY_DEPART_ANNEES': round(sum(anciennetes_depart)/len(anciennetes_depart), 1) if anciennetes_depart else 0.0,
        
        'TOTAL_SANTE_EUROS': int(round(cotis_sante)), 'TOTAL_PREVOYANCE_EUROS': int(round(cotis_prev)), 'TOTAL_RETRAITE_EUROS': int(round(cotis_retraite))
    }
    
    return kpi_base, contrats_hist, salaires_hist, infos_statiques

# ==========================================
# 4. PIPELINE D'EXÉCUTION & PANDAS
# ==========================================
print("Extraction des données en cours...")
tous_kpis, tous_contrats, tous_salaires, dictionnaire_entreprises = [], [], [], {}

if FICHIER_CONCAT.exists():
    for siret in lister_sirets_dans_fichier(FICHIER_CONCAT):
        kpi, c, s, i = parser_fichier_dsn(FICHIER_CONCAT, datetime(2026, 1, 31), siret)
        tous_kpis.append(kpi); tous_contrats.extend(c); tous_salaires.extend(s); dictionnaire_entreprises[siret] = i

if DOSSIER_NVX.exists():
    for file_path in DOSSIER_NVX.glob("*.edi"):
        date_analyse, siret = analyser_nom_fichier(file_path.name)
        if date_analyse and siret:
            kpi, c, s, i = parser_fichier_dsn(file_path, date_analyse, siret)
            tous_kpis.append(kpi); tous_contrats.extend(c); tous_salaires.extend(s); dictionnaire_entreprises[siret] = i

# --- DIMENSION ---
df_dim_entreprise = pd.DataFrame([{'SIRET': s, 'NOM_ENTREPRISE': recuperer_nom_entreprise(s[:9]), **i} for s, i in dictionnaire_entreprises.items()])

# --- FAITS ---
df = pd.DataFrame(tous_kpis)
df_c = pd.DataFrame(tous_contrats).drop_duplicates(subset=['SIRET', 'debut', 'statut'], keep='last')
df_s = pd.DataFrame(tous_salaires)

if not df.empty:
    print("Calcul des indicateurs complexes...")
    
    eff = np.where(df['NOMBRE_CONTRATS_ACTIFS'] > 0, df['NOMBRE_CONTRATS_ACTIFS'], 1)
    msb = np.where(df['MS_BASE_EUROS_BRUT'] > 0, df['MS_BASE_EUROS_BRUT'], 1)
    j_theo, h_theo = eff * 21.67, eff * 151.67
    
    # Ratios Socles
    df['TAUX_FEMINISATION_POURCENT'] = np.round((df['NB_FEMMES'] / eff) * 100, 1)
    df['TAUX_CADRES_POURCENT'] = np.round((df['NB_CADRES'] / eff) * 100, 1)
    df['TAUX_NON_CADRES_POURCENT'] = np.round((df['NB_NON_CADRES'] / eff) * 100, 1)
    df['TAUX_TEMPS_PARTIEL_POURCENT'] = np.round((df['NB_TEMPS_PARTIEL'] / eff) * 100, 1)
    
    df['TAUX_FEMINISATION_MANAGEMENT_POURCENT'] = np.round(np.where(df['NB_CADRES'] > 0, (df['NB_FEMMES_CADRES'] / df['NB_CADRES']) * 100, 0), 1)
    
    df['MS_CHARGEE_KE'] = np.round((df['MS_BASE_EUROS_BRUT'] + df['CHARGES_PAT_EUROS']) / 1000).astype(int)
    df['PART_VARIABLE_POURCENT'] = np.round((df['MS_PRIMES_EUROS'] / msb) * 100, 1)
    
    df['TAUX_AFFILIES_SANTE_POURCENT'] = np.round((df['NB_AFFILIES_SANTE'] / eff) * 100, 1)
    df['TAUX_AFFILIES_PREV_POURCENT'] = np.round((df['NB_AFFILIES_PREVOYANCE'] / eff) * 100, 1)
    
    df['TAUX_MALADIE_POURCENT'] = np.round((df['J_MALADIE'] / j_theo) * 100, 2)
    df['TAUX_AT_POURCENT'] = np.round((df['J_AT'] / j_theo) * 100, 2)
    df['TAUX_FREQUENCE_AT'] = np.round((df['NB_SINI_AT'] * 1000000) / (h_theo * 12), 1)
    df['TAUX_GRAVITE_AT'] = np.round((df['J_AT'] * 1000) / h_theo, 2)
    df['DUREE_MOY_ARRET_JOURS'] = np.round(np.where(df['NB_ARRETS_TOTAL'] > 0, df['TOTAL_JOURS_ABSENCES'] / df['NB_ARRETS_TOTAL'], 0), 1)

    kpis_complexes = []
    for _, row in df.iterrows():
        siret, d_cible = row['SIRET'], row['DATE_ANALYSE']
        d_12m = d_cible - relativedelta(months=12)

        c_s = df_c[df_c['SIRET'] == siret].copy()
        s_s = df_s[(df_s['SIRET'] == siret) & (df_s['ANNEE_MOIS'] == d_cible)]

        # --- Turnover & Recrutements ---
        rec = len(c_s[(c_s['debut'] > d_12m) & (c_s['debut'] <= d_cible)])
        sorties = len(c_s[c_s['fin'].notna() & (c_s['fin'] > d_12m) & (c_s['fin'] <= d_cible)])
        act_deb = len(c_s[(c_s['debut'] <= d_12m) & ((c_s['fin'].isna()) | (c_s['fin'] > d_12m))])
        act_fin = len(c_s[(c_s['debut'] <= d_cible) & ((c_s['fin'].isna()) | (c_s['fin'] > d_cible))])
        eff_moy = (act_deb + act_fin) / 2
        to = round((((rec + sorties) / 2) / eff_moy) * 100, 1) if eff_moy > 0 else 0.0

        # --- Pyramide des âges & Ancienneté ---
        actifs = c_s[(c_s['debut'] <= d_cible) & ((c_s['fin'].isna()) | (c_s['fin'] > d_cible))].copy()
        actifs['AGE'] = (d_cible - actifs['date_naissance']).dt.days / 365.25
        bins, labels = [0, 25, 35, 45, 55, 100], ['NB_MOINS_26', 'NB_26_35', 'NB_36_45', 'NB_46_55', 'NB_PLUS_55']
        ages_counts = pd.cut(actifs['AGE'], bins=bins, labels=labels, right=True).value_counts().to_dict()

        actifs['ANC_CDI'] = (d_cible - actifs['debut']).dt.days / 365.25
        anc_mediane = round(actifs['ANC_CDI'].median(), 1) if not actifs.empty else 0.0

        # --- Salaires moyens ---
        sal_h  = s_s[s_s['SEXE'] == '1']['MONTANT_BRUT'].mean()
        sal_f  = s_s[s_s['SEXE'] == '2']['MONTANT_BRUT'].mean()
        sal_c  = s_s[s_s['STATUT'] == '01']['MONTANT_BRUT'].mean()
        sal_nc = s_s[s_s['STATUT'] == '04']['MONTANT_BRUT'].mean()

        sal_h = 0 if pd.isna(sal_h) else int(round(sal_h))
        sal_f = 0 if pd.isna(sal_f) else int(round(sal_f))
        ecart_hf = round(((sal_h - sal_f) / sal_h) * 100, 1) if sal_h > 0 else 0.0

        # --- Salaires médians ---
        sal_med_c   = s_s[s_s['STATUT'] == '01']['MONTANT_BRUT'].median()
        sal_med_nc  = s_s[s_s['STATUT'] == '04']['MONTANT_BRUT'].median()
        sal_med_h   = s_s[s_s['SEXE'] == '1']['MONTANT_BRUT'].median()
        sal_med_f   = s_s[s_s['SEXE'] == '2']['MONTANT_BRUT'].median()
        sal_med_tot = s_s['MONTANT_BRUT'].median()

        # --- Années dynamiques N, N-1, N-2 ---
        s_s_3ans = df_s[df_s['SIRET'] == siret]
        annees_cibles = [d_cible.year, d_cible.year - 1, d_cible.year - 2]
        ms_grp = s_s_3ans[s_s_3ans['ANNEE_MOIS'].dt.year.isin(annees_cibles)].groupby(
            [s_s_3ans['ANNEE_MOIS'].dt.year, 'STATUT']
        )['MONTANT_BRUT'].sum().to_dict()

        # --- Construction du dict comp ---
        comp = {
            'SIRET': siret, 'DATE_ANALYSE': d_cible,
            'RECRUTEMENTS_12_MOIS': rec,
            'TAUX_TURNOVER_POURCENT': to,
            'EFFECTIF_MOYEN': eff_moy,
            'ANCIENNETE_MEDIANE_CDI_ANNEES': anc_mediane,
            # Moyens
            'SALAIRE_MOYEN_HOMME':     sal_h,
            'SALAIRE_MOYEN_FEMME':     sal_f,
            'ECART_SALARIAL_HF_POURCENT': ecart_hf,
            'SALAIRE_MOYEN_CADRE':     0 if pd.isna(sal_c)  else int(round(sal_c)),
            'SALAIRE_MOYEN_NON_CADRE': 0 if pd.isna(sal_nc) else int(round(sal_nc)),
            # Médians
            'SALAIRE_MEDIAN_CADRE':     0 if pd.isna(sal_med_c)   else int(round(sal_med_c)),
            'SALAIRE_MEDIAN_NON_CADRE': 0 if pd.isna(sal_med_nc)  else int(round(sal_med_nc)),
            'SALAIRE_MEDIAN_HOMME':     0 if pd.isna(sal_med_h)   else int(round(sal_med_h)),
            'SALAIRE_MEDIAN_FEMME':     0 if pd.isna(sal_med_f)   else int(round(sal_med_f)),
            'SALAIRE_MEDIAN_TOTAL':     0 if pd.isna(sal_med_tot) else int(round(sal_med_tot)),
        }
        comp.update(ages_counts)

        # Init colonnes MS 3 ans
        for annee_rel in annees_cibles:
            suf = "N" if annee_rel == d_cible.year else f"N_{d_cible.year - annee_rel}"
            comp[f'MS_CADRE_{suf}_KE'] = 0
            comp[f'MS_NON_CADRE_{suf}_KE'] = 0

        for (an, st), mnt in ms_grp.items():
            nom = "CADRE" if st == '01' else "NON_CADRE"
            suf = "N" if an == d_cible.year else f"N_{d_cible.year - an}"
            comp[f'MS_{nom}_{suf}_KE'] = int(round(mnt / 1000))

        kpis_complexes.append(comp)

    df = pd.merge(df, pd.DataFrame(kpis_complexes).fillna(0), on=['SIRET', 'DATE_ANALYSE'])

    # --- VARIATIONS M-1 et N-1 ---
    mets = [
        'NOMBRE_CONTRATS_ACTIFS', 'MASSE_SALARIALE_BRUTE_KE', 'SALAIRE_MOYEN_TOTAL',
        'TAUX_ABSENTEISME_POURCENT', 'RECRUTEMENTS_12_MOIS', 'TAUX_TURNOVER_POURCENT',
        'TOTAL_SANTE_EUROS', 'TOTAL_PREVOYANCE_EUROS', 'TOTAL_RETRAITE_EUROS',
        'SALAIRE_MEDIAN_CADRE', 'SALAIRE_MEDIAN_NON_CADRE', 'SALAIRE_MEDIAN_TOTAL',
    ]
    
    df_m1 = df[['SIRET', 'DATE_ANALYSE'] + mets].copy()
    df_m1['DATE_ANALYSE'] = df_m1['DATE_ANALYSE'] + MonthEnd(1)
    df_m1 = df_m1.rename(columns={m: f"{m}_M1" for m in mets})
    
    df_n1 = df[['SIRET', 'DATE_ANALYSE'] + mets].copy()
    df_n1['DATE_ANALYSE'] = df_n1['DATE_ANALYSE'] + MonthEnd(12)
    df_n1 = df_n1.rename(columns={m: f"{m}_N1" for m in mets})
    
    df = df.merge(df_m1, on=['SIRET', 'DATE_ANALYSE'], how='left').merge(df_n1, on=['SIRET', 'DATE_ANALYSE'], how='left')

    for e, suf in [('M_1', '_M1'), ('N_1', '_N1')]:
        df[f'EVOL_EFFECTIF_{e}_ABS'] = df['NOMBRE_CONTRATS_ACTIFS'] - df[f'NOMBRE_CONTRATS_ACTIFS{suf}']
        df[f'EVOL_RECRUTEMENTS_{e}_ABS'] = df['RECRUTEMENTS_12_MOIS'] - df[f'RECRUTEMENTS_12_MOIS{suf}']
        df[f'EVOL_MSB_{e}_POURCENT'] = np.round(np.where(df[f'MASSE_SALARIALE_BRUTE_KE{suf}'] > 0, ((df['MASSE_SALARIALE_BRUTE_KE'] - df[f'MASSE_SALARIALE_BRUTE_KE{suf}']) / df[f'MASSE_SALARIALE_BRUTE_KE{suf}']) * 100, 0), 1)
        df[f'EVOL_SALAIRE_MOYEN_{e}_POURCENT'] = np.round(np.where(df[f'SALAIRE_MOYEN_TOTAL{suf}'] > 0, ((df['SALAIRE_MOYEN_TOTAL'] - df[f'SALAIRE_MOYEN_TOTAL{suf}']) / df[f'SALAIRE_MOYEN_TOTAL{suf}']) * 100, 0), 1)
        df[f'EVOL_ABSENTEISME_{e}_PTS'] = np.round(df['TAUX_ABSENTEISME_POURCENT'] - df[f'TAUX_ABSENTEISME_POURCENT{suf}'], 1)
        df[f'EVOL_TURNOVER_{e}_PTS'] = np.round(df['TAUX_TURNOVER_POURCENT'] - df[f'TAUX_TURNOVER_POURCENT{suf}'], 1)

    df = df.drop(columns=[f"{m}_M1" for m in mets] + [f"{m}_N1" for m in mets])
    df['DATE_ANALYSE'] = df['DATE_ANALYSE'].dt.strftime('%Y-%m-%d')
    
    df = df.drop(columns=['MS_BASE_EUROS_BRUT', 'MS_PRIMES_EUROS', 'CHARGES_PAT_EUROS', 'NB_FEMMES_CADRES'])

    df_dim_entreprise.to_csv('dim_entreprise.csv', index=False)
    df.to_csv('fait_indicateurs_mensuels.csv', index=False)
    print("\n✅ Terminé ! Fichiers 'dim_entreprise.csv' et 'fait_indicateurs.csv' générés. Prêt pour Streamlit.")