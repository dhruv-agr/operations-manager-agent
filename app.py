import streamlit as st
import json
import os
from datetime import datetime

# Import functions from our backend logic
# Ensure main.py and database.py are in the same directory or accessible via PYTHONPATH
from main import analyze_request, generate_quote, check_availability_tool, draft_email
from database import create_new_project, save_project_state, get_project_details, init_db, insert_initial_pricing_data

# --- Streamlit UI Configuration ---
st.set_page_config(layout="wide", page_title="Operations Manager Assistant")
st.title("Operations Manager Assistant")
st.markdown("Automate initial customer inquiries and quoting for central vacuum systems.")

# Initialize database and pricing data on app start
# This ensures the DB is ready when the app runs
init_db()
insert_initial_pricing_data()

# --- Session State Initialization ---
# This is crucial for maintaining state across Streamlit reruns
if 'project_id' not in st.session_state:
    st.session_state.project_id = None
if 'customer_request' not in st.session_state:
    st.session_state.customer_request = ""
if 'extracted_details' not in st.session_state:
    st.session_state.extracted_details = None
if 'approved_details' not in st.session_state:
    st.session_state.approved_details = None
if 'quote_draft' not in st.session_state:
    st.session_state.quote_draft = None
if 'final_quote' not in st.session_state:
    st.session_state.final_quote = None
if 'availability_info' not in st.session_state:
    st.session_state.availability_info = None
if 'email_draft' not in st.session_state:
    st.session_state.email_draft = None
if 'current_step' not in st.session_state:
    st.session_state.current_step = "input_request" # States: input_request, review_extracted, review_quote, review_email, completed

# --- UI Layout ---
st.sidebar.header("Project Status")
if st.session_state.project_id:
    st.sidebar.write(f"**Project ID:** `{st.session_state.project_id}`")
    project_status = get_project_details(st.session_state.project_id)
    if project_status:
        st.sidebar.write(f"**Status:** `{project_status.get('status', 'N/A')}`")
else:
    st.sidebar.write("No active project.")

# --- Main Workflow ---

# Step: Input Customer Request
if st.session_state.current_step == "input_request":
    st.header("1. Enter Customer Request")
    customer_input = st.text_area(
        "Paste the customer's inquiry here:",
        value=st.session_state.customer_request,
        height=150,
        key="customer_request_input"
    )

    if st.button("Analyze Request", key="analyze_button"):
        if customer_input:
            with st.spinner("Analyzing request with AI..."):
                st.session_state.customer_request = customer_input
                st.session_state.project_id = create_new_project(customer_input)
                st.session_state.extracted_details = analyze_request(customer_input)
                if st.session_state.extracted_details:
                    save_project_state(st.session_state.project_id, extracted_details=json.dumps(st.session_state.extracted_details), status='pending_extraction_approval')
                    st.session_state.current_step = "review_extracted"
                    st.rerun() # Rerun to update UI for next step
                else:
                    st.error("Failed to analyze request. Please try again or check logs.")
                    save_project_state(st.session_state.project_id, status='extraction_failed')
        else:
            st.warning("Please enter a customer request.")

# Step: Review Extracted Details
if st.session_state.current_step == "review_extracted":
    st.header("2. Review Extracted Details")
    st.write("Please review and approve or modify the details extracted by the AI.")
    
    # Display extracted details in a more user-friendly way
    if st.session_state.extracted_details:
        st.subheader("Extracted Information:")
        details = st.session_state.extracted_details
        st.write(f"**Primary Item:** {details.get('item_requested', 'N/A')}")
        st.write(f"**Model/Type:** {details.get('model', 'N/A')}")
        if 'hose_length_ft' in details and details['hose_length_ft'] != "N/A":
            st.write(f"**Hose Length:** {details['hose_length_ft']} ft")
        if 'attachment_set' in details and details['attachment_set'] != "N/A":
            st.write(f"**Attachment Set:** {details['attachment_set']}")
        if 'parts_needed' in details and details['parts_needed'] != "N/A":
            st.write("**Parts Needed:**")
            for part in details['parts_needed']:
                st.write(f"- {part.get('quantity', 1)} x {part.get('part_name', 'N/A')}")
        if 'services' in details and details['services'] != "N/A":
            st.write(f"**Services Requested:** {', '.join(details['services'])}")
        st.write(f"**Customer Name:** {details.get('customer_name', 'N/A')}")
        st.write(f"**Customer Address:** {details.get('customer_address', 'N/A')}")
        
        st.markdown("---")
        st.subheader("Raw Extracted Details (for modification):")
    
    extracted_details_str = json.dumps(st.session_state.extracted_details, indent=2)
    modified_details_str = st.text_area("Extracted Details (JSON):", value=extracted_details_str, height=300, key="modified_details_input")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve Extracted Details", key="approve_extracted"):
            try:
                st.session_state.approved_details = json.loads(modified_details_str)
                save_project_state(st.session_state.project_id, extracted_details=json.dumps(st.session_state.approved_details), status='extracted_details_approved')
                st.session_state.current_step = "generate_quote"
                st.rerun()
            except json.JSONDecodeError:
                st.error("Invalid JSON format. Please correct it.")
    with col2:
        if st.button("Reject & Abort Project", key="reject_extracted"):
            save_project_state(st.session_state.project_id, status='aborted_by_human')
            st.warning("Project aborted.")
            st.session_state.current_step = "input_request"
            st.session_state.clear() # Clear all state to start fresh
            st.rerun()

