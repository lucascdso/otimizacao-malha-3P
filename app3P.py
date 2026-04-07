import streamlit as st
import pandas as pd
import numpy as np
import io

# ==============================================================================
# 1. CONFIGURAÇÕES DA PÁGINA E PARÂMETROS
# ==============================================================================
st.set_page_config(page_title="Otimização de Prazos", layout="wide")
st.title("⏱️ Otimizador de Prazos e Nível de Serviço (NS) 3P")
st.write("Faça o upload da sua base CSV para simular o melhor cenário de prazo de entrega (em Dias Úteis).")

# Menu lateral para estipular as metas dinamicamente
st.sidebar.header("🎯 Parâmetros de Otimização")
meta_ns = st.sidebar.slider("Meta de Nível de Serviço (%)", min_value=0, max_value=100, value=95) / 100.0
limite_prazo = st.sidebar.number_input("Prazo Máximo Aceitável (Dias Úteis)", min_value=1, value=7)

st.sidebar.info(f"O motor tentará atingir **{meta_ns*100:.0f}% de NS** sem deixar o novo prazo ultrapassar **{limite_prazo} dias úteis**.")

# ==============================================================================
# 2. FUNÇÕES DE LIMPEZA E LÓGICA
# ==============================================================================
def clean_num(x):
    if pd.isna(x): return np.nan
    if isinstance(x, str):
        x = x.replace('%', '').replace(',', '.').strip()
    try:
        return float(x)
    except ValueError:
        return np.nan

ns_cols = ['NS (-3)', 'NS (-2)', 'NS (-1)', 'NS (Atual)', 'NS (+1)', 'NS (+2)', 'NS (+3)']

def get_best_adjustment(row, meta_ns, limite_prazo):
    ns_values = [row.get(c, np.nan) for c in ns_cols]
    adjustments = [-3, -2, -1, 0, 1, 2, 3]
    prazo_atual = row.get('Prazo_Atual', 0)

    best_adj = None
    best_ns = None

    # 3.1 Cenario Ideal: Atinge a Meta de NS e respeita o Limite de Prazo
    for adj, ns in zip(adjustments, ns_values):
        if pd.isna(ns): continue
        novo_prazo_temp = max(prazo_atual + adj, 1)
        
        if ns >= meta_ns and novo_prazo_temp <= limite_prazo:
            best_adj = adj
            best_ns = ns
            break

    # 3.2 Fallback 1: Ninguém bateu a meta de NS. Busca o MAIOR NS possível dentro do Limite de Prazo
    if best_adj is None:
        valid_pairs = []
        for adj, ns in zip(adjustments, ns_values):
            if not pd.isna(ns):
                novo_prazo_temp = max(prazo_atual + adj, 1)
                if novo_prazo_temp <= limite_prazo:
                    valid_pairs.append((adj, ns))
        
        if valid_pairs:
            best_pair = max(valid_pairs, key=lambda x: x[1])
            return best_pair[0], best_pair[1]

    # 3.3 Fallback 2: O prazo atual já é tão alto que é impossível chegar no teto de dias.
    # Nesse caso extremo, pega o cenário de MAIOR NS absoluto entre todas as opções.
    if best_adj is None:
        valid_pairs_all = [(adj, ns) for adj, ns in zip(adjustments, ns_values) if not pd.isna(ns)]
        if not valid_pairs_all:
            return 0, row.get('NS_Atual', 0)
        best_pair = max(valid_pairs_all, key=lambda x: x[1])
        return best_pair[0], best_pair[1]

    return best_adj, best_ns

# ==============================================================================
# 3. INTERFACE E PROCESSAMENTO
# ==============================================================================
uploaded_file = st.file_uploader("Selecione o arquivo CSV", type=['csv'])

