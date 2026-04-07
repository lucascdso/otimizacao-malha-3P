import streamlit as st
import pandas as pd
import numpy as np
import io
import heapq

# ==============================================================================
# 1. CONFIGURAÇÕES DA PÁGINA E PARÂMETROS
# ==============================================================================
st.set_page_config(page_title="Otimização de Prazos", layout="wide")
st.title("⏱️ Otimizador Global de Prazos e Nível de Serviço (NS) 3P")
st.write("Faça o upload da sua base CSV para otimizar os prazos focando na Média Ponderada Global.")

# Menu lateral para estipular as metas dinamicamente
st.sidebar.header("🎯 Parâmetros de Otimização")
meta_ns = st.sidebar.slider("Meta de Nível de Serviço (%)", min_value=0, max_value=100, value=95) / 100.0

# O limite agora aceita números quebrados (float) para a média ponderada
limite_prazo = st.sidebar.number_input(
    "Prazo Máximo Aceitável (Média Global em Dias Úteis)", 
    min_value=1.0, 
    value=7.0, 
    step=0.1, 
    format="%.2f",
    help="O motor sacrificará o Nível de Serviço apenas onde o impacto for menor, até que a média ponderada da malha inteira atinja este limite."
)

st.sidebar.info(f"O motor tentará atingir **{meta_ns*100:.0f}% de NS** global. Se a média de prazo ultrapassar **{limite_prazo:.2f} dias úteis**, ele reduzirá os prazos priorizando as menores perdas de NS.")

# ==============================================================================
# 2. FUNÇÕES DE LIMPEZA E LÓGICA GULOSA
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

def get_ideal_adjustment(row, meta_ns):
    """Busca o ajuste ideal ignorando limites de prazo iniciais (Foco total no NS)"""
    ns_values = [row.get(c, np.nan) for c in ns_cols]
    adjustments = [-3, -2, -1, 0, 1, 2, 3]
    
    for adj, ns in zip(adjustments, ns_values):
        if pd.isna(ns): continue
        if ns >= meta_ns:
            return adj
            
    # Fallback: Se não atinge a meta, pega o maior NS possível
    valid_pairs = [(adj, ns) for adj, ns in zip(adjustments, ns_values) if not pd.isna(ns)]
    if not valid_pairs:
        return 0
    best_pair = max(valid_pairs, key=lambda x: x[1])
    return best_pair[0]

# ==============================================================================
# 3. INTERFACE E PROCESSAMENTO
# ==============================================================================
uploaded_file = st.file_uploader("Selecione o arquivo CSV", type=['csv'])

if uploaded_file is not None:
    with st.spinner("Analisando malha e aplicando otimização matemática avançada..."):
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

        # ----------------------------------------------------------------------
        # MOTOR DE OTIMIZAÇÃO GLOBAL (KNAPSACK GREEDY ALGORITHM)
        # ----------------------------------------------------------------------
        
        # PASSO 1: Dar a todos o melhor cenário de NS
        df['Ajuste_Dias'] = df.apply(lambda row: get_ideal_adjustment(row, meta_ns), axis=1)
        df['Novo_Prazo'] = (df['Prazo_Atual'] + df['Ajuste_Dias']).clip(lower=1)

        total_pedidos = df['Qtd Pedidos'].sum()
        target_prazo_sum = limite_prazo * total_pedidos
        current_prazo_sum = (df['Novo_Prazo'] * df['Qtd Pedidos']).sum()

        records = df.to_dict('records')
        current_adjs = df['Ajuste_Dias'].tolist()

        # PASSO 2: Redução dinâmica caso a média global ultrapasse o estipulado
        if current_prazo_sum > target_prazo_sum:
            heap = [] # Fila de prioridade
            
            # Avalia o "Custo de Oportunidade" de remover 1 dia de cada seller
            for i, r in enumerate(records):
                a = current_adjs[i]
                if a > -3:
                    new_a = a - 1
                    ns_new = r.get(ns_cols[new_a + 3], np.nan)
                    if pd.notna(ns_new):
                        old_p = max(r['Prazo_Atual'] + a, 1)
                        new_p = max(r['Prazo_Atual'] + new_a, 1)
                        if new_p < old_p: # Só conta se realmente reduzir prazo
                            ns_loss = r[ns_cols[a + 3]] - ns_new
                            days_saved_total = (old_p - new_p) * r['Qtd Pedidos']
                            heapq.heappush(heap, (ns_loss, i, a, new_a, days_saved_total))
            
            # Loop de sacrifício: rebaixa quem perde MENOS NS até atingir a média alvo
            while heap and current_prazo_sum > target_prazo_sum:
                ns_loss, i, a, new_a, days_saved_total = heapq.heappop(heap)
                
                current_adjs[i] = new_a
                current_prazo_sum -= days_saved_total
                
                # Após rebaixar, verifica se esse seller ainda aguenta ser rebaixado mais uma vez
                r = records[i]
                curr_a = new_a
                if curr_a > -3:
                    next_a = curr_a - 1
                    ns_next = r.get(ns_cols[next_a + 3], np.nan)
                    if pd.notna(ns_next):
                        old_p = max(r['Prazo_Atual'] + curr_a, 1)
                        new_p = max(r['Prazo_Atual'] + next_a, 1)
                        if new_p < old_p:
                            next_loss = r[ns_cols[curr_a + 3]] - ns_next
                            next_days_saved = (old_p - new_p) * r['Qtd Pedidos']
                            heapq.heappush(heap, (next_loss, i, curr_a, next_a, next_days_saved))
            
            # Atualiza a base com os cortes aplicados
            df['Ajuste_Dias'] = current_adjs
            df['Novo_Prazo'] = (df['Prazo_Atual'] + df['Ajuste_Dias']).clip(lower=1)

        # Atualiza o Nível de Serviço projetado final para bater com o ajuste selecionado
        df['NS_Projetado'] = [records[i].get(ns_cols[current_adjs[i] + 3], np.nan) for i in range(len(records))]

        # Resumo Global com Média Ponderada
        if total_pedidos > 0:
            prazo_atual_pond = (df['Prazo_Atual'] * df['Qtd Pedidos']).sum() / total_pedidos
            novo_prazo_pond = (df['Novo_Prazo'] * df['Qtd Pedidos']).sum() / total_pedidos
            ns_atual_pond = (df['NS_Atual'] * df['Qtd Pedidos']).sum() / total_pedidos
            ns_projetado_pond = (df['NS_Projetado'] * df['Qtd Pedidos']).sum() / total_pedidos
            diferenca_dias = novo_prazo_pond - prazo_atual_pond
        else:
            prazo_atual_pond = novo_prazo_pond = ns_atual_pond = ns_projetado_pond = diferenca_dias = 0

    st.success("Análise matemática concluída com sucesso!")

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

    # Formatação para o Excel (Substituindo Ponto por Vírgula)
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
