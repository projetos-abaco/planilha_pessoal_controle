import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Prova de Superendividamento", page_icon="⚖️", layout="wide")

def formatar_br(valor): return f"{valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

@st.cache_resource
def conectar_google_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credenciais = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(credenciais)
        return client.open_by_url(st.secrets["url_planilha"])
    except Exception as e: return f"{type(e).__name__}: {str(e)}" 

planilha = conectar_google_sheets()
if isinstance(planilha, str): st.stop()

st.sidebar.header("👥 Seleção de Cliente")
abas = planilha.worksheets()
nomes_abas = [aba.title for aba in abas]

if 'cliente_selecionado' not in st.session_state or st.session_state.cliente_selecionado not in nomes_abas:
    st.session_state.cliente_selecionado = nomes_abas[0]

cliente_selecionado = st.sidebar.selectbox("Cliente Ativo (Aba):", nomes_abas, index=nomes_abas.index(st.session_state.cliente_selecionado))
st.session_state.cliente_selecionado = cliente_selecionado
aba_atual = planilha.worksheet(cliente_selecionado)

st.title(f"⚖️ Diagnóstico de Superendividamento (Lei 14.181/21) - {cliente_selecionado}")

dados_brutos = aba_atual.get_all_values()
linhas_lanc = [l[:8] for l in dados_brutos[1:] if len(l + [""]*(19-len(l))) >= 8 and l[0] != ""]
linhas_cart = [l[9:19] for l in dados_brutos[1:] if len(l + [""]*(19-len(l))) >= 19 and l[9] != ""]
df_lanc = pd.DataFrame(linhas_lanc, columns=['Data', 'Tipo', 'Categoria', 'Conta/Banco', 'Método de Pagamento', 'Valor', 'Descrição', 'Status'])
df_cart = pd.DataFrame(linhas_cart, columns=['Data da Compra', 'Cartão', 'Valor Total', 'Categoria', 'Parcelas', 'Descrição', 'Valor da Parcela', 'Parcela Atual', 'Data de Vencimento', 'Status'])

def converter_moeda(val):
    if pd.isna(val) or val == "": return None
    v = str(val).replace('R$', '').replace(' ', '')
    if ',' in v and '.' in v: v = v.replace('.', '').replace(',', '.') if v.rfind(',') > v.rfind('.') else v.replace(',', '')
    elif ',' in v: v = v.replace(',', '.')
    return v

if not df_lanc.empty:
    df_lanc['Data'] = pd.to_datetime(df_lanc['Data'], format="%d/%m/%Y", errors='coerce')
    df_lanc['Valor'] = pd.to_numeric(df_lanc['Valor'].apply(converter_moeda), errors='coerce')
if not df_cart.empty:
    df_cart['Data de Vencimento'] = pd.to_datetime(df_cart['Data de Vencimento'], format="%d/%m/%Y", errors='coerce')
    df_cart['Valor da Parcela'] = pd.to_numeric(df_cart['Valor da Parcela'].apply(converter_moeda), errors='coerce')

df_lanc['Mes_Ano'] = pd.to_datetime(df_lanc['Data']).dt.strftime('%m/%Y') if not df_lanc.empty else []
df_cart['Mes_Ano'] = pd.to_datetime(df_cart['Data de Vencimento']).dt.strftime('%m/%Y') if not df_cart.empty else []
todos_meses = sorted(list(set(df_lanc['Mes_Ano'].tolist() + df_cart['Mes_Ano'].tolist())), key=lambda x: pd.to_datetime(x, format='%m/%Y'))

# --- FILTROS DA LEI 14.181/2021 ---
categorias_inelegiveis = ["Financiamento (Garantia Real/Imóvel)", "Tributos / Impostos / Multas", "Pensão Alimentícia Paga", "Crédito Rural / Empresarial", "Artigos de Luxo (Má-fé)"]

st.markdown("---")
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Parâmetros do Cálculo")
    if not todos_meses: st.stop()
    mes_alvo = st.selectbox("Mês de Referência:", todos_meses)
    minimo_existencial = st.number_input("Mínimo Existencial (R$)", value=600.00, step=50.00)
    
df_lanc_kpi = df_lanc[df_lanc['Mes_Ano'] == mes_alvo]
df_cart_kpi = df_cart[df_cart['Mes_Ano'] == mes_alvo]