if uploaded_file is not None:
    with st.spinner("Analisando cenários e calculando novos prazos..."):
        try:
            df = pd.read_csv(uploaded_file, sep=';', encoding='utf-8')
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=';', encoding='latin1')

        if 'Qtd Pedidos' in df.columns:
            df['Qtd Pedidos'] = df['Qtd Pedidos'].apply(clean_num)
            df = df.dropna(subset=['Qtd Pedidos'])
        else:
            st.error("Aviso: Coluna 'Qtd Pedidos' não encontrada na planilha.")
            st.stop()

        if 'Prazo Prometido (Dias Úteis)' in df.columns:
            df['Prazo_Atual'] = df['Prazo Prometido (Dias Úteis)'].apply(clean_num)
        else:
            st.error("Aviso: Coluna 'Prazo Prometido (Dias Úteis)' não encontrada na planilha.")
            st.stop()

        for col in ns_cols:
            if col in df.columns:
                df[col] = df[col].apply(clean_num) / 100.0

        df['NS_Atual'] = df.get('NS (Atual)', 0)

        # Execução da Lógica de Decisão passando os novos parâmetros da tela
        resultados = df.apply(lambda row: get_best_adjustment(row, meta_ns, limite_prazo), axis=1)
        df['Ajuste_Dias'] = [r[0] for r in resultados]
        df['NS_Projetado'] = [r[1] for r in resultados]

        # Cálculo do Novo Prazo
        df['Novo_Prazo'] = (df['Prazo_Atual'] + df['Ajuste_Dias']).clip(lower=1)

        # Resumo Global com Média Ponderada
        total_pedidos = df['Qtd Pedidos'].sum()

        if total_pedidos > 0:
            prazo_atual_pond = (df['Prazo_Atual'] * df['Qtd Pedidos']).sum() / total_pedidos
            novo_prazo_pond = (df['Novo_Prazo'] * df['Qtd Pedidos']).sum() / total_pedidos
            ns_atual_pond = (df['NS_Atual'] * df['Qtd Pedidos']).sum() / total_pedidos
            ns_projetado_pond = (df['NS_Projetado'] * df['Qtd Pedidos']).sum() / total_pedidos
            diferenca_dias = novo_prazo_pond - prazo_atual_pond
        else:
            prazo_atual_pond = novo_prazo_pond = ns_atual_pond = ns_projetado_pond = diferenca_dias = 0

    st.success("Análise concluída com sucesso!")

    # ==============================================================================
    # 4. EXIBIÇÃO DE RESULTADOS (DASHBOARD)
    # ==============================================================================
    st.subheader("📊 Resumo da Eficiência Global Projetada (Média Ponderada)")
    
    st.write(f"**📦 Volume Total de Pedidos Considerados:** {int(total_pedidos):,}".replace(',', '.'))
    
    col1, col2 = st.columns(2)
    
    col1.metric("⏳ Prazo Promessa Atual (Dias Úteis)", f"{prazo_atual_pond:.2f} dias")
    col2.metric("🚀 Novo Prazo Promessa (Dias Úteis)", f"{novo_prazo_pond:.2f} dias", f"{diferenca_dias:+.2f} dias úteis", delta_color="inverse")
    
    col1.metric("📉 Nível de Serviço (Atual)", f"{ns_atual_pond:.2%}")
    col2.metric("📈 Nível de Serviço (Projetado)", f"{ns_projetado_pond:.2%}", f"{(ns_projetado_pond - ns_atual_pond)*100:+.2f}%")

    st.markdown("---")

    # ==============================================================================
    # 5. EXPORTAÇÃO E DOWNLOAD
    # ==============================================================================
    st.subheader("📥 Exportação de Dados")
    
    output_cols = ['Seller', 'Estado', 'Qtd Pedidos', 'Prazo_Atual', 'NS_Atual', 'Ajuste_Dias', 'Novo_Prazo', 'NS_Projetado']
    cols_to_export = [c for c in output_cols if c in df.columns]
    
    # 5.1 Gera DataFrame da Base Completa
    df_completo = df[cols_to_export].copy()
    
    # 5.2 Gera DataFrame apenas dos Sellers que NÃO bateram a meta de NS
    df_abaixo_meta = df[df['NS_Projetado'] < meta_ns][cols_to_export].copy()

    # Formatação para o Excel (Substituindo Ponto por Vírgula para facilitar a leitura no Brasil)
    for col in ['Prazo_Atual', 'Novo_Prazo', 'NS_Atual', 'NS_Projetado']:
        if col in df_completo.columns:
            df_completo[col] = df_completo[col].apply(lambda x: str(x).replace('.', ','))
        if col in df_abaixo_meta.columns:
            df_abaixo_meta[col] = df_abaixo_meta[col].apply(lambda x: str(x).replace('.', ','))

    # Criação dos arquivos CSV em Memória
    csv_completo = df_completo.to_csv(sep=';', index=False, encoding='utf-8').encode('utf-8')
    csv_abaixo = df_abaixo_meta.to_csv(sep=';', index=False, encoding='utf-8').encode('utf-8')

    # Layout dos Botões Lado a Lado
    col_dw1, col_dw2 = st.columns(2)
    
    with col_dw1:
        st.download_button(
            label="📦 Baixar Base Completa (CSV)",
            data=csv_completo,
            file_name='base_prazos_uteis_otimizados.csv',
            mime='text/csv'
        )
        
    with col_dw2:
        st.download_button(
            label="⚠️ Baixar Sellers Abaixo da Meta (CSV)",
            data=csv_abaixo,
            file_name='sellers_abaixo_meta_ns.csv',
            mime='text/csv',
            help="Extrai apenas os sellers onde o NS Projetado ficou menor que a meta estipulada no menu lateral."
        )
