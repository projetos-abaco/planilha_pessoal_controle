import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Prova de Superendividamento", page_icon="⚖️", layout="wide")

# --- CONEXÃO COM O GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credenciais = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(credenciais)
        planilha = client.open_by_url(st.secrets["url_planilha"])
        return planilha
    except Exception as e:
        return f"{type(e).__name__}: {str(e)}" 

planilha = conectar_google_sheets()

if isinstance(planilha, str):
    st.error(f"⚠️ Erro real do Google: {planilha}")
    st.stop()

# --- BARRA LATERAL (SELEÇÃO DE CLIENTE) ---
st.sidebar.header("👥 Seleção de Cliente")
abas = planilha.worksheets()
nomes_abas = [aba.title for aba in abas]

if 'cliente_selecionado' not in st.session_state or st.session_state.cliente_selecionado not in nomes_abas:
    st.session_state.cliente_selecionado = nomes_abas[0]

cliente_selecionado = st.sidebar.selectbox(
    "Cliente Ativo (Aba):", 
    nomes_abas, 
    index=nomes_abas.index(st.session_state.cliente_selecionado)
)
st.session_state.cliente_selecionado = cliente_selecionado
aba_atual = planilha.worksheet(cliente_selecionado)

# --- PUXA OS DADOS DO CLIENTE SELECIONADO ---
st.title(f"⚖️ Diagnóstico de Superendividamento - {cliente_selecionado}")

dados_brutos = aba_atual.get_all_values()
cabecalhos_lanc = ['Data', 'Tipo', 'Categoria', 'Conta/Banco', 'Método de Pagamento', 'Valor', 'Descrição', 'Status']
cabecalhos_cart = ['Data da Compra', 'Cartão', 'Valor Total', 'Categoria', 'Parcelas', 'Descrição', 'Valor da Parcela', 'Parcela Atual', 'Data de Vencimento', 'Status']

linhas_lanc = [linha[:8] for linha in dados_brutos[1:] if len(linha) >= 8 and linha[0] != ""]
linhas_cart = [linha[9:19] for linha in dados_brutos[1:] if len(linha) >= 19 and linha[9] != ""]

df_lanc = pd.DataFrame(linhas_lanc, columns=cabecalhos_lanc)
df_cart = pd.DataFrame(linhas_cart, columns=cabecalhos_cart)

if not df_lanc.empty:
    df_lanc['Data'] = pd.to_datetime(df_lanc['Data'], format="%d/%m/%Y", errors='coerce')
    df_lanc['Valor'] = pd.to_numeric(df_lanc['Valor'], errors='coerce')

if not df_cart.empty:
    df_cart['Data da Compra'] = pd.to_datetime(df_cart['Data da Compra'], format="%d/%m/%Y", errors='coerce')
    df_cart['Data de Vencimento'] = pd.to_datetime(df_cart['Data de Vencimento'], format="%d/%m/%Y", errors='coerce')
    df_cart['Valor Total'] = pd.to_numeric(df_cart['Valor Total'], errors='coerce')
    df_cart['Valor da Parcela'] = pd.to_numeric(df_cart['Valor da Parcela'], errors='coerce')
    df_cart['Parcelas'] = pd.to_numeric(df_cart['Parcelas'], errors='coerce')
    df_cart['Parcela Atual'] = pd.to_numeric(df_cart['Parcela Atual'], errors='coerce')

# --- INÍCIO DO CÓDIGO DA PÁGINA ---
st.markdown("""
Esta ferramenta gera uma comprovação visual baseada na **Lei 14.181/2021**. 
O objetivo é evidenciar a incapacidade financeira do consumidor de arcar com suas dívidas sem comprometer seu **Mínimo Existencial** (gastos fundamentais de sobrevivência).
""")
st.markdown("---")

df_lanc['Mes_Ano'] = pd.to_datetime(df_lanc['Data']).dt.strftime('%m/%Y') if not df_lanc.empty else []
df_cart['Mes_Ano'] = pd.to_datetime(df_cart['Data de Vencimento']).dt.strftime('%m/%Y') if not df_cart.empty else []
todos_meses = sorted(list(set(df_lanc['Mes_Ano'].tolist() + df_cart['Mes_Ano'].tolist())), key=lambda x: pd.to_datetime(x, format='%m/%Y'))

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Parâmetros do Cálculo")
    if not todos_meses:
        st.info("Cadastre dados para selecionar o mês de análise.")
        st.stop()
        
    mes_alvo = st.selectbox("Mês de Referência da Dívida:", todos_meses, help="Selecione o mês onde o déficit é mais severo para apresentar ao juiz.")
    
    minimo_existencial = st.number_input(
        "Mínimo Existencial / Custo de Vida (R$)", 
        value=600.00, step=50.00, 
        help="Insira o limite legal (Ex: Decreto R$ 600) ou o custo real e comprovado de sobrevivência (Moradia, Alimentação, Saúde)."
    )
    
