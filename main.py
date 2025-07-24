import os
import json
import sqlite3
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import datetime
import uuid

# Import functions from our database.py file
from database import init_db, insert_initial_pricing_data, get_pricing_data, save_project_state, create_new_project, get_project_details

# --- Configuration and Initialization ---

# Load environment variables from .env file (e.g., GOOGLE_API_KEY)
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found. Please set it in your .env file.")

# Initialize the database and insert initial data (this will only run if the DB doesn't exist or data isn't there)
init_db()
insert_initial_pricing_data()

# Initialize Gemini LLM
# Using 'gemini-1.5-flash' as per user's working configuration.
# Temperature controls randomness: 0.0 for more deterministic, higher for more creative. For structured output, lower is better.
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.0)

# Load pricing data from our SQLite database for the agents to use
PRICING_DATA = get_pricing_data()
# Format pricing data into a readable string to inject into LLM prompts (RAG principle)
pricing_context = "\n".join([
    f"- Item Type: {row[0]}, Material: {row[1]}, Unit Cost: ${row[2]} {row[3]}"
    for row in PRICING_DATA
])

print("CustomCraft QuoteBot initialized. Ready to process requests.")

# --- Human-in-the-Loop Functions ---
def human_approval(data, step_name):
    """
    Prompts the human operator for approval or modification of AI-generated data.
    Allows for 'y' (yes), 'n' (no/abort), or 'm' (modify JSON).
    """
    print(f"\n--- HUMAN APPROVAL REQUIRED: {step_name} ---")
    # Check if data is already a string (e.g., for email draft)
    if isinstance(data, dict):
        print(f"Proposed data:\n{json.dumps(data, indent=2)}") # Pretty print JSON for readability
    else: # Assume it's a string (like the email draft)
        print(f"Proposed data:\n{data}")
    
    while True:
        choice = input("Approve (y/n)? or (m)odify? ").lower()
        if choice == 'y':
            print(f"--- {step_name} APPROVED ---")
            return data
        elif choice == 'n':
            print(f"--- {step_name} REJECTED. ABORTING. ---")
            return None # Signal to abort the project workflow
        elif choice == 'm':
            print("Please provide the modified data. If it's JSON, ensure valid JSON. Type 'done' on a new line when finished.")
            modified_input_str = ""
            while True:
                line = input()
                if line.lower() == 'done':
                    break
                modified_input_str += line + "\n"
            
            # Attempt to parse as JSON if the original data was a dict, otherwise treat as string
            if isinstance(data, dict):
                try:
                    modified_data = json.loads(modified_input_str)
                    print("\nModified data received. Please review:")
                    print(json.dumps(modified_data, indent=2))
                    # Recursively call human_approval for the modified data to ensure it's also approved
                    return human_approval(modified_data, step_name + " (Modified)")
                except json.JSONDecodeError:
                    print("Invalid JSON. Please try again.")
            else: # Treat as plain string modification
                print("\nModified data received. Please review:")
                print(modified_input_str)
                return human_approval(modified_input_str, step_name + " (Modified)")
        else:
            print("Invalid input. Please enter 'y', 'n', or 'm'.")

# --- Agent Chains ---

# --- Request Analyzer Agent ---
# This chain extracts structured information from the customer's free-form request.
extraction_prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system",
         """You are an expert assistant for a custom central vacuum system company (like HausVac).
         Your task is to analyze customer requests and extract key details into a structured JSON format.
         Identify the primary item requested (e.g., 'power_unit', 'hose', 'attachment_set', 'part', 'service'),
         its specific material/model (e.g., 'PP650', '50ft_Retractable', 'HEPA_Filter', 'New_System_Installation'),
         any relevant dimensions or quantities (e.g., length for hoses, number of units for parts),
         and customer contact info (name, address, if available).

         Be precise and only include information explicitly mentioned or clearly inferable.
         For quantities, try to extract numerical values. If dimensions are mentioned, try to convert them to feet if possible.
         If a detail is not clear or not applicable, omit the key or state "N/A" for its value.
         Output only the JSON.

         Example Output Format:
         ```json
         {{
             "item_requested": "power_unit",
             "model": "PP650",
             "services": ["New_System_Installation", "Shipping_Standard"],
             "hose_length_ft": 50,
             "attachment_set": "Bare_Floor_Set",
             "parts_needed": [
                 {{"part_name": "HEPA_Filter", "quantity": 1}},
                 {{"part_name": "Disposable_Bag_Pack", "quantity": 2}}
             ],
             "customer_name": "Jane Doe",
             "customer_address": "456 Oak Ave, Townsville"
         }}
         ```
         """),
        ("human", "Customer Request: {customer_request}")
    ]
)

