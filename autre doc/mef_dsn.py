import pandas as pd
import re
from datetime import datetime

def extract_insurance_data_from_dsn(file_path):
    """
    Parse un fichier DSN avec une approche "Liste Blanche" (Whitelist).
    Ne conserve QUE les données utiles à la tarification d'assurance,
    traduit les segments en variables métier et calcule l'âge dynamiquement.
    """
    # Dictionnaire de Mapping (Liste Blanche)
    # Si le segment n'est pas ici, il est purement et simplement ignoré.
    # La liste de tout les segments avec leur correspondnace est dispo dans le fichier 'Lexique_dsn.txt' 
    dsn_mapping = {
        'S21.G00.06.001': 'SIREN',
        'S21.G00.06.003': 'CODE_NAF',
        'S21.G00.06.004': 'ADRESSE_ENTREPRISE',
        'S21.G00.06.005': 'CP_ENTREPRISE',
        'S21.G00.06.006': 'VILLE_ENTREPRISE',
        'S21.G00.11.001': 'NIC',
        'S21.G00.15.001': 'REFERENCE_CONTRAT_ACTUEL',
        'S21.G00.15.002': 'CODE_ASSUREUR_ACTUEL',
        'S21.G00.40.006': 'EMPLOI_LIBELLE',
        'S21.G00.40.011': 'STATUT_CONVENTIONNEL',
        'S21.G00.51.013': 'REMUNERATION_BRUTE', 
    }

    data = []
    current_siren = None
    today = datetime.today()
    pattern = re.compile(r"^(S\d{2}\.G\d{2}\.\d{2}\.\d{3}),'(.*)'$")

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        for line in file:
            match = pattern.match(line.strip())
            if not match: 
                continue 
             
            seg, val = match.groups()

            # 1. Identifier et mémoriser le SIREN
            if seg == 'S21.G00.06.001': 
                current_siren = val
            
            # 2. Règle spéciale : Transformer la Date de naissance en Âge
            if seg == 'S21.G00.30.006':
                try:
                    dob = datetime.strptime(val, "%d%m%Y")
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    if current_siren:
                        data.append({'SIREN': current_siren, 'Variable': 'AGE_SALARIE', 'Valeur': str(age)})
                except ValueError:
                    pass
                continue 

            # 3. Règle générale : On ne prend QUE les segments de notre dictionnaire
            if seg in dsn_mapping and current_siren:
                variable_metier = dsn_mapping[seg]
                data.append({'SIREN': current_siren, 'Variable': variable_metier, 'Valeur': val})

    return pd.DataFrame(data)

# Test du script
df_clean = extract_insurance_data_from_dsn('DSN_VICADI_202601_53354636200021!_NE_01.edi')
print(df_clean)