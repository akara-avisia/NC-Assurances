import streamlit as st
import pandas as pd
import tempfile
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pandas.tseries.offsets import MonthEnd
import numpy as np

import dash_complexe # Votre script métier

# ==========================================
# 1. CONFIGURATION ET UI
# ==========================================
st.set_page_config(page_title="Cockpit DSN - Expert", layout="wide", page_icon="🚀")

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# --- MOTEUR DE SEUILS ---
def evaluer_kpi(nom_kpi, valeur):
    """Retourne 2 (Critique), 1 (Warning), ou 0 (Normal)"""
    if pd.isna(valeur) or valeur == "": return 0
    v = float(valeur)
    if nom_kpi == "absenteisme": return 2 if v >= 5.5 else 1 if v >= 4.0 else 0
    elif nom_kpi == "turnover": return 2 if v >= 22.0 else 1 if v >= 15.0 else 0
    elif nom_kpi == "sante": return 2 if v < 95.0 else 1 if v < 100.0 else 0
    elif nom_kpi == "prevoyance": return 2 if v < 90.0 else 1 if v < 100.0 else 0
    return 0

# --- FORMATAGE CSS MAQUETTE ---
def create_card(title, value, subtitle, top_color, bottom_content="", has_dot=False):
    dot = f"<span style='float:right; color:{top_color}; font-size:2.5em; line-height:0.2;'>•</span>" if has_dot else ""
    return f"""
    <div style="border: 1px solid #e0e0e0; border-top: 3px solid {top_color}; border-radius: 5px; padding: 15px; background-color: white; min-height: 180px; margin-bottom: 20px; display: flex; flex-direction: column;">
        <div style="color: #a0aabf; font-size: 0.75rem; text-transform: uppercase; font-weight: bold; margin-bottom: 8px;">{title} {dot}</div>
        <div style="font-size: 2.2rem; font-weight: 900; color: #0B1940; line-height: 1.1; margin-bottom: 5px;">{value}</div>
        <div style="color: #a0aabf; font-size: 0.75rem; margin-bottom: 15px;">{subtitle}</div>
        <div style="margin-top: auto; padding-top: 10px; border-top: 1px solid #f0f2f6;">{bottom_content}</div>
    </div>
    """

def format_single_evol(valeur, unite="", texte_cible="M-1", inverser_couleur=False):
    if pd.isna(valeur):
        return f"<div style='font-size:0.85em; color:#838ea5; margin-bottom:4px;'>Évol. {texte_cible} = <span style='background-color:#f0f2f6; color:#838ea5; padding:2px 6px; border-radius:4px; font-weight:600;'>Pas de données</span></div>"
    if valeur == 0:
        return f"<div style='font-size:0.85em; color:#838ea5; margin-bottom:4px;'>Évol. {texte_cible} = <span style='background-color:#f0f2f6; color:#838ea5; padding:2px 6px; border-radius:4px; font-weight:600;'>stable</span></div>"
    is_positive = valeur > 0
    if inverser_couleur:
        color = "#e91e63" if is_positive else "#00b289"
        bg_color = "#fce4ec" if is_positive else "#e2f9f1"
    else:
        color = "#00b289" if is_positive else "#e91e63"
        bg_color = "#e2f9f1" if is_positive else "#fce4ec"
    fleche = "↑" if is_positive else "↓"
    val_str = f"+{str(round(valeur, 1)).replace('.', ',')}" if is_positive else str(round(valeur, 1)).replace('.', ',')
    return f"<div style='font-size:0.85em; color:#838ea5; margin-bottom:4px;'>Évol. {texte_cible} = <span style='background-color:{bg_color}; color:{color}; padding:2px 6px; border-radius:4px; font-weight:700;'>{fleche} {val_str}{unite}</span></div>"

def generate_evol_block(val_m1, val_n1, unite="", inverser_couleur=False, supplement=None, hide_m1=False):
    html_m1 = format_single_evol(val_m1, unite, "M-1", inverser_couleur) if not hide_m1 else ""
    html_n1 = format_single_evol(val_n1, unite, "N-1", inverser_couleur)
    html_sup = f"<div style='font-size:0.75em; color:#a0aabf; margin-top:6px;'>{supplement}</div>" if supplement else ""
    return f"{html_m1}{html_n1}{html_sup}"

def format_status_badge(niveau_alerte):
    if niveau_alerte == 2: return "<span style='background-color:#fce4ec; color:#e91e63; padding:2px 6px; border-radius:4px; font-size:0.7em; font-weight:bold;'>ALERTE</span>"
    if niveau_alerte == 1: return "<span style='background-color:#fff3cd; color:#ffb020; padding:2px 6px; border-radius:4px; font-size:0.7em; font-weight:bold;'>ATTENTION</span>"
    return ""

def create_progress_bar(label, value, total, color):
    pct = (value / total * 100) if total > 0 else 0
    return f"""
    <div style="display: flex; align-items: center; margin-bottom: 12px;">
        <div style="width: 80px; font-size: 0.85em; font-weight: 700; color: #0B1940;">{label}</div>
        <div style="flex-grow: 1; background-color: #f0f2f6; height: 8px; border-radius: 4px; margin: 0 15px;">
            <div style="width: {pct}%; background-color: {color}; height: 100%; border-radius: 4px;"></div>
        </div>
        <div style="width: 30px; text-align: right; font-weight: 900; font-size: 0.95em; color: #0B1940;">{int(value)}</div>
        <div style="width: 45px; text-align: right; font-size: 0.8em; color: #a0aabf;">{round(pct,1)}%</div>
    </div>
    """

# ==========================================
# 2. SIDEBAR
# ==========================================
with st.sidebar:
    st.header("📂 1. Chargement des DSN")
    fichiers = st.file_uploader("Upload des DSN (.edi)", type=['edi'], accept_multiple_files=True, key=f"dsn_uploader_{st.session_state.uploader_key}")
    
    st.header("📅 2. Période d'analyse")
    date_cible = None
    
    if fichiers:
        dates_dispos = set()
        for f in fichiers:
            d, _ = dash_complexe.analyser_nom_fichier(f.name)
            if d: dates_dispos.add(d)
        if dates_dispos:
            dates_triees = sorted(list(dates_dispos), reverse=True)
            options_dates = [d.strftime("%d/%m/%Y") for d in dates_triees]
            date_selectionnee = st.selectbox("Sélectionnez le mois cible :", options_dates)
            date_cible = datetime.strptime(date_selectionnee, "%d/%m/%Y")
            
    st.divider()
    if st.button("🔄 Nouvelle Analyse (Vider cache)", type="primary"):
        st.session_state.uploader_key += 1
        for k in ['df_indicateurs', 'nom_entreprise', 'last_files']:
            if k in st.session_state: del st.session_state[k]
        st.rerun()

    st.divider()
    st.header("🧭 3. Navigation")
    choix_vue = st.radio(
        "Vues disponibles :",
        ["🏠 Accueil", "👥 Effectifs", "💶 Masse salariale", "📋 Absentéisme", "🔄 Turnover",
         "⚖️ Égalité pro.", "🦺 Santé & Sécu", "🛡️ Couvertures", "📈 Évolutions", "🔔 Alertes"]
    )

