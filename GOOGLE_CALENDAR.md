# Integració Google Calendar

Sincronització automàtica d'events de Gestoria amb el Google Calendar de `pau@rodonverges.com`.

## Setup inicial

### 1. Google Cloud Console

1. Ves a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un projecte nou o usa'n un d'existent
3. Activa la **Google Calendar API** (APIs & Services > Library)
4. Crea credencials **OAuth 2.0** (APIs & Services > Credentials > Create Credentials > OAuth Client ID)
   - Tipus: **Desktop App**
   - Descarrega el JSON

### 2. Obtenir el refresh_token

```bash
pip install google-auth-oauthlib
python scripts/get_google_token.py
```

Inicia sessió amb `pau@rodonverges.com` al navegador. El script mostrarà les credencials.

### 3. Configurar variables d'entorn a Render

| Variable | Descripció |
|---|---|
| `GOOGLE_CLIENT_ID` | Client ID del projecte OAuth |
| `GOOGLE_CLIENT_SECRET` | Client Secret |
| `GOOGLE_REFRESH_TOKEN` | Refresh token obtingut al pas 2 |
| `GOOGLE_CALENDAR_ID` | `pau@rodonverges.com` (default) |

### 4. Sincronització inicial

Un cop desplegat, crida:

```bash
curl -X POST https://EL-TEU-SERVEI.onrender.com/api/calendar/sync-all
```

Això sincronitzarà tots els events futurs que encara no estiguin al Calendar.

## Com funciona

- **Crear event** → es crea automàticament al Google Calendar (asíncron)
- **Editar event** → s'actualitza al Calendar
- **Eliminar event** → s'elimina del Calendar
- Si les credencials no estan configurades, el sistema funciona normalment sense sincronització

## Fitxers

| Fitxer | Funció |
|---|---|
| `google_auth.py` | Inicialització del client OAuth2 |
| `calendar_service.py` | CRUD d'events al Google Calendar |
| `calendar_sync.py` | Lògica de sincronització |
| `scripts/get_google_token.py` | Script per obtenir el refresh_token |

## Troubleshooting

- **"Credencials no configurades"**: Verifica que les 3 variables d'entorn estan a Render
- **Error 403**: L'API de Calendar no està activada o el consent screen no està configurat
- **Token expirat**: El refresh_token no caduca si l'app està en mode "producció" a Google Cloud. Si és en mode "test", caduca cada 7 dies — publica l'app per evitar-ho
