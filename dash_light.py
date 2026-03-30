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
from collections import defaultdict

# ==========================================
# 1. CACHE ET API INSEE
# ==========================================
cache_noms_entreprises = {} 

def recuperer_nom_entreprise(siren):
    if siren in cache_noms_entreprises:
        return cache_noms_entreprises[siren]
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}"
        reponse = requests.get(url, timeout=5) 
        if reponse.status_code == 200:
            data = reponse.json()
            if data.get('results'):
                nom = data['results'][0].get('nom_complet', 'Nom introuvable')
                cache_noms_entreprises[siren] = nom
                time.sleep(0.1) 
                return nom
    except Exception:
        pass 
    cache_noms_entreprises[siren] = "Nom inconnu (API)"
    return "Nom inconnu (API)"

# ==========================================
# 2. UTILITAIRES DSN
# ==========================================
def analyser_nom_fichier(filename):
    """Extrait la date de fin de mois et le SIRET depuis le nom du fichier."""
    try:
        parts = filename.replace('.edi', '').split('_')
        annee_mois = parts[2]
        siret = parts[3].replace('!', '')
        
        annee = int(annee_mois[:4])
        mois = int(annee_mois[4:])
        dernier_jour = calendar.monthrange(annee, mois)[1]
        
        return datetime(annee, mois, dernier_jour), siret
    except Exception:
        return None, None

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
    """Analyse sémantique du nom du contrat de manière autonome."""
    if not nom_contrat: return "INCONNU"
    nom_propre = str(nom_contrat).upper()
    
    mots_clefs_sante = ['SANTE', 'SANTÉ', 'MUTUELLE', 'MUT', 'FRAIS DE SANTE', 'COMPLEMENTAIRE']
    mots_clefs_prevoyance = ['PREVOYANCE', 'PRÉVOYANCE', 'PREV', 'PRV', 'INCAPACITE', 'INVALIDITE', 'DECES', 'RISO']
    
    if any(mot in nom_propre for mot in mots_clefs_sante): return "SANTE"
    elif any(mot in nom_propre for mot in mots_clefs_prevoyance): return "PREVOYANCE"
    return "INCONNU"

def lister_sirets_dans_fichier(file_path):
    """Parcourt rapidement un fichier DSN pour lister tous les SIRET distincts (Bloc 40)."""
    sirets = set()
    pattern_siret = re.compile(r"^S21\.G00\.40\.019,'(.*)'$")
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = pattern_siret.match(line.strip())
            if match: sirets.add(match.group(1))
    return list(sirets)

