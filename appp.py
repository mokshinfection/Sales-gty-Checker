import streamlit as st
import pandas as pd
from datetime import datetime
import io
import sqlite3
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Sales Quantity Checker", layout="wide")
st.title("Sales Quantity Checker")

# 🔴 WORKING PATHS 🔴
GITHUB_ZIP_URL = "https://raw.githubusercontent.com/mokshinfection/Sales-gty-Checker/main/Sales.zip"
DB_FILE_PATH = "Sales.db"

# --- DB ENGINE CORE HELPERS ---
def create_sqlite_db_from_df(df, table_name="sales_records"):
    """Packs an initial base dataframe into a clean local SQLite structure."""
    conn = sqlite3.connect(DB_FILE_PATH)
    df_to_save = df.copy()
    date_col = 'Invoice Date' if 'Invoice Date' in df_to_save.columns else 'Date'
    if date_col in df_to_save.columns:
        df_to_save[date_col] = df_to_save[date_col].dt.strftime('%Y-%m-%d %H:%M:%S')
        
    df_to_save.to_sql(table_name, conn, if_exists='replace', index=False)
    conn.commit()
    conn.close()

# --- DATA PROCESSING (CACHED FROM SQLITE) ---
@st.cache_data(ttl=3600)
def load_backend_data_from_sqlite():
    """Loads historical sales records dynamically out of the SQLite Engine."""
    if not os.path.exists(DB_FILE_PATH):
        with st.spinner("Downloading base initialization matrix from GitHub..."):
            initial_df = pd.read_csv(GITHUB_ZIP_URL, compression='zip', low_memory=False, on_bad_lines='skip')
            initial_df.columns = initial_df.columns.str.strip()
            date_col = 'Invoice Date' if 'Invoice Date' in initial_df.columns else 'Date'
            initial_df[date_col] = pd.to_datetime(initial_df[date_col], dayfirst=True, errors='coerce')
            initial_df = initial_df.dropna(subset=[date_col])
            create_sqlite_db_from_df(initial_df)

    conn = sqlite3.connect(DB_FILE_PATH)
    df = pd.read_sql_query("SELECT * FROM sales_records", conn)
    conn.close()
    
    date_col = 'Invoice Date' if 'Invoice Date' in df.columns else 'Date'
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    return df, date_col