total_receitas = df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Receita']['Valor'].sum() if not df_lanc_kpi.empty else 0

df_despesas = df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Despesa']
dividas_inelegiveis = df_despesas[df_despesas['Categoria'].isin(categorias_inelegiveis)]['Valor'].abs().sum() if not df_despesas.empty else 0
dividas_elegiveis = df_despesas[~df_despesas['Categoria'].isin(categorias_inelegiveis)]['Valor'].abs().sum() if not df_despesas.empty else 0
cartoes_elegiveis = df_cart_kpi['Valor da Parcela'].sum() if not df_cart_kpi.empty else 0
total_dividas_negociaveis = dividas_elegiveis + cartoes_elegiveis

renda_disponivel = total_receitas - dividas_inelegiveis
margem_repactuacao = renda_disponivel - minimo_existencial
saldo_final_juiz = margem_repactuacao - total_dividas_negociaveis

with col2:
    st.subheader("Auditoria de Renda e Margem (CDC Art. 54-A)")
    fig_cascata = go.Figure(go.Waterfall(
        name="Auditoria", orientation="v", measure=["relative", "relative", "relative", "total", "relative", "total"],
        x=["Renda Total", "Dívidas INEGOCIÁVEIS", "Mínimo Existencial", "Margem p/ Acordo", "Dívidas Negociáveis", "Situação Real"],
        textposition="outside",
        text=[f"R$ {formatar_br(total_receitas)}", f"-R$ {formatar_br(dividas_inelegiveis)}", f"-R$ {formatar_br(minimo_existencial)}", f"R$ {formatar_br(margem_repactuacao)}", f"-R$ {formatar_br(total_dividas_negociaveis)}", f"R$ {formatar_br(saldo_final_juiz)}"],
        y=[total_receitas, -dividas_inelegiveis, -minimo_existencial, margem_repactuacao, -total_dividas_negociaveis, saldo_final_juiz],
        connector={"line": {"color": "rgba(63, 63, 63, 0.5)", "width": 2}}, decreasing={"marker": {"color": "#d62728"}}, increasing={"marker": {"color": "#2ca02c"}}, totals={"marker": {"color": "#1f77b4"}}
    ))
    fig_cascata.update_layout(title=f"Impacto das Dívidas vs. Proteção Existencial", showlegend=False, height=500, separators=".,")
    st.plotly_chart(fig_cascata, use_container_width=True)
    st.caption("*As dívidas inegociáveis (Tributos, Pensão, Financiamentos com Garantia) são descontadas antes da margem de negociação, conforme Art. 104-A, CDC.*")

st.markdown("---")

# --- NOVO MÓDULO: AUDITORIA INSS (IN 138/2022) ---
st.subheader("🔎 Auditoria de Margem Consignável (INSS IN 138/2022)")
st.markdown("Verificação de abusividade de crédito descontado em folha, limite de linhas e teto de comprometimento.")

col_in1, col_in2 = st.columns([1, 2])
with col_in1:
    tipo_beneficio = st.radio("Tipo de Benefício:", ["Aposentado/Pensionista RGPS (Teto 45%)", "BPC/LOAS ou RMV (Teto 35%)"])
    # O valor padrão é a receita lançada na planilha, mas o usuário pode editar na tela.
    renda_bruta_inss = st.number_input("Renda Bruta do Benefício (R$)", value=float(total_receitas), step=100.0)
    descontos_inss = st.number_input("Descontos Obrigatórios (IRPF, etc.)", value=0.0)
    base_calculo_inss = renda_bruta_inss - descontos_inss

