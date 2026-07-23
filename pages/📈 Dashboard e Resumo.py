import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Dashboard Financeiro", page_icon="📈", layout="wide")

# Função para formatar os valores no padrão brasileiro (R$ 2.000,00)
def formatar_br(valor):
    return f"{valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

@st.cache_resource
def conectar_google_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credenciais = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(credenciais)
        return client.open_by_url(st.secrets["url_planilha"])
    except Exception as e:
        return f"{type(e).__name__}: {str(e)}" 

planilha = conectar_google_sheets()

if isinstance(planilha, str):
    st.error(f"⚠️ Erro real do Google: {planilha}")
    st.stop()

st.sidebar.header("👥 Seleção de Cliente")
abas = planilha.worksheets()
nomes_abas = [aba.title for aba in abas]

if 'cliente_selecionado' not in st.session_state or st.session_state.cliente_selecionado not in nomes_abas:
    st.session_state.cliente_selecionado = nomes_abas[0]

cliente_selecionado = st.sidebar.selectbox("Cliente Ativo (Aba):", nomes_abas, index=nomes_abas.index(st.session_state.cliente_selecionado))
st.session_state.cliente_selecionado = cliente_selecionado
aba_atual = planilha.worksheet(cliente_selecionado)

st.title(f"📈 Dashboard e Resumo - {cliente_selecionado}")

dados_brutos = aba_atual.get_all_values()
cabecalhos_lanc = ['Data', 'Tipo', 'Categoria', 'Conta/Banco', 'Método de Pagamento', 'Valor', 'Descrição', 'Status']
cabecalhos_cart = ['Data da Compra', 'Cartão', 'Valor Total', 'Categoria', 'Parcelas', 'Descrição', 'Valor da Parcela', 'Parcela Atual', 'Data de Vencimento', 'Status']

linhas_lanc, linhas_cart = [], []
for linha in dados_brutos[1:]:
    linha_completa = linha + [""] * (19 - len(linha))
    if linha_completa[0] != "": linhas_lanc.append(linha_completa[:8])
    if linha_completa[9] != "": linhas_cart.append(linha_completa[9:19])

df_lanc = pd.DataFrame(linhas_lanc, columns=cabecalhos_lanc)
df_cart = pd.DataFrame(linhas_cart, columns=cabecalhos_cart)

def converter_moeda(val):
    if pd.isna(val) or val == "": return None
    v = str(val).replace('R$', '').replace(' ', '')
    if ',' in v and '.' in v:
        v = v.replace('.', '').replace(',', '.') if v.rfind(',') > v.rfind('.') else v.replace(',', '')
    elif ',' in v: v = v.replace(',', '.')
    return v

if not df_lanc.empty:
    df_lanc['Data'] = pd.to_datetime(df_lanc['Data'], format="%d/%m/%Y", errors='coerce')
    df_lanc['Valor'] = pd.to_numeric(df_lanc['Valor'].apply(converter_moeda), errors='coerce')

if not df_cart.empty:
    df_cart['Data da Compra'] = pd.to_datetime(df_cart['Data da Compra'], format="%d/%m/%Y", errors='coerce')
    df_cart['Data de Vencimento'] = pd.to_datetime(df_cart['Data de Vencimento'], format="%d/%m/%Y", errors='coerce')
    df_cart['Valor Total'] = pd.to_numeric(df_cart['Valor Total'].apply(converter_moeda), errors='coerce')
    df_cart['Valor da Parcela'] = pd.to_numeric(df_cart['Valor da Parcela'].apply(converter_moeda), errors='coerce')
    df_cart['Parcelas'] = pd.to_numeric(df_cart['Parcelas'], errors='coerce')
    df_cart['Parcela Atual'] = pd.to_numeric(df_cart['Parcela Atual'], errors='coerce')

df_lanc['Mes_Ano'] = pd.to_datetime(df_lanc['Data']).dt.strftime('%m/%Y') if not df_lanc.empty else []
df_cart['Mes_Ano'] = pd.to_datetime(df_cart['Data de Vencimento']).dt.strftime('%m/%Y') if not df_cart.empty else []
todos_meses = sorted(list(set(df_lanc['Mes_Ano'].tolist() + df_cart['Mes_Ano'].tolist())), key=lambda x: pd.to_datetime(x, format='%m/%Y'))

st.markdown("### 📅 Filtro de Competência (Visão de Caixa)")
filtro_mes_global = st.selectbox("Selecione o mês:", ["Visão Geral (Todos os Meses)"] + todos_meses)

if filtro_mes_global != "Visão Geral (Todos os Meses)":
    df_lanc_kpi = df_lanc[df_lanc['Mes_Ano'] == filtro_mes_global]
    df_cart_kpi = df_cart[df_cart['Mes_Ano'] == filtro_mes_global]
else:
    df_lanc_kpi, df_cart_kpi = df_lanc, df_cart