# ==========================================
# 3. LECTURE ET PARSING UNIFIÉ
# ==========================================
def parser_fichier_dsn(file_path, date_analyse, siret_attendu):
    dsn_mapping_entreprise = {
        'S21.G00.06.003': 'CODE_NAF', 'S21.G00.06.004': 'ADRESSE_ENTREPRISE',
        'S21.G00.06.005': 'CP_ENTREPRISE', 'S21.G00.06.006': 'VILLE_ENTREPRISE',
    }
    
    pattern = re.compile(r"^(S\d{2}\.G\d{2}\.\d{2}\.\d{3}),'(.*)'$")
    
    # RETOUR ARRIÈRE : Liste complète des codes retraites (Demande de Laura annulée)
    codes_retraite = {"105", "106", "109", "110", "111", "112", "113", "131", "132", "915", "060", "061"}
    
    contrats_hist, salaires_hist = [], []
    infos_statiques = {}
    
    # Mémoires Salarié/Contrat
    contrat_en_cours, absence_en_cours = {}, {}
    current_siret, current_siren_lecture = None, None
    statut_cadre, nature_contrat, type_remuneration = None, None, None
    
    # Utilitaires pour les bornes mensuelles
    debut_mois = date_analyse.replace(day=1)
    
    # Compteurs RH
    effectif, ms_totale, jours_absence = 0, 0.0, 0
    nb_cadres, ms_cadre, nb_non_cadres, ms_non_cadre = 0, 0.0, 0, 0.0
    anciennetes_cdi = []
    
    # Mémoires et compteurs Cotisations
    adhesions_globales, affiliations_salarie = {}, {}
    current_ref_contrat, current_id_affiliation = None, None
    current_base_affiliation_id, code_cotisation_en_cours = None, None
    cotisation_sante, cotisation_prevoyance, cotisation_retraite = 0.0, 0.0, 0.0
    cotisations_non_identifiees = set()
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        for line in file:
            match = pattern.match(line.strip())
            if not match: continue 
            seg, val = match.groups()

            # --- A. ENTREPRISE ---
            if seg == 'S21.G00.06.001': current_siren_lecture = val
            elif seg in dsn_mapping_entreprise and current_siren_lecture:
                infos_statiques[dsn_mapping_entreprise[seg]] = val

            # --- B. CONTRATS GLOBAUX (Bloc 15) ---
            elif seg == 'S21.G00.15.001': current_ref_contrat = val
            elif seg == 'S21.G00.15.005':
                if current_ref_contrat: adhesions_globales[val] = current_ref_contrat
                current_ref_contrat = None

            # --- C. CONTRATS SALARIÉS ---
            elif seg == 'S21.G00.40.019': current_siret = val
            elif seg == 'S21.G00.40.001':
                if contrat_en_cours and current_siret == siret_attendu:
                    contrats_hist.append(contrat_en_cours)
                    if est_actif(contrat_en_cours, date_analyse):
                        effectif += 1
                        
                        # MODIF METIER : Cadres = 01 et 02
                        if statut_cadre in ('01', '02'): nb_cadres += 1
                        elif statut_cadre == '04': nb_non_cadres += 1
                        
                        if nature_contrat == '01' and contrat_en_cours.get('debut'):
                            anciennetes_cdi.append((date_analyse - contrat_en_cours['debut']).days / 365.25)
                
                # Réinitialisation pour un nouveau contrat
                contrat_en_cours = {'SIRET': siret_attendu, 'debut': convertir_date_dsn(val), 'fin': None, 'statut': None}
                statut_cadre, nature_contrat = None, None
                affiliations_salarie.clear()
                current_id_affiliation, current_base_affiliation_id, code_cotisation_en_cours = None, None, None
                
            elif seg == 'S21.G00.40.003':
                statut_cadre = val
                if contrat_en_cours: contrat_en_cours['statut'] = val
            elif seg == 'S21.G00.40.007': nature_contrat = val
            elif seg in ('S21.G00.40.010', 'S21.G00.62.001'):
                if contrat_en_cours: contrat_en_cours['fin'] = convertir_date_dsn(val)
            
            # --- D. SALAIRES ---
            elif seg == 'S21.G00.51.011': type_remuneration = val 
            elif seg == 'S21.G00.51.013':
                if current_siret == siret_attendu and type_remuneration == '010':
                    try:
                        montant = float(val)
                        salaires_hist.append({'SIRET': siret_attendu, 'ANNEE_MOIS': date_analyse, 'MONTANT_BRUT': montant, 'STATUT': statut_cadre})
                        if est_actif(contrat_en_cours, date_analyse):
                            ms_totale += montant
                            # MODIF METIER : MS Cadres inclus statuts 01 et 02
                            if statut_cadre in ('01', '02'): ms_cadre += montant
                            elif statut_cadre == '04': ms_non_cadre += montant
                    except ValueError: pass
                type_remuneration = None
            
            # --- E. GESTION DES ABSENCES ---
            elif seg == 'S21.G00.60.002':
                djt = convertir_date_dsn(val)
                if djt:
                                                                                              
                    absence_en_cours = {'debut': djt + timedelta(days=1), 'fin': None}
                    
            elif seg == 'S21.G00.60.003':
                if absence_en_cours and absence_en_cours.get('debut'):
                    fin_absence = convertir_date_dsn(val)
                    if fin_absence and current_siret == siret_attendu:
                                                                                      
                        debut_abs_bornee = max(absence_en_cours['debut'], debut_mois)
                        fin_abs_bornee = min(fin_absence, date_analyse)
                        
                                                                                          
                        if fin_abs_bornee >= debut_abs_bornee:
                                                                           
                            jours_calendaires = (fin_abs_bornee - debut_abs_bornee).days + 1
                                                                                                  
                            jours_ouvres = jours_calendaires * (5 / 7)
                            
                            jours_absence += jours_ouvres
                    absence_en_cours = {}

            # --- F. COTISATIONS ---
            elif seg == 'S21.G00.70.012': current_id_affiliation = val
            elif seg == 'S21.G00.70.013':
                if current_id_affiliation: affiliations_salarie[current_id_affiliation] = val
                current_id_affiliation = None
            elif seg == 'S21.G00.78.001': current_base_affiliation_id = None 
            elif seg == 'S21.G00.78.005': current_base_affiliation_id = val 
            elif seg == 'S21.G00.81.001': code_cotisation_en_cours = val
            elif seg == 'S21.G00.81.004': 
                if current_siret == siret_attendu and code_cotisation_en_cours:
                    try:
                        montant_val = float(val)
                        if code_cotisation_en_cours in codes_retraite:
                            cotisation_retraite += montant_val
                        elif code_cotisation_en_cours == '059':
                            id_adhesion = affiliations_salarie.get(current_base_affiliation_id)
                            nom_contrat_reel = adhesions_globales.get(id_adhesion)
                            categorie = auto_classer_contrat(nom_contrat_reel)
                            
                            if categorie == "SANTE": cotisation_sante += montant_val
                            elif categorie == "PREVOYANCE": cotisation_prevoyance += montant_val
                            elif nom_contrat_reel: cotisations_non_identifiees.add(nom_contrat_reel)
                    except ValueError: pass
                code_cotisation_en_cours = None 

        # Traitement du tout dernier contrat du fichier
        if contrat_en_cours and current_siret == siret_attendu:
            contrats_hist.append(contrat_en_cours)
            if est_actif(contrat_en_cours, date_analyse):
                effectif += 1
                if statut_cadre in ('01', '02'): nb_cadres += 1
                elif statut_cadre == '04': nb_non_cadres += 1
                if nature_contrat == '01' and contrat_en_cours.get('debut'):
                    anciennetes_cdi.append((date_analyse - contrat_en_cours['debut']).days / 365.25)

    kpi_base = {
        'SIRET': siret_attendu,
        'DATE_ANALYSE': date_analyse,
        'NOMBRE_CONTRATS_ACTIFS': effectif,
        'MASSE_SALARIALE_BRUTE_KE': int(round(ms_totale / 1000)),
        'SALAIRE_MOYEN_TOTAL': int(round(ms_totale / effectif)) if effectif > 0 else 0,
        'TAUX_ABSENTEISME_POURCENT': round((jours_absence / (effectif * 21.67)) * 100, 2) if effectif > 0 else 0.0,
        'ANCIENNETE_MOYENNE_CDI_ANNEES': round(sum(anciennetes_cdi) / len(anciennetes_cdi), 1) if anciennetes_cdi else 0.0,
        'NOMBRE_CADRES': nb_cadres,
        'TAUX_CADRE_POURCENT': round((nb_cadres / effectif) * 100, 1) if effectif > 0 else 0.0,
        'MS_CADRE_KE': int(round(ms_cadre / 1000)),
        'PART_MS_CADRE_POURCENT': round((ms_cadre / ms_totale) * 100, 1) if ms_totale > 0 else 0.0,
        'SALAIRE_MOYEN_CADRE': int(round(ms_cadre / nb_cadres)) if nb_cadres > 0 else 0,
        'NOMBRE_NON_CADRES': nb_non_cadres,
        'TAUX_NON_CADRE_POURCENT': round((nb_non_cadres / effectif) * 100, 1) if effectif > 0 else 0.0,
        'MS_NON_CADRE_KE': int(round(ms_non_cadre / 1000)),
        'PART_MS_NON_CADRE_POURCENT': round((ms_non_cadre / ms_totale) * 100, 1) if ms_totale > 0 else 0.0,
        'SALAIRE_MOYEN_NON_CADRE': int(round(ms_non_cadre / nb_non_cadres)) if nb_non_cadres > 0 else 0,
        'TOTAL_SANTE_EUROS': int(round(cotisation_sante)),
        'TOTAL_PREVOYANCE_EUROS': int(round(cotisation_prevoyance)),
        'TOTAL_RETRAITE_EUROS': int(round(cotisation_retraite))
    }
    
    return kpi_base, contrats_hist, salaires_hist, infos_statiques, cotisations_non_identifiees