# ==========================================
# 3. PIPELINE DE CALCULS EXPERT (PANDAS)
# ==========================================
if fichiers and date_cible:
    noms_fichiers = [f.name for f in fichiers]
    
    if 'df_indicateurs' not in st.session_state or st.session_state.get('last_files') != noms_fichiers:
        tous_kpis, tous_contrats, tous_salaires = [], [], []
        nom_entreprise = "Inconnue"
        
        with st.spinner("⚙️ Traitement complet des données DSN..."):
            with tempfile.TemporaryDirectory() as temp_dir:
                for f in fichiers:
                    d_file, s_file = dash_complexe.analyser_nom_fichier(f.name)
                    if d_file and s_file:
                        chem_temp = os.path.join(temp_dir, f.name)
                        with open(chem_temp, "wb") as f_out: f_out.write(f.getbuffer())
                        kb, ch, sh, infos_stat = dash_complexe.parser_fichier_dsn(chem_temp, d_file, s_file)
                        tous_kpis.append(kb)
                        tous_contrats.extend(ch)
                        tous_salaires.extend(sh)
                        if nom_entreprise == "Inconnue":
                            nom_entreprise = infos_stat.get('NOM_ENTREPRISE', dash_complexe.recuperer_nom_entreprise(s_file[:9]))

            df_base = pd.DataFrame(tous_kpis)
            
            if not df_base.empty:
                sirets_uniques = df_base['SIRET'].unique()
                if len(sirets_uniques) > 1:
                    st.error("❌ ERREUR : Plusieurs entreprises détectées. Veuillez charger les DSN d'un seul SIRET.")
                    st.stop()
                    
                siret_principal = sirets_uniques[0]
                df_c = pd.DataFrame(tous_contrats).drop_duplicates(subset=['SIRET', 'debut', 'statut'], keep='last')
                df_s = pd.DataFrame(tous_salaires)
                
                eff = np.where(df_base['NOMBRE_CONTRATS_ACTIFS'] > 0, df_base['NOMBRE_CONTRATS_ACTIFS'], 1)
                h_theo = eff * 151.67
                
                df_base['TAUX_FEMINISATION_POURCENT'] = np.round((df_base['NB_FEMMES'] / eff) * 100, 1)
                df_base['TAUX_CADRES_POURCENT'] = np.round((df_base['NB_CADRES'] / eff) * 100, 1)
                df_base['TAUX_NON_CADRES_POURCENT'] = np.round((df_base['NB_NON_CADRES'] / eff) * 100, 1)
                df_base['TAUX_AFFILIES_SANTE_POURCENT'] = np.round((df_base['NB_AFFILIES_SANTE'] / eff) * 100, 1)
                df_base['TAUX_AFFILIES_PREV_POURCENT'] = np.round((df_base['NB_AFFILIES_PREVOYANCE'] / eff) * 100, 1)
                df_base['CHARGES_PAT_KE'] = np.round(df_base['CHARGES_PAT_EUROS'] / 1000, 1)
                df_base['TAUX_FREQUENCE_AT'] = np.round((df_base['NB_SINI_AT'] * 1000000) / (h_theo * 12), 1)
                df_base['TAUX_GRAVITE_AT'] = np.round((df_base['J_AT'] * 1000) / h_theo, 2)
                
                kpis_complexes = []
                for _, row in df_base.iterrows():
                    d_c = row['DATE_ANALYSE']
                    an_c = d_c.year
                    d_12m = d_c - relativedelta(months=12)
                    c_s = df_c[df_c['SIRET'] == siret_principal]
                    s_s = df_s[(df_s['SIRET'] == siret_principal) & (df_s['ANNEE_MOIS'] == d_c)]
                    s_s_m12 = df_s[(df_s['SIRET'] == siret_principal) & (df_s['ANNEE_MOIS'] == d_12m)]
                    
                    # Turnover & Effectif
                    rec = len(c_s[(c_s['debut'] > d_12m) & (c_s['debut'] <= d_c)])
                    sorties = len(c_s[c_s['fin'].notna() & (c_s['fin'] > d_12m) & (c_s['fin'] <= d_c)])
                    act_deb = len(c_s[(c_s['debut'] <= d_12m) & ((c_s['fin'].isna()) | (c_s['fin'] > d_12m))])
                    act_fin = len(c_s[(c_s['debut'] <= d_c) & ((c_s['fin'].isna()) | (c_s['fin'] > d_c))])
                    eff_moy = (act_deb + act_fin) / 2
                    to = round((((rec + sorties) / 2) / eff_moy) * 100, 1) if eff_moy > 0 else 0.0
                    
                    # Âge
                    actifs = c_s[(c_s['debut'] <= d_c) & ((c_s['fin'].isna()) | (c_s['fin'] > d_c))].copy()
                    if not actifs.empty and 'date_naissance' in actifs.columns:
                        actifs['AGE'] = (d_c - pd.to_datetime(actifs['date_naissance'])).dt.days / 365.25
                        bins, labels = [0, 25, 35, 45, 55, 100], ['NB_MOINS_26', 'NB_26_35', 'NB_36_45', 'NB_46_55', 'NB_PLUS_55']
                        ages_counts = pd.cut(actifs['AGE'], bins=bins, labels=labels, right=True).value_counts().to_dict()
                    else:
                        ages_counts = {'NB_MOINS_26': 0, 'NB_26_35': 0, 'NB_36_45': 0, 'NB_46_55': 0, 'NB_PLUS_55': 0}

                    # Salaires globaux
                    sal_h = s_s[s_s['SEXE'] == '1']['MONTANT_BRUT'].mean()
                    sal_f = s_s[s_s['SEXE'] == '2']['MONTANT_BRUT'].mean()
                    sal_h = 0 if pd.isna(sal_h) else sal_h
                    sal_f = 0 if pd.isna(sal_f) else sal_f
                    ecart_hf = round(((sal_h - sal_f) / sal_h) * 100, 1) if sal_h > 0 else 0.0

                    # Salaires croisés H/F et Statut
                    sal_c_h = s_s[(s_s['STATUT'] == '01') & (s_s['SEXE'] == '1')]['MONTANT_BRUT'].mean()
                    sal_c_f = s_s[(s_s['STATUT'] == '01') & (s_s['SEXE'] == '2')]['MONTANT_BRUT'].mean()
                    sal_nc_h = s_s[(s_s['STATUT'] == '04') & (s_s['SEXE'] == '1')]['MONTANT_BRUT'].mean()
                    sal_nc_f = s_s[(s_s['STATUT'] == '04') & (s_s['SEXE'] == '2')]['MONTANT_BRUT'].mean()
                    
                    sal_c_h = 0 if pd.isna(sal_c_h) else int(round(sal_c_h))
                    sal_c_f = 0 if pd.isna(sal_c_f) else int(round(sal_c_f))
                    sal_nc_h = 0 if pd.isna(sal_nc_h) else int(round(sal_nc_h))
                    sal_nc_f = 0 if pd.isna(sal_nc_f) else int(round(sal_nc_f))
                    
                    ecart_c_hf = round(((sal_c_h - sal_c_f) / sal_c_h) * 100, 1) if sal_c_h > 0 else 0.0
                    ecart_nc_hf = round(((sal_nc_h - sal_nc_f) / sal_nc_h) * 100, 1) if sal_nc_h > 0 else 0.0

                    # Ecart d'augmentations (si la DSN le permet)
                    tx_augm_h, tx_augm_f, ecart_augm_pts = 0.0, 0.0, 0.0
                    if not s_s.empty and not s_s_m12.empty and 'NIR' in s_s.columns:
                        s_s_g = s_s.groupby(['NIR', 'SEXE'])['MONTANT_BRUT'].sum().reset_index()
                        s_s_m12_g = s_s_m12.groupby(['NIR', 'SEXE'])['MONTANT_BRUT'].sum().reset_index()
                        merged_s = s_s_g.merge(s_s_m12_g, on=['NIR', 'SEXE'], suffixes=('_N', '_N1'))
                        if not merged_s.empty:
                            merged_s['AUGMENTE'] = merged_s['MONTANT_BRUT_N'] > (merged_s['MONTANT_BRUT_N1'] * 1.01)
                            h_augm_rate = merged_s[merged_s['SEXE'] == '1']['AUGMENTE'].mean() * 100
                            f_augm_rate = merged_s[merged_s['SEXE'] == '2']['AUGMENTE'].mean() * 100
                            tx_augm_h = 0.0 if pd.isna(h_augm_rate) else round(h_augm_rate, 1)
                            tx_augm_f = 0.0 if pd.isna(f_augm_rate) else round(f_augm_rate, 1)
                            ecart_augm_pts = round(tx_augm_h - tx_augm_f, 1)

                    comp = {
                        'SIRET': siret_principal, 'DATE_ANALYSE': d_c,
                        'TAUX_TURNOVER_POURCENT': to, 'RECRUTEMENTS_12_MOIS': rec,
                        'DEMISSIONS': row.get('DEMISSIONS', 0), 'EFFECTIF_MOYEN': eff_moy,
                        'ECART_SALARIAL_HF_POURCENT': ecart_hf,
                        'SALAIRE_MOYEN_CADRE_HOMME': sal_c_h,
                        'SALAIRE_MOYEN_CADRE_FEMME': sal_c_f,
                        'ECART_SALARIAL_CADRES_HF_POURCENT': ecart_c_hf,
                        'SALAIRE_MOYEN_NON_CADRE_HOMME': sal_nc_h,
                        'SALAIRE_MOYEN_NON_CADRE_FEMME': sal_nc_f,
                        'ECART_SALARIAL_NON_CADRES_HF_POURCENT': ecart_nc_hf,
                        'ECART_AUGMENTATION_HF_PTS': ecart_augm_pts,
                    }
                    comp.update(ages_counts)

                    ms_3ans = df_s[(df_s['SIRET'] == siret_principal) & (df_s['ANNEE_MOIS'].dt.year.isin([an_c, an_c-1, an_c-2]))]
                    ms_grp = ms_3ans.groupby([ms_3ans['ANNEE_MOIS'].dt.year, 'STATUT'])['MONTANT_BRUT'].sum().to_dict()
                    for (annee, statut), montant in ms_grp.items():
                        nom_st = "CADRE" if statut in ('01', '02') else "NON_CADRE"
                        comp[f'MS_{nom_st}_{annee}_KE'] = comp.get(f'MS_{nom_st}_{annee}_KE', 0) + int(round(montant / 1000))

                    kpis_complexes.append(comp)

                df_fait = pd.merge(df_base, pd.DataFrame(kpis_complexes).fillna(0), on=['SIRET', 'DATE_ANALYSE'])
                
                # Management F
                df_fait['TAUX_FEMINISATION_MANAGEMENT_POURCENT'] = np.round(np.where(df_fait['NB_CADRES'] > 0, (df_fait['NB_FEMMES_CADRES'] / df_fait['NB_CADRES']) * 100, 0), 1)

                mets = ['NOMBRE_CONTRATS_ACTIFS', 'MASSE_SALARIALE_BRUTE_KE', 'SALAIRE_MOYEN_TOTAL',
                        'TAUX_ABSENTEISME_POURCENT', 'TAUX_TURNOVER_POURCENT', 'ANCIENNETE_MOYENNE_CDI_ANNEES',
                        'TAUX_FEMINISATION_POURCENT', 'CHARGES_PAT_KE', 'TAUX_AFFILIES_SANTE_POURCENT', 'TAUX_AFFILIES_PREV_POURCENT',
                        'NB_CDI', 'NB_CDD', 'NB_ALTERNANTS', 'NB_STAGIAIRES', 'NB_TEMPS_PLEIN', 'NB_TEMPS_PARTIEL', 'NB_CADRES', 'NB_NON_CADRES',
                        'TAUX_FEMINISATION_MANAGEMENT_POURCENT']
                
                df_m1 = df_fait[['SIRET', 'DATE_ANALYSE'] + mets].copy()
                df_m1['DATE_ANALYSE'] = df_m1['DATE_ANALYSE'] + MonthEnd(1)
                df_m1 = df_m1.rename(columns={m: f"{m}_M1" for m in mets})
                
                df_n1 = df_fait[['SIRET', 'DATE_ANALYSE'] + mets].copy()
                df_n1['DATE_ANALYSE'] = df_n1['DATE_ANALYSE'] + MonthEnd(12)
                df_n1 = df_n1.rename(columns={m: f"{m}_N1" for m in mets})
                
                df_fait = df_fait.merge(df_m1, on=['SIRET', 'DATE_ANALYSE'], how='left').merge(df_n1, on=['SIRET', 'DATE_ANALYSE'], how='left')
                
                def calc_croiss(act, prec): return np.where(prec > 0, ((act - prec) / prec * 100), np.nan)
                
                for e, suff in [('M_1', '_M1'), ('N_1', '_N1')]:
                    df_fait[f'EVOL_EFFECTIF_{e}_ABS'] = df_fait['NOMBRE_CONTRATS_ACTIFS'] - df_fait[f'NOMBRE_CONTRATS_ACTIFS{suff}']
                    df_fait[f'EVOL_CDI_{e}_ABS'] = df_fait['NB_CDI'] - df_fait[f'NB_CDI{suff}']
                    df_fait[f'EVOL_CDD_{e}_ABS'] = df_fait['NB_CDD'] - df_fait[f'NB_CDD{suff}']
                    df_fait[f'EVOL_ALT_{e}_ABS'] = df_fait['NB_ALTERNANTS'] - df_fait[f'NB_ALTERNANTS{suff}']
                    df_fait[f'EVOL_CADRES_{e}_ABS'] = df_fait['NB_CADRES'] - df_fait[f'NB_CADRES{suff}']
                    df_fait[f'EVOL_NON_CADRES_{e}_ABS'] = df_fait['NB_NON_CADRES'] - df_fait[f'NB_NON_CADRES{suff}']
                    df_fait[f'EVOL_MSB_{e}_POURCENT'] = calc_croiss(df_fait['MASSE_SALARIALE_BRUTE_KE'], df_fait[f'MASSE_SALARIALE_BRUTE_KE{suff}']).round(1)
                    df_fait[f'EVOL_SALAIRE_MOYEN_{e}_POURCENT'] = calc_croiss(df_fait['SALAIRE_MOYEN_TOTAL'], df_fait[f'SALAIRE_MOYEN_TOTAL{suff}']).round(1)
                    df_fait[f'EVOL_ABSENTEISME_{e}_PTS'] = (df_fait['TAUX_ABSENTEISME_POURCENT'] - df_fait[f'TAUX_ABSENTEISME_POURCENT{suff}']).round(1)
                    df_fait[f'EVOL_TURNOVER_{e}_PTS'] = (df_fait['TAUX_TURNOVER_POURCENT'] - df_fait[f'TAUX_TURNOVER_POURCENT{suff}']).round(1)
                    df_fait[f'EVOL_ANCIENNETE_{e}_ABS'] = (df_fait['ANCIENNETE_MOYENNE_CDI_ANNEES'] - df_fait[f'ANCIENNETE_MOYENNE_CDI_ANNEES{suff}']).round(1)
                    df_fait[f'EVOL_FEMINISATION_{e}_PTS'] = (df_fait['TAUX_FEMINISATION_POURCENT'] - df_fait[f'TAUX_FEMINISATION_POURCENT{suff}']).round(1)
                    df_fait[f'EVOL_FEMINISATION_MANAGEMENT_{e}_PTS'] = (df_fait['TAUX_FEMINISATION_MANAGEMENT_POURCENT'] - df_fait[f'TAUX_FEMINISATION_MANAGEMENT_POURCENT{suff}']).round(1)
                    df_fait[f'EVOL_SANTE_{e}_PTS'] = (df_fait['TAUX_AFFILIES_SANTE_POURCENT'] - df_fait[f'TAUX_AFFILIES_SANTE_POURCENT{suff}']).round(1)
                    df_fait[f'EVOL_PREVOYANCE_{e}_PTS'] = (df_fait['TAUX_AFFILIES_PREV_POURCENT'] - df_fait[f'TAUX_AFFILIES_PREV_POURCENT{suff}']).round(1)
                    df_fait[f'EVOL_CHARGES_PAT_{e}_POURCENT'] = calc_croiss(df_fait['CHARGES_PAT_KE'], df_fait[f'CHARGES_PAT_KE{suff}']).round(1)

                st.session_state['df_indicateurs'] = df_fait
                st.session_state['nom_entreprise'] = nom_entreprise
                st.session_state['last_files'] = noms_fichiers

