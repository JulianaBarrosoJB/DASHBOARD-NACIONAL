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
    for permitido. Detalhes de configuração (nomes de variável, o que
    falta ajustar) só aparecem com MOTORVIEW_DEBUG=true - um visitante
    comum nunca vê pista nenhuma de infraestrutura interna."""
    if not config.auth_configured():
        if config.require_auth():
            # MOTORVIEW_REQUIRE_AUTH=true e faltam os Secrets de [auth]:
            # falha fechada em vez de abrir o painel por engano em produção.
            if config.debug_mode():
                st.error(
                    "MOTORVIEW_REQUIRE_AUTH está ativado, mas os Secrets `[auth]`/`[auth.microsoft]` "
                    "não foram configurados. O acesso fica bloqueado até isso ser corrigido "
                    "(veja o README do dashboard)."
                )
            else:
                st.error("Acesso indisponível no momento.")
            st.stop()
        if config.debug_mode():
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

    if config.require_auth() and not allowlist:
        # REQUIRE_AUTH=true + allowlist vazia (erro de configuração) = bloqueia
        # todo mundo, em vez de deixar qualquer usuário autenticado entrar.
        if config.debug_mode():
            st.error(
                "MOTORVIEW_REQUIRE_AUTH está ativado, mas AUTHORIZED_EMAILS está vazio ou "
                "não configurado. Por segurança, o acesso fica bloqueado para todos até a "
                "allowlist ser preenchida (veja o README do dashboard)."
            )
        else:
            st.error("Acesso indisponível no momento.")
        st.stop()

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


def current_user() -> dict:
    """Info do usuário pro cabeçalho do app.py: {logged_in, name, email}.
    Em modo aberto (auth não configurada) logged_in vem False - app.py
    decide o que mostrar nesse caso (ex.: "sessão local/dev")."""
    if not config.auth_configured() or not _user_attr("is_logged_in", False):
        return {"logged_in": False, "name": None, "email": None}
    return {
        "logged_in": True,
        "name": _user_attr("name") or _user_attr("email") or "Usuário",
        "email": _user_attr("email"),
    }


def logout_button(key: str = "motorview_logout_btn") -> bool:
    return st.button("Sair", key=key)