def generate_filtered_database(df, date_col, start_date, end_date):
    """Slices data by selected dates and pivots to find Quantities, Frequencies, and Trend metrics."""
    # Find overall dataset max date for historical trend sliding baselines
    max_db_date = df[date_col].max()
    three_months_ago = (max_db_date - pd.DateOffset(months=3)).date()
    twelve_months_ago = (max_db_date - pd.DateOffset(months=12)).date()
    max_date_conv = max_db_date.date()

    # Pre-calculate Trend numbers across full file intervals before window filters are applied
    mask_3m = (df[date_col].dt.date >= three_months_ago) & (df[date_col].dt.date <= max_date_conv)
    mask_12m = (df[date_col].dt.date >= twelve_months_ago) & (df[date_col].dt.date <= max_date_conv)

    part_col = 'PartNumber' if 'PartNumber' in df.columns else 'Part Number'
    qty_col = 'qty' if 'qty' in df.columns else 'Quantity'
    code_col = 'Product Code' if 'Product Code' in df.columns else 'Part Code'
    desc_col = 'Description'

    # 3-Month and 12-Month volumes per part
    qty_3m = df[mask_3m].groupby(part_col)[qty_col].sum().reset_index(name='qty_3m')
    qty_12m = df[mask_12m].groupby(part_col)[qty_col].sum().reset_index(name='qty_12m')
    
    # Calculate average unit cost across historical items safely if rate info exists
    rate_col = 'Rate' if 'Rate' in df.columns else ('Unit Cost' if 'Unit Cost' in df.columns else None)
    if rate_col:
        unit_costs = df.groupby(part_col)[rate_col].mean().reset_index(name='Unit Cost')
    else:
        unit_costs = pd.DataFrame(columns=[part_col, 'Unit Cost'])

    # Standard filtering for the UI window
    mask = (df[date_col].dt.date >= start_date) & (df[date_col].dt.date <= end_date)
    filtered_df = df[mask].copy()
    
    target_areas = ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]
    
    # Pivot generation
    pivot_qty = filtered_df.pivot_table(
        index=[part_col, code_col, desc_col], columns='Area', values=qty_col, aggfunc='sum', fill_value=0
    ).reset_index()
    
    pivot_freq = filtered_df.pivot_table(
        index=[part_col, code_col, desc_col], columns='Area', values=qty_col, aggfunc='count', fill_value=0
    ).reset_index()
    
    pivot_qty.rename(columns={part_col: 'PartNumber', code_col: 'Product Code'}, inplace=True)
    pivot_freq.rename(columns={part_col: 'PartNumber', code_col: 'Product Code'}, inplace=True)
    
    for area in target_areas:
        if area not in pivot_qty.columns: pivot_qty[area] = 0
        if area not in pivot_freq.columns: pivot_freq[area] = 0
            
    pivot_qty['Total Qty'] = pivot_qty[target_areas].sum(axis=1)
    pivot_freq['Total Freq'] = pivot_freq[target_areas].sum(axis=1)
    
    freq_rename_map = {area: f"{area} Freq" for area in target_areas}
    pivot_freq.rename(columns=freq_rename_map, inplace=True)
    
    merge_cols = ['PartNumber', 'Product Code', 'Description', 'Total Freq'] + list(freq_rename_map.values())
    final_db = pd.merge(pivot_qty, pivot_freq[merge_cols], on=['PartNumber', 'Product Code', 'Description'], how='left')
    
    # Attach Trend information
    qty_3m.rename(columns={part_col: 'PartNumber'}, inplace=True)
    qty_12m.rename(columns={part_col: 'PartNumber'}, inplace=True)
    unit_costs.rename(columns={part_col: 'PartNumber'}, inplace=True)
    
    final_db = pd.merge(final_db, qty_3m, on='PartNumber', how='left').fillna({'qty_3m': 0})
    final_db = pd.merge(final_db, qty_12m, on='PartNumber', how='left').fillna({'qty_12m': 0})
    final_db = pd.merge(final_db, unit_costs, on='PartNumber', how='left').fillna({'Unit Cost': 0.0})
    
    # Compute Trend logic mapping strings
    def calculate_trend_row(row):
        q3 = row['qty_3m']
        q12 = row['qty_12m']
        if q12 <= 0:
            return "🟡 Moderate Trend" if q3 == 0 else "🟢 Upward Trend"
        ratio = q3 / q12
        if ratio < 0.70:
            return "🔴 Downward Trend"
        elif 0.70 <= ratio <= 1.14:
            return "🟡 Moderate Trend"
        else:
            return "🟢 Upward Trend"

    final_db['Trend'] = final_db.apply(calculate_trend_row, axis=1)
    return final_db, target_areas

# --- EXCEL EXPORT HELPER ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales Report')
    return output.getvalue()