# Chain for extraction: Takes customer_request, passes to prompt, then LLM, then parses JSON.
request_analyzer_chain = (
    {"customer_request": RunnablePassthrough()} # Input is directly the customer request
    | extraction_prompt_template
    | llm
    | JsonOutputParser() # Expects and parses JSON output from the LLM
)

def analyze_request_step(project_id, customer_request):
    """
    Executes the Request Analyzer Agent to extract details and saves state.
    """
    print("\n[AI Agent] Analyzing customer request...")
    try:
        extracted_details = request_analyzer_chain.invoke(customer_request)
        print("Extracted Details:", json.dumps(extracted_details, indent=2))
        # Save extracted details as a JSON string in the database
        save_project_state(project_id, extracted_details=json.dumps(extracted_details), status='pending_extraction_approval')
        return extracted_details
    except Exception as e:
        print(f"Error analyzing request: {e}")
        save_project_state(project_id, status='extraction_failed')
        return None

# --- Availability Checking Agent ---
def check_availability_tool(service_type):
    """
    Simulates checking a calendar for available slots based on service type.
    This acts as our 'tool' for the LLM.
    """
    today = datetime.date.today()
    # Mock availability for the next few days
    if "installation" in service_type.lower() or "service" in service_type.lower() or "tune-up" in service_type.lower() or "repair" in service_type.lower():
        # For installation/service, suggest specific dates/times
        return {
            "available_slots": [
                {"date": str(today + datetime.timedelta(days=3)), "time": "9:00 AM - 12:00 PM"},
                {"date": str(today + datetime.timedelta(days=5)), "time": "1:00 PM - 4:00 PM"},
                {"date": str(today + datetime.timedelta(days=7)), "time": "10:00 AM - 1:00 PM"}
            ],
            "note": "These are preliminary availability slots. A representative will confirm exact timing."
        }
    else:
        # For general inquiries or product-only requests, no specific slots needed
        return {
            "available_slots": [],
            "note": "No specific service installation/consultation requested, so no availability slots needed."
        }

# --- Initial Quoting Agent ---
# This chain generates an itemized quote based on extracted details and pricing data.
quoting_prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system",
         """You are an expert quoting assistant for a custom central vacuum system company (like HausVac).
         Your task is to generate an itemized quote in JSON format based on the customer's extracted details
         and the provided pricing information.

         **Pricing Data (RAG Context):**
         {pricing_context}

         **Instructions:**
         1.  Go through each item, service, or part requested in the `extracted_details`.
         2.  For each, find the matching `material` (model/type) in the `Pricing Data`.
         3.  Calculate the `line_total` based on `unit_cost` and `quantity`/`dimensions`.
             * For 'unit' based items (e.g., power_units, hoses, attachment_sets, parts, additional_inlet_installation, shipping_standard, service_call_diagnostic, system_tune_up, clog_removal, motor_replacement_labor): `quantity * unit_cost`. Assume quantity is 1 if not specified.
             * For 'linear_ft' based items (e.g., Low_Voltage_Wiring): `hose_length_ft` or other relevant dimension * `unit_cost`. Assume length is 1 if not specified.
             * For 'per_hour' services (e.g., Labor_Rate): `estimated_hours * unit_cost`. Assume 1 hour if not specified.
             * For 'flat_fee' services: The `unit_cost` is the `line_total`.
         4.  If an item/service/part from `extracted_details` cannot be found in `Pricing Data`, its `line_total` should be "TBD" (To Be Determined) and `cost_breakdown` should state "Price not found in database.".
         5.  Calculate a `subtotal` for all quantifiable items.
         6.  Calculate a `shipping` cost. Use 'Shipping_Standard' from pricing data if applicable, otherwise 0.
         7.  Calculate a `total_estimated_cost` (subtotal + shipping).
         8.  Output only the JSON.

         **Extracted Customer Details:**
         {extracted_details}

         Example Output Format:
         ```json
         {{
             "quote_items": [
                 {{"item": "PP650 Power Unit", "quantity": 1, "unit_price": 1200.00, "line_total": 1200.00, "cost_breakdown": "1 unit @ $1200.00/unit"}},
                 {{"item": "New System Installation", "quantity": 1, "unit_price": 750.00, "line_total": 750.00, "cost_breakdown": "Flat fee"}},
                 {{"item": "50ft Retractable Hose", "quantity": 1, "unit_price": 350.00, "line_total": 350.00, "cost_breakdown": "1 unit @ $350.00/unit"}},
                 {{"item": "HEPA Filter", "quantity": 2, "unit_price": 75.00, "line_total": 150.00, "cost_breakdown": "2 units @ $75.00/unit"}},
                 {{"item": "Custom Cabinetry for Power Unit", "quantity": 1, "unit_price": "TBD", "line_total": "TBD", "cost_breakdown": "Price not found in database."}}
             ],
             "subtotal": 2450.00,
             "shipping": 50.00,
             "total_estimated_cost": 2500.00,
             "notes": "This is an estimated quote based on provided details and current pricing. Final pricing may vary upon site visit and detailed requirements."
         }}
         ```
         """),
        ("human", "Generate quote for the following extracted details: {extracted_details}")
    ]
)

