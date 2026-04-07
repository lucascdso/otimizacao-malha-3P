import streamlit as st
import pandas as pd
import numpy as np
import io

# ==============================================================================
# 1. CONFIGURAÇÕES DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Otimização de Prazos", layout="wide")
st.title("⏱️ Otimizador de Prazos e Nível de Serviço (NS) 3P")
st.write("Faça o upload da sua base CSV para simular o melhor cenário de prazo de entrega (em Dias Úteis).")

# ==============================================================================
# 2. FUNÇÕES DE LIMPEZA E LÓGICA
# ==============================================================================
def clean_num(x):
    if pd.isna(x): return np.nan
    if isinstance(x, str):
        # Removemos o % e trocamos a vírgula do decimal para ponto
        x = x.replace('%', '').replace(',', '.').strip()
    try:
        return float(x)
    except ValueError:
        return np.nan

ns_cols = ['NS (-3)', 'NS (-2)', 'NS (-1)', 'NS (Atual)', 'NS (+1)', 'NS (+2)', 'NS (+3)']

def get_best_adjustment(row):
    ns_values = [row.get(c, np.nan) for c in ns_cols]
    adjustments = [-3, -2, -1, 0, 1, 2, 3]

    best_adj = None
    best_ns = None

    # 3.1 Procura o primeiro cenário onde o NS seja >= 95% (em ordem de competitividade)
    for adj, ns in zip(adjustments, ns_values):
        if pd.isna(ns): continue
        if ns >= 0.95:
            best_adj = adj
            best_ns = ns
            break

    # 3.2 Fallback: se nenhum atinge 95%, pega o que dá o maior NS absoluto
    if best_adj is None:
        valid_pairs = [(adj, ns) for adj, ns in zip(adjustments, ns_values) if not pd.isna(ns)]
        if not valid_pairs:
            return 0, row.get('NS_Atual', 0)
        best_pair = max(valid_pairs, key=lambda x: x[1])
        return best_pair[0], best_pair[1]

    return best_adj, best_ns

# ==============================================================================
# 3. INTERFACE E PROCESSAMENTO
# ==============================================================================
uploaded_file = st.file_uploader("Selecione o arquivo CSV", type=['csv'])

if uploaded_file is not None:
    with st.spinner("Analisando cenários e calculando novos prazos..."):
        # 1. Leitura do arquivo (tratando encodings comuns)
        try:
            df = pd.read_csv(uploaded_file, sep=';', encoding='utf-8')
        except UnicodeDecodeError:
            # Se falhar, reseta o ponteiro do arquivo e tenta latin1
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=';', encoding='latin1')

        # 2. Limpeza
        if 'Qtd Pedidos' in df.columns:
            df['Qtd Pedidos'] = df['Qtd Pedidos'].apply(clean_num)
            df = df.dropna(subset=['Qtd Pedidos'])
        else:
            st.error("Aviso: Coluna 'Qtd Pedidos' não encontrada na planilha.")
            st.stop()

        # ALTERAÇÃO AQUI: Mudança para buscar os Dias Úteis como base
        if 'Prazo Prometido (Dias Úteis)' in df.columns:
            df['Prazo_Atual'] = df['Prazo Prometido (Dias Úteis)'].apply(clean_num)
        else:
            st.error("Aviso: Coluna 'Prazo Prometido (Dias Úteis)' não encontrada na planilha.")
            st.stop()

        # Limpando Colunas de NS e transformando em decimal
        for col in ns_cols:
            if col in df.columns:
                df[col] = df[col].apply(clean_num) / 100.0

        df['NS_Atual'] = df.get('NS (Atual)', 0)

        # 3. Execução da Lógica de Decisão
        resultados = df.apply(get_best_adjustment, axis=1)
        df['Ajuste_Dias'] = [r[0] for r in resultados]
        df['NS_Projetado'] = [r[1] for r in resultados]

        # 4. Cálculo do Novo Prazo (Aplicando o ajuste matemático sobre os Dias Úteis com limite mínimo de 1)
        df['Novo_Prazo'] = (df['Prazo_Atual'] + df['Ajuste_Dias']).clip(lower=1)

        # 5. Resumo Global com Média Ponderada
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
    
    # Cartões de Indicadores Visuais (Atualizados para refletir Dias Úteis)
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
    
    # Garante que só puxe as colunas que realmente existem na tabela
    cols_to_export = [c for c in output_cols if c in df.columns]
    df_out = df[cols_to_export].copy()

    # Devolvendo a formatação para facilitar leitura no Excel (Troca Ponto por Vírgula)
    for col in ['Prazo_Atual', 'Novo_Prazo', 'NS_Atual', 'NS_Projetado']:
        if col in df_out.columns:
            df_out[col] = df_out[col].apply(lambda x: str(x).replace('.', ','))

    # Criação do CSV em Memória
    csv_data = df_out.to_csv(sep=';', index=False, encoding='utf-8').encode('utf-8')

    st.download_button(
        label="📦 Baixar Base de Prazos Otimizados (CSV)",
        data=csv_data,
        file_name='base_prazos_uteis_otimizados.csv',
        mime='text/csv'
    )
