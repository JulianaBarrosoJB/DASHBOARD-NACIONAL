"""
MotorView Dashboard - autenticação/autorização
==================================================
Usa a autenticação nativa OIDC do Streamlit (st.login/st.logout/st.user),
com Microsoft Entra ID como provedor. Só fica realmente ATIVA quando o
bloco [auth]/[auth.microsoft] existir em secrets.toml (ver
.streamlit/secrets.example.toml e o README) - sem isso, roda em modo
"aviso" (banner, sem bloquear), pra não travar quem está testando local
antes de configurar o Entra.

Duas camadas de autorização, como pedido:
  1. Microsoft Entra Enterprise Application com "Assignment required = Yes"
     (só usuários/grupos explicitamente atribuídos no Azure conseguem
     sequer completar o login).
  2. Allowlist própria do app (AUTHORIZED_EMAILS em secrets/env) - mesmo
     quem loga com sucesso no Entra só entra se o e-mail estiver nela.
"""

import streamlit as st

import config


def _user_attr(name: str, default=None):
    """st.user aceita acesso tipo objeto (st.user.email) - isolado aqui
    pra não espalhar getattr por todo lugar."""
    return getattr(st.user, name, default)


def require_login():
    """Chamar como a PRIMEIRA coisa em app.py, antes de qualquer outro
    st.write/menu/etc. Interrompe a execução (st.stop()) se o acesso não
    for permitido."""
    if not config.auth_configured():
        if config.require_auth():
            # MOTORVIEW_REQUIRE_AUTH=true e faltam os Secrets de [auth]:
            # falha fechada em vez de abrir o painel por engano em produção.
            st.error(
                "MOTORVIEW_REQUIRE_AUTH está ativado, mas os Secrets `[auth]`/`[auth.microsoft]` "
                "não foram configurados. O acesso fica bloqueado até isso ser corrigido "
                "(veja o README do dashboard)."
            )
            st.stop()
        st.info(
            "Autenticação Microsoft ainda não configurada (Secrets `[auth]` ausentes) - "
            "rodando em modo aberto, só para desenvolvimento. Configure antes de publicar "
            "(veja o README do dashboard)."
        )
        return

    if not _user_attr("is_logged_in", False):
        _render_login_screen()
        st.stop()

    email = (_user_attr("email") or "").strip().lower()
    allowlist = config.authorized_emails()
    if allowlist and email not in allowlist:
        _render_access_denied(email)
        st.stop()


def _render_login_screen():
    st.markdown("## MotorView")
    st.write("Faça login com sua conta Microsoft corporativa para continuar.")
    if st.button("Entrar com Microsoft", type="primary"):
        st.login("microsoft")


def _render_access_denied(email: str):
    st.error(
        f"Acesso negado para **{email or 'usuário desconhecido'}**. "
        "Fale com o administrador do MotorView para solicitar acesso."
    )
    if st.button("Sair"):
        st.logout()


def render_user_badge():
    """Nome do usuário logado + botão de sair, pro cabeçalho do app.
    Não faz nada se a autenticação ainda não estiver configurada."""
    if not config.auth_configured():
        return
    name = _user_attr("name") or _user_attr("email") or "Usuário"
    col_a, col_b = st.columns([5, 1])
    with col_b:
        st.caption(name)
        if st.button("Sair", key="motorview_logout_btn"):
            st.logout()