# Chain for quoting: Takes extracted_details and pricing_context, passes to prompt, then LLM, then parses JSON.
initial_quoting_chain = (
    {
        "extracted_details": RunnablePassthrough(), # Pass the extracted details directly
        "pricing_context": lambda x: pricing_context # Inject the global pricing context
    }
    | quoting_prompt_template
    | llm
    | JsonOutputParser() # Expects and parses JSON output from the LLM
)

def generate_quote_step(project_id, approved_details):
    """
    Executes the Initial Quoting Agent to generate a quote draft and saves state.
    """
    print("\n[AI Agent] Generating initial quote...")
    try:
        # The LLM needs the extracted_details as a string to process it in the prompt
        quote_draft = initial_quoting_chain.invoke({"extracted_details": json.dumps(approved_details)})
        print("Quote Draft:", json.dumps(quote_draft, indent=2))
        # Save quote draft as a JSON string in the database
        save_project_state(project_id, quote_draft=json.dumps(quote_draft), status='pending_quote_approval')
        return quote_draft
    except Exception as e:
        print(f"Error generating quote: {e}")
        save_project_state(project_id, status='quote_failed')
        return None

# --- Communication Drafter Agent ---
email_prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system",
         """You are a professional and friendly sales assistant for CustomCraft (HausVac).
         Your task is to draft a personalized email to the customer based on their initial request,
         the generated quote, and the available service slots.

         **Customer Request:**
         {customer_request}

         **Extracted Details:**
         {extracted_details}

         **Final Approved Quote:**
         {final_quote}

         **Availability Information:**
         {availability_info}

         **Instructions:**
         1.  Start with a polite greeting, addressing the customer by name if available in `extracted_details`.
         2.  Acknowledge their request for a central vacuum system and related items/services.
         3.  Present the "Estimated Quote" clearly, listing the `quote_items` and the `total_estimated_cost`.
         4.  Mention the `notes` from the quote if present.
         5.  If `availability_info` contains `available_slots`, suggest these as potential times for a consultation or installation. Emphasize that these are preliminary and require confirmation.
         6.  Invite them to reply or call to discuss the quote, confirm availability, or schedule a site visit.
         7.  Maintain a professional, helpful, and concise tone.
         8.  Conclude with a professional closing from "The CustomCraft Team".
         9.  Do NOT include any pricing data from the `pricing_context` directly in the email. Only use the `final_quote` JSON.
         10. Output only the email text.
         """),
        ("human", "Draft an email for the customer.")
    ]
)

