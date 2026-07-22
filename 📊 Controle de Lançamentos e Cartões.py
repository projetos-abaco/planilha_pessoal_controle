import streamlit as st
import pandas as pd
from datetime import date
import calendar
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Registros Financeiros", page_icon="📝", layout="wide")
st.title("📝 Registros Financeiros (Sincronizado com Nuvem)")

# --- 1. CONEXÃO COM O GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credenciais = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(credenciais)
        planilha = client.open_by_url(st.secrets["url_planilha"])
        return planilha
    except Exception as e:
        return None

planilha = conectar_google_sheets()

if planilha is None:
    st.error("⚠️ Não foi possível conectar ao Google Sheets. Verifique o arquivo .streamlit/secrets.toml e o compartilhamento da planilha.")
    st.stop()

# --- 2. GESTÃO DE CLIENTES (ABAS) ---
st.sidebar.header("👥 Seleção de Cliente")
st.sidebar.markdown("Crie novas abas na sua planilha do Google para adicionar clientes.")

abas = planilha.worksheets()
nomes_abas = [aba.title for aba in abas]

cliente_selecionado = st.sidebar.selectbox("Cliente Ativo (Aba):", nomes_abas)
st.session_state.cliente_selecionado = cliente_selecionado # Guarda o nome para as outras abas!
aba_atual = planilha.worksheet(cliente_selecionado)

# --- 3. LEITURA DOS DADOS DA NUVEM ---
dados_brutos = aba_atual.get_all_values()

cabecalhos_lanc = ['Data', 'Tipo', 'Categoria', 'Conta/Banco', 'Método de Pagamento', 'Valor', 'Descrição', 'Status']
cabecalhos_cart = ['Data da Compra', 'Cartão', 'Valor Total', 'Categoria', 'Parcelas', 'Descrição', 'Valor da Parcela', 'Parcela Atual', 'Data de Vencimento', 'Status']

# Se a aba estiver vazia, cria a estrutura automaticamente (Lançamentos na coluna A, Cartões na J)
if not dados_brutos:
    aba_atual.update(range_name='A1', values=[cabecalhos_lanc])
    aba_atual.update(range_name='J1', values=[cabecalhos_cart])
    dados_brutos = aba_atual.get_all_values()

# Separar os dados lidos (A:H para Lançamentos, J:S para Cartões)
linhas_lanc = [linha[:8] for linha in dados_brutos[1:] if len(linha) >= 8 and linha[0] != ""]
linhas_cart = [linha[9:19] for linha in dados_brutos[1:] if len(linha) >= 19 and linha[9] != ""]

df_lanc = pd.DataFrame(linhas_lanc, columns=cabecalhos_lanc)
df_cart = pd.DataFrame(linhas_cart, columns=cabecalhos_cart)

# Converter colunas financeiras e de data para os tipos corretos
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

# Salvar na memória do Streamlit para as outras páginas usarem
st.session_state.lancamentos = df_lanc
st.session_state.cartoes = df_cart
if 'vencimentos_cartoes' not in st.session_state:
    st.session_state.vencimentos_cartoes = {"Cartão Nubank": 10, "Cartão Santander": 15, "Cartão BB": 20, "Cartão Inter": 25}

def salvar_no_sheets():
    """Função para reescrever os dados atualizados na aba do cliente"""
    # ==========================================
    # 1. PREPARAÇÃO DOS LANÇAMENTOS GERAIS
    # ==========================================
    df_l = st.session_state.lancamentos.copy()
    if not df_l.empty:
        # Formata as datas
        df_l['Data'] = pd.to_datetime(df_l['Data'], errors='coerce') 
        df_l['Data'] = df_l['Data'].dt.strftime('%d/%m/%Y')
    
    # A SOLUÇÃO: Substitui qualquer tipo de vazio (NaN, None, NaT, pd.NA) por texto em branco ("")
    # em TODAS as colunas da tabela de uma só vez. Isso impede o erro de JSON.
    df_l = df_l.fillna("")
    
    valores_l = [cabecalhos_lanc] + df_l.values.tolist()
    
    # ==========================================
    # 2. PREPARAÇÃO DOS CARTÕES
    # ==========================================
    df_c = st.session_state.cartoes.copy()
    if not df_c.empty:
        # Formata as datas
        df_c['Data da Compra'] = pd.to_datetime(df_c['Data da Compra'], errors='coerce')
        df_c['Data de Vencimento'] = pd.to_datetime(df_c['Data de Vencimento'], errors='coerce')
        
        df_c['Data da Compra'] = df_c['Data da Compra'].dt.strftime('%d/%m/%Y')
        df_c['Data de Vencimento'] = df_c['Data de Vencimento'].dt.strftime('%d/%m/%Y')
    
    # A SOLUÇÃO APLICADA AOS CARTÕES
    df_c = df_c.fillna("")
    
    valores_c = [cabecalhos_cart] + df_c.values.tolist()
    
    # ==========================================
    # 3. ENVIO PARA O GOOGLE SHEETS
    # ==========================================
    # Limpa a aba e reescreve 
    aba_atual.clear()
    aba_atual.update(range_name='A1', values=valores_l)
    aba_atual.update(range_name='J1', values=valores_c)

def calcular_data_vencimento(data_compra_dt, parcela_num, dia_venc_config):
    mes_alvo = data_compra_dt.month + parcela_num
    ano_venc = data_compra_dt.year + (mes_alvo - 1) // 12
    mes_venc = (mes_alvo - 1) % 12 + 1
    u_dia = calendar.monthrange(ano_venc, mes_venc)[1]
    return date(ano_venc, mes_venc, min(dia_venc_config, u_dia))