# ==========================================
# 4. PIPELINE D'EXÉCUTION
# ==========================================
base_dir_nc = Path(r"C:\Users\Azad\Documents\NC Assurances")
dossier_nvx = base_dir_nc / "NVX_fichier_evol"

tous_kpis_base = []
tous_contrats = []
tous_salaires = []
dictionnaire_entreprises = {}
toutes_cotisations_non_id = set()

print("Extraction des données en cours...")

# --- PHASE A : Traitement du gros fichier concaténé ---
fichier_concat = base_dir_nc / "concatenation_DSN.edi"
date_concat = datetime(2026, 1, 31)

if fichier_concat.exists():
    print(f" -> Traitement du fichier global : {fichier_concat.name}")
    sirets_trouves = lister_sirets_dans_fichier(fichier_concat)
    
    for siret in sirets_trouves:
        kpi_base, contrats, salaires, infos_stat, non_id = parser_fichier_dsn(fichier_concat, date_concat, siret)
        tous_kpis_base.append(kpi_base)
        tous_contrats.extend(contrats)
        tous_salaires.extend(salaires)
        dictionnaire_entreprises[siret] = infos_stat
        toutes_cotisations_non_id.update(non_id)

# --- PHASE B : Traitement des nouveaux fichiers individuels ---
if dossier_nvx.exists():
    for file_path in dossier_nvx.glob("*.edi"):
        date_analyse, siret = analyser_nom_fichier(file_path.name)
        if date_analyse and siret:
            print(f" -> Traitement de : {file_path.name}")
            kpi_base, contrats, salaires, infos_stat, non_id = parser_fichier_dsn(file_path, date_analyse, siret)
            tous_kpis_base.append(kpi_base)
            tous_contrats.extend(contrats)
            tous_salaires.extend(salaires)
            dictionnaire_entreprises[siret] = infos_stat
            toutes_cotisations_non_id.update(non_id)