df_lanc_kpi = df_lanc[df_lanc['Mes_Ano'] == mes_alvo]
df_cart_kpi = df_cart[df_cart['Mes_Ano'] == mes_alvo]

total_receitas = df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Receita']['Valor'].sum() if not df_lanc_kpi.empty else 0
total_fatura_mes = df_cart_kpi['Valor da Parcela'].sum() if not df_cart_kpi.empty else 0

margem_repactuacao = total_receitas - minimo_existencial
saldo_final_juiz = margem_repactuacao - total_fatura_mes

with col2:
    st.subheader("Auditoria de Renda e Margem Disponível")
    
    fig_cascata = go.Figure(go.Waterfall(
        name="Auditoria de Renda", orientation="v",
        measure=["relative", "relative", "total", "relative", "total"],
        x=["Renda Total", "Mínimo Existencial", "Margem p/ Negociação", "Dívida (Cartões)", "Situação Real"],
        textposition="outside",
        text=[
            f"R$ {total_receitas:,.2f}", 
            f"-R$ {minimo_existencial:,.2f}", 
            f"R$ {margem_repactuacao:,.2f}", 
            f"-R$ {total_fatura_mes:,.2f}", 
            f"R$ {saldo_final_juiz:,.2f}"
        ],
        y=[total_receitas, -minimo_existencial, margem_repactuacao, -total_fatura_mes, saldo_final_juiz],
        connector={"line": {"color": "rgba(63, 63, 63, 0.5)", "width": 2}},
        decreasing={"marker": {"color": "#d62728"}},
        increasing={"marker": {"color": "#2ca02c"}},
        totals={"marker": {"color": "#1f77b4"}},
    ))
    
    fig_cascata.update_layout(
        title=f"Impacto das Dívidas vs. Proteção Existencial ({mes_alvo})",
        showlegend=False,
        height=500,
        margin=dict(t=50, l=20, r=20, b=20)
    )
    
    st.plotly_chart(fig_cascata, use_container_width=True)

st.markdown("---")

st.subheader("🤝 Simulador de Plano de Pagamento (Art. 104-A, Lei 14.181/21)")
st.markdown("Análise de viabilidade de repactuação da dívida global do cliente no prazo máximo de 5 anos.")

divida_global = df_cart[df_cart['Status'] == 'A Pagar']['Valor da Parcela'].sum() if not df_cart.empty else 0
st.metric("Dívida Global Acumulada (Principal)", f"R$ {divida_global:,.2f}")

if divida_global > 0 and margem_repactuacao > 0:
    col_sim1, col_sim2, col_sim3 = st.columns(3)
    
    prazos = [36, 48, 60]
    colunas = [col_sim1, col_sim2, col_sim3]
    
    for prazo, col in zip(prazos, colunas):
        parcela_proposta = divida_global / prazo
        viavel = parcela_proposta <= margem_repactuacao
        
        with col:
            st.markdown(f"#### Proposta em {prazo} meses")
            st.markdown(f"**Parcela Simples:** R$ {parcela_proposta:,.2f}")
            
            if viavel:
                sobra = margem_repactuacao - parcela_proposta
                st.success(f"✅ **Viável**\nA parcela cabe na Margem de R$ {margem_repactuacao:,.2f}.\n\n*Folga no orçamento: R$ {sobra:,.2f}*")
            else:
                falta = parcela_proposta - margem_repactuacao
                st.error(f"❌ **Inviável**\nA parcela ultrapassa a Margem de R$ {margem_repactuacao:,.2f}.\n\n*Déficit contínuo: R$ {falta:,.2f}*")
elif divida_global > 0 and margem_repactuacao <= 0:
    st.error(f"⚠️ **Atenção:** O cliente não possui Margem de Repactuação positiva (R$ {margem_repactuacao:,.2f}). Não é possível propor parcelamento bancário sem antes reduzir o custo do Mínimo Existencial ou aumentar a renda.")
else:
    st.info("Não há dívidas pendentes registradas para simulação de acordo.")