# --- SIDEBAR: SYSTEM STATUS & UPDATE ---
with st.sidebar:
    st.header("System Status")
    try:
        raw_data, date_col_name = load_backend_data_from_sqlite()
        db_min_date = raw_data[date_col_name].min().date()
        db_max_date = raw_data[date_col_name].max().date()
            
        st.success("SQLite Engine Active")
        # 🔄 DYNAMIC TIME-WINDOW DISPLAY DETECTED FROM THE INTERNAL FILE MATRIX
        st.info(f"**Total History Available:**\n\n{db_min_date.strftime('%d %b %Y')} to {db_max_date.strftime('%d %b %Y')}")
        
        if st.button("Force Data Refresh"):
            st.cache_data.clear()
            st.rerun()
    except Exception as e:
        st.error(f"Failed to load data from SQLite instance.\n\nError: {e}")
        st.stop()
        
    st.divider()
    st.header("Update Master Database")
    st.write("Upload your new monthly files or a custom `Sales.db` snapshot file to append records incrementally.")
    
    monthly_files = st.file_uploader("Upload Data Files (.csv, .xlsx, .db)", type=["csv", "xlsx", "db"], accept_multiple_files=True)
    
    if monthly_files:
        try:
            new_dataframes = []
            for file in monthly_files:
                if file.name.endswith('.db'):
                    with open(DB_FILE_PATH, "wb") as f:
                        f.write(file.getbuffer())
                    st.info("Restoring data infrastructure from uploaded SQLite model database...")
            
            for file in monthly_files:
                if file.name.endswith('.csv'):
                    df_temp = pd.read_csv(file, low_memory=False)
                    df_temp.columns = df_temp.columns.str.strip()
                    new_dataframes.append(df_temp)
                elif file.name.endswith('.xlsx'):
                    df_temp = pd.read_excel(file)
                    df_temp.columns = df_temp.columns.str.strip()
                    new_dataframes.append(df_temp)
            
            if new_dataframes:
                with st.spinner("Appending new records directly to existing database..."):
                    conn = sqlite3.connect(DB_FILE_PATH)
                    for incoming_df in new_dataframes:
                        t_date = 'Invoice Date' if 'Invoice Date' in incoming_df.columns else 'Date'
                        if t_date in incoming_df.columns:
                            incoming_df[t_date] = pd.to_datetime(incoming_df[t_date], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
                        incoming_df.to_sql("sales_records", conn, if_exists='append', index=False)
                    
                    dedup_df = pd.read_sql_query("SELECT * FROM sales_records", conn)
                    dedup_df = dedup_df.drop_duplicates()
                    dedup_df.to_sql("sales_records", conn, if_exists='replace', index=False)
                    conn.close()
                    st.success("New entries saved cleanly without matching duplicates!")
            
            conn = sqlite3.connect(DB_FILE_PATH)
            final_row_count = conn.execute("SELECT count(*) FROM sales_records").fetchone()[0]
            conn.close()
            
            st.metric("Total Consolidated Records", f"{final_row_count:,} rows")
            st.cache_data.clear()
            
            with open(DB_FILE_PATH, "rb") as f:
                st.download_button(
                    label="Download Updated Master Database (.db)",
                    data=f.read(),
                    file_name="Sales.db",
                    mime="application/x-sqlite3"
                )
            if st.button("Refresh View Interface"):
                st.rerun()
        except Exception as e:
            st.error(f"Error executing database append operations: {e}")


# --- DATE FILTERING UI ---
st.write("### Set Timeframe")

time_preset = st.radio("Quick Filters:", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"], horizontal=True)

if time_preset == "Last 3 Months":
    start_date = (db_max_date - pd.DateOffset(months=3)).date()
    end_date = db_max_date
elif time_preset == "Last 6 Months":
    start_date = (db_max_date - pd.DateOffset(months=6)).date()
    end_date = db_max_date
elif time_preset == "Last 12 Months":
    start_date = (db_max_date - pd.DateOffset(months=12)).date()
    end_date = db_max_date
else:
    date_range = st.slider("Select Custom Date Range", min_value=db_min_date, max_value=db_max_date, value=(db_min_date, db_max_date), format="DD/MM/YY")
    start_date, end_date = date_range[0], date_range[1]

database, areas = generate_filtered_database(raw_data, date_col_name, start_date, end_date)


# --- MAIN INTERFACE: THE CHECKER ---
st.write("### Enter Part Numbers")

if 'editor_key' not in st.session_state: st.session_state['editor_key'] = 0
# 🔄 UPDATED: Added structural default input row entry point for order counts
if 'input_df' not in st.session_state: 
    st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""], "Order Qty": [0, 0, 0, 0, 0]})

if st.button("Clear List", key="clear_list_btn"):
    st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""], "Order Qty": [0, 0, 0, 0, 0]})
    st.session_state['editor_key'] += 1
    st.rerun()

edited_input = st.data_editor(
    st.session_state['input_df'],
    num_rows="dynamic",
    column_config={
        "PartNumber": st.column_config.TextColumn("Part Number (Editable)", required=True),
        "Order Qty": st.column_config.NumberColumn("Order Qty", min_value=0, default=0, step=1)
    },
    key=f"data_editor_{st.session_state['editor_key']}" 
)