total_receitas = df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Receita']['Valor'].sum() if not df_lanc_kpi.empty else 0
total_despesas_gerais = df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Despesa']['Valor'].abs().sum() if not df_lanc_kpi.empty else 0
total_fatura_mes = df_cart_kpi['Valor da Parcela'].sum() if not df_cart_kpi.empty else 0
faturas_pagas = df_cart_kpi[df_cart_kpi['Status'] == 'Pago']['Valor da Parcela'].sum() if not df_cart_kpi.empty else 0
saldo_conta = total_receitas - total_despesas_gerais - total_fatura_mes
total_saidas = total_despesas_gerais + total_fatura_mes
taxa_comprometimento = (total_saidas / total_receitas) * 100 if total_receitas > 0 else (100.0 if total_saidas > 0 else 0.0)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Receitas do Período", f"R$ {formatar_br(total_receitas)}")
c2.metric("Despesas Gerais", f"R$ {formatar_br(total_despesas_gerais)}")
c3.metric("Faturas de Cartão", f"R$ {formatar_br(total_fatura_mes)}", f"Pago: R$ {formatar_br(faturas_pagas)}", delta_color="off")
c4.metric("Saldo Líquido", f"R$ {formatar_br(saldo_conta)}")
c5.metric("Renda Comprometida", f"{formatar_br(taxa_comprometimento).replace(',00', '')}%")

st.markdown("---")

st.subheader("1. Nível de Comprometimento da Renda")
if filtro_mes_global == "Visão Geral (Todos os Meses)":
    dados_comp = []
    for m in todos_meses:
        rec_m = df_lanc[(df_lanc['Mes_Ano'] == m) & (df_lanc['Tipo'] == 'Receita')]['Valor'].sum()
        saida_m = df_lanc[(df_lanc['Mes_Ano'] == m) & (df_lanc['Tipo'] == 'Despesa')]['Valor'].abs().sum() + df_cart[df_cart['Mes_Ano'] == m]['Valor da Parcela'].sum()
        tx = (saida_m / rec_m * 100) if rec_m > 0 else (100.0 if saida_m > 0 else 0.0)
        dados_comp.append({'Mes_Ano': m, 'Comprometimento (%)': tx})
    df_comp = pd.DataFrame(dados_comp)
    if not df_comp.empty:
        df_comp['Ordenação'] = pd.to_datetime(df_comp['Mes_Ano'], format='%m/%Y')
        df_comp = df_comp.sort_values('Ordenação')
        fig_comp = px.line(df_comp, x='Mes_Ano', y='Comprometimento (%)', markers=True, title="Evolução do Comprometimento")
        fig_comp.update_traces(text=df_comp['Comprometimento (%)'].apply(lambda x: f'{formatar_br(x).replace(",00","")}%'), textposition="top center", line=dict(color='#d62728', width=3), marker=dict(size=8))
        fig_comp.add_hline(y=100, line_dash="dash", line_color="black", annotation_text="100%")
        fig_comp.update_yaxes(range=[0, max(120, df_comp['Comprometimento (%)'].max() + 10)])
        fig_comp.update_layout(separators=".,")
        st.plotly_chart(fig_comp, use_container_width=True)
else:
    cor_velocimetro = "#d62728" if taxa_comprometimento > 80 else ("#ff7f0e" if taxa_comprometimento > 50 else "#2ca02c")
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number", value=taxa_comprometimento, number={'suffix': "%", 'valueformat': '.1f'},
        domain={'x': [0, 1], 'y': [0, 1]}, title={'text': f"Comprometimento ({filtro_mes_global})", 'font': {'size': 20}},
        gauge={'axis': {'range': [None, max(100, taxa_comprometimento + 20)]}, 'bar': {'color': cor_velocimetro},
               'steps': [{'range': [0, 50], 'color': 'rgba(44, 160, 44, 0.2)'}, {'range': [50, 80], 'color': 'rgba(255, 127, 14, 0.2)'}, {'range': [80, 100], 'color': 'rgba(214, 39, 40, 0.2)'}], 
               'threshold': {'line': {'color': "black", 'width': 4}, 'thickness': 0.75, 'value': 100}}
    ))
    fig_gauge.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20), separators=".,")
    st.plotly_chart(fig_gauge, use_container_width=True)

