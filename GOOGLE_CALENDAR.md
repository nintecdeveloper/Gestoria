# Integració Google Calendar

Sincronització automàtica d'events de Gestoria amb el Google Calendar de `pau@rodonverges.com`.

## Setup inicial

### 1. Google Cloud Console

1. Ves a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un projecte nou o usa'n un d'existent
3. Activa la **Google Calendar API** (APIs & Services > Library)
4. Crea credencials **OAuth 2.0** (APIs & Services > Credentials > Create Credentials > OAuth Client ID)
   - Tipus: **Web Application**
   - Redirect URI autoritzada: `https://gestoriarodonverges.com/auth/google/callback`

### 2. Autoritzar el Google Calendar (via web)

1. Configura les variables d'entorn a Render (veure pas 3)
2. Obre al navegador:
   ```
   https://gestoriarodonverges.com/auth/google?token=EL_TEU_GOOGLE_AUTH_TOKEN
   ```
3. Inicia sessió amb `pau@rodonverges.com` i accepta els permisos
4. El sistema guardarà el `refresh_token` automàticament a Render

**Alternativa local** (si prefereixes):
```bash
pip install google-auth-oauthlib
python scripts/get_google_token.py
```

### 3. Variables d'entorn a Render

| Variable | Descripció |
|---|---|
| `GOOGLE_CLIENT_ID` | Client ID del projecte OAuth |
| `GOOGLE_CLIENT_SECRET` | Client Secret |
| `GOOGLE_REFRESH_TOKEN` | Es genera automàticament via `/auth/google` |
| `GOOGLE_CALENDAR_ID` | `pau@rodonverges.com` (default) |
| `GOOGLE_AUTH_TOKEN` | Token secret per protegir `/auth/google` (inventa un string aleatori) |
| `RENDER_API_KEY` | API Key de Render (Account Settings > API Keys) |
| `RENDER_SERVICE_ID` | ID del servei a Render (a la URL del dashboard) |

### 4. Sincronització inicial

Un cop autoritzat, crida:

```bash
curl -X POST https://gestoriarodonverges.com/api/calendar/sync-all
```

Això sincronitzarà tots els events futurs que encara no estiguin al Calendar.

## Com funciona

- **Crear event** → es crea automàticament al Google Calendar (asíncron)
- **Editar event** → s'actualitza al Calendar
- **Eliminar event** → s'elimina del Calendar
- Si les credencials no estan configurades, el sistema funciona normalment sense sincronització

## Flux OAuth Web

```
Usuari → /auth/google?token=XXX → Google Login → /auth/google/callback
                                                       ↓
                                                  Obté refresh_token
                                                       ↓
                                              Guarda a Render via API
                                                       ↓
                                              Pàgina de confirmació
```

## Fitxers

| Fitxer | Funció |
|---|---|
| `google_auth.py` | Inicialització del client OAuth2 |
| `calendar_service.py` | CRUD d'events al Google Calendar |
| `calendar_sync.py` | Lògica de sincronització |
| `scripts/get_google_token.py` | Script alternatiu per obtenir el refresh_token en local |

## Troubleshooting

- **"Credencials no configurades"**: Verifica que les 3 variables d'entorn estan a Render
- **Error 403 a `/auth/google`**: El `GOOGLE_AUTH_TOKEN` de la URL no coincideix
- **Error 403 de Google**: L'API de Calendar no està activada o el consent screen no està configurat
- **No s'obté refresh_token**: Revoca l'accés a [myaccount.google.com/permissions](https://myaccount.google.com/permissions) i torna a autoritzar
- **Token expirat**: El refresh_token no caduca si l'app està en mode "producció" a Google Cloud. Si és en mode "test", caduca cada 7 dies — publica l'app per evitar-ho
- **No es guarda a Render**: Verifica `RENDER_API_KEY` i `RENDER_SERVICE_ID`. El token es mostra a la pàgina de confirmació per copiar-lo manualment