if not edited_input.empty:
    valid_inputs = edited_input[edited_input["PartNumber"].astype(str).str.strip() != ""].copy()
    if not valid_inputs.empty:
        valid_inputs['PartNumber'] = valid_inputs['PartNumber'].astype(str)
        database['PartNumber'] = database['PartNumber'].astype(str)
        
        # Merge input data array with master file features
        result_df = pd.merge(valid_inputs, database, on="PartNumber", how="left")
        
        result_df['Description'] = result_df['Description'].fillna("Not Found")
        result_df['Product Code'] = result_df['Product Code'].fillna("N/A")
        result_df['Unit Cost'] = result_df['Unit Cost'].fillna(0.0)
        result_df['Trend'] = result_df['Trend'].fillna("🟡 Moderate Trend")
        result_df['Order Qty'] = result_df['Order Qty'].fillna(0).astype(int)
        
        # Calculate dynamic structural cost metrics
        result_df['Total Cost'] = result_df['Order Qty'] * result_df['Unit Cost']
        
        all_numeric_cols = areas + [f"{a} Freq" for a in areas] + ['Total Qty', 'Total Freq']
        for col in all_numeric_cols:
            if col in result_df.columns:
                result_df[col] = result_df[col].fillna(0).astype(int)
        
        st.write("### Final Sales Report")
        st.info(f"**Data Range Selected:** Quantities and Frequencies below represent sales from **{start_date.strftime('%d %b %Y')}** to **{end_date.strftime('%d %B %Y')}**")
        
        view_mode = st.radio(
            "Select Display Format:", 
            ["Color-Coded Detailed View", "Compact View (Text Combined)"], 
            horizontal=True
        )
        
        # Dynamic placement order injection rule
        leading_cols = ['PartNumber', 'Product Code', 'Description', 'Order Qty', 'Unit Cost', 'Total Cost', 'Trend']
        
        if view_mode == "Compact View (Text Combined)":
            display_df = result_df[leading_cols].copy()
            for area in areas:
                display_df[area] = "Qty: " + result_df[area].astype(str) + " | Freq: " + result_df[f"{area} Freq"].astype(str)
            display_df['Total'] = "Qty: " + result_df['Total Qty'].astype(str) + " | Freq: " + result_df['Total Freq'].astype(str)
            st.dataframe(display_df, width="stretch")
            
        else:
            display_cols = list(leading_cols)
            for area in areas:
                display_cols.extend([area, f"{area} Freq"])
            display_cols.extend(['Total Qty', 'Total Freq'])
            
            detailed_df = result_df[[c for c in display_cols if c in result_df.columns]]
            
            def color_columns(col):
                if col.name == "Trend":
                    styles = []
                    for val in col:
                        if "🔴" in str(val):
                            styles.append('background-color: rgba(231, 76, 60, 0.15); color: #C0392B; font-weight: bold')
                        elif "🟢" in str(val):
                            styles.append('background-color: rgba(46, 204, 113, 0.15); color: #27AE60; font-weight: bold')
                        else:
                            styles.append('background-color: rgba(241, 196, 15, 0.15); color: #D35400; font-weight: bold')
                    return styles
                elif "Freq" in col.name:
                    return ['background-color: rgba(41, 128, 185, 0.15); color: #2980B9; font-weight: bold'] * len(col)
                elif col.name in areas or col.name in ["Total Qty", "Order Qty"]:
                    return ['background-color: rgba(39, 174, 96, 0.15); color: #27AE60; font-weight: bold'] * len(col)
                elif col.name in ["Unit Cost", "Total Cost"]:
                    return ['background-color: rgba(155, 89, 182, 0.11); color: #8E44AD; font-weight: bold'] * len(col)
                else:
                    return [''] * len(col)

            styled_df = detailed_df.style.apply(color_columns, axis=0).format({
                'Unit Cost': '₹{:.2f}',
                'Total Cost': '₹{:.2f}'
            })
            st.dataframe(styled_df, width="stretch")
        
        # --- EXCEL DOWNLOAD FORMAT SETTING ---
        export_cols = list(leading_cols)
        for area in areas:
            export_cols.extend([area, f"{area} Freq"])
        export_cols.extend(['Total Qty', 'Total Freq'])
        export_df = result_df[[c for c in export_cols if c in result_df.columns]]
        
        st.download_button(
            label="Download Full Report (Excel)",
            data=convert_df_to_excel(export_df),
            file_name=f"VECV_Report_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