communication_drafter_chain = (
    {
        "customer_request": RunnablePassthrough(),
        "extracted_details": RunnablePassthrough(),
        "final_quote": RunnablePassthrough(),
        "availability_info": RunnablePassthrough(),
    }
    | email_prompt_template
    | llm
    | StrOutputParser() # Expects and parses string output (the email text)
)

def draft_email_step(project_id, customer_request, extracted_details, final_quote, availability_info):
    """
    Executes the Communication Drafter Agent to draft an email and saves state.
    """
    print("\n[AI Agent] Drafting customer email...")
    try:
        # Pass all necessary context to the chain. Convert dicts to JSON strings for LLM processing.
        email_draft = communication_drafter_chain.invoke({
            "customer_request": customer_request,
            "extracted_details": json.dumps(extracted_details),
            "final_quote": json.dumps(final_quote),
            "availability_info": json.dumps(availability_info)
        })
        print("\n--- Drafted Email ---")
        print(email_draft)
        # Save email draft to the database
        save_project_state(project_id, email_draft=email_draft, status='pending_email_approval')
        return email_draft
    except Exception as e:
        print(f"Error drafting email: {e}")
        save_project_state(project_id, status='email_draft_failed')
        return None

# --- Main Orchestration Logic ---
def run_quotebot():
    """
    Orchestrates the entire workflow of the CustomCraft QuoteBot.
    """
    print("\nWelcome to CustomCraft QuoteBot!")
    customer_request = input("Enter customer request (e.g., 'I need a new PP650 vacuum unit with installation and a 50ft retractable hose. Also, when can you install it?'):\n")
    
    # Create a new project in the database
    project_id = create_new_project(customer_request)
    print(f"New project created with ID: {project_id}")

    # Step 1: Request Analysis
    extracted_details = analyze_request_step(project_id, customer_request)
    if extracted_details is None:
        print("Request analysis failed or aborted.")
        return

    # Human-in-the-Loop for Extracted Details
    approved_details = human_approval(extracted_details, "Extracted Details")
    if approved_details is None:
        print("Project aborted by human.")
        save_project_state(project_id, status='aborted_by_human')
        return
    # Save the human-approved details back to the database
    save_project_state(project_id, extracted_details=json.dumps(approved_details), status='extracted_details_approved')

    # Step 2: Initial Quoting
    quote_draft = generate_quote_step(project_id, approved_details)
    if quote_draft is None:
        print("Quote generation failed or aborted.")
        return

    # Human-in-the-Loop for Quote Draft
    final_quote = human_approval(quote_draft, "Quote Draft")
    if final_quote is None:
        print("Project aborted by human.")
        save_project_state(project_id, status='aborted_by_human')
        return
    # Save the human-approved final quote to the database
    save_project_state(project_id, final_quote=json.dumps(final_quote), status='quote_approved')

    # Step 3: Availability Checking (using the mock tool)
    # Extract service names from quote_items for availability check
    services_from_quote = final_quote.get("quote_items", [])
    service_types_requested = [item.get("item", "") for item in services_from_quote if "service" in item.get("item", "").lower() or "installation" in item.get("item", "").lower() or "tune-up" in item.get("item", "").lower() or "repair" in item.get("item", "").lower()]
    
    availability_info = check_availability_tool(", ".join(service_types_requested))
    print("\n[AI Agent] Checked Availability:")
    print(json.dumps(availability_info, indent=2))
    # Save availability info to project state for later use in email drafting
    save_project_state(project_id, availability_info=json.dumps(availability_info), status='availability_checked')

    # Step 4: Communication Drafter
    email_draft = draft_email_step(project_id, customer_request, approved_details, final_quote, availability_info)
    if email_draft is None:
        print("Email drafting failed or aborted.")
        return

    # Human-in-the-Loop for Email Draft
    final_email = human_approval(email_draft, "Final Email Draft")
    if final_email is None:
        print("Project aborted by human.")
        save_project_state(project_id, status='aborted_by_human')
        return
    # Save the human-approved final email to the database
    save_project_state(project_id, email_draft=final_email, status='email_approved')

    print(f"\n--- Project {project_id} Completed! ---")
    print("Final approved email is ready to be sent manually.")
    save_project_state(project_id, status='completed')


if __name__ == "__main__":
    run_quotebot()