# --- CONSTRUCTION TABLE DIMENSION ---
lignes_dim = []
for siret, infos in dictionnaire_entreprises.items():
    siren = siret[:9]
    dim = {'SIRET': siret, 'NOM_ENTREPRISE': recuperer_nom_entreprise(siren)}
    dim.update(infos)
    lignes_dim.append(dim)
df_dim_entreprise = pd.DataFrame(lignes_dim)

# --- CONSTRUCTION TABLE DE FAITS ---
df_base = pd.DataFrame(tous_kpis_base)
df_contrats = pd.DataFrame(tous_contrats).sort_values('fin', na_position='first').drop_duplicates(subset=['SIRET', 'debut', 'statut'], keep='last')
df_salaires = pd.DataFrame(tous_salaires)

# Ajout des KPI Complexes (12 mois & 3 ans)
kpis_complexes = []
for _, row in df_base.iterrows():
    siret = row['SIRET']
    date_cible = row['DATE_ANALYSE']
    date_12m = date_cible - relativedelta(months=12)
    annee_cible = date_cible.year
    
    c_siret = df_contrats[df_contrats['SIRET'] == siret]
    s_siret = df_salaires[df_salaires['SIRET'] == siret]
    
    recrutements = len(c_siret[(c_siret['debut'] > date_12m) & (c_siret['debut'] <= date_cible)])
    sorties = len(c_siret[c_siret['fin'].notna() & (c_siret['fin'] > date_12m) & (c_siret['fin'] <= date_cible)])
    actifs_debut = len(c_siret[(c_siret['debut'] <= date_12m) & ((c_siret['fin'].isna()) | (c_siret['fin'] > date_12m))])
    actifs_fin = len(c_siret[(c_siret['debut'] <= date_cible) & ((c_siret['fin'].isna()) | (c_siret['fin'] > date_cible))])
    
    effectif_moyen = (actifs_debut + actifs_fin) / 2
    turnover = round((((recrutements + sorties) / 2) / effectif_moyen) * 100, 1) if effectif_moyen > 0 else 0.0
    
    ms_3ans = s_siret[s_siret['ANNEE_MOIS'].dt.year.isin([annee_cible, annee_cible-1, annee_cible-2])]
    ms_grp = ms_3ans.groupby([ms_3ans['ANNEE_MOIS'].dt.year, 'STATUT'])['MONTANT_BRUT'].sum().to_dict()
    
    ligne_comp = {'SIRET': siret, 'DATE_ANALYSE': date_cible, 'RECRUTEMENTS_12_MOIS': recrutements, 'TAUX_TURNOVER_POURCENT': turnover}
    for (annee, statut), montant in ms_grp.items():
        # MODIF METIER : Évolutions MS 3 ans inclus statuts 01 et 02
        nom_statut = "CADRE" if statut in ('01', '02') else "NON_CADRE"
        cle = f'MS_{nom_statut}_{annee}_KE'
        ligne_comp[cle] = ligne_comp.get(cle, 0) + int(round(montant / 1000))
        
    kpis_complexes.append(ligne_comp)

