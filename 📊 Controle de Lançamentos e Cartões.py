import streamlit as st
import pandas as pd
from datetime import date
import calendar
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Registros Financeiros", page_icon="📝", layout="wide")
st.title("📝 Registros Financeiros (Sincronizado com Nuvem)")

@st.cache_resource
def conectar_google_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credenciais = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(credenciais)
        planilha = client.open_by_url(st.secrets["url_planilha"])
        return planilha
    except Exception as e: return f"{type(e).__name__}: {str(e)}" 

planilha = conectar_google_sheets()

if isinstance(planilha, str):
    st.error(f"⚠️ Erro real do Google: {planilha}")
    st.stop()

st.sidebar.header("👥 Seleção de Cliente")
st.sidebar.markdown("Crie novas abas na sua planilha para adicionar clientes.")
abas = planilha.worksheets()
nomes_abas = [aba.title for aba in abas]

if 'cliente_selecionado' not in st.session_state or st.session_state.cliente_selecionado not in nomes_abas:
    st.session_state.cliente_selecionado = nomes_abas[0]

cliente_selecionado = st.sidebar.selectbox("Cliente Ativo (Aba):", nomes_abas, index=nomes_abas.index(st.session_state.cliente_selecionado))
st.session_state.cliente_selecionado = cliente_selecionado
aba_atual = planilha.worksheet(cliente_selecionado)

dados_brutos = aba_atual.get_all_values()
cabecalhos_lanc = ['Data', 'Tipo', 'Categoria', 'Conta/Banco', 'Método de Pagamento', 'Valor', 'Descrição', 'Status']
cabecalhos_cart = ['Data da Compra', 'Cartão', 'Valor Total', 'Categoria', 'Parcelas', 'Descrição', 'Valor da Parcela', 'Parcela Atual', 'Data de Vencimento', 'Status']

if not dados_brutos:
    aba_atual.update(range_name='A1', values=[cabecalhos_lanc])
    aba_atual.update(range_name='J1', values=[cabecalhos_cart])
    dados_brutos = aba_atual.get_all_values()

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
    if ',' in v and '.' in v: v = v.replace('.', '').replace(',', '.') if v.rfind(',') > v.rfind('.') else v.replace(',', '')
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

st.session_state.lancamentos = df_lanc
st.session_state.cartoes = df_cart
if 'vencimentos_cartoes' not in st.session_state: st.session_state.vencimentos_cartoes = {"Cartão Nubank": 10, "Cartão Santander": 15, "Cartão BB": 20, "Cartão Inter": 25}

def salvar_no_sheets():
    df_l = st.session_state.lancamentos.copy()
    if not df_l.empty: df_l['Data'] = pd.to_datetime(df_l['Data'], errors='coerce').dt.strftime('%d/%m/%Y')
    df_l = df_l.fillna("")
    valores_l = [cabecalhos_lanc] + df_l.values.tolist()
    
    df_c = st.session_state.cartoes.copy()
    if not df_c.empty:
        df_c['Data da Compra'] = pd.to_datetime(df_c['Data da Compra'], errors='coerce').dt.strftime('%d/%m/%Y')
        df_c['Data de Vencimento'] = pd.to_datetime(df_c['Data de Vencimento'], errors='coerce').dt.strftime('%d/%m/%Y')
    df_c = df_c.fillna("")
    valores_c = [cabecalhos_cart] + df_c.values.tolist()
    
    aba_atual.clear()
    aba_atual.update(range_name='A1', values=valores_l)
    aba_atual.update(range_name='J1', values=valores_c)

def calcular_data_vencimento(data_compra_dt, parcela_num, dia_venc_config):
    mes_alvo = data_compra_dt.month + parcela_num
    ano_venc = data_compra_dt.year + (mes_alvo - 1) // 12
    mes_venc = (mes_alvo - 1) % 12 + 1
    u_dia = calendar.monthrange(ano_venc, mes_venc)[1]
    return date(ano_venc, mes_venc, min(dia_venc_config, u_dia))

aba1, aba2 = st.tabs(["📝 Novo Lançamento", "💳 Cartão de Crédito"])

