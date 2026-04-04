#!/usr/bin/env python3
"""
Script per obtenir el refresh_token de Google Calendar OAuth2.

INSTRUCCIONS:
1. Ves a https://console.cloud.google.com/
2. Crea un projecte (o usa'n un d'existent)
3. Activa la Google Calendar API
4. Crea credencials OAuth 2.0 (tipus "Desktop App")
5. Descarrega el JSON i posa'l a aquest directori com a 'credentials.json'
   O bé configura les variables d'entorn GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET
6. Executa: python scripts/get_google_token.py
7. S'obrirà el navegador per autoritzar amb pau@rodonverges.com
8. Copia el refresh_token que es mostrarà per consola
9. Configura les variables d'entorn a Render:
   - GOOGLE_CLIENT_ID
   - GOOGLE_CLIENT_SECRET
   - GOOGLE_REFRESH_TOKEN
   - GOOGLE_CALENDAR_ID=pau@rodonverges.com
"""

import os
import json

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: Cal instal\u00b7lar google-auth-oauthlib")
    print("  pip install google-auth-oauthlib")
    exit(1)

SCOPES = ['https://www.googleapis.com/auth/calendar']


def main():
    # Intentar llegir credentials.json primer
    creds_file = os.path.join(os.path.dirname(__file__), 'credentials.json')

    if os.path.exists(creds_file):
        print(f"Usant credencials de: {creds_file}")
        flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
    else:
        # Usar variables d'entorn
        client_id = os.environ.get('GOOGLE_CLIENT_ID')
        client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
        if not client_id or not client_secret:
            print("ERROR: No s'ha trobat credentials.json ni variables d'entorn")
            print("  Opcio A: Descarrega credentials.json de Google Cloud Console")
            print("           i posa'l a scripts/credentials.json")
            print("  Opcio B: Configura GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET")
            exit(1)

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"]
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    # Executar el flow OAuth (obre el navegador)
    print("\nS'obrira el navegador. Inicia sessio amb pau@rodonverges.com")
    print("i autoritza l'acces al Google Calendar.\n")

    creds = flow.run_local_server(port=8090, prompt='consent', access_type='offline')

    print("\n" + "=" * 60)
    print("CREDENCIALS OBTINGUDES CORRECTAMENT")
    print("=" * 60)
    print(f"\nGOOGLE_CLIENT_ID={flow.client_config['client_id']}")
    print(f"GOOGLE_CLIENT_SECRET={flow.client_config['client_secret']}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print(f"GOOGLE_CALENDAR_ID=pau@rodonverges.com")
    print("\n" + "=" * 60)
    print("PASSOS SEGUENTS:")
    print("=" * 60)
    print("1. Ves a Render > el teu servei > Environment")
    print("2. Afegeix les 4 variables d'entorn de dalt")
    print("3. Fes un deploy manual o espera al proper push")
    print("4. Crida POST /api/calendar/sync-all per sincronitzar events existents")
    print("=" * 60)


if __name__ == '__main__':
    main()