df_fait_indicateurs = pd.merge(df_base, pd.DataFrame(kpis_complexes).fillna(0), on=['SIRET', 'DATE_ANALYSE'])

# --- CALCUL DES VARIATIONS M-1 et N-1 ---
def calc_croissance(val_actuelle, val_prec):
    return np.where(val_prec > 0, ((val_actuelle - val_prec) / val_prec * 100), 0.0)

                                                         
metriques = [
    'NOMBRE_CONTRATS_ACTIFS', 'MASSE_SALARIALE_BRUTE_KE', 'SALAIRE_MOYEN_TOTAL', 
    'TAUX_ABSENTEISME_POURCENT', 'ANCIENNETE_MOYENNE_CDI_ANNEES', 
    'RECRUTEMENTS_12_MOIS', 'TAUX_TURNOVER_POURCENT',
    'TOTAL_SANTE_EUROS', 'TOTAL_PREVOYANCE_EUROS', 'TOTAL_RETRAITE_EUROS'
]

df_m1 = df_fait_indicateurs[['SIRET', 'DATE_ANALYSE'] + metriques].copy()
df_m1['DATE_ANALYSE'] = df_m1['DATE_ANALYSE'] + MonthEnd(1)
df_m1 = df_m1.rename(columns={m: f"{m}_M1" for m in metriques})

df_n1 = df_fait_indicateurs[['SIRET', 'DATE_ANALYSE'] + metriques].copy()
df_n1['DATE_ANALYSE'] = df_n1['DATE_ANALYSE'] + MonthEnd(12)
df_n1 = df_n1.rename(columns={m: f"{m}_N1" for m in metriques})

df_fait_indicateurs = df_fait_indicateurs.merge(df_m1, on=['SIRET', 'DATE_ANALYSE'], how='left')
df_fait_indicateurs = df_fait_indicateurs.merge(df_n1, on=['SIRET', 'DATE_ANALYSE'], how='left')