with aba1:
    st.header(f"Lançamento Geral - {cliente_selecionado}")
    data_lanc = st.date_input("Data Inicial", date.today(), format="DD/MM/YYYY")
    tipo = st.selectbox("Tipo", ["Receita", "Despesa"])
    
    if tipo == "Receita":
        opcoes_categoria = ["Benefício INSS", "Salário", "Rendimentos financeiros", "Pensão Recebida", "Outros"]
        opcoes_status = ["Recebido", "A Receber"]
    else:
        # ATENÇÃO AQUI: Categorias mapeadas milimetricamente com a Lei 14.181 e IN 138/2022
        opcoes_categoria = [
            "Contas Essenciais (Água/Luz/Gás/Tel)", "Moradia (Aluguel/Condomínio)", "Alimentação", "Saúde", "Transporte", 
            "Empréstimo Pessoal / Crediário", "Cheque Especial", "Empréstimo Consignado INSS", "Cartão de Crédito Consignado (RMC)", 
            "Cartão de Benefício Consignado (RCC)", "Financiamento (Garantia Real/Imóvel)", "Tributos / Impostos / Multas", 
            "Pensão Alimentícia Paga", "Crédito Rural / Empresarial", "Artigos de Luxo (Má-fé)", "Outros"
        ]
        opcoes_status = ["Pago", "A Pagar"]
        
    categoria = st.selectbox("Categoria", opcoes_categoria)
    conta = st.selectbox("Conta/Banco", ["Banco do Brasil", "Santander", "Nubank", "Inter", "Desconto em Folha (INSS)", "Dinheiro Físico"])
    metodo_pagamento = st.selectbox("Método de Pagamento", ["Pix", "Débito", "Boleto", "Retido na Fonte"])
    valor = st.number_input("Valor (R$)", min_value=0.01, format="%.2f")
    descricao = st.text_input("Descrição (Ex: Empréstimo BMG, Conta de Luz)")
    
    recorrencia = st.number_input("Repetir lançamento por quantos meses?", min_value=1, max_value=120, value=1, step=1)
    status = st.radio("Status Inicial (Mês Atual)", opcoes_status, horizontal=True)
        
    if st.button("Salvar Lançamento no Sistema"):
        valor_final = valor if tipo == "Receita" else -valor
        linhas_novas = []
        for i in range(recorrencia):
            mes_alvo = data_lanc.month - 1 + i
            ano_novo = data_lanc.year + (mes_alvo // 12)
            mes_novo = (mes_alvo % 12) + 1
            dia_novo = min(data_lanc.day, calendar.monthrange(ano_novo, mes_novo)[1])
            data_parcela = date(ano_novo, mes_novo, dia_novo)
            
            status_atual = status if i == 0 else ("A Receber" if tipo == "Receita" else "A Pagar")
            linhas_novas.append({'Data': pd.to_datetime(data_parcela), 'Tipo': tipo, 'Categoria': categoria, 'Conta/Banco': conta, 'Método de Pagamento': metodo_pagamento, 'Valor': valor_final, 'Descrição': descricao, 'Status': status_atual})
            
        st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, pd.DataFrame(linhas_novas)], ignore_index=True)
        salvar_no_sheets()
        st.success("Sincronizado com o Google Sheets com sucesso!")
        st.rerun()

    st.subheader("Histórico (Sincronizado)")
    df_lanc_editado = st.data_editor(st.session_state.lancamentos, use_container_width=True, hide_index=True, num_rows="dynamic", column_config={"Status": st.column_config.SelectboxColumn("Status", options=["Pago", "A Pagar", "Recebido", "A Receber"], required=True), "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"), "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")}, key="ed_lanc")
    if not st.session_state.lancamentos.equals(df_lanc_editado):
        st.session_state.lancamentos = df_lanc_editado
        salvar_no_sheets()
        st.rerun()