# --- INTERFACE DE ENTRADA ---
aba1, aba2 = st.tabs(["📝 Novo Lançamento", "💳 Cartão de Crédito"])

with aba1:
    st.header(f"Lançamento Geral - {cliente_selecionado}")
    data_lanc = st.date_input("Data", date.today(), format="DD/MM/YYYY")
    tipo = st.selectbox("Tipo", ["Receita", "Despesa"])
    
    opcoes_categoria = ["Salário", "Rendimentos financeiros", "Outros"] if tipo == "Receita" else ["Moradia", "Alimentação", "Transporte", "Saúde", "Outros"]
    opcoes_status = ["Recebido", "A Receber"] if tipo == "Receita" else ["Pago", "A Pagar"]
        
    categoria = st.selectbox("Categoria", opcoes_categoria)
    conta = st.selectbox("Conta/Banco", ["Banco do Brasil", "Santander", "Nubank", "Inter", "Dinheiro Físico"])
    metodo_pagamento = st.selectbox("Método de Pagamento", ["Pix", "Débito", "Boleto"])
    valor = st.number_input("Valor (R$)", min_value=0.01, format="%.2f")
    descricao = st.text_input("Descrição")
    status = st.radio("Status", opcoes_status, horizontal=True)
        
    if st.button("Salvar Lançamento no Sistema"):
        valor_final = valor if tipo == "Receita" else -valor
        novo_dado = pd.DataFrame([{
            'Data': pd.to_datetime(data_lanc), 'Tipo': tipo, 'Categoria': categoria,
            'Conta/Banco': conta, 'Método de Pagamento': metodo_pagamento,
            'Valor': valor_final, 'Descrição': descricao, 'Status': status
        }])
        st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_dado], ignore_index=True)
        salvar_no_sheets()
        st.success("Sincronizado com o Google Sheets com sucesso!")
        st.rerun()

    st.subheader("Histórico (Sincronizado)")
    df_lanc_editado = st.data_editor(
        st.session_state.lancamentos, use_container_width=True, hide_index=True, num_rows="dynamic", 
        column_config={
            "Status": st.column_config.SelectboxColumn("Status", options=["Pago", "A Pagar", "Recebido", "A Receber"], required=True),
            "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY")
        }, key="ed_lanc"
    )
    if not st.session_state.lancamentos.equals(df_lanc_editado):
        st.session_state.lancamentos = df_lanc_editado
        salvar_no_sheets()
        st.toast("✅ Nuvem atualizada!", icon="☁️")
        st.rerun()

with aba2:
    st.header(f"Lançamento de Cartão - {cliente_selecionado}")
    with st.form(key="form_cartoes", clear_on_submit=True):
        data_compra = st.date_input("Data da Compra", date.today(), format="DD/MM/YYYY")
        nome_cartao = st.selectbox("Cartão", ["Cartão Nubank", "Cartão Santander", "Cartão BB", "Cartão Inter"])
        tipo_valor = st.radio("Refere-se a:", ["Valor Total", "Valor da Parcela"], horizontal=True)
        valor_informado = st.number_input("Valor Informado (R$)", min_value=0.01, format="%.2f")
        cat_cartao = st.selectbox("Categoria", ["Alimentação", "Transporte", "Saúde", "Lazer", "Outros"])
        parcelas = st.number_input("Parcelas", min_value=1, step=1)
        desc_cartao = st.text_input("Descrição")
            
        if st.form_submit_button("Gerar Parcelas na Nuvem"):
            v_parc = valor_informado if tipo_valor == "Valor da Parcela" else valor_informado / parcelas
            v_tot = v_parc * parcelas if tipo_valor == "Valor da Parcela" else valor_informado
            linhas = []
            dia_v = st.session_state.vencimentos_cartoes[nome_cartao]
            
            for i in range(1, parcelas + 1):
                linhas.append({
                    'Data da Compra': pd.to_datetime(data_compra), 'Cartão': nome_cartao,
                    'Valor Total': v_tot, 'Categoria': cat_cartao, 'Parcelas': parcelas,
                    'Descrição': desc_cartao, 'Valor da Parcela': v_parc, 'Parcela Atual': i,
                    'Data de Vencimento': pd.to_datetime(calcular_data_vencimento(data_compra, i, dia_v)), 
                    'Status': 'A Pagar' 
                })
            st.session_state.cartoes = pd.concat([st.session_state.cartoes, pd.DataFrame(linhas)], ignore_index=True)
            salvar_no_sheets()
            st.success("Parcelas sincronizadas com o Google Sheets!")
            st.rerun()

    st.subheader("Faturas (Sincronizadas)")
    df_cartoes_editado = st.data_editor(
        st.session_state.cartoes, use_container_width=True, hide_index=True, num_rows="dynamic",
        column_config={
            "Status": st.column_config.SelectboxColumn("Status", options=["Pago", "A Pagar"], required=True),
            "Data da Compra": st.column_config.DateColumn("Compra", format="DD/MM/YYYY"),
            "Data de Vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY")
        }, key="ed_cart"
    )
    if not st.session_state.cartoes.equals(df_cartoes_editado):
        st.session_state.cartoes = df_cartoes_editado
        salvar_no_sheets()
        st.toast("✅ Fatura atualizada na nuvem!", icon="☁️")
        st.rerun()