# ProdView — versão web (Python) — ENDTECH · Nacional Gás

Base funcional do ProdView, feita em [Streamlit](https://streamlit.io) para apresentação
rápida. Visual no estilo Power BI (cards claros, gauges, rankings), com a identidade
ENDTECH e paleta azul/vermelho do setor de gás. É um software de verdade: menu
totalmente no topo (sem barra lateral), botões de ação, muitos gráficos de produção e
um banco de dados real por trás (SQLite local, pronto para ser trocado pela base
definitiva).

> **Sobre integrar o Power BI de verdade**: dá para embutir um relatório Power BI real
> de duas formas — (1) um link de **"Publicar na Web"** do próprio Power BI, inserido
> num iframe (simples, mas o relatório fica acessível a quem tiver o link); ou (2)
> **Power BI Embedded** via API, que exige um workspace Pro/Premium e um *App
> Registration* no Azure AD (tenant ID, client ID, client secret, workspace ID, report
> ID). Por enquanto o dashboard só *imita* visualmente o Power BI — quando você tiver
> um desses prontos, me manda os dados/credenciais que eu faço a integração de verdade.

## Como rodar

```bash
cd prodview
pip install -r requirements.txt
streamlit run app.py
```

Abre em `http://localhost:8501`. Na primeira execução o banco `data/prodview.db` é
criado e populado automaticamente com dados simulados (30 dias de histórico + leituras
do dia), então já dá pra apresentar sem nenhum passo manual extra.

## O que já tem

- **Menu todo no topo**: sem barra lateral — marca ENDTECH, status do banco, turno,
  botões de ação e as abas ficam no cabeçalho.
- **Abas**: Visão Geral, Produção, Linhas, Conectividade, Relatórios.
- **Botões de ação**: atualizar dados (grava uma nova leitura no banco, como se
  viesse do CLP), regerar dados de demonstração, registrar leitura/parada manual
  por linha, simular queda de link com failover automático, exportar relatório em
  **CSV e PDF**.
- **Cards estilo Power BI**: painel de produção (hoje/semana/mês + meta do dia em
  círculo), ranking de linhas por meta atingida, top causas de parada.
- **Gráficos de produção** (Plotly, interativos — zoom, hover, exportar PNG):
  gauges de OEE/Disponibilidade/Performance/Qualidade, produção acumulada do dia,
  participação por linha, produção total por linha, produção diária histórica, OEE
  ao longo do tempo, Pareto de causas de parada, mapa de calor de minutos parados
  por linha/categoria, velocidade por linha.
- **Relatório em PDF** ([`report_pdf.py`](report_pdf.py)): gerado com ReportLab,
  com KPIs do período, produção por linha, detalhe diário e principais causas de
  parada — pronto para mostrar ou enviar ao cliente.
- **Banco de dados**: SQLite local (`data/prodview.db`) com tabelas `lines`,
  `readings`, `daily_production` (incluindo Disponibilidade/Performance/Qualidade),
  `downtime_events`, `connectivity_log`. Toda a lógica de acesso está isolada em
  [`db.py`](db.py).

## Publicar online (link para abrir no celular)

O jeito mais simples e gratuito, feito sob medida pra apps Streamlit:

1. **Suba o projeto pro GitHub** (o repositório git local já está preparado, na raiz
   de `DASHBOARD NACIONAL`):
   ```bash
   git remote add origin https://github.com/SEU-USUARIO/prodview-endtech.git
   git branch -M main
   git push -u origin main
   ```
   (crie o repositório vazio antes em github.com/new — pode ser privado).
2. Entre em **[share.streamlit.io](https://share.streamlit.io)**, faça login com o
   GitHub e clique em **"New app"**.
3. Selecione o repositório, branch `main`, e em **"Main file path"** informe
   `prodview/app.py`.
4. Clique em **Deploy**. Em 1–2 minutos você recebe um link público (algo como
   `https://prodview-endtech.streamlit.app`) que abre normalmente no celular, em
   qualquer rede.

> **Atenção**: como o banco é o SQLite local de demonstração, ele é recriado do zero
> a cada novo deploy/hibernação do app gratuito (fica sem acesso após um tempo
> ocioso e "acorda" no próximo acesso, ~30s). Ótimo pra demonstrar; quando ligar na
> base de dados real (seção abaixo), os dados passam a ser persistentes de verdade.

## Conectando a base de dados real depois

Tudo que fala com o banco passa por `db.py`. Para apontar para a base definitiva
(SQL Server, PostgreSQL, MySQL, uma API do CLP, um broker OPC-UA/MQTT alimentando
um banco, etc.), só é preciso:

1. Trocar a função `get_conn()` para abrir a conexão real (ex.: `pyodbc.connect(...)`,
   `psycopg2.connect(...)`).
2. Ajustar as queries SQL das funções `df_*` se os nomes de tabela/coluna forem
   diferentes (a interface — os nomes das funções e o formato dos DataFrames que
   elas retornam — pode continuar igual).
3. Nada no `app.py` precisa mudar, porque ele só conhece as funções públicas do
   `db.py`.

## Estrutura

```
prodview/
  app.py                 # app Streamlit (UI, menu no topo, cards, gráficos)
  db.py                  # camada de dados (SQLite agora → base real depois)
  report_pdf.py          # geração do relatório em PDF (ReportLab)
  requirements.txt
  .streamlit/config.toml # tema (claro, estilo Power BI, cores ENDTECH/Nacional Gás)
  data/prodview.db       # criado automaticamente na 1ª execução
```

## Próximos passos sugeridos

- Autenticação de usuários (login por turno/operador).
- Conexão com a base real de produção (ver seção acima).
- Integração real com Power BI (Publish to Web ou Power BI Embedded — ver nota acima).
- Alertas configuráveis (ex.: OEE abaixo de meta, linha parada há X min).
- Logo real da ENDTECH (hoje é um monograma "ET" provisório).