# ==========================================
# 4. AFFICHAGE DES VUES
# ==========================================
if 'df_indicateurs' in st.session_state and not st.session_state['df_indicateurs'].empty:
    df = st.session_state['df_indicateurs']
    row_curr = df[df['DATE_ANALYSE'] == pd.to_datetime(date_cible)]
    
    if not row_curr.empty:
        data = row_curr.iloc[0].copy()
        
        # --- HEADER COMMUN ---
        col_titre, col_badges = st.columns([2, 1])
        with col_titre:
            st.markdown(f"<h3 style='color:#0B1940; margin-top:0;'>🏢 {st.session_state['nom_entreprise']}</h3>", unsafe_allow_html=True)
        with col_badges:
            st.markdown(f"""
            <div style='text-align: right; margin-top:10px;'>
                <span style='background-color:#e2f9f1; color:#00b289; padding:6px 12px; border-radius:20px; font-weight:bold; font-size:0.8em; margin-right:10px;'>🟢 DSN {date_cible.strftime('%B %Y')} importée</span>
            </div>
            """, unsafe_allow_html=True)

        # ==========================================
        # VUE : 🏠 ACCUEIL
        # ==========================================
        if choix_vue == "🏠 Accueil":
            
            niv_abs = evaluer_kpi("absenteisme", data.get('TAUX_ABSENTEISME_POURCENT', 0))
            niv_to = evaluer_kpi("turnover", data.get('TAUX_TURNOVER_POURCENT', 0))
            niv_prev = evaluer_kpi("prevoyance", data.get('TAUX_AFFILIES_PREV_POURCENT', 100))
            niv_sante = evaluer_kpi("sante", data.get('TAUX_AFFILIES_SANTE_POURCENT', 100))
            nb_manquants = int(data.get('NOMBRE_CONTRATS_ACTIFS', 0) - data.get('NB_AFFILIES_PREVOYANCE', 0))
            
            alertes_banniere = []
            if niv_prev > 0: alertes_banniere.append(f"Prévoyance Incomplète ({nb_manquants} sal.)")
            if niv_abs > 0: alertes_banniere.append(f"Absentéisme {str(data.get('TAUX_ABSENTEISME_POURCENT', 0)).replace('.',',')}% > seuil")
            if niv_to > 0: alertes_banniere.append(f"Turnover {str(data.get('TAUX_TURNOVER_POURCENT', 0)).replace('.',',')}% > seuil")
            
            if alertes_banniere:
                texte_banniere = f"🔴 **{len(alertes_banniere)} alertes détectées :** " + " · ".join(alertes_banniere)
                st.markdown(f"<div style='background-color:#e91e63; color:white; padding:12px 20px; border-radius:5px; font-weight:bold; margin-bottom:25px;'>{texte_banniere}</div>", unsafe_allow_html=True)

            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| KPI SYNTHÈSE — MOIS EN COURS</p>", unsafe_allow_html=True)
            
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_EFFECTIF_M_1_ABS', np.nan), ' sal.', 'M-1')}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_EFFECTIF_N_1_ABS', np.nan), ' sal.', False, supplement=sup, hide_m1=True)
                st.markdown(create_card("EFFECTIF TOTAL", f"{int(data.get('NOMBRE_CONTRATS_ACTIFS', 0))}", "salariés déclarés", "#0B1940", bottom), unsafe_allow_html=True)
            with c2:
                ms_annu = f"Annualisé : {round((data.get('MASSE_SALARIALE_BRUTE_KE', 0) * 12) / 1000, 2)} M€"
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_MSB_M_1_POURCENT', np.nan), '%', 'M-1')}</div><div style='color:#838ea5; font-size:0.75em; margin-top:5px;'>{ms_annu}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_MSB_N_1_POURCENT', np.nan), '%', False, supplement=sup, hide_m1=True)
                st.markdown(create_card("MASSE SALARIALE BRUTE", f"{int(data.get('MASSE_SALARIALE_BRUTE_KE', 0))}k€", "mensuel brut", "#e91e63", bottom, has_dot=True), unsafe_allow_html=True)
            with c3:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_ABSENTEISME_M_1_PTS', np.nan), ' pts', 'M-1', True)}</div><div style='display:flex; justify-content:space-between; margin-top:5px;'><span style='color:#838ea5; font-size:0.75em;'>Secteur : 3,8%</span> {format_status_badge(niv_abs)}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_ABSENTEISME_N_1_PTS', np.nan), ' pts', True, supplement=sup, hide_m1=True)
                couleur_top = "#e91e63" if niv_abs == 2 else ("#ffb020" if niv_abs == 1 else "#0B1940")
                st.markdown(create_card("ABSENTÉISME", f"{str(data.get('TAUX_ABSENTEISME_POURCENT', 0)).replace('.',',')}%", "taux global", couleur_top, bottom, has_dot=(niv_abs>0)), unsafe_allow_html=True)
            with c4:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_TURNOVER_M_1_PTS', np.nan), ' pts', 'M-1', True)}</div><div style='display:flex; justify-content:space-between; margin-top:5px;'><span style='color:#838ea5; font-size:0.75em;'>Secteur : 12%</span> {format_status_badge(niv_to)}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_TURNOVER_N_1_PTS', np.nan), ' pts', True, supplement=sup, hide_m1=True)
                couleur_top = "#e91e63" if niv_to == 2 else ("#ffb020" if niv_to == 1 else "#0B1940")
                st.markdown(create_card("TURNOVER", f"{str(data.get('TAUX_TURNOVER_POURCENT', 0)).replace('.',',')}%", "12 mois glissants", couleur_top, bottom, has_dot=(niv_to>0)), unsafe_allow_html=True)
            with c5:
                val_prev = data.get('TAUX_AFFILIES_PREV_POURCENT', 0)
                badge_p = "<span style='background-color:#fff3cd; color:#ffb020; padding:2px 8px; border-radius:4px; font-size:0.75em; font-weight:700;'>⚠ Partiel</span>" if 0 < val_prev < 100 else format_single_evol(data.get('EVOL_PREVOYANCE_N_1_PTS', np.nan), ' pts', 'N-1')
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_PREVOYANCE_M_1_PTS', np.nan), ' pts', 'M-1')}</div><div style='display:flex; justify-content:space-between; margin-top:5px;'><span style='color:#838ea5; font-size:0.75em;'>Risque URSSAF</span> {format_status_badge(niv_prev)}</div>"
                bottom = f"{badge_p}{sup}"
                couleur_top = "#e91e63" if niv_prev == 2 else ("#ffb020" if val_prev < 100 else "#0B1940")
                st.markdown(create_card("COUVERTURE PRÉVOYANCE", f"{str(val_prev).replace('.0','')}%", f"{nb_manquants} salariés non-affiliés", couleur_top, bottom, has_dot=(niv_prev>0)), unsafe_allow_html=True)

            c6, c7, c8, c9, c10 = st.columns(5)
            with c6:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_SALAIRE_MOYEN_M_1_POURCENT', np.nan), '%', 'M-1')}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_SALAIRE_MOYEN_N_1_POURCENT', np.nan), '%', False, supplement=sup, hide_m1=True)
                sm_str = f"{int(data.get('SALAIRE_MOYEN_TOTAL', 0)):,} €".replace(",", " ")
                st.markdown(create_card("SALAIRE MOYEN BRUT", sm_str, "tous salariés", "#00b289", bottom), unsafe_allow_html=True)
            with c7:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_ANCIENNETE_M_1_ABS', np.nan), ' ans', 'M-1')}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_ANCIENNETE_N_1_ABS', np.nan), ' ans', False, supplement=sup, hide_m1=True)
                st.markdown(create_card("ANCIENNETÉ MOY. CDI", f"{str(data.get('ANCIENNETE_MOYENNE_CDI_ANNEES', 0)).replace('.',',')}", "années", "#3b82f6", bottom), unsafe_allow_html=True)
            with c8:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_FEMINISATION_M_1_PTS', np.nan), ' pts', 'M-1')}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_FEMINISATION_N_1_PTS', np.nan), ' pts', False, supplement=sup, hide_m1=True)
                st.markdown(create_card("TAUX FÉMINISATION", f"{str(data.get('TAUX_FEMINISATION_POURCENT', 0)).replace('.',',')}%", "part femmes", "#0B1940", bottom), unsafe_allow_html=True)
            with c9:
                val_sante = data.get('TAUX_AFFILIES_SANTE_POURCENT', 0)
                badge_s = "<span style='background-color:#e2f9f1; color:#00b289; padding:2px 8px; border-radius:4px; font-size:0.75em; font-weight:700;'>✓ Conforme</span>" if val_sante == 100 else format_single_evol(data.get('EVOL_SANTE_N_1_PTS', np.nan), ' pts', 'N-1')
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_SANTE_M_1_PTS', np.nan), ' pts', 'M-1')}</div>"
                bottom = f"{badge_s}{sup}"
                couleur_top = "#e91e63" if niv_sante == 2 else ("#00b289" if niv_sante == 0 else "#ffb020")
                st.markdown(create_card("COUVERTURE SANTÉ", f"{str(val_sante).replace('.0','')}%", "mutuelle collective", couleur_top, bottom), unsafe_allow_html=True)
            with c10:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_CHARGES_PAT_M_1_POURCENT', np.nan), '%', 'M-1')}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_CHARGES_PAT_N_1_POURCENT', np.nan), '%', False, supplement=sup, hide_m1=True)
                ch_str = f"{str(data.get('CHARGES_PAT_KE', 0)).replace('.',',')}k€"
                st.markdown(create_card("CHARGES PATRONALES", ch_str, "mensuel", "#0B1940", bottom), unsafe_allow_html=True)

            st.markdown("<br><p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| ALERTES ACTIVES</p>", unsafe_allow_html=True)
            if not alertes_banniere:
                st.info("Aucune alerte critique pour la période sélectionnée.")
            else:
                if niv_prev > 0:
                    couleur_bande, mot_badge = ("#e91e63", "URGENT") if niv_prev == 2 else ("#ffb020", "ATTENTION")
                    st.markdown(f"<div style='background-color:#f8f9fa; border-left:4px solid {couleur_bande}; padding:15px; margin-bottom:10px;'><span style='background-color:{couleur_bande}; color:white; padding:3px 8px; border-radius:3px; font-size:0.8em; font-weight:bold; margin-right:10px;'>{mot_badge}</span> <b>Prévoyance incomplète — {nb_manquants} salariés non-couverts</b><br><span style='color:grey; font-size:0.9em; margin-left:75px;'>Détecté via S21.G00.81. Risque de redressement URSSAF si CCN impose l'adhésion obligatoire.</span></div>", unsafe_allow_html=True)
                if niv_abs > 0:
                    couleur_bande, mot_badge = ("#e91e63", "URGENT") if niv_abs == 2 else ("#ffb020", "ATTENTION")
                    evol_abs_m1 = data.get('EVOL_ABSENTEISME_M_1_PTS', np.nan)
                    txt_evol = "Pas d'historique M-1" if pd.isna(evol_abs_m1) else f"{'+' if evol_abs_m1 > 0 else ''}{str(round(evol_abs_m1,1)).replace('.',',')} pts vs M-1"
                    st.markdown(f"<div style='background-color:#f8f9fa; border-left:4px solid {couleur_bande}; padding:15px; margin-bottom:10px;'><span style='background-color:{couleur_bande}; color:white; padding:3px 8px; border-radius:3px; font-size:0.8em; font-weight:bold; margin-right:10px;'>{mot_badge}</span> <b>Absentéisme {str(data['TAUX_ABSENTEISME_POURCENT']).replace('.',',')}% — seuil dépassé ({txt_evol})</b><br><span style='color:grey; font-size:0.9em; margin-left:75px;'>Impact sur la production. Analyser les motifs (Maladie vs AT).</span></div>", unsafe_allow_html=True)
                if niv_to > 0:
                    couleur_bande, mot_badge = ("#e91e63", "URGENT") if niv_to == 2 else ("#ffb020", "ATTENTION")
                    st.markdown(f"<div style='background-color:#f8f9fa; border-left:4px solid {couleur_bande}; padding:15px; margin-bottom:10px;'><span style='background-color:{couleur_bande}; color:white; padding:3px 8px; border-radius:3px; font-size:0.8em; font-weight:bold; margin-right:10px;'>{mot_badge}</span> <b>Turn-over {str(data['TAUX_TURNOVER_POURCENT']).replace('.',',')}% — au-dessus du seuil sectoriel (12%)</b><br><span style='color:grey; font-size:0.9em; margin-left:75px;'>{data.get('RECRUTEMENTS_12_MOIS', 0)} recrutements sur 12 mois. Analyser la rétention.</span></div>", unsafe_allow_html=True)

        # ==========================================
        # VUE : 👥 EFFECTIFS
        # ==========================================
        elif choix_vue == "👥 Effectifs":
            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| EFFECTIFS — DONNÉES DSN MOIS EN COURS</p>", unsafe_allow_html=True)
            
            c1, c2, c3, c4, c5 = st.columns(5)
            eff_tot = int(data.get('NOMBRE_CONTRATS_ACTIFS', 0))
            
            with c1:
                sup = f"<div style='margin-top:8px;'>{format_single_evol(data.get('EVOL_EFFECTIF_M_1_ABS', np.nan), ' sal.', 'M-1')}</div>"
                bottom = generate_evol_block(np.nan, data.get('EVOL_EFFECTIF_N_1_ABS', np.nan), ' sal.', False, supplement=sup, hide_m1=True)
                st.markdown(create_card("EFFECTIF TOTAL", f"{eff_tot}", "salariés déclarés DSN", "#0B1940", bottom), unsafe_allow_html=True)
            with c2:
                st.markdown(create_card("EFFECTIF MOYEN", f"{str(data.get('EFFECTIF_MOYEN', 0)).replace('.',',')}", "12 mois glissants", "#0B1940", "<span style='font-size:0.75em; color:grey;'>Calcul ETP mensuel</span>"), unsafe_allow_html=True)
            with c3:
                nb_cdi = int(data.get('NB_CDI', 0))
                pct_cdi = round((nb_cdi / eff_tot * 100), 1) if eff_tot > 0 else 0
                badge = format_single_evol(data.get('EVOL_CDI_N_1_ABS', np.nan), ' sal.', 'N-1')
                st.markdown(create_card("EFFECTIF CDI", f"{nb_cdi}", f"{str(pct_cdi).replace('.',',')}% de l'effectif", "#00b289", badge), unsafe_allow_html=True)
            with c4:
                nb_cdd = int(data.get('NB_CDD', 0))
                pct_cdd = round((nb_cdd / eff_tot * 100), 1) if eff_tot > 0 else 0
                badge = format_single_evol(data.get('EVOL_CDD_M_1_ABS', np.nan), ' sal.', 'M-1')
                st.markdown(create_card("EFFECTIF CDD", f"{nb_cdd}", f"{str(pct_cdd).replace('.',',')}% de l'effectif", "#3b82f6", badge), unsafe_allow_html=True)
            with c5:
                nb_alt = int(data.get('NB_ALTERNANTS', 0))
                pct_alt = round((nb_alt / eff_tot * 100), 1) if eff_tot > 0 else 0
                badge = format_single_evol(data.get('EVOL_ALT_N_1_ABS', np.nan), ' sal.', 'N-1')
                st.markdown(create_card("ALTERNANTS", f"{nb_alt}", f"{str(pct_alt).replace('.',',')}% de l'effectif", "#e91e63", badge), unsafe_allow_html=True)

            c6, c7, c8, c9 = st.columns([1, 1, 1, 2])
            with c6:
                nb_stag = int(data.get('NB_STAGIAIRES', 0))
                badge = format_single_evol(np.nan, '', 'M-1')
                st.markdown(create_card("STAGIAIRES", f"{nb_stag}", "convention > 2 mois", "#0B1940", badge), unsafe_allow_html=True)
            with c7:
                nb_tp = int(data.get('NB_TEMPS_PLEIN', 0))
                pct_tp = round((nb_tp / eff_tot * 100), 1) if eff_tot > 0 else 0
                badge = format_single_evol(np.nan, '', 'M-1')
                st.markdown(create_card("TEMPS PLEIN", f"{nb_tp}", f"{str(pct_tp).replace('.',',')}% de l'effectif", "#0B1940", badge), unsafe_allow_html=True)
            with c8:
                nb_tpa = int(data.get('NB_TEMPS_PARTIEL', 0))
                pct_tpa = str(data.get('TAUX_TEMPS_PARTIEL_POURCENT', 0)).replace('.',',')
                badge = format_single_evol(np.nan, '', 'M-1')
                st.markdown(create_card("TEMPS PARTIEL", f"{nb_tpa}", f"{pct_tpa}% de l'effectif", "#0B1940", badge), unsafe_allow_html=True)
            with c9:
                nb_f_val = int(data.get('NB_FEMMES', 0))
                nb_h_val = int(data.get('NB_HOMMES', 0))
                pct_fem = str(data.get('TAUX_FEMINISATION_POURCENT', 0)).replace('.',',')
                badge = format_single_evol(data.get('EVOL_FEMINISATION_M_1_PTS', np.nan), ' pts', 'M-1')
                st.markdown(create_card("TAUX FÉMINISATION", f"{pct_fem}%", f"{nb_f_val} femmes / {eff_tot} sal.", "#00b289", badge), unsafe_allow_html=True)

            col_pop, col_age = st.columns([1.3, 1])
            
            with col_pop:
                nb_c = int(data.get('NB_CADRES', 0))
                tx_c = str(data.get('TAUX_CADRES_POURCENT', 0)).replace('.',',')
                sm_c = f"{int(data.get('SALAIRE_MOYEN_CADRE', 0)):,} €".replace(",", " ")
                ev_c = format_single_evol(data.get('EVOL_CADRES_N_1_ABS', np.nan), ' sal.', 'N-1')
                nb_nc = int(data.get('NB_NON_CADRES', 0))
                tx_nc = str(data.get('TAUX_NON_CADRES_POURCENT', 0)).replace('.',',')
                sm_nc = f"{int(data.get('SALAIRE_MOYEN_NON_CADRE', 0)):,} €".replace(",", " ")
                ev_nc = format_single_evol(data.get('EVOL_NON_CADRES_N_1_ABS', np.nan), ' sal.', 'N-1')
                sm_tot = f"{int(data.get('SALAIRE_MOYEN_TOTAL', 0)):,} €".replace(",", " ")
                ev_tot = format_single_evol(data.get('EVOL_EFFECTIF_N_1_ABS', np.nan), ' sal.', 'N-1')

                html_population = f"""
                <div style="background-color: white; border: 1px solid #e0e0e0; border-radius: 5px; padding: 20px; min-height: 350px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h4 style="margin:0; color:#0B1940;">Répartition par population</h4>
                        <span style="background-color:#fce4ec; color:#e91e63; font-size:0.7em; padding:2px 8px; border-radius:10px; font-weight:bold;">DSN S21.G00.40</span>
                    </div>
                    <table style="width: 100%; text-align: left; font-size: 0.9em; border-collapse: collapse;">
                        <tr style="color: #a0aabf; border-bottom: 1px solid #f0f2f6; text-transform: uppercase; font-size: 0.75em;">
                            <th style="padding-bottom: 10px;">Population</th>
                            <th style="padding-bottom: 10px;">Nombre</th>
                            <th style="padding-bottom: 10px;">Taux</th>
                            <th style="padding-bottom: 10px;">Sal. Moyen Brut</th>
                            <th style="padding-bottom: 10px;">Variation N-1</th>
                        </tr>
                        <tr style="border-bottom: 1px solid #f0f2f6;">
                            <td style="padding: 15px 0;"><b><span style="color:#0B1940;">■</span> Cadres</b><br><span style="color:grey; font-size:0.8em;">Statut 01, 02</span></td>
                            <td style="font-weight: 900; font-size: 1.2em; color: #0B1940;">{nb_c}</td>
                            <td style="font-weight: bold; border-bottom: 3px solid #0B1940; display: inline-block; padding-bottom: 2px; margin-top: 15px;">{tx_c}%</td>
                            <td style="font-weight: bold; color: #0B1940;">{sm_c}</td>
                            <td>{ev_c}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f0f2f6;">
                            <td style="padding: 15px 0;"><b><span style="color:#e91e63;">■</span> Non-cadres</b><br><span style="color:grey; font-size:0.8em;">Statut 04 (ETAM)</span></td>
                            <td style="font-weight: 900; font-size: 1.2em; color: #e91e63;">{nb_nc}</td>
                            <td style="font-weight: bold; border-bottom: 3px solid #e91e63; display: inline-block; padding-bottom: 2px; margin-top: 15px; color: #e91e63;">{tx_nc}%</td>
                            <td style="font-weight: bold; color: #0B1940;">{sm_nc}</td>
                            <td>{ev_nc}</td>
                        </tr>
                        <tr style="background-color: #0B1940; color: white;">
                            <td style="padding: 15px 10px; font-weight: bold; border-radius: 5px 0 0 5px;">Total</td>
                            <td style="font-weight: 900; font-size: 1.2em; color: #e91e63;">{eff_tot}</td>
                            <td style="font-weight: bold;">100%</td>
                            <td style="font-weight: bold; color: #e91e63;">{sm_tot}</td>
                            <td style="border-radius: 0 5px 5px 0;">{ev_tot}</td>
                        </tr>
                    </table>
                </div>
                """
                st.markdown(html_population, unsafe_allow_html=True)

            with col_age:
                tot_age = (data.get("NB_MOINS_26", 0) + data.get("NB_26_35", 0) +
                           data.get("NB_36_45", 0) + data.get("NB_46_55", 0) + data.get("NB_PLUS_55", 0))

                def _bar(label, value, color):
                    pct = (value / tot_age * 100) if tot_age > 0 else 0
                    return (
                        f'<div style="display:flex;align-items:center;margin-bottom:12px;">'
                        f'<div style="width:80px;font-size:0.85em;font-weight:700;color:#0B1940;">{label}</div>'
                        f'<div style="flex-grow:1;background-color:#f0f2f6;height:8px;border-radius:4px;margin:0 15px;">'
                        f'<div style="width:{pct:.1f}%;background-color:{color};height:100%;border-radius:4px;"></div>'
                        f'</div>'
                        f'<div style="width:30px;text-align:right;font-weight:900;font-size:0.95em;color:#0B1940;">{int(value)}</div>'
                        f'<div style="width:45px;text-align:right;font-size:0.8em;color:#a0aabf;">{pct:.1f}%</div>'
                        f'</div>'
                    )

                barres_age = (
                    _bar("&lt; 26 ans", data.get("NB_MOINS_26", 0), "#3b82f6") +
                    _bar("26-35 ans",   data.get("NB_26_35", 0),    "#e91e63") +
                    _bar("36-45 ans",   data.get("NB_36_45", 0),    "#0B1940") +
                    _bar("46-55 ans",   data.get("NB_46_55", 0),    "#ffb020") +
                    _bar("&gt; 55 ans", data.get("NB_PLUS_55", 0),  "#a0aabf")
                )

                html_age = (
                    '<div style="background-color:white;border:1px solid #e0e0e0;border-top:3px solid #0B1940;'
                    'border-radius:5px;padding:20px;min-height:350px;">'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;">'
                    '<h4 style="margin:0;color:#0B1940;">Répartition par âge</h4>'
                    '<span style="background-color:#fce4ec;color:#e91e63;font-size:0.7em;padding:2px 8px;'
                    'border-radius:10px;font-weight:bold;">TRANCHES 10 ANS</span>'
                    '</div>'
                    + barres_age +
                    '<div style="margin-top:16px;background-color:#e2f9f1;border-left:4px solid #00b289;'
                    'padding:10px;border-radius:4px;font-size:0.8em;color:#0B1940;">'
                    '<span style="color:#00b289;font-weight:bold;">Note RGPD :</span>'
                    ' tranches de 10 ans minimum — aucune date de naissance stockée.'
                    '</div>'
                    '</div>'
                )
                st.markdown(html_age, unsafe_allow_html=True)

            col_anc, col_comp = st.columns(2)
            
            with col_anc:
                anc_moy = str(data.get('ANCIENNETE_MOYENNE_CDI_ANNEES', 0)).replace('.',',')
                anc_med = str(data.get('ANCIENNETE_MEDIANE_CDI_ANNEES', 0)).replace('.',',')
                anc_dep = str(data.get('ANCIENNETE_MOY_DEPART_ANNEES', 0)).replace('.',',')
                st.markdown(f"""
                <div style="background-color: white; border: 1px solid #e0e0e0; border-radius: 5px; padding: 20px; height: 180px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h4 style="margin:0; color:#0B1940;">Ancienneté</h4>
                        <span style="background-color:#fce4ec; color:#e91e63; font-size:0.7em; padding:2px 8px; border-radius:10px; font-weight:bold;">CDI UNIQUEMENT</span>
                    </div>
                    <div style="display: flex; justify-content: space-around; text-align: center;">
                        <div style="border-right: 1px solid #f0f2f6; padding-right: 20px; width: 33%;">
                            <div style="color: #a0aabf; font-size: 0.7em; text-transform: uppercase; font-weight: bold;">MOYENNE</div>
                            <div style="font-size: 2.2rem; font-weight: 900; color: #0B1940; line-height: 1.2;">{anc_moy}</div>
                            <div style="color: #a0aabf; font-size: 0.8em;">années</div>
                        </div>
                        <div style="border-right: 1px solid #f0f2f6; padding: 0 20px; width: 33%;">
                            <div style="color: #a0aabf; font-size: 0.7em; text-transform: uppercase; font-weight: bold;">MÉDIANE</div>
                            <div style="font-size: 2.2rem; font-weight: 900; color: #e91e63; line-height: 1.2;">{anc_med}</div>
                            <div style="color: #a0aabf; font-size: 0.8em;">années</div>
                        </div>
                        <div style="padding-left: 20px; width: 33%;">
                            <div style="color: #a0aabf; font-size: 0.7em; text-transform: uppercase; font-weight: bold;">MOY. DÉPARTS</div>
                            <div style="font-size: 2.2rem; font-weight: 900; color: #ffb020; line-height: 1.2;">{anc_dep}</div>
                            <div style="color: #a0aabf; font-size: 0.8em;">années</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with col_comp:
                nb_c = int(data.get('NB_CADRES', 0))
                nb_nc = int(data.get('NB_NON_CADRES', 0))
                nb_f_val = int(data.get('NB_FEMMES', 0))
                nb_tpa = int(data.get('NB_TEMPS_PARTIEL', 0))

                def _bar_comp(label, value, color):
                    pct = (value / eff_tot * 100) if eff_tot > 0 else 0
                    return (
                        f'<div style="display:flex;align-items:center;margin-bottom:12px;">'
                        f'<div style="width:90px;font-size:0.85em;font-weight:700;color:#0B1940;">{label}</div>'
                        f'<div style="flex-grow:1;background-color:#f0f2f6;height:8px;border-radius:4px;margin:0 15px;">'
                        f'<div style="width:{pct:.1f}%;background-color:{color};height:100%;border-radius:4px;"></div>'
                        f'</div>'
                        f'<div style="width:30px;text-align:right;font-weight:900;font-size:0.95em;color:#0B1940;">{int(value)}</div>'
                        f'<div style="width:45px;text-align:right;font-size:0.8em;color:#a0aabf;">{pct:.1f}%</div>'
                        f'</div>'
                    )

                barres_comp = (
                    _bar_comp("Cadres",       nb_c,     "#0B1940") +
                    _bar_comp("Non-cadres",   nb_nc,    "#e91e63") +
                    _bar_comp("Féminisation", nb_f_val, "#8a2be2") +
                    _bar_comp("Tps partiel",  nb_tpa,   "#ffb020")
                )

                html_comp = (
                    '<div style="background-color:white;border:1px solid #e0e0e0;border-top:3px solid #0B1940;'
                    'border-radius:5px;padding:20px;min-height:220px;">'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">'
                    '<h4 style="margin:0;color:#0B1940;">Composition</h4>'
                    '<span style="background-color:#fce4ec;color:#e91e63;font-size:0.7em;padding:2px 8px;'
                    'border-radius:10px;font-weight:bold;">RATIOS CLÉS</span>'
                    '</div>'
                    + barres_comp +
                    '</div>'
                )
                st.markdown(html_comp, unsafe_allow_html=True)

        # ==========================================
        # VUE : 💶 MASSE SALARIALE
        # ==========================================
        elif choix_vue == "💶 Masse salariale":
            an = date_cible.year

            msb_ke      = data.get('MASSE_SALARIALE_BRUTE_KE', 0)
            charges_ke  = data.get('CHARGES_PAT_KE', 0)
            ms_ch_ke    = data.get('MS_CHARGEE_KE', 0)
            primes_e    = data.get('MS_PRIMES_EUROS', 0)
            part_var    = data.get('PART_VARIABLE_POURCENT', 0)
            eff_tot     = int(data.get('NOMBRE_CONTRATS_ACTIFS', 1) or 1)
            sm_c        = int(data.get('SALAIRE_MOYEN_CADRE', 0))
            sm_nc       = int(data.get('SALAIRE_MOYEN_NON_CADRE', 0))
            sm_tot      = int(data.get('SALAIRE_MOYEN_TOTAL', 0))
            sm_h        = int(data.get('SALAIRE_MOYEN_HOMME', 0))
            sm_f        = int(data.get('SALAIRE_MOYEN_FEMME', 0))
            med_c       = int(data.get('SALAIRE_MEDIAN_CADRE', 0))
            med_nc      = int(data.get('SALAIRE_MEDIAN_NON_CADRE', 0))
            med_tot     = int(data.get('SALAIRE_MEDIAN_TOTAL', 0))
            med_h       = int(data.get('SALAIRE_MEDIAN_HOMME', 0))
            med_f       = int(data.get('SALAIRE_MEDIAN_FEMME', 0))
            ecart_hf    = data.get('ECART_SALARIAL_HF_POURCENT', 0)
            nb_c        = int(data.get('NB_CADRES', 0))
            nb_nc       = int(data.get('NB_NON_CADRES', 0))
            ms_annu_me  = round((msb_ke * 12) / 1000, 2)
            msc_annu_me = round((ms_ch_ke * 12) / 1000, 2)
            cout_sal_moy = int(round((ms_ch_ke * 1000) / eff_tot)) if eff_tot > 0 else 0

            ms_c_n   = data.get('MS_CADRE_N_KE', 0)
            ms_nc_n  = data.get('MS_NON_CADRE_N_KE', 0)
            ms_c_n1  = data.get('MS_CADRE_N_1_KE', 0)
            ms_nc_n1 = data.get('MS_NON_CADRE_N_1_KE', 0)
            ms_c_n2  = data.get('MS_CADRE_N_2_KE', 0)
            ms_nc_n2 = data.get('MS_NON_CADRE_N_2_KE', 0)
            tot_n    = ms_c_n  + ms_nc_n
            tot_n1   = ms_c_n1 + ms_nc_n1
            tot_n2   = ms_c_n2 + ms_nc_n2

            evol_msb_n1     = data.get('EVOL_MSB_N_1_POURCENT', np.nan)
            evol_charges_n1 = data.get('EVOL_CHARGES_PAT_N_1_POURCENT', np.nan)
            evol_sm_n1      = data.get('EVOL_SALAIRE_MOYEN_N_1_POURCENT', np.nan)

            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| MASSE SALARIALE — DÉTAIL MENSUEL ET ANNUALISÉ</p>", unsafe_allow_html=True)

            # ── LIGNE 1 : 5 cartes ──
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                taux_eff = round((charges_ke / msb_ke * 100), 1) if msb_ke > 0 else 0
                bottom = generate_evol_block(np.nan, evol_msb_n1, '%', False,
                    supplement=f"<span style='color:#a0aabf;font-size:0.75em;'>Annualisé : {ms_annu_me} M€</span>",
                    hide_m1=True)
                st.markdown(create_card("MS BRUTE MENSUELLE", f"{int(msb_ke)}k€", "brut déclaré", "#e91e63", bottom), unsafe_allow_html=True)
            with c2:
                taux_eff = round((charges_ke / msb_ke * 100), 1) if msb_ke > 0 else 0
                bottom = generate_evol_block(np.nan, evol_charges_n1, '%', False,
                    supplement=f"<span style='color:#a0aabf;font-size:0.75em;'>Taux effectif : {taux_eff}%</span>",
                    hide_m1=True)
                st.markdown(create_card("CHARGES PATRONALES", f"{charges_ke}k€", "mensuel", "#0B1940", bottom), unsafe_allow_html=True)
            with c3:
                bottom = generate_evol_block(np.nan, np.nan, '%', False,
                    supplement=f"<span style='color:#a0aabf;font-size:0.75em;'>Annualisé : {msc_annu_me} M€</span>",
                    hide_m1=True)
                st.markdown(create_card("MS CHARGÉE", f"{int(ms_ch_ke)}k€", "coût total mensuel", "#00b289", bottom), unsafe_allow_html=True)
            with c4:
                primes_ke = round(primes_e / 1000, 1)
                bottom = generate_evol_block(np.nan, np.nan, '', False,
                    supplement=f"<span style='color:#a0aabf;font-size:0.75em;'>{primes_ke}k€ de la MS brute</span>",
                    hide_m1=True)
                st.markdown(create_card("TOTAL PRIMES", f"{int(primes_e):,} €".replace(',', ' '), "variable mensuel", "#3b82f6", bottom), unsafe_allow_html=True)
            with c5:
                niv_var = 1 if part_var > 15 else 0
                couleur_top_var = "#ffb020" if niv_var else "#0B1940"
                bottom = generate_evol_block(np.nan, np.nan, ' pts', False, hide_m1=True)
                st.markdown(create_card("ÉCART DU VARIABLE", f"{str(part_var).replace('.',',')}%", "part / MS brute", couleur_top_var, bottom, has_dot=(niv_var > 0)), unsafe_allow_html=True)

            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-top:10px; margin-bottom:10px;'>| SALAIRES MOYENS — PAR CATÉGORIE ET PAR SEXE</p>", unsafe_allow_html=True)

            # ── LIGNE 2 : 2 tableaux ──
            col_cat, col_sex = st.columns(2)

            with col_cat:
                badge_brut = f"<span style='background-color:#fce4ec;color:#e91e63;padding:3px 8px;border-radius:10px;font-size:0.7em;font-weight:bold;'>BRUT MENSUEL · {int(msb_ke)}k€</span>"

                def _row_cat(label, legende, nb, moy, med, evol_n1, color):
                    evol_html = format_single_evol(evol_n1, '%', 'N-1')
                    moy_fmt = f"{moy:,} €".replace(',', ' ')
                    med_fmt = f"{med:,} €".replace(',', ' ')
                    return (
                        f'<tr style="border-bottom:1px solid #f0f2f6;">'
                        f'<td style="padding:14px 0;"><b><span style="color:{color};">■</span> {label}</b>'
                        f'<br><span style="color:grey;font-size:0.78em;">{legende}</span></td>'
                        f'<td style="font-weight:900;font-size:1.1em;color:{color};">{nb}</td>'
                        f'<td style="font-weight:bold;color:#0B1940;">{moy_fmt}</td>'
                        f'<td style="color:#555;">{med_fmt}</td>'
                        f'<td>{evol_html}</td>'
                        f'</tr>'
                    )

                row_c  = _row_cat("Cadres",     "Statut 01, 02", nb_c,  sm_c,  med_c,  evol_sm_n1, "#0B1940")
                row_nc = _row_cat("Non-cadres", "Statut 04",     nb_nc, sm_nc, med_nc, evol_sm_n1, "#e91e63")
                sm_tot_fmt  = f"{sm_tot:,} €".replace(',', ' ')
                med_tot_fmt = f"{med_tot:,} €".replace(',', ' ')
                row_tot = (
                    '<tr style="background-color:#0B1940;color:white;">'
                    '<td style="padding:14px 10px;font-weight:bold;border-radius:5px 0 0 5px;">Total</td>'
                    f'<td style="font-weight:900;font-size:1.1em;color:#e91e63;">{eff_tot}</td>'
                    f'<td style="font-weight:bold;color:#e91e63;">{sm_tot_fmt}</td>'
                    f'<td style="color:#ccc;">{med_tot_fmt}</td>'
                    f'<td style="border-radius:0 5px 5px 0;">{format_single_evol(evol_sm_n1, "%", "N-1")}</td>'
                    '</tr>'
                )
                note_rgpd = "<div style='margin-top:10px;font-size:0.72em;color:#a0aabf;'>⚠ Agrégats uniquement · Min. 3 individus par groupe</div>"
                html_cat = (
                    '<div style="background-color:white;border:1px solid #e0e0e0;border-radius:5px;padding:20px;">'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
                    f'<h4 style="margin:0;color:#0B1940;">Salaire moyen par catégorie</h4>{badge_brut}'
                    '</div>'
                    '<table style="width:100%;border-collapse:collapse;font-size:0.88em;">'
                    '<tr style="color:#a0aabf;text-transform:uppercase;font-size:0.75em;border-bottom:1px solid #f0f2f6;">'
                    '<th style="padding-bottom:8px;">Catégorie</th><th>Nb sal.</th>'
                    '<th>Sal. moyen</th><th>Sal. médian</th><th>Variation N-1</th>'
                    '</tr>'
                    + row_c + row_nc + row_tot +
                    '</table>'
                    + note_rgpd +
                    '</div>'
                )
                st.markdown(html_cat, unsafe_allow_html=True)

            with col_sex:
                niv_ecart = 2 if abs(ecart_hf) > 10 else 1 if abs(ecart_hf) > 5 else 0
                couleur_badge_e = "#e91e63" if niv_ecart == 2 else "#ffb020" if niv_ecart == 1 else "#00b289"
                bg_badge_e = "#fce4ec" if niv_ecart == 2 else "#fff3cd" if niv_ecart == 1 else "#e2f9f1"
                label_badge_e = "⚠ Surveiller" if niv_ecart > 0 else "✓ Conforme"
                badge_egal = f"<span style='background-color:{bg_badge_e};color:{couleur_badge_e};padding:3px 8px;border-radius:10px;font-size:0.7em;font-weight:bold;'>INDICE ÉGALITÉ · {label_badge_e}</span>"
                sm_h_fmt  = f"{sm_h:,} €".replace(',', ' ')
                sm_f_fmt  = f"{sm_f:,} €".replace(',', ' ')
                med_h_fmt = f"{med_h:,} €".replace(',', ' ')
                med_f_fmt = f"{med_f:,} €".replace(',', ' ')
                ecart_cell = (
                    f'<td rowspan="2" style="text-align:center;vertical-align:middle;padding:10px;">'
                    f'<div style="background-color:{bg_badge_e};border-radius:8px;padding:15px;">'
                    f'<div style="font-size:1.8rem;font-weight:900;color:{couleur_badge_e};">{str(ecart_hf).replace(".",",")}%</div>'
                    f'<div style="font-size:0.7em;color:#555;margin-top:4px;">Écart salarial<br>H/F (brut)</div>'
                    f'<div style="margin-top:8px;font-size:0.7em;font-weight:bold;color:{couleur_badge_e};">{"⚠ Surveiller" if niv_ecart > 0 else "✓ OK"}</div>'
                    f'</div></td>'
                )
                row_h = (
                    '<tr style="border-bottom:1px solid #f0f2f6;">'
                    '<td style="padding:14px 0;"><b><span style="color:#3b82f6;">■</span> Hommes</b></td>'
                    f'<td style="font-weight:900;color:#3b82f6;">{int(data.get("NB_HOMMES", 0))}</td>'
                    f'<td style="font-weight:bold;color:#0B1940;">{sm_h_fmt}</td>'
                    f'<td>{med_h_fmt}</td>'
                    + ecart_cell +
                    '</tr>'
                )
                row_f = (
                    '<tr style="border-bottom:1px solid #f0f2f6;">'
                    '<td style="padding:14px 0;"><b><span style="color:#e91e63;">■</span> Femmes</b></td>'
                    f'<td style="font-weight:900;color:#e91e63;">{int(data.get("NB_FEMMES", 0))}</td>'
                    f'<td style="font-weight:bold;color:#0B1940;">{sm_f_fmt}</td>'
                    f'<td>{med_f_fmt}</td>'
                    '</tr>'
                )
                row_tot_sex = (
                    '<tr style="background-color:#0B1940;color:white;">'
                    '<td style="padding:14px 10px;font-weight:bold;border-radius:5px 0 0 5px;">Ensemble</td>'
                    f'<td style="font-weight:900;color:#e91e63;">{eff_tot}</td>'
                    f'<td style="font-weight:bold;color:#e91e63;">{sm_tot_fmt}</td>'
                    f'<td style="color:#ccc;">{med_tot_fmt}</td>'
                    '<td style="border-radius:0 5px 5px 0;"></td>'
                    '</tr>'
                )
                note_sex = "<div style='margin-top:10px;font-size:0.72em;color:#a0aabf;'>⚠ Données agrégées — 3 individus minimum</div>"
                html_sex = (
                    '<div style="background-color:white;border:1px solid #e0e0e0;border-radius:5px;padding:20px;">'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
                    f'<h4 style="margin:0;color:#0B1940;">Salaire moyen par sexe</h4>{badge_egal}'
                    '</div>'
                    '<table style="width:100%;border-collapse:collapse;font-size:0.88em;">'
                    '<tr style="color:#a0aabf;text-transform:uppercase;font-size:0.75em;border-bottom:1px solid #f0f2f6;">'
                    '<th style="padding-bottom:8px;">Population</th><th>Nb sal.</th>'
                    '<th>Sal. moyen</th><th>Sal. médian</th><th>Écart H/F</th>'
                    '</tr>'
                    + row_h + row_f + row_tot_sex +
                    '</table>'
                    + note_sex +
                    '</div>'
                )
                st.markdown(html_sex, unsafe_allow_html=True)

            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-top:20px; margin-bottom:10px;'>| ÉVOLUTION DE LA MASSE SALARIALE — 3 ANS</p>", unsafe_allow_html=True)

            # ── GRAPHIQUE 3 ANS ──
            max_val = max(tot_n2, tot_n1, tot_n, 1)

            def _barre_ms(an_label, ms_c_val, ms_nc_val, max_v):
                h_total = 220
                h_c  = int((ms_c_val  / max_v) * h_total) if max_v > 0 else 0
                h_nc = int((ms_nc_val / max_v) * h_total) if max_v > 0 else 0
                tot_me = round((ms_c_val + ms_nc_val) * 12 / 1000, 2)
                return (
                    f'<div style="display:flex;flex-direction:column;align-items:center;flex:1;padding:0 30px;">'
                    f'<div style="font-size:0.8em;font-weight:bold;color:#0B1940;margin-bottom:6px;">{tot_me} M€</div>'
                    f'<div style="display:flex;flex-direction:column;justify-content:flex-end;height:{h_total}px;width:80px;">'
                    f'<div style="background-color:#0B1940;height:{h_c}px;width:100%;border-radius:3px 3px 0 0;"></div>'
                    f'<div style="background-color:#e91e63;height:{h_nc}px;width:100%;border-radius:0 0 3px 3px;"></div>'
                    f'</div>'
                    f'<div style="font-size:0.9em;font-weight:bold;color:#555;margin-top:8px;">{an_label}</div>'
                    f'</div>'
                )

            barre_n2 = _barre_ms(str(an - 2), ms_c_n2, ms_nc_n2, max_val)
            barre_n1 = _barre_ms(str(an - 1), ms_c_n1, ms_nc_n1, max_val)
            barre_n  = _barre_ms(str(an),     ms_c_n,  ms_nc_n,  max_val)

            annu_str = f"{round(msb_ke * 12 / 1000, 2)} M€"
            legende = (
                '<span style="display:inline-flex;align-items:center;margin-right:16px;font-size:0.8em;">'
                '<span style="width:12px;height:12px;background:#0B1940;border-radius:2px;margin-right:5px;"></span>Cadres</span>'
                '<span style="display:inline-flex;align-items:center;margin-right:16px;font-size:0.8em;">'
                '<span style="width:12px;height:12px;background:#e91e63;border-radius:2px;margin-right:5px;"></span>Non-cadres</span>'
                f'<span style="background-color:#fce4ec;color:#e91e63;padding:2px 8px;border-radius:10px;font-size:0.75em;font-weight:bold;">ANNUALISÉ · {annu_str}</span>'
            )
            html_graph = (
                '<div style="background-color:white;border:1px solid #e0e0e0;border-radius:5px;padding:24px;">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">'
                '<h4 style="margin:0;color:#0B1940;">Évolution de la masse salariale — 3 ans</h4>'
                f'<div>{legende}</div>'
                '</div>'
                '<div style="display:flex;justify-content:space-around;align-items:flex-end;padding:0 40px;">'
                + barre_n2 + barre_n1 + barre_n +
                '</div>'
                '<div style="margin-top:12px;font-size:0.72em;color:#a0aabf;">Source : S21.G00.51 · Données annualisées · NEODES agrégé</div>'
                '</div>'
            )
            st.markdown(html_graph, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # ── LIGNE BASSE : 3 cartes ──
            cb1, cb2, cb3 = st.columns(3)
            with cb1:
                bottom = generate_evol_block(np.nan, evol_sm_n1, '%', False, hide_m1=True)
                st.markdown(create_card("SALAIRE MOYEN CADRES", f"{sm_c:,} €".replace(',', ' '), "brut mensuel", "#e91e63", bottom), unsafe_allow_html=True)
            with cb2:
                bottom = generate_evol_block(np.nan, evol_sm_n1, '%', False, hide_m1=True)
                st.markdown(create_card("SALAIRE MOYEN NON-CADRES", f"{sm_nc:,} €".replace(',', ' '), "brut mensuel", "#e91e63", bottom), unsafe_allow_html=True)
            with cb3:
                cout_str = f"{cout_sal_moy:,} €".replace(',', ' ')
                bottom = generate_evol_block(np.nan, evol_charges_n1, '%', False, hide_m1=True)
                st.markdown(create_card("COÛT SALARIAL MOYEN", cout_str, "MS chargée / effectif", "#3b82f6", bottom), unsafe_allow_html=True)

        # ==========================================
        # VUE : 📋 ABSENTÉISME
        # ==========================================
        elif choix_vue == "📋 Absentéisme":
            # Récupération des données métiers
            eff_moy = data.get('EFFECTIF_MOYEN', 1)
            eff_actifs = data.get('NOMBRE_CONTRATS_ACTIFS', 1)
            j_theo = eff_actifs * 21.67
            
            tx_abs = data.get('TAUX_ABSENTEISME_POURCENT', 0)
            jours_tot = data.get('TOTAL_JOURS_ABSENCES', 0)
            duree_moy = data.get('DUREE_MOY_ARRET_JOURS', 0)
            nb_arrets = data.get('NB_ARRETS_TOTAL', 0)
            freq_arrets = nb_arrets / eff_moy if eff_moy > 0 else 0
            
            sal_moyen_jour = data.get('SALAIRE_MOYEN_TOTAL', 0) / 21.67
            cout_total = jours_tot * sal_moyen_jour
            
            niv_abs = evaluer_kpi("absenteisme", tx_abs)
            
            # --- BANDEAU ALERTE HAUT DE PAGE ---
            if niv_abs > 0:
                couleur_bande = "#e91e63" if niv_abs == 2 else "#ffb020"
                mot = "Alerte" if niv_abs == 2 else "Attention"
                cout_str = f"{int(cout_total):,} €/mois".replace(',', ' ')
                tx_str = str(tx_abs).replace('.',',')
                st.markdown(f"""
                <div style='background-color:{couleur_bande}; color:white; padding:12px 20px; border-radius:5px; margin-bottom:20px;'>
                    <span style='font-size:1.2em;'>🔴</span> <b>{mot} :</b> Taux d'absentéisme {tx_str}% — seuil secteur 3,8% dépassé. Coût estimé : {cout_str}.
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| ABSENTÉISME — VUE GLOBALE</p>", unsafe_allow_html=True)
            
            # --- LIGNE 1 : CARTES GLOBALES ---
            c1, c2, c3, c4 = st.columns(4)
            
            with c1:
                evol_abs = data.get('EVOL_ABSENTEISME_N_1_PTS', np.nan)
                badge = format_single_evol(evol_abs, ' pts', 'N-1', inverser_couleur=True)
                statut = format_status_badge(niv_abs) if niv_abs > 0 else ""
                bottom = f"<div style='margin-top:8px;'>{badge}</div><div style='color:gray; font-size:0.75em; margin-top:8px; margin-bottom:4px;'>Secteur : 3,8%</div>{statut}"
                coul_top = "#e91e63" if niv_abs == 2 else ("#ffb020" if niv_abs == 1 else "#0B1940")
                st.markdown(create_card("TAUX ABSENTÉISME GLOBAL", f"{str(tx_abs).replace('.',',')}%", "Σ jours / (eff * 21,67) * 100", coul_top, bottom, has_dot=(niv_abs>0)), unsafe_allow_html=True)
                
            with c2:
                badge = format_single_evol(np.nan, ' j', 'N-1') # Pas calculé dans le main
                cout_str = f"{int(cout_total):,} €".replace(',', ' ')
                bottom = f"<div style='margin-top:8px;'>{badge}</div><div style='color:gray; font-size:0.75em; margin-top:8px;'>Coût : {cout_str}</div>"
                st.markdown(create_card("TOTAL JOURS ABSENCES", str(int(jours_tot)), f"jours · {date_cible.strftime('%B %Y')}", "#ffb020", bottom), unsafe_allow_html=True)
                
            with c3:
                badge = format_single_evol(np.nan, ' j', 'N-1')
                bottom = f"<div style='margin-top:8px;'>{badge}</div><div style='color:gray; font-size:0.75em; margin-top:8px;'>Seuil alerte : 5 j</div>"
                st.markdown(create_card("DURÉE MOY. ARRÊT", str(round(duree_moy, 1)).replace('.',','), "jours par arrêt", "#0B1940", bottom), unsafe_allow_html=True)
                
            with c4:
                badge = format_single_evol(np.nan, '', 'N-1')
                bottom = f"<div style='margin-top:8px;'>{badge}</div>"
                st.markdown(create_card("FRÉQUENCE ARRÊTS", str(round(freq_arrets, 2)).replace('.',','), "arrêts / salarié / mois", "#0B1940", bottom), unsafe_allow_html=True)

            # --- LIGNE 2 : TABLEAU DÉTAILLÉ (HTML/CSS) ---
            st.markdown("<br><p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| DÉTAIL PAR NATURE D'ABSENCE — SOURCE DSN S21.G00.60 (CODE MOTIF)</p>", unsafe_allow_html=True)
            
            j_mal = data.get('J_MALADIE', 0)
            j_at = data.get('J_AT', 0)
            j_cng = data.get('J_CONGES', 0) 
            n_ld = data.get('NB_ABS_LONGUE_DUREE', 0) 
            
            tx_mal = data.get('TAUX_MALADIE_POURCENT', 0)
            tx_at = data.get('TAUX_AT_POURCENT', 0)
            tx_cng = round((j_cng / j_theo) * 100, 2) if j_theo > 0 else 0.0
            tx_ld = round((n_ld / j_theo) * 100, 2) if j_theo > 0 else 0.0
            
            def row_html(titre, desc, code, val_j, col_theme, tx_partiel):
                pct_tot = round((val_j / jours_tot * 100), 1) if jours_tot > 0 else 0.0
                cout = int(val_j * sal_moyen_jour)
                
                cout_fmt = f"{cout:,}".replace(',', ' ')
                pct_tot_fmt = str(pct_tot).replace('.', ',')
                tx_partiel_fmt = str(tx_partiel).replace('.', ',')
                badge_n1 = format_single_evol(np.nan, ' j', 'N-1')
                
                return f"""
                <tr style="border-bottom: 1px solid #f0f2f6; font-size:0.9em;">
                    <td style="padding: 15px 10px;"><b><span style="color:{col_theme};">■</span> {titre}</b><br><span style="color:grey; font-size:0.8em;">{desc}</span></td>
                    <td style="text-align:center;"><span style="background-color:#f0f2f6; padding:3px 8px; border-radius:4px; font-size:0.8em; font-weight:bold; color:#555;">{code}</span></td>
                    <td style="text-align:center; font-weight:900; font-size:1.1em; color:{col_theme};">{int(val_j)}</td>
                    <td style="text-align:center; color:#555;">{pct_tot_fmt}%</td>
                    <td style="text-align:center; font-weight:bold; color:{col_theme};">{tx_partiel_fmt}%</td>
                    <td style="text-align:center; font-weight:bold; color:#0B1940;">{cout_fmt} €</td>
                    <td style="text-align:center;">{badge_n1}</td>
                </tr>
                """
                
            lignes_tab = (
                row_html("Maladie", "Arrêts ordinaires", "01", j_mal, "#e91e63", tx_mal) +
                row_html("Accident du travail", "AT/MP", "04", j_at, "#ffb020", tx_at) +
                row_html("Maternité / Paternité", "Congés légaux", "10 / 13", j_cng, "#a0aabf", tx_cng) +
                row_html("Longue durée", "> 90 jours continus", "01+", n_ld, "#3b82f6", tx_ld)
            )
            
            cout_tot_str = f"{int(cout_total):,} €".replace(',', ' ')
            
            st.markdown(f"""
            <div style="background-color: white; border: 1px solid #e0e0e0; border-radius: 5px; padding: 20px; margin-bottom: 20px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h4 style="margin:0; color:#0B1940;">Absentéisme détaillé par nature</h4>
                    <span style="background-color:#fce4ec; color:#e91e63; font-size:0.7em; padding:2px 8px; border-radius:10px; font-weight:bold;">CATÉGORIES DSN · ART. 9 AGRÉGÉ</span>
                </div>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="color: #a0aabf; border-bottom: 1px solid #e91e63; text-transform: uppercase; font-size: 0.75em; text-align:center;">
                        <th style="text-align:left; padding-bottom: 10px; padding-left:10px;">Nature d'absence</th>
                        <th style="padding-bottom: 10px;">Code DSN</th>
                        <th style="padding-bottom: 10px;">Nb Jours</th>
                        <th style="padding-bottom: 10px;">% du total abs.</th>
                        <th style="padding-bottom: 10px;">Taux abs. partiel</th>
                        <th style="padding-bottom: 10px;">Coût estimé</th>
                        <th style="padding-bottom: 10px;">Variation N-1</th>
                    </tr>
                    {lignes_tab}
                    <tr style="background-color: #0B1940; color: white; font-size:0.95em;">
                        <td style="padding: 15px 10px; font-weight: bold; border-radius: 5px 0 0 5px;">Total absences</td>
                        <td style="text-align:center; font-weight:bold;">–</td>
                        <td style="text-align:center; font-weight:900; font-size:1.1em; color:#e91e63;">{int(jours_tot)}</td>
                        <td style="text-align:center; font-weight:bold;">100%</td>
                        <td style="text-align:center; font-weight:bold; color:#e91e63;">{str(tx_abs).replace('.',',')}%</td>
                        <td style="text-align:center; font-weight:bold;">{cout_tot_str}</td>
                        <td style="border-radius: 0 5px 5px 0; text-align:center;">{format_single_evol(np.nan, '', 'N-1')}</td>
                    </tr>
                </table>
                <div style="margin-top: 20px; background-color: #fce4ec; border-left: 4px solid #e91e63; padding: 10px; border-radius: 4px; font-size: 0.85em; color: #0B1940;">
                    <span style="color:#e91e63; font-weight:bold;">🔴 RGPD Art. 9 :</span> Données de santé agrégées par catégorie — aucun arrêt individuel stocké. Seule la durée calculée est conservée (3 ans max). Sous-motifs et diagnostics non traités.
                </div>
            </div>
            """, unsafe_allow_html=True)

            # --- LIGNE 3 : CARTES TAUX PARTIELS ---
            c5, c6, c7 = st.columns(3)
            
            with c5:
                badge = format_single_evol(np.nan, ' pts', 'N-1')
                niv_mal = 2 if tx_mal >= 4.0 else 1 if tx_mal >= 2.5 else 0
                col_top = "#e91e63" if niv_mal == 2 else ("#ffb020" if niv_mal == 1 else "#e91e63")
                st.markdown(create_card("ABS. MALADIE", f"{str(tx_mal).replace('.',',')}%", "taux partiel", col_top, f"<div style='margin-top:8px;'>{badge}</div><div style='color:gray; font-size:0.75em; margin-top:8px;'>Secteur : 2,1%</div>"), unsafe_allow_html=True)
                
            with c6:
                badge = format_single_evol(np.nan, ' pts', 'N-1')
                niv_at = 2 if tx_at >= 1.5 else 1 if tx_at >= 0.8 else 0
                col_top = "#e91e63" if niv_at == 2 else ("#ffb020" if niv_at == 1 else "#ffb020")
                st.markdown(create_card("ABS. ACCIDENT TRAVAIL", f"{str(tx_at).replace('.',',')}%", "taux AT", col_top, f"<div style='margin-top:8px;'>{badge}</div><div style='color:gray; font-size:0.75em; margin-top:8px;'>Secteur : 0,7%</div>"), unsafe_allow_html=True)
                
            with c7:
                badge = format_single_evol(0, '', 'N-1')
                st.markdown(create_card("ABS. CONGÉS LÉGAUX", f"{str(tx_cng).replace('.',',')}%", "maternité + paternité", "#8a2be2", f"<div style='margin-top:8px;'>{badge}</div><div style='color:gray; font-size:0.75em; margin-top:8px;'>Taux normal</div>"), unsafe_allow_html=True)

        # ==========================================
        # VUE : ⚖️ ÉGALITÉ PRO
        # ==========================================
        elif choix_vue == "⚖️ Égalité pro.":
            st.markdown("<p style='color:#a0aabf; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>| ÉGALITÉ PROFESSIONNELLE — INDEX L.1142-8 ET INDICATEURS DSN</p>", unsafe_allow_html=True)
            
            # --- LIGNE 1 : CARTES SYNTHÈSE ---
            c1, c2, c3, c4 = st.columns(4)
            
            with c1:
                # Carte 1 : Index DARES (Non géré actuellement)
                badge_na = "<span style='background-color:#fff3cd; color:#ffb020; padding:2px 6px; border-radius:4px; font-weight:bold; font-size:0.75em;'>⚠ Seuil 85 non atteint</span>"
                st.markdown(create_card("INDEX ÉGALITÉ PRO.", "N/A <span style='font-size:0.5em; color:gray;'>/100</span>", "Calcul DARES 5 indicateurs", "#0B1940", badge_na), unsafe_allow_html=True)

            with c2:
                # Carte 2 : Écart salarial
                ecart_hf = data.get('ECART_SALARIAL_HF_POURCENT', 0.0)
                coul_ecart = "#ffb020" if abs(ecart_hf) > 5 else "#00b289"
                bg_ecart = "#fff3cd" if abs(ecart_hf) > 5 else "#e2f9f1"
                txt_badge_ecart = "À surveiller" if abs(ecart_hf) > 5 else "Conforme"
                bottom_ecart = f"<span style='background-color:{bg_ecart}; color:{coul_ecart}; padding:2px 6px; border-radius:4px; font-weight:bold; font-size:0.75em;'>Seuil recommandé &lt;5% · {txt_badge_ecart}</span>"
                st.markdown(create_card("ÉCART SALARIAL H/F", f"{str(ecart_hf).replace('.',',')}%", "(H-F)/H à catég. équiv.", coul_ecart, bottom_ecart), unsafe_allow_html=True)

            with c3:
                # Carte 3 : Écart d'augmentations
                ecart_augm = data.get('ECART_AUGMENTATION_HF_PTS', 0.0)
                signe = "+" if ecart_augm > 0 else ""
                txt_augm = "Favorable H" if ecart_augm > 0 else ("Favorable F" if ecart_augm < 0 else "Parfaitement neutre")
                col_augm_badge = "#e91e63" if ecart_augm < 0 else ("#3b82f6" if ecart_augm > 0 else "#00b289")
                bg_augm_badge = "#fce4ec" if ecart_augm < 0 else ("#e0f2fe" if ecart_augm > 0 else "#e2f9f1")
                bottom_augm = f"<span style='background-color:{bg_augm_badge}; color:{col_augm_badge}; padding:2px 6px; border-radius:4px; font-weight:bold; font-size:0.75em;'>{txt_augm}</span>"
                st.markdown(create_card("ÉCART AUGMENTATIONS", f"{signe}{str(ecart_augm).replace('.',',')}%", "hommes vs femmes", "#0B1940", bottom_augm), unsafe_allow_html=True)

            with c4:
                # Carte 4 : Féminisation Management
                tx_fem_man = data.get('TAUX_FEMINISATION_MANAGEMENT_POURCENT', 0.0)
                nb_fem_cadres = int(data.get('NB_FEMMES_CADRES', 0))
                nb_cadres = int(data.get('NB_CADRES', 0))
                evol_fem_man = data.get('EVOL_FEMINISATION_MANAGEMENT_N_1_PTS', np.nan)
                bottom_fem = format_single_evol(evol_fem_man, ' pts', 'N-1')
                st.markdown(create_card("FÉMINISATION MANAGEMENT", f"{str(tx_fem_man).replace('.',',')}%", f"{nb_fem_cadres}/{nb_cadres} cadres = femmes", "#00b289", bottom_fem), unsafe_allow_html=True)

            # --- LIGNE 2 : TABLEAUX ET BARRES ---
            col_tab, col_bar = st.columns(2)

            with col_tab:
                badge_tab = "<span style='background-color:#fce4ec; color:#e91e63; padding:4px 10px; border-radius:15px; font-size:0.7em; font-weight:bold; letter-spacing:0.5px;'>AGRÉGATS ≥3 INDIVIDUS</span>"
                
                # Récupération données du tableau
                sal_c_h = f"{int(data.get('SALAIRE_MOYEN_CADRE_HOMME', 0)):,} €".replace(',', ' ')
                sal_c_f = f"{int(data.get('SALAIRE_MOYEN_CADRE_FEMME', 0)):,} €".replace(',', ' ')
                ecart_c = data.get('ECART_SALARIAL_CADRES_HF_POURCENT', 0.0)
                
                sal_nc_h = f"{int(data.get('SALAIRE_MOYEN_NON_CADRE_HOMME', 0)):,} €".replace(',', ' ')
                sal_nc_f = f"{int(data.get('SALAIRE_MOYEN_NON_CADRE_FEMME', 0)):,} €".replace(',', ' ')
                ecart_nc = data.get('ECART_SALARIAL_NON_CADRES_HF_POURCENT', 0.0)
                
                sal_tot_h = f"{int(data.get('SALAIRE_MOYEN_HOMME', 0)):,} €".replace(',', ' ')
                sal_tot_f = f"{int(data.get('SALAIRE_MOYEN_FEMME', 0)):,} €".replace(',', ' ')
                ecart_tot = data.get('ECART_SALARIAL_HF_POURCENT', 0.0)

                def style_ecart(val, is_dark_bg=False):
                    if is_dark_bg:
                        coul = "#e91e63"
                        bg = "#2a1525"
                    else:
                        coul = "#ffb020"
                        bg = "#fff3cd"
                    signe = "+" if val > 0 else ""
                    return f"<span style='background-color:{bg}; color:{coul}; padding:4px 10px; border-radius:6px; font-weight:900; font-size:0.85em;'>{signe}{str(val).replace('.',',')}%</span>"

                # /!\ Le texte HTML ci-dessous est volontairement collé à gauche
                html_tab_egalite = f"""<div style="background-color:white; border:1px solid #e0e0e0; border-radius:8px; padding:25px; min-height:320px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <h4 style="margin:0; color:#0B1940; font-weight:900;">Salaires H/F par catégorie</h4>{badge_tab}
    </div>
    <table style="width:100%; border-collapse:collapse; font-size:0.95em; text-align:center;">
        <tr style="color:#a0aabf; text-transform:uppercase; font-size:0.75em; border-bottom:2px solid #e91e63;">
            <th style="padding-bottom:12px; text-align:left; letter-spacing:1px;">Catégorie</th>
            <th style="padding-bottom:12px; letter-spacing:1px;">Hommes</th>
            <th style="padding-bottom:12px; letter-spacing:1px;">Femmes</th>
            <th style="padding-bottom:12px; letter-spacing:1px;">Écart %</th>
        </tr>
        <tr style="border-bottom:1px solid #f0f2f6;">
            <td style="padding:16px 10px; text-align:left; font-weight:900; color:#0B1940;">Cadres</td>
            <td style="font-weight:bold; color:#0B1940;">{sal_c_h}</td>
            <td style="font-weight:bold; color:#0B1940;">{sal_c_f}</td>
            <td>{style_ecart(ecart_c, False)}</td>
        </tr>
        <tr style="background-color:#f4f5f8;">
            <td style="padding:16px 10px; text-align:left; font-weight:900; color:#0B1940;">Non-cadres</td>
            <td style="font-weight:bold; color:#0B1940;">{sal_nc_h}</td>
            <td style="font-weight:bold; color:#0B1940;">{sal_nc_f}</td>
            <td>{style_ecart(ecart_nc, False)}</td>
        </tr>
        <tr style="background-color:#0B1940;">
            <td style="padding:16px 10px; text-align:left; font-weight:900; color:white;">Ensemble</td>
            <td style="font-weight:900; color:#3b82f6; font-size:1.05em;">{sal_tot_h}</td>
            <td style="font-weight:900; color:#8a2be2; font-size:1.05em;">{sal_tot_f}</td>
            <td>{style_ecart(ecart_tot, True)}</td>
        </tr>
    </table>
    <div style="margin-top:15px; font-size:0.7em; color:#a0aabf; display:flex; align-items:center;">
        🔒 Données agrégées uniquement — groupes ≥ 3 individus · S21.G00.30 + S21.G00.51
    </div>
</div>"""
                st.markdown(html_tab_egalite, unsafe_allow_html=True)

            with col_bar:
                badge_dsn = "<span style='background-color:#fce4ec; color:#e91e63; padding:4px 10px; border-radius:15px; font-size:0.7em; font-weight:bold; letter-spacing:0.5px;'>S21.G00.30</span>"
                
                # Data Effectif Global
                nb_h_tot = int(data.get('NB_HOMMES', 0))
                nb_f_tot = int(data.get('NB_FEMMES', 0))
                eff_tot = nb_h_tot + nb_f_tot
                pct_h_tot = round(nb_h_tot / eff_tot * 100, 1) if eff_tot > 0 else 0
                pct_f_tot = round(nb_f_tot / eff_tot * 100, 1) if eff_tot > 0 else 0

                # Data Cadres
                nb_h_c = int(data.get('NB_HOMMES_CADRES', 0))
                nb_f_c = int(data.get('NB_FEMMES_CADRES', 0))
                eff_c = nb_h_c + nb_f_c
                pct_h_c = round(nb_h_c / eff_c * 100, 1) if eff_c > 0 else 0
                pct_f_c = round(nb_f_c / eff_c * 100, 1) if eff_c > 0 else 0

                def _bar_egalite(label, nb, pct, color):
                    return f"""<div style="display:flex; align-items:center; margin-bottom:12px;">
    <div style="width:80px; font-size:0.95em; font-weight:900; color:#0B1940;">{label}</div>
    <div style="flex-grow:1; background-color:#eef0f4; height:10px; border-radius:5px; margin:0 20px;">
        <div style="width:{pct}%; background-color:{color}; height:100%; border-radius:5px;"></div>
    </div>
    <div style="width:30px; text-align:right; font-weight:900; color:{color}; font-size:1.05em;">{nb}</div>
    <div style="width:50px; text-align:right; font-size:0.8em; color:#a0aabf;">{str(pct).replace('.',',')}%</div>
</div>"""

                html_bar_egalite = f"""<div style="background-color:white; border:1px solid #e0e0e0; border-radius:8px; padding:25px; min-height:320px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <h4 style="margin:0; color:#0B1940; font-weight:900;">Répartition H/F</h4>{badge_dsn}
    </div>
    <div style="color:#a0aabf; font-size:0.75em; text-transform:uppercase; font-weight:bold; letter-spacing:1px; margin-bottom:12px;">EFFECTIF GLOBAL</div>
    {_bar_egalite("Hommes", nb_h_tot, pct_h_tot, "#3b82f6")}
    {_bar_egalite("Femmes", nb_f_tot, pct_f_tot, "#8a2be2")}
    <hr style="border:none; border-top:1px solid #f0f2f6; margin: 25px 0;">
    <div style="color:#a0aabf; font-size:0.75em; text-transform:uppercase; font-weight:bold; letter-spacing:1px; margin-bottom:12px;">CADRES</div>
    {_bar_egalite("Hommes", nb_h_c, pct_h_c, "#3b82f6")}
    {_bar_egalite("Femmes", nb_f_c, pct_f_c, "#8a2be2")}
</div>"""
                st.markdown(html_bar_egalite, unsafe_allow_html=True)

            
        # ==========================================
        # VUES GÉRÉES PAR ÉQUIPE EXTERNE
        # ==========================================
        elif choix_vue in ["🔄 Turnover"]:
            st.title(f"{choix_vue} (Géré par équipe externe)")

        # ==========================================
        # AUTRES VUES
        # ==========================================
        else:
            st.title(f"{choix_vue}")
            st.write("En cours de construction...")

    else:
        st.error("Données indisponibles pour le mois sélectionné.")

else:
    st.info("👈 Veuillez charger vos fichiers DSN (.edi) dans le menu de gauche pour commencer.")