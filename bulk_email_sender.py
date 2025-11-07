import streamlit as st
import pandas as pd
import csv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
import os
import time
import queue
from threading import Thread
from io import StringIO, BytesIO

from email_validator import validate_email, EmailNotValidError

# --- 0. Initial Setup ---

# Load environment variables from a .env file (for local development)
load_dotenv()

# Streamlit page configuration
st.set_page_config(
    page_title="Customizable Mail Merge Sender",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 1. Session State Management ---

STEP_LABELS = [
    "1️⃣ Data & Mapping", 
    "2️⃣ Template Editor", 
    "3️⃣ Record Preview", 
    "4️⃣ SMTP & Test", 
    "5️⃣ Send & Status"
]
MAX_STEPS = len(STEP_LABELS)

def initialize_session_state():
    """
    Initializes all necessary state variables.
    """
    defaults = {
        'step_index': 0, # NEW: Tracks the current step
        'df': None,
        'html_template': None,
        'is_sending': False,
        'recipient_col': None,
        'subject_line': "Your Personalized Message",
        'from_name': "Bulk Sender App",
        # --- SMTP Configuration Defaults ---
        'sender_email': "",
        'sender_password': "", 
        'smtp_server': "",   
        'smtp_port': 587,
        'smtp_test_passed': False, 
        # -----------------------------------
        'workers': 3,
        'retries': 3,
        'job_queue': queue.Queue(),
        'email_list_input': "",
        'column_mapping': {},
        'last_csv_name': None,
        'html_uploader_name': None,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

initialize_session_state()

# --- 2. Navigation Functions ---

def set_step(index):
    """Sets the current step index."""
    if 0 <= index < MAX_STEPS:
        st.session_state.step_index = index

def go_next():
    """Increments the step index if possible."""
    set_step(st.session_state.step_index + 1)

def go_prev():
    """Decrements the step index if possible."""
    set_step(st.session_state.step_index - 1)

# --- 3. Core Logic Functions ---

def is_valid_email(email):
    """Validates the email address format."""
    try:
        validate_email(email, check_deliverability=False) 
        return True
    except EmailNotValidError:
        return False

def get_colored_dataframe(df):
    """Apply conditional coloring to the Status column."""
    if df is None:
        return pd.DataFrame()

    def color_status(val):
        color = ''
        if val == 'Sent':
            color = 'lightgreen'
        elif val in ['Failed', 'Authentication Error']:
            color = '#ffcccb'
        elif val == 'Invalid Email':
            color = 'orange'
        elif val == 'Queued':
            color = 'lightblue'
        return f'background-color: {color}'

    return df.style.applymap(color_status, subset=['Status'])

def update_status(index, status):
    """Safely update the status of a specific record in session state."""
    if st.session_state.df is not None:
        try:
            st.session_state.df.loc[index, 'Status'] = status
        except KeyError:
            pass

def apply_personalization(html_template, subject_line, record, mapping, recipient_col_name):
    """Applies the personalized data to the template and subject using the defined mapping."""
    customized_html = html_template
    customized_subject = subject_line
    
    # 1. Apply Mapped Placeholders
    for placeholder_name, csv_column in mapping.items():
        placeholder = "{{" + placeholder_name + "}}"
        value = record.get(csv_column, "")
        str_value = str(value) if pd.notna(value) else ""
        customized_html = customized_html.replace(placeholder, str_value)
        customized_subject = customized_subject.replace(placeholder, str_value)

    # 2. Also ensure the recipient column can be used as a fallback placeholder 
    if recipient_col_name in record:
         recipient_placeholder = "{{" + recipient_col_name + "}}"
         recipient_value = record.get(recipient_col_name, "")
         str_recipient_value = str(recipient_value) if pd.notna(recipient_value) else ""
         customized_html = customized_html.replace(recipient_placeholder, str_recipient_value)
         customized_subject = customized_subject.replace(recipient_placeholder, str_recipient_value)
         
    return customized_html, customized_subject


def send_email_worker(q, app_state):
    """Worker function to send emails from a queue with retries."""
    while True:
        try:
            record_index, record = q.get(timeout=1)
        except queue.Empty:
            break

        recipient_email = record.get(app_state['recipient_col'], "").strip()
        
        if not is_valid_email(recipient_email):
            update_status(record_index, "Invalid Email")
            q.task_done()
            continue

        try:
            customized_html, customized_subject = apply_personalization(
                app_state['html_template'], 
                app_state['subject_line'], 
                record, 
                app_state['column_mapping'],
                app_state['recipient_col']
            )

            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(customized_subject, 'utf-8')
            msg["From"] = Header(f"{app_state['from_name']} <{app_state['sender_email']}>", 'utf-8')
            msg["To"] = recipient_email
            part1 = MIMEText(customized_html, "html", 'utf-8')
            msg.attach(part1)

            retries = app_state['retries']
            delay = 5
            
            for attempt in range(retries):
                try:
                    with smtplib.SMTP(app_state['smtp_server'], app_state['smtp_port']) as server:
                        server.starttls()
                        server.login(app_state['sender_email'], app_state['sender_password'])
                        server.sendmail(app_state['sender_email'], recipient_email, msg.as_string())
                        update_status(record_index, "Sent")
                        break
                except smtplib.SMTPAuthenticationError:
                    update_status(record_index, "Authentication Error")
                    break 
                except Exception as e:
                    print(f"SMTP attempt {attempt + 1} failed for {recipient_email}. Error: {e}")
                    if attempt < retries - 1:
                        time.sleep(delay)
                        delay *= 2
                    else:
                        update_status(record_index, "Failed")
                        break
        
        except Exception as e:
            print(f"Critical error processing record {record_index}: {e}")
            update_status(record_index, "Failed")

        finally:
            q.task_done()

def test_smtp_connection():
    """Attempts to connect and log in to the configured SMTP server."""
    st.session_state.smtp_test_passed = False
    
    if not all([st.session_state.sender_email, st.session_state.sender_password, st.session_state.smtp_server, st.session_state.smtp_port]):
        st.error("Please fill in all SMTP fields before testing.")
        return

    try:
        with st.spinner("Attempting to connect and authenticate..."):
            with smtplib.SMTP(st.session_state.smtp_server, st.session_state.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(st.session_state.sender_email, st.session_state.sender_password)
                st.session_state.smtp_test_passed = True
                st.success("SMTP connection and authentication successful! You are ready to send.")
    except smtplib.SMTPAuthenticationError:
        st.error("Authentication failed. Check your **Sender Email** and **App Password/Token**.")
    except Exception as e:
        st.error(f"Connection Error: {e}. Check if the SMTP server address, port, and App Password are correct.")
        
    if not st.session_state.smtp_test_passed:
        st.warning("Test failed. Please correct configuration before proceeding.")


def load_html_file():
    """Loads and processes HTML template file from session state."""
    html_file = st.session_state.html_uploader
    
    if html_file:
        try:
            st.session_state.html_template = html_file.getvalue().decode("utf-8")
            st.session_state.html_uploader_name = html_file.name
            st.success(f"HTML template '{html_file.name}' loaded successfully.")
        except Exception as e:
            st.error(f"Error reading HTML file: {e}")
            st.session_state.html_template = None
    else:
        st.session_state.html_template = None
        st.session_state.html_uploader_name = None

def load_data_source(csv_file_data, email_list_text):
    """Determines data source (CSV or text list) and populates st.session_state.df."""
    
    new_csv_uploaded = csv_file_data and (st.session_state.df is None or csv_file_data.name != st.session_state.get('last_csv_name'))

    if csv_file_data:
        try:
            csv_data = StringIO(csv_file_data.getvalue().decode("utf-8"))
            df = pd.read_csv(csv_data).fillna('')
            
            if new_csv_uploaded:
                st.session_state.recipient_col = None
                st.session_state.column_mapping = {} 
                st.session_state.last_csv_name = csv_file_data.name

            if 'Status' not in df.columns:
                df['Status'] = 'Pending'
            df['Record ID'] = df.index
            
            st.session_state.df = df
            return

        except Exception as e:
            st.error(f"Error reading CSV file: {e}")
            st.session_state.df = None
            st.session_state.column_mapping = {}
            return

    elif email_list_text.strip():
        emails = [e.strip() for e in email_list_text.split(',') if e.strip()]
        
        if not emails:
            st.session_state.df = None
            st.session_state.column_mapping = {}
            return

        valid_emails_only = [e for e in emails if is_valid_email(e)]
        if not valid_emails_only:
            st.error("Email list provided, but no valid email formats were found.")
            st.session_state.df = None
            st.session_state.column_mapping = {}
            return

        recipient_col_name = 'Recipient Email'
        df = pd.DataFrame(valid_emails_only, columns=[recipient_col_name])
        df['Status'] = 'Pending'
        df['Record ID'] = df.index
        
        st.session_state.df = df
        st.session_state.recipient_col = recipient_col_name
        st.session_state.column_mapping = {recipient_col_name: recipient_col_name}
        return

    st.session_state.df = None
    st.session_state.column_mapping = {}


def start_sending():
    """Starts the email sending process in a background thread."""
    df = st.session_state.df
    
    if not all([df is not None, st.session_state.html_template, st.session_state.recipient_col, st.session_state.smtp_test_passed]):
        st.error("Please complete all previous steps (Data, Template, and SMTP Test) before starting the send job.")
        return
        
    st.session_state.job_queue = queue.Queue()
    st.session_state.is_sending = True
    st.session_state.threads = []

    pending_df = df[df['Status'] != 'Sent'].copy() 

    if pending_df.empty:
        st.warning("No pending emails found.")
        st.session_state.is_sending = False
        return

    for index, row in pending_df.iterrows():
        update_status(index, "Queued")
        st.session_state.job_queue.put((index, row.to_dict()))
        
    st.info(f"Starting {st.session_state.job_queue.qsize()} emails with {st.session_state.workers} workers...")
    
    for i in range(st.session_state.workers):
        worker = Thread(target=send_email_worker, args=(st.session_state.job_queue, st.session_state), daemon=True)
        worker.start()
        st.session_state.threads.append(worker)

def check_sending_status():
    """Checks the queue and updates the UI (called periodically)."""
    
    total_records = len(st.session_state.df)
    completed_statuses = ['Sent', 'Failed', 'Invalid Email', 'Authentication Error']
    completed_count = st.session_state.df['Status'].isin(completed_statuses).sum()

    if completed_count == total_records or st.session_state.job_queue.empty() and not any(t.is_alive() for t in st.session_state.threads):
        if st.session_state.is_sending: # Only show success message if it was actively sending
            st.session_state.is_sending = False
            st.success("Email sending job finished!")
            st.rerun()
        
    return completed_count, total_records

def get_available_csv_columns(df, recipient_col):
    """Returns a list of CSV columns available for mapping."""
    if df is not None:
        columns = df.columns.tolist()
        cols_to_exclude = ['Status', 'Record ID', recipient_col]
        return [col for col in columns if col not in cols_to_exclude]
    return []

# --- 4. Streamlit UI Layout ---

st.title("✉️ Bulk Mail Merge Sender: Guided Setup")

# Step navigation bar 
st.markdown("""
<style>
/* Custom styling for the navigation buttons to simulate a progress bar/wizard */
.stRadio > div {
    flex-direction: row;
    gap: 1rem;
    padding: 10px;
    border-bottom: 2px solid #ddd;
}
.stRadio > div > label {
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
    transition: background-color 0.2s, color 0.2s;
    font-weight: bold;
    cursor: pointer;
}
.stRadio > div > label:has(input:checked) {
    background-color: #0d47a1; /* Dark Blue */
    color: white;
}
/* Style for placeholder list in Step 2 */
.placeholder-list {
    background-color: #f0f2f6;
    border-radius: 0.5rem;
    padding: 1rem;
    height: 300px; /* Match height of text area */
    overflow-y: scroll;
}
.placeholder-item {
    padding: 0.3rem 0;
    font-family: monospace;
    font-size: 14px;
    color: #c0392b; /* A distinct color for easy spotting */
}
</style>
""", unsafe_allow_html=True)

current_step_label = STEP_LABELS[st.session_state.step_index]
st.radio(
    "Navigation", 
    options=STEP_LABELS, 
    index=st.session_state.step_index, 
    key="step_radio",
    label_visibility="collapsed"
)

st.markdown(f"## {current_step_label}")
st.markdown("---")

# --- Content Containers based on Step Index ---

# --- Step 1: Data & Mapping (Index 0) ---
if st.session_state.step_index == 0:
    st.header("Upload Data and Configure Merge Fields")
    
    csv_file = st.file_uploader("Upload CSV Data File (Optional)", type=['csv'], key="csv_uploader")
    
    st.session_state.email_list_input = st.text_area(
        "OR Enter Comma-Separated Email IDs (e.g., a@a.com, b@b.com)", 
        value=st.session_state.email_list_input, 
        height=100, 
        key="email_list_text_input"
    )
    
    load_data_source(csv_file, st.session_state.email_list_input)
    
    if st.session_state.df is not None:
        st.success(f"Data loaded successfully. Found **{len(st.session_state.df)}** records.")
        st.subheader("Campaign Details & Mapping")
        
        col_options = st.session_state.df.columns.tolist()
        
        default_index = col_options.index(st.session_state.recipient_col) + 1 if st.session_state.recipient_col in col_options else 0
        
        st.session_state.recipient_col = st.selectbox(
            "1. Select Recipient Email Column (Mandatory)", 
            options=[None] + col_options, 
            index=default_index,
            key="recipient_column_select"
        )
        
        st.session_state.from_name = st.text_input("2. Sender Display Name", value=st.session_state.from_name)
        st.session_state.subject_line = st.text_input("3. Email Subject Line (Use Mapped Variables)", value=st.session_state.subject_line)
        
        available_cols = get_available_csv_columns(st.session_state.df, st.session_state.recipient_col)
        
        if st.session_state.recipient_col and available_cols:
            st.subheader("4. Variable Mapping")
            st.markdown("Define short names for your CSV columns to use as placeholders (e.g., `{{Name}}`).")
            
            new_mapping = st.session_state.column_mapping.copy()
            col_map, col_placeholder = st.columns([1, 1])
            col_map.markdown("**:blue[CSV Column Name]**")
            col_placeholder.markdown("**:blue[Template Variable (e.g., `Name`)]**")
            
            with st.container(border=True):
                for csv_col in available_cols:
                    placeholder_key = f"placeholder_map_{csv_col}"
                    
                    initial_placeholder = ""
                    for p_name, c_name in st.session_state.column_mapping.items():
                        if c_name == csv_col:
                            initial_placeholder = p_name
                            break
                    
                    if not initial_placeholder:
                        initial_placeholder = csv_col.replace(' ', '_').replace('-', '_').strip()
                        
                    c1, c2 = st.columns([1, 1])
                    c1.text_input(csv_col, value=csv_col, disabled=True, label_visibility="collapsed", key=f"csv_{csv_col}")
                    
                    user_input = c2.text_input("Placeholder Name", value=initial_placeholder, key=placeholder_key, label_visibility="collapsed")
                    
                    if user_input.strip():
                        new_mapping[user_input.strip()] = csv_col
                    else:
                        keys_to_remove = [k for k, v in new_mapping.items() if v == csv_col]
                        for k in keys_to_remove:
                            del new_mapping[k]

            st.session_state.column_mapping = new_mapping
            
            # Placeholders for display are generated here
            placeholders = [f"{{{{{p}}}}}" for p in st.session_state.column_mapping.keys()]
            if st.session_state.recipient_col:
                placeholders.append(f"{{{{{st.session_state.recipient_col}}}}}")
                
            st.info(f"Available Placeholders for Template: {', '.join(placeholders)}")

    else:
        st.warning("Please upload a CSV or enter an email list to proceed to the next step.")

# --- Step 2: Template Editor (Index 1) ---
elif st.session_state.step_index == 1:
    st.header("Upload and Edit HTML Template")
    
    # Check if data is ready for template mapping
    is_data_ready = st.session_state.df is not None and st.session_state.recipient_col is not None
    
    html_file = st.file_uploader(
        "Upload HTML Template File", 
        type=['html'], 
        on_change=load_html_file,
        key="html_uploader"
    )

    if st.session_state.html_template:
        
        col_editor, col_placeholders = st.columns([3, 1])
        
        with col_editor:
            st.subheader("Template Editor")
            st.caption(f"Editing content from: **{st.session_state.get('html_uploader_name', 'Manual Input')}**")
            st.session_state.html_template = st.text_area(
                "Edit HTML Template Content (Use `{{Placeholders}}`)",
                value=st.session_state.html_template,
                height=300,
                key="template_editor_area"
            )
            
        with col_placeholders:
            st.subheader("Placeholders")
            if is_data_ready:
                
                # Re-generate placeholders list based on mapping
                placeholders = [f"{{{{{p}}}}}" for p in st.session_state.column_mapping.keys()]
                if st.session_state.recipient_col:
                    placeholders.append(f"{{{{{st.session_state.recipient_col}}}}}")
                
                # Display placeholders list for easy copying
                st.markdown('<div class="placeholder-list">', unsafe_allow_html=True)
                st.markdown("**Copy and paste into your HTML:**")
                for p in placeholders:
                    st.markdown(f'<div class="placeholder-item">{p}</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            else:
                st.warning("Complete **Step 1** to define placeholders.")

        st.markdown("---")
        st.subheader("Live Template Preview (Un-personalized)")
        st.html(st.session_state.html_template)
    else:
        st.warning("Please upload an HTML file to proceed to the next step.")

# --- Step 3: Record Preview (Index 2) ---
elif st.session_state.step_index == 2:
    st.header("Personalized Email Preview")
    
    if st.session_state.df is not None and st.session_state.html_template is not None and st.session_state.recipient_col:
        st.markdown("Select a **Record ID** from the table to see exactly how the email will look for that recipient.")
        
        max_index = len(st.session_state.df) - 1
        
        # Display Data for reference
        st.subheader("Data Records")
        st.dataframe(st.session_state.df[['Record ID'] + [col for col in st.session_state.df.columns if col not in ['Status', 'Record ID']]], 
                     use_container_width=True, hide_index=True)

        st.subheader("Preview Generator")
        
        col_index, col_button = st.columns([1, 2])
        
        with col_index:
            preview_row_idx = st.number_input(
                "Enter Record ID to Preview (0 to Max)", 
                min_value=0, 
                max_value=max_index, 
                step=1, 
                key="preview_index",
                help="The Record ID corresponds to the index in the table above."
            )
        
        with col_button:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Generate Personalized Preview", use_container_width=True):
                try:
                    record_to_preview = st.session_state.df.iloc[preview_row_idx].to_dict()
                    
                    preview_html, preview_subject = apply_personalization(
                        st.session_state.html_template, 
                        st.session_state.subject_line, 
                        record_to_preview, 
                        st.session_state.column_mapping,
                        st.session_state.recipient_col
                    )
                        
                    st.success(f"Preview for **{record_to_preview.get(st.session_state.recipient_col, 'Record')}**")
                    st.info(f"**Final Subject:** {preview_subject}")
                    st.html(preview_html)
                    
                except IndexError:
                    st.error("Invalid Record ID. Please enter a number within the range.")
                except Exception as e:
                    st.error(f"Could not generate personalized preview. Error: {e}")
    else:
        st.warning("Please ensure Data, Mapping, and Template are configured in Steps 1 and 2.")

# --- Step 4: SMTP Configuration & Test (Index 3) ---
elif st.session_state.step_index == 3:
    st.header("SMTP Server Configuration & Test")
    st.markdown("Enter your server details. You **must** use an App Password or Token if required by your email provider.")
    
    col_smtp_1, col_smtp_2 = st.columns(2)
    
    with col_smtp_1:
        st.session_state.sender_email = st.text_input("Sender Email (From)", value=st.session_state.sender_email, key="smtp_sender_email")
        st.session_state.smtp_server = st.text_input("SMTP Server", value=st.session_state.smtp_server, key="smtp_server_input", help="e.g., smtp.gmail.com")
    with col_smtp_2:
        st.session_state.sender_password = st.text_input("App Password / Token", value=st.session_state.sender_password, type="password", key="smtp_sender_password", help="Use a generated App Password for services like Gmail.")
        st.session_state.smtp_port = st.number_input("SMTP Port (usually 587 or 465)", value=st.session_state.smtp_port, min_value=1, max_value=65535, step=1, key="smtp_port_input")
        
    st.subheader("Sending Parameters")
    col_adv_1, col_adv_2 = st.columns(2)
    with col_adv_1:
        st.session_state.workers = st.slider("Concurrent Workers (Threads)", 1, 10, st.session_state.workers, key="workers_slider", help="More workers speed up the job but may cause rate limiting issues.")
    with col_adv_2:
        st.session_state.retries = st.slider("Email Retries on Failure", 0, 5, st.session_state.retries, key="retries_slider", help="Number of times to retry a failed email.")

    st.markdown("---")
    st.subheader("Test Connection")
    
    if st.session_state.smtp_test_passed:
        st.success("✅ SMTP Test Passed: Credentials confirmed.")
    else:
        st.warning("Run the test below to confirm credentials before proceeding.")

    st.button("⚙️ Test SMTP Connection", on_click=test_smtp_connection, type="secondary", use_container_width=True)

# --- Step 5: Send & Status (Index 4) ---
elif st.session_state.step_index == 4:
    st.header("Start Sending and Track Status")
    
    if st.session_state.df is not None:
        
        # Readiness Checks
        is_ready = st.session_state.smtp_test_passed and st.session_state.html_template is not None and st.session_state.recipient_col is not None

        if not is_ready:
            st.error("🚨 Configuration incomplete. Ensure **Data, Template, and SMTP Test (Step 4)** are successful.")
        else:
            st.success("✅ All checks passed! The application is ready to start the bulk send job.")

        
        send_disabled = not is_ready or st.session_state.is_sending

        st.button("🚀 Start Bulk Send", on_click=start_sending, type="primary", use_container_width=True, disabled=send_disabled)
        
        st.markdown("---")
        st.subheader("Current Data Status")

        # Progress Bar and Status (Active during sending)
        if st.session_state.is_sending:
            completed, total = check_sending_status()
            progress_percent = completed / total if total > 0 else 0
            
            st.progress(progress_percent, text=f"Processing: {completed}/{total} ({progress_percent*100:.1f}%)")
            st.warning("Sending in progress. Do not refresh the page until complete.")
            
            # Display and constantly update the dataframe via st.rerun
            st.dataframe(get_colored_dataframe(st.session_state.df), use_container_width=True, hide_index=True)
            
            time.sleep(1)
            st.rerun()
            
        else:
            # Final Status Table
            if st.session_state.df is not None:
                st.dataframe(get_colored_dataframe(st.session_state.df), use_container_width=True, hide_index=True)

    else:
        st.warning("Please upload a CSV or enter an email list in Step 1 to begin configuration.")


# --- Navigation Buttons (Placed at the bottom of every step) ---
st.markdown("---")
col_prev, col_spacer, col_next = st.columns([1, 4, 1])

# Previous Button
if st.session_state.step_index > 0:
    with col_prev:
        st.button(f"← Previous: {STEP_LABELS[st.session_state.step_index - 1]}", on_click=go_prev)

# Next Button
if st.session_state.step_index < MAX_STEPS - 1:
    with col_next:
        st.button(f"Next: {STEP_LABELS[st.session_state.step_index + 1]} →", on_click=go_next, type="primary")