suffixes = [('M_1', '_M1'), ('N_1', '_N1')]
for e_name, col_suffix in suffixes:
    # 1. Absolu
    df_fait_indicateurs[f'EVOL_EFFECTIF_{e_name}_ABS'] = df_fait_indicateurs['NOMBRE_CONTRATS_ACTIFS'] - df_fait_indicateurs[f'NOMBRE_CONTRATS_ACTIFS{col_suffix}']
    df_fait_indicateurs[f'EVOL_RECRUTEMENTS_{e_name}_ABS'] = df_fait_indicateurs['RECRUTEMENTS_12_MOIS'] - df_fait_indicateurs[f'RECRUTEMENTS_12_MOIS{col_suffix}']
    df_fait_indicateurs[f'EVOL_ANCIENNETE_{e_name}_ABS'] = (df_fait_indicateurs['ANCIENNETE_MOYENNE_CDI_ANNEES'] - df_fait_indicateurs[f'ANCIENNETE_MOYENNE_CDI_ANNEES{col_suffix}']).round(1)
    
    # 2. Pourcentages
    df_fait_indicateurs[f'EVOL_MSB_{e_name}_POURCENT'] = calc_croissance(df_fait_indicateurs['MASSE_SALARIALE_BRUTE_KE'], df_fait_indicateurs[f'MASSE_SALARIALE_BRUTE_KE{col_suffix}']).round(1)
    df_fait_indicateurs[f'EVOL_SALAIRE_MOYEN_{e_name}_POURCENT'] = calc_croissance(df_fait_indicateurs['SALAIRE_MOYEN_TOTAL'], df_fait_indicateurs[f'SALAIRE_MOYEN_TOTAL{col_suffix}']).round(1)
    df_fait_indicateurs[f'EVOL_SANTE_{e_name}_POURCENT'] = calc_croissance(df_fait_indicateurs['TOTAL_SANTE_EUROS'], df_fait_indicateurs[f'TOTAL_SANTE_EUROS{col_suffix}']).round(1)
    df_fait_indicateurs[f'EVOL_PREVOYANCE_{e_name}_POURCENT'] = calc_croissance(df_fait_indicateurs['TOTAL_PREVOYANCE_EUROS'], df_fait_indicateurs[f'TOTAL_PREVOYANCE_EUROS{col_suffix}']).round(1)
    df_fait_indicateurs[f'EVOL_RETRAITE_{e_name}_POURCENT'] = calc_croissance(df_fait_indicateurs['TOTAL_RETRAITE_EUROS'], df_fait_indicateurs[f'TOTAL_RETRAITE_EUROS{col_suffix}']).round(1)
    
    # 3. Points
    df_fait_indicateurs[f'EVOL_ABSENTEISME_{e_name}_PTS'] = (df_fait_indicateurs['TAUX_ABSENTEISME_POURCENT'] - df_fait_indicateurs[f'TAUX_ABSENTEISME_POURCENT{col_suffix}']).round(1)
    df_fait_indicateurs[f'EVOL_TURNOVER_{e_name}_PTS'] = (df_fait_indicateurs['TAUX_TURNOVER_POURCENT'] - df_fait_indicateurs[f'TAUX_TURNOVER_POURCENT{col_suffix}']).round(1)

# Nettoyage
cols_to_drop = [f"{m}_M1" for m in metriques] + [f"{m}_N1" for m in metriques]
df_fait_indicateurs = df_fait_indicateurs.drop(columns=cols_to_drop)
df_fait_indicateurs = df_fait_indicateurs.sort_values(by=['SIRET', 'DATE_ANALYSE']).reset_index(drop=True)
df_fait_indicateurs['DATE_ANALYSE'] = df_fait_indicateurs['DATE_ANALYSE'].dt.strftime('%Y-%m-%d')

# --- AFFICHAGE ET EXPORT ---
pd.set_option('display.max_columns', None)
print("\nTABLE 1 : DIMENSION ENTREPRISE (Adresse + API INSEE)")
print("-" * 50)
print(df_dim_entreprise.head())

print("\nTABLE 2 : FAIT INDICATEURS (Calculs + Cotisations + Évolutions M-1/N-1)")
print("-" * 50)
print(df_fait_indicateurs.head())

if toutes_cotisations_non_id:
    print("\nINFO : Les contrats suivants génèrent des cotisations OC (059) mais n'ont pas pu être classés automatiquement :")
    for c in toutes_cotisations_non_id:
        print(f" - {c}")