st.markdown("---")
st.subheader("2. Visão Geral: Fluxo de Caixa")
col_fluxo1, col_fluxo2 = st.columns(2)
with col_fluxo1:
    if not df_lanc_kpi.empty or not df_cart_kpi.empty:
        frames = []
        agrupamento = ['Mes_Ano', 'Tipo'] if filtro_mes_global == "Visão Geral (Todos os Meses)" else ['Tipo']
        if not df_lanc_kpi.empty:
            df_l = df_lanc_kpi.groupby(agrupamento)['Valor'].sum().reset_index()
            df_l['Valor'] = df_l['Valor'].abs()
            frames.append(df_l)
        if not df_cart_kpi.empty:
            grp = ['Mes_Ano', 'Status'] if filtro_mes_global == "Visão Geral (Todos os Meses)" else ['Status']
            df_c = df_cart_kpi.groupby(grp)['Valor da Parcela'].sum().reset_index()
            df_c['Tipo'] = df_c['Status'].apply(lambda x: f'Cartão ({x})')
            df_c = df_c.rename(columns={'Valor da Parcela': 'Valor'}).drop(columns=['Status'])
            frames.append(df_c)
        df_fluxo = pd.concat(frames) if frames else pd.DataFrame()
        if not df_fluxo.empty:
            if 'Mes_Ano' in df_fluxo.columns:
                df_fluxo['Ordenação'] = pd.to_datetime(df_fluxo['Mes_Ano'], format='%m/%Y')
                df_fluxo = df_fluxo.sort_values('Ordenação')
            x_col = 'Mes_Ano' if 'Mes_Ano' in df_fluxo.columns else 'Tipo'
            fig_fluxo = px.bar(df_fluxo, x=x_col, y='Valor', color='Tipo', barmode='group', text_auto=',.2f', color_discrete_map={'Receita': '#2ca02c', 'Despesa': '#ff7f0e', 'Cartão (Pago)': '#1f77b4', 'Cartão (A Pagar)': '#d62728'})
            fig_fluxo.update_traces(textposition='outside', texttemplate='R$ %{y:,.2f}')
            fig_fluxo.update_layout(separators=".,")
            st.plotly_chart(fig_fluxo, use_container_width=True)

with col_fluxo2:
    frames_cat = []
    if not df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Despesa'].empty:
        df_l_cat = df_lanc_kpi[df_lanc_kpi['Tipo'] == 'Despesa'][['Categoria', 'Valor']].copy()
        df_l_cat['Valor'] = df_l_cat['Valor'].abs()
        frames_cat.append(df_l_cat)
    if not df_cart_kpi.empty:
        df_c_cat = df_cart_kpi[['Categoria', 'Valor da Parcela']].copy()
        df_c_cat = df_c_cat.rename(columns={'Valor da Parcela': 'Valor'})
        frames_cat.append(df_c_cat)
    if frames_cat:
        df_cat_agrupado = pd.concat(frames_cat).groupby('Categoria')['Valor'].sum().reset_index()
        fig1 = px.pie(df_cat_agrupado, values='Valor', names='Categoria', hole=0.3)
        fig1.update_traces(textposition='inside', textinfo='percent+label')
        fig1.update_layout(separators=".,")
        st.plotly_chart(fig1, use_container_width=True)
    else: st.info("Nenhuma despesa registrada neste período.")

st.markdown("---")
st.subheader("3. Raio-X dos Cartões: Previsão de Faturas")
if not df_cart.empty:
    df_previsao = df_cart[df_cart['Status'] == 'A Pagar'].copy()
    if not df_previsao.empty:
        col_f1, col_f2 = st.columns(2)
        with col_f1: filtro_cartao = st.selectbox("Filtrar por Cartão:", ["Todos"] + list(df_previsao['Cartão'].unique()))
        with col_f2: filtro_tempo = st.selectbox("Previsão (Meses à frente):", ["Todos", "3 meses", "6 meses", "12 meses"])
        if filtro_cartao != "Todos": df_previsao = df_previsao[df_previsao['Cartão'] == filtro_cartao]
        if filtro_tempo != "Todos":
            periodo_limite = (pd.to_datetime(date.today()) + pd.DateOffset(months=int(filtro_tempo.split()[0]))).to_period('M')
            df_previsao = df_previsao[pd.to_datetime(df_previsao['Data de Vencimento']).dt.to_period('M') <= periodo_limite]
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            if not df_previsao.empty:
                df_prev_agrup = df_previsao.sort_values('Data de Vencimento').groupby('Mes_Ano', sort=False)['Valor da Parcela'].sum().reset_index()
                fig_prev = px.bar(df_prev_agrup, x='Mes_Ano', y='Valor da Parcela', text='Valor da Parcela', title=f"Faturas ({filtro_cartao})", color_discrete_sequence=['#d62728'])
                fig_prev.update_traces(texttemplate='R$ %{text:,.2f}', textposition='outside')
                fig_prev.update_layout(separators=".,")
                st.plotly_chart(fig_prev, use_container_width=True)
            else: st.info("Nenhuma fatura pendente.")
        with col_g2:
            if not df_previsao.empty:
                fig2 = px.bar(df_previsao.groupby('Cartão')['Valor da Parcela'].sum().reset_index(), x='Cartão', y='Valor da Parcela', text='Valor da Parcela', color='Cartão', title="Dívida Restante no Período")
                fig2.update_traces(texttemplate='R$ %{text:,.2f}', textposition='outside')
                fig2.update_layout(separators=".,")
                st.plotly_chart(fig2, use_container_width=True)
    else: st.success("Todas as faturas estão pagas!")
else: st.info("Nenhuma compra registrada.")