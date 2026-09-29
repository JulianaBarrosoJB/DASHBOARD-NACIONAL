# MotorView Dashboard

App [Streamlit](https://streamlit.io) que assina o MQTT publicado pelo
[gateway](../gateway/README.md) (Raspberry Pi + Modbus RTU) e mostra em tempo
real: corrente por inversor, frequência/rotação/torque, registro de falhas e
histórico com exportação em CSV. Segue a mesma linha visual do
[ProdView](../../prodview/README.md), que serviu de referência.

## Rodar localmente

```bash
cd motorview/dashboard
pip install -r requirements.txt
cp .streamlit/secrets.example.toml .streamlit/secrets.toml   # e edite com os dados do broker
streamlit run app.py
```

Abre em `http://localhost:8501`. Assim que o gateway começar a publicar,
os dados aparecem automaticamente (o app assina o MQTT em background).

## Publicar online (Streamlit Community Cloud)

1. Suba o repositório pro GitHub (mesmo passo do ProdView, veja
   [prodview/README.md](../../prodview/README.md#publicar-online-link-para-abrir-no-celular)).
2. Em [share.streamlit.io](https://share.streamlit.io), **New app**, escolha
   o repositório/branch e em **"Main file path"** informe `motorview/dashboard/app.py`.
3. Antes (ou depois) de dar Deploy, abra **Settings -> Secrets** do app e
   cole o conteúdo de [`.streamlit/secrets.example.toml`](.streamlit/secrets.example.toml)
   já com host/usuário/senha reais do broker MQTT (o mesmo broker para o
   qual o gateway do Raspberry Pi publica).
4. Deploy. Em 1-2 minutos você tem um link público - abre no celular também.

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
   qualquer hibernação/redeploy.
2. **Worker de ingestão sempre ativo**: rodar `mqtt_ingest.py` como um
   processo separado e sempre ligado (um serviço pequeno em
   Render/Railway/VPS, ou até no próprio Raspberry Pi) gravando na mesma
   base Postgres - garante zero perda mesmo com o Streamlit dormindo.

## Estrutura

```
dashboard/
  app.py                       # UI Streamlit (abas: Visão Geral, Corrente em
                                # Tempo Real, Falhas, Histórico)
  db.py                        # camada de dados (SQLite agora -> Postgres depois)
  mqtt_ingest.py                # assinante MQTT em background, grava no banco
  config.py                     # lê credenciais MQTT de st.secrets / .env
  requirements.txt
  .streamlit/
    config.toml                 # tema (mesma paleta do ProdView)
    secrets.example.toml         # modelo de credenciais MQTT
  data/motorview.db             # criado automaticamente na 1ª execução
```