with col_in2:
    is_bpc = "BPC" in tipo_beneficio
    teto_emp = 0.30 if is_bpc else 0.35
    teto_cartao = 0.05 if is_bpc else 0.10 # BPC = 5% (um cartão). RGPS = 5% RMC + 5% RCC.
    
    gastos_emp = df_despesas[df_despesas['Categoria'] == 'Empréstimo Consignado INSS']['Valor'].abs().sum() if not df_despesas.empty else 0
    gastos_rmc = df_despesas[df_despesas['Categoria'] == 'Cartão de Crédito Consignado (RMC)']['Valor'].abs().sum() if not df_despesas.empty else 0
    gastos_rcc = df_despesas[df_despesas['Categoria'] == 'Cartão de Benefício Consignado (RCC)']['Valor'].abs().sum() if not df_despesas.empty else 0
    gastos_cartoes_consig = gastos_rmc + gastos_rcc
    
    # Nova Lógica de Exibição Inteligente
    if base_calculo_inss <= 0:
        if gastos_emp > 0 or gastos_cartoes_consig > 0:
            st.warning("⚠️ **Identificamos descontos consignados na planilha!** Para rodar a auditoria de abusividade, digite a Renda Bruta do Benefício no campo ao lado.")
        else:
            st.info("Informe a Renda Bruta do Benefício ao lado para simular o limite consignável do cliente.")
    else:
        limite_emp_reais = base_calculo_inss * teto_emp
        limite_cartao_reais = base_calculo_inss * teto_cartao
        
        st.markdown(f"**Base de Cálculo Líquida:** R$ {formatar_br(base_calculo_inss)}")
        
        # Auditoria Empréstimo Pessoal
        if gastos_emp > limite_emp_reais:
            st.error(f"🚨 **ABUSIVIDADE DETECTADA (Empréstimo Pessoal):** O banco está descontando R$ {formatar_br(gastos_emp)}, mas a Lei limita a R$ {formatar_br(limite_emp_reais)} ({int(teto_emp*100)}%). Indício de crédito abusivo.")
        elif gastos_emp > 0:
            st.success(f"✅ **Empréstimo Pessoal:** Dentro da margem legal de {int(teto_emp*100)}% (Gasto: R$ {formatar_br(gastos_emp)} | Limite: R$ {formatar_br(limite_emp_reais)})")
        else:
            st.info(f"⚪ **Empréstimo Pessoal:** Nenhum desconto registrado. (Limite disponível: R$ {formatar_br(limite_emp_reais)})")
            
        # Auditoria Cartões (RMC / RCC)
        if gastos_cartoes_consig > limite_cartao_reais or (is_bpc and gastos_rmc > 0 and gastos_rcc > 0):
            motivo = "O cliente possui as duas modalidades ativas, sendo permitido apenas UMA para BPC" if (is_bpc and gastos_rmc > 0 and gastos_rcc > 0) else f"O desconto ultrapassa o teto legal de {int(teto_cartao*100)}%"
            st.error(f"🚨 **ABUSIVIDADE DETECTADA (Cartões Consignados):** {motivo}. (Gasto: R$ {formatar_br(gastos_cartoes_consig)} | Limite: R$ {formatar_br(limite_cartao_reais)})")
        elif gastos_cartoes_consig > 0:
            st.success(f"✅ **Cartões Consignados:** Dentro das normativas (Gasto: R$ {formatar_br(gastos_cartoes_consig)} | Limite Global: R$ {formatar_br(limite_cartao_reais)})")
        else:
            st.info(f"⚪ **Cartões Consignados:** Nenhum desconto registrado. (Limite disponível: R$ {formatar_br(limite_cartao_reais)})")
            
        st.caption("💡 *Nota Legal (IN 138/2022): O INSS limita a 13 contratos simultâneos de empréstimo pessoal e o prazo de parcelamento em até 84 meses. Benefícios novos ficam bloqueados nos primeiros 90 dias.*")

st.markdown("---")
st.subheader("🤝 Simulador de Plano de Pagamento (Dívidas Negociáveis)")
st.metric("Dívida Negociável Acumulada (Principal + A Vencer)", f"R$ {formatar_br(total_dividas_negociaveis)}")

if total_dividas_negociaveis > 0 and margem_repactuacao > 0:
    col_sim1, col_sim2, col_sim3 = st.columns(3)
    for prazo, col in zip([36, 48, 60], [col_sim1, col_sim2, col_sim3]):
        parcela_proposta = total_dividas_negociaveis / prazo
        viavel = parcela_proposta <= margem_repactuacao
        with col:
            st.markdown(f"#### Proposta em {prazo} meses")
            st.markdown(f"**Parcela Simples:** R$ {formatar_br(parcela_proposta)}")
            if viavel: st.success(f"✅ **Viável** (Folga: R$ {formatar_br(margem_repactuacao - parcela_proposta)})")
            else: st.error(f"❌ **Inviável** (Déficit: R$ {formatar_br(parcela_proposta - margem_repactuacao)})")
elif total_dividas_negociaveis > 0 and margem_repactuacao <= 0: st.error(f"⚠️ O cliente não possui Margem de Repactuação positiva.")
else: st.info("Não há dívidas pendentes elegíveis para negociação.")