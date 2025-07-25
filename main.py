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
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.0)

# Load pricing data from our SQLite database for the agents to use
PRICING_DATA = get_pricing_data()
# Format pricing data into a readable string to inject into LLM prompts (RAG principle)
pricing_context = "\n".join([
    f"- Item Type: {row[0]}, Material: {row[1]}, Unit Cost: ${row[2]} {row[3]}"
    for row in PRICING_DATA
])

print("CustomCraft QuoteBot backend initialized.") # Changed print for UI context

# --- Agent Chains ---

# --- Request Analyzer Agent ---
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

request_analyzer_chain = (
    {"customer_request": RunnablePassthrough()}
    | extraction_prompt_template
    | llm
    | JsonOutputParser()
)

def analyze_request(customer_request):
    """
    Executes the Request Analyzer Agent to extract details.
    Returns the extracted details (dict) or None on failure.
    """
    try:
        extracted_details = request_analyzer_chain.invoke(customer_request)
        return extracted_details
    except Exception as e:
        print(f"Error analyzing request: {e}") # Keep print for debug logs
        return None

# --- Availability Checking Agent ---
def check_availability_tool(service_type):
    """
    Simulates checking a calendar for available slots based on service type.
    This acts as our 'tool' for the LLM.
    """
    today = datetime.date.today()
    if "installation" in service_type.lower() or "service" in service_type.lower() or "tune-up" in service_type.lower() or "repair" in service_type.lower():
        return {
            "available_slots": [
                {"date": str(today + datetime.timedelta(days=3)), "time": "9:00 AM - 12:00 PM"},
                {"date": str(today + datetime.timedelta(days=5)), "time": "1:00 PM - 4:00 PM"},
                {"date": str(today + datetime.timedelta(days=7)), "time": "10:00 AM - 1:00 PM"}
            ],
            "note": "These are preliminary availability slots. A representative will confirm exact timing."
        }
    else:
        return {
            "available_slots": [],
            "note": "No specific service installation/consultation requested, so no availability slots needed."
        }

# --- Initial Quoting Agent ---
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

initial_quoting_chain = (
    {
        "extracted_details": RunnablePassthrough(),
        "pricing_context": lambda x: pricing_context
    }
    | quoting_prompt_template
    | llm
    | JsonOutputParser()
)

def generate_quote(approved_details):
    """
    Executes the Initial Quoting Agent to generate a quote draft.
    Returns the quote draft (dict) or None on failure.
    """
    try:
        quote_draft = initial_quoting_chain.invoke({"extracted_details": json.dumps(approved_details)})
        return quote_draft
    except Exception as e:
        print(f"Error generating quote: {e}") # Keep print for debug logs
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
    | StrOutputParser()
)

def draft_email(customer_request, extracted_details, final_quote, availability_info):
    """
    Executes the Communication Drafter Agent to draft an email.
    Returns the email draft (str) or None on failure.
    """
    try:
        email_draft = communication_drafter_chain.invoke({
            "customer_request": customer_request,
            "extracted_details": json.dumps(extracted_details),
            "final_quote": json.dumps(final_quote),
            "availability_info": json.dumps(availability_info)
        })
        return email_draft
    except Exception as e:
        print(f"Error drafting email: {e}") # Keep print for debug logs
        return None

# --- Main Orchestration Logic (Removed CLI-specific logic) ---
# The run_quotebot function and direct execution (__name__ == "__main__")
# will be moved to app.py to be driven by the Streamlit UI.
# The init_db() and insert_initial_pricing_data() calls remain at the top
# to ensure the database is always ready when main.py is imported.
