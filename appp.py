import streamlit as st
import pandas as pd
from datetime import datetime
import io

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Sales Quantity Checker", layout="wide")
st.title("📦 Sales Quantity Checker")

# 🔴 REPLACE THIS WITH YOUR ACTUAL GITHUB RAW URL 🔴
GITHUB_CSV_URL = "https://raw.githubusercontent.com/mokshinfection/Sales-gty-Checker/main/Sales.zip"
# 1. Update the URL to point to the .zip fil

# ... inside your load_and_process_backend_data function ...

    # 2. Tell Pandas to unzip the file automatically
df = pd.read_csv("https://raw.githubusercontent.com/mokshinfection/Sales-gty-Checker/main/Sales.zip", compression='zip', low_memory=False, on_bad_lines='skip')
# --- DATA PROCESSING ---
@st.cache_data(ttl=3600) # Keeps data in memory for 1 hour before checking GitHub again
# --- DATA PROCESSING ---
@st.cache_data(ttl=3600) # Keeps data in memory for 1 hour before checking GitHub again
def load_and_process_backend_data(url):
    """Fetches data from GitHub, filters for last 12 months, and pivots."""
    # Load directly from GitHub and skip bad rows
    df = pd.read_csv(url, low_memory=False, on_bad_lines='skip')
    
    # 1. Clean up column names (removes any accidental hidden spaces)
    df.columns = df.columns.str.strip()
    
    # 2. Smartly detect the date column
    if 'Invoice Date' in df.columns:
        date_col = 'Invoice Date'
    elif 'Date' in df.columns:
        date_col = 'Date'
    else:
        # If it still fails, this will print out the exact columns it found to help you debug!
        raise KeyError(f"Could not find a date column. The columns found in your GitHub file are: {', '.join(df.columns)}")
    
    # Ensure Date column is datetime format 
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
    
    # Filter: Only consider last 12 months from the most recent data
    most_recent_date = df[date_col].max()
    twelve_months_ago = most_recent_date - pd.DateOffset(months=12)
    recent_df = df[df[date_col] >= twelve_months_ago]
    
    # Pivot the data to get Areas as columns
    target_areas = ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]
    
    # Make sure we use the correct Part Number column name (checking for spaces)
    part_col = 'PartNumber' if 'PartNumber' in df.columns else 'Part Number'
    desc_col = 'Description'
    code_col = 'Product Code' if 'Product Code' in df.columns else 'Part Code'
    
    pivot_df = recent_df.pivot_table(
        index=[part_col, code_col, desc_col],
        columns='Area',
        values='qty' if 'qty' in df.columns else 'Quantity',
        aggfunc='sum',
        fill_value=0
    ).reset_index()
    
    # Rename the part column back to 'PartNumber' just for consistency in the app
    pivot_df.rename(columns={part_col: 'PartNumber', code_col: 'Product Code'}, inplace=True)
    
    # Ensure all required areas exist in the columns
    for area in target_areas:
        if area not in pivot_df.columns:
            pivot_df[area] = 0
            
    # Calculate Total
    pivot_df['Total'] = pivot_df[target_areas].sum(axis=1)
    
    return pivot_df, most_recent_date, twelve_months_ago
    # Calculate Total
    pivot_df['Total'] = pivot_df[target_areas].sum(axis=1)
    
    return pivot_df, most_recent_date, twelve_months_ago

# --- EXCEL EXPORT HELPER ---
def convert_df_to_excel(df):
    """Converts a dataframe to an Excel file in memory."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales Report')
    processed_data = output.getvalue()
    return processed_data

# --- SIDEBAR: SYSTEM STATUS ---
with st.sidebar:
    st.header("⚙️ System Status")
    
    try:
        with st.spinner("Fetching data from GitHub..."):
            database, max_date, min_date = load_and_process_backend_data(GITHUB_CSV_URL)
            
        st.success("✅ Database Active & In-Memory")
        st.info(f"📅 **Data Range:**\n\n{min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}")
        
        # Button to manually clear the cache if the GitHub file was just updated
        if st.button("🔄 Force Data Refresh"):
            st.cache_data.clear()
            st.rerun()
            
    except Exception as e:
        st.error(f"Failed to load data from GitHub. Please check the URL. \n\nError: {e}")
        st.stop()

# --- MAIN INTERFACE: THE CHECKER ---
st.write("### Enter Part Numbers")
st.write("Type or paste your **Part Numbers** below to instantly pull VECV inventory metrics.")

if 'input_df' not in st.session_state:
    st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""]})

edited_input = st.data_editor(
    st.session_state['input_df'],
    num_rows="dynamic",
    column_config={
        "PartNumber": st.column_config.TextColumn("Part Number (Editable)", required=True)
    },
    key="data_editor"
)

if not edited_input.empty:
    valid_inputs = edited_input[edited_input["PartNumber"].astype(str).str.strip() != ""]
    
    if not valid_inputs.empty:
        valid_inputs['PartNumber'] = valid_inputs['PartNumber'].astype(str)
        database['PartNumber'] = database['PartNumber'].astype(str)
        
        result_df = pd.merge(
            valid_inputs, 
            database, 
            on="PartNumber", 
            how="left"
        )
        
        result_df['Description'] = result_df['Description'].fillna("Not Found")
        result_df['Product Code'] = result_df['Product Code'].fillna("N/A")
        
        numeric_cols = ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore", "Total"]
        for col in numeric_cols:
            if col in result_df.columns:
                result_df[col] = result_df[col].fillna(0)
        
        display_cols = ['PartNumber', 'Product Code', 'Description', 'Hoskote', 'Kothagudem', 'Ramagundam', 'Neyveli', 'Nellore', 'Total']
        display_cols = [c for c in display_cols if c in result_df.columns]
        result_df = result_df[display_cols]
        
        st.write("### 📊 Sales Report")
        st.dataframe(
            result_df,
            use_container_width=True,
            column_config={
                "PartNumber": st.column_config.TextColumn("Part Number"),
                "Product Code": st.column_config.TextColumn("Product Code"),
                "Description": st.column_config.TextColumn("Description"),
                "Total": st.column_config.NumberColumn("Total Sales", format="%d")
            }
        )
        
        # --- EXCEL DOWNLOAD BUTTON ---
        excel_data = convert_df_to_excel(result_df)
        
        st.download_button(
            label="📥 Download Report (Excel)",
            data=excel_data,
            file_name=f"VECV_sales_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
