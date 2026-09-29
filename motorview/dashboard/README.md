# MotorView Dashboard

App [Streamlit](https://streamlit.io) que assina o MQTT publicado pelo
[gateway](../gateway/README.md) (Raspberry Pi + Modbus RTU) e mostra em tempo
real: status por motor, corrente (com pico via `current_fast`), falhas
(evento atual + últimas 3 falhas internas do CFW-500) e histórico com
exportação em CSV. Segue a mesma linha visual do
[ProdView](../../prodview/README.md) - menu em cards no topo, sem sidebar,
sem `st.tabs` padrão: **Visão Geral, Motores, Corrente, Falhas, Histórico,
Conectividade, Relatórios**.

## Rodar localmente

```bash
cd motorview/dashboard
pip install -r requirements.txt
cp .streamlit/secrets.example.toml .streamlit/secrets.toml   # e edite com os dados do broker
streamlit run app.py
```

Abre em `http://localhost:8501`. Assim que o gateway começar a publicar,
os dados aparecem automaticamente (o app assina o MQTT em background).
Sem os Secrets de `[auth]` preenchidos, o app roda em **modo aberto** (sem
exigir login) - é assim que dá pra desenvolver localmente sem depender do
Azure AD; ver seção de segurança abaixo antes de publicar de verdade.

## Contrato de tópicos MQTT (real, validado em campo)

O dashboard usa **sempre** a credencial *subscribe only* do broker
(`motorview-ingest`) - nunca a credencial de publicação do gateway
(`motorview-gateway-planta1`). Tópicos assinados (filtro
`motorview/<site_id>/#`):

| Tópico | Frequência |
|---|---|
| `motorview/<site>/gateway/status` | on-change (Last Will) |
| `motorview/<site>/<inv>/telemetry` | ~2s |
| `motorview/<site>/<inv>/current_fast` | ~500ms (amostrado a ~100ms no gateway) |
| `motorview/<site>/<inv>/fault` | on-change |

Não existe um tópico `fault_history` separado: o histórico interno do
CFW-500 (P0050/P0051-P0055, P0060, P0070) já viaja **embutido na própria
`telemetry`**, nos campos `last_fault_code`, `last_fault_description`,
`last_fault_current_A`, `last_fault_dc_link_V`, `last_fault_frequency_Hz`,
`last_fault_igbt_temp_C`, `last_fault_status_word`, `second_fault_code`,
`second_fault_description`, `third_fault_code`, `third_fault_description` -
ver `db.py` (tabela `telemetry`) e a tela "Falhas" em `app.py`.

Todos os timestamps chegam em **UTC com milissegundos** (o banco grava como
recebido; a conversão pra `America/Sao_Paulo` é só na hora de exibir, em
`app.py`).

## Segurança - leia antes de publicar

- **Nunca** hardcode credenciais em `app.py`/`config.py`/README - tudo vem
  de `st.secrets` (deploy) ou `.env` local (nunca commitado, já no
  `.gitignore`).
- A credencial MQTT do dashboard deve ser a **subscribe only**
  (`motorview-ingest`) - crie uma credencial separada da do gateway no
  broker. A do gateway (`motorview-gateway-planta1`) nunca deve aparecer
  aqui.
- **Não deixe o app público sem autenticação.** Camadas suportadas pelo
  código:
  1. **Streamlit Community Cloud**: nas configurações do app, marque como
     **privado** e restrinja quem pode abrir o link (ver
     [documentação de app settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings)).
  2. **Login Microsoft (Entra ID) dentro do próprio app** - preferível pra
     controle corporativo de identidade. Usa a autenticação OIDC nativa do
     Streamlit (`st.login`/`st.logout`/`st.user`, ver `auth.py`):
     1. Crie um **App registration** no Azure/Entra, tipo *Web*, com
        redirect URI `https://SEU_APP.streamlit.app/oauth2callback`.
     2. Marque a Enterprise Application correspondente com
        **"Assignment required = Yes"** e atribua só os usuários/grupos
        que podem acessar.
     3. Preencha em `secrets.toml` (ver `secrets.example.toml`):
        ```toml
        [auth]
        redirect_uri = "https://SEU_APP.streamlit.app/oauth2callback"
        cookie_secret = "SEGREDO_LONGO_ALEATORIO"

        [auth.microsoft]
        client_id = "..."
        client_secret = "..."
        server_metadata_url = "https://login.microsoftonline.com/SEU_TENANT_ID/v2.0/.well-known/openid-configuration"
        ```
     4. Defina `AUTHORIZED_EMAILS` (lista separada por vírgula) - 2ª camada
        de allowlist dentro do próprio app: mesmo quem loga com sucesso no
        Entra só entra se o e-mail estiver nessa lista.
  3. **`MOTORVIEW_REQUIRE_AUTH = "true"`** - ative isso no deploy de
     produção. Sem essa flag, se alguém esquecer de configurar `[auth]`
     por engano, o app sobe em modo aberto (só com um aviso). Com a flag
     ativa e `[auth]` ausente, o app **bloqueia tudo** (`st.stop()`) em vez
     de abrir por acidente - fail-closed.

## Limitação importante (plano gratuito)

O Streamlit Community Cloud grátis **hiberna** o app depois de um tempo sem
acesso, e o disco (onde fica o `data/motorview.db`) é recriado do zero a
cada novo deploy/hibernação longa. Ou seja, nessa demo:

- Enquanto o app está "acordado", ele recebe e grava tudo em tempo real
  normalmente.
- Se hibernar, ele perde a conexão MQTT; ao reabrir, reconecta e volta a
  gravar normalmente, mas o que foi publicado durante o período hibernado
  **não é recuperado no dashboard** (fica só no log local do gateway, em
  `gateway/data/motorview_gateway.db`, no próprio Raspberry Pi).

Para produção de verdade (histórico contínuo, sem lacunas), duas opções,
ambas sem precisar tocar em `app.py` (só em `db.py`, mesmo ponto de troca
usado no ProdView):

1. **Base persistente na nuvem**: trocar `get_conn()` em `db.py` por uma
   conexão Postgres (ex.: [Supabase](https://supabase.com) ou
   [Neon](https://neon.tech), ambos com free tier) - os dados sobrevivem a
   qualquer hibernação/redeploy. Recomendado especialmente por causa do
   `current_fast` (~2 msg/s por inversor gera bastante linha por dia).
2. **Worker de ingestão sempre ativo**: rodar `mqtt_ingest.py` como um
   processo separado e sempre ligado (um serviço pequeno em
   Render/Railway/VPS, ou até no próprio Raspberry Pi) gravando na mesma
   base Postgres - garante zero perda mesmo com o Streamlit dormindo.

## Estrutura

```
dashboard/
  app.py                       # UI Streamlit (menu em cards: Visão Geral,
                                # Motores, Corrente, Falhas, Histórico,
                                # Conectividade, Relatórios)
  db.py                        # camada de dados (SQLite agora -> Postgres depois)
  mqtt_ingest.py                # assinante MQTT em background, grava no banco
  auth.py                       # login Microsoft (st.login) + allowlist
  config.py                     # lê credenciais MQTT/auth de st.secrets / .env
  requirements.txt
  .streamlit/
    config.toml                 # tema (mesma paleta do ProdView)
    secrets.example.toml         # modelo (só placeholders) de MQTT + auth + allowlist
  data/motorview.db             # criado automaticamente na 1ª execução
```