with aba2:
    st.header(f"Lançamento de Cartão - {cliente_selecionado}")
    with st.expander("⚙️ Configurar Dias de Vencimento dos Cartões"):
        cols_venc = st.columns(4)
        lista_cartoes = list(st.session_state.vencimentos_cartoes.keys())
        for i, cartao in enumerate(lista_cartoes):
            with cols_venc[i]:
                dia_atual_cfg = st.session_state.vencimentos_cartoes[cartao]
                novo_dia_cfg = st.number_input(f"Venc. {cartao}", min_value=1, max_value=31, value=dia_atual_cfg, key=f"cfg_{cartao}")
                if novo_dia_cfg != dia_atual_cfg:
                    st.session_state.vencimentos_cartoes[cartao] = novo_dia_cfg
                    if not st.session_state.cartoes.empty:
                        def atualizar_linha_vencimento(row):
                            if row['Cartão'] == cartao and row['Status'] == 'A Pagar':
                                d_compra = pd.to_datetime(row['Data da Compra']).date()
                                p_num = int(row['Parcela Atual'])
                                return pd.to_datetime(calcular_data_vencimento(d_compra, p_num, novo_dia_cfg))
                            return row['Data de Vencimento']
                        st.session_state.cartoes['Data de Vencimento'] = st.session_state.cartoes.apply(atualizar_linha_vencimento, axis=1)
                        salvar_no_sheets()
                        st.rerun()
                        
    st.markdown("---")
    with st.form(key="form_cartoes", clear_on_submit=True):
        data_compra = st.date_input("Data da Compra", date.today(), format="DD/MM/YYYY")
        nome_cartao = st.selectbox("Cartão", ["Cartão Nubank", "Cartão Santander", "Cartão BB", "Cartão Inter"])
        tipo_valor = st.radio("O valor informado se refere a:", ["Valor Total da Compra", "Valor da Parcela"], horizontal=True)
        valor_informado = st.number_input("Valor Informado (R$)", min_value=0.01, format="%.2f")
        cat_cartao = st.selectbox("Categoria da Compra", ["Alimentação", "Transporte", "Saúde", "Lazer", "Educação", "Crediário/Loja", "Outros"])
        parcelas = st.number_input("Número Total de Parcelas", min_value=1, max_value=72, step=1)
        desc_cartao = st.text_input("Descrição")
            
        if st.form_submit_button("Gerar Parcelas na Nuvem"):
            v_parc = valor_informado if tipo_valor == "Valor da Parcela" else valor_informado / parcelas
            v_tot = v_parc * parcelas if tipo_valor == "Valor da Parcela" else valor_informado
            linhas = []
            dia_v = st.session_state.vencimentos_cartoes[nome_cartao]
            for i in range(1, parcelas + 1):
                linhas.append({'Data da Compra': pd.to_datetime(data_compra), 'Cartão': nome_cartao, 'Valor Total': v_tot, 'Categoria': cat_cartao, 'Parcelas': parcelas, 'Descrição': desc_cartao, 'Valor da Parcela': v_parc, 'Parcela Atual': i, 'Data de Vencimento': pd.to_datetime(calcular_data_vencimento(data_compra, i, dia_v)), 'Status': 'A Pagar'})
            st.session_state.cartoes = pd.concat([st.session_state.cartoes, pd.DataFrame(linhas)], ignore_index=True)
            salvar_no_sheets()
            st.rerun()

    st.subheader("Faturas (Sincronizadas)")
    df_cartoes_editado = st.data_editor(st.session_state.cartoes, use_container_width=True, hide_index=True, num_rows="dynamic", column_config={"Status": st.column_config.SelectboxColumn("Status", options=["Pago", "A Pagar"], required=True), "Data da Compra": st.column_config.DateColumn("Compra", format="DD/MM/YYYY"), "Data de Vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"), "Valor Total": st.column_config.NumberColumn("Valor Total", format="R$ %.2f"), "Valor da Parcela": st.column_config.NumberColumn("Valor da Parcela", format="R$ %.2f")}, key="ed_cart")
    if not st.session_state.cartoes.equals(df_cartoes_editado):
        st.session_state.cartoes = df_cartoes_editado
        salvar_no_sheets()
        st.rerun()