# Step: Generate Quote (Automatic after approval)
if st.session_state.current_step == "generate_quote":
    st.header("3. Generating Quote...")
    with st.spinner("Generating quote with AI..."):
        st.session_state.quote_draft = generate_quote(st.session_state.approved_details)
        if st.session_state.quote_draft:
            save_project_state(st.session_state.project_id, quote_draft=json.dumps(st.session_state.quote_draft), status='pending_quote_approval')
            st.session_state.current_step = "review_quote"
            st.rerun()
        else:
            st.error("Failed to generate quote. Please try again or check logs.")
            save_project_state(st.session_state.project_id, status='quote_failed')
            st.session_state.current_step = "input_request" # Go back to start on failure
            st.rerun()

# Step: Review Quote
if st.session_state.current_step == "review_quote":
    st.header("4. Review Quote Draft")
    st.write("Please review and approve or modify the generated quote.")
    
    # Display quote items in a table
    if st.session_state.quote_draft and 'quote_items' in st.session_state.quote_draft:
        st.subheader("Itemized Quote:")
        st.dataframe(st.session_state.quote_draft['quote_items'], use_container_width=True)
        
        # Display summary
        st.write(f"**Subtotal:** ${st.session_state.quote_draft.get('subtotal', 0):,.2f}")
        st.write(f"**Shipping:** ${st.session_state.quote_draft.get('shipping', 0):,.2f}")
        st.markdown(f"### **Total Estimated Cost: ${st.session_state.quote_draft.get('total_estimated_cost', 0):,.2f}**")
        if 'notes' in st.session_state.quote_draft:
            st.info(f"**Notes:** {st.session_state.quote_draft['notes']}")

        st.markdown("---")
        st.subheader("Raw Quote Draft (for modification):")

    quote_draft_str = json.dumps(st.session_state.quote_draft, indent=2)
    modified_quote_str = st.text_area("Quote Draft (JSON):", value=quote_draft_str, height=400, key="modified_quote_input")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve Quote", key="approve_quote"):
            try:
                st.session_state.final_quote = json.loads(modified_quote_str)
                save_project_state(st.session_state.project_id, final_quote=json.dumps(st.session_state.final_quote), status='quote_approved')
                st.session_state.current_step = "check_availability_and_draft_email"
                st.rerun()
            except json.JSONDecodeError:
                st.error("Invalid JSON format. Please correct it.")
    with col2:
        if st.button("Reject Quote & Abort Project", key="reject_quote"):
            save_project_state(st.session_state.project_id, status='aborted_by_human')
            st.warning("Project aborted.")
            st.session_state.current_step = "input_request"
            st.session_state.clear()
            st.rerun()

# Step: Check Availability & Draft Email (Automatic after quote approval)
if st.session_state.current_step == "check_availability_and_draft_email":
    st.header("5. Checking Availability & Drafting Email...")
    with st.spinner("Checking availability and drafting email with AI..."):
        # Check Availability
        services_from_quote = st.session_state.final_quote.get("quote_items", [])
        service_types_requested = [item.get("item", "") for item in services_from_quote if "service" in item.get("item", "").lower() or "installation" in item.get("item", "").lower() or "tune-up" in item.get("item", "").lower() or "repair" in item.get("item", "").lower()]
        st.session_state.availability_info = check_availability_tool(", ".join(service_types_requested))
        save_project_state(st.session_state.project_id, availability_info=json.dumps(st.session_state.availability_info), status='availability_checked')
        
        # Draft Email
        st.session_state.email_draft = draft_email(
            st.session_state.customer_request,
            st.session_state.approved_details,
            st.session_state.final_quote,
            st.session_state.availability_info
        )
        if st.session_state.email_draft:
            save_project_state(st.session_state.project_id, email_draft=st.session_state.email_draft, status='pending_email_approval')
            st.session_state.current_step = "review_email"
            st.rerun()
        else:
            st.error("Failed to draft email. Please try again or check logs.")
            save_project_state(st.session_state.project_id, status='email_draft_failed')
            st.session_state.current_step = "input_request" # Go back to start on failure
            st.rerun()

# Step: Review Email
if st.session_state.current_step == "review_email":
    st.header("6. Review Final Email Draft")
    st.write("Please review and approve or modify the drafted email.")
    
    # Display availability information clearly
    if st.session_state.availability_info and st.session_state.availability_info.get('available_slots'):
        st.subheader("Suggested Availability:")
        for slot in st.session_state.availability_info['available_slots']:
            st.write(f"- **Date:** {slot['date']}, **Time:** {slot['time']}")
        st.info(st.session_state.availability_info.get('note', ''))
        st.markdown("---")

    modified_email_str = st.text_area("Email Draft:", value=st.session_state.email_draft, height=500, key="modified_email_input")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve Email & Complete Project", key="approve_email"):
            st.session_state.final_email = modified_email_str
            save_project_state(st.session_state.project_id, email_draft=st.session_state.final_email, status='completed')
            st.success("Project Completed! Final email is ready.")
            st.session_state.current_step = "completed"
            st.rerun()
    with col2:
        if st.button("Reject Email & Abort Project", key="reject_email"):
            save_project_state(st.session_state.project_id, status='aborted_by_human')
            st.warning("Project aborted.")
            st.session_state.current_step = "input_request"
            st.session_state.clear()
            st.rerun()

# Step: Completed
if st.session_state.current_step == "completed":
    st.header("Project Completed!")
    st.success(f"Project ID: {st.session_state.project_id}")
    st.subheader("Final Approved Email:")
    st.markdown(st.session_state.final_email)
    st.write("You can now manually send this email to the customer.")
    if st.button("Start New Project", key="new_project_button"):
        st.session_state.clear()
        st.rerun()

# Reset button in sidebar for convenience
st.sidebar.markdown("---")
if st.sidebar.button("Reset All", key="reset_all_button"):
    st.session_state.clear()
    st.rerun()
