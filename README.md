# Operations Manager AI Agent
Agentic system that automates scheduling, quoting, invoicing, and communication, while a human stays in the loop for final oversight.
Use case:
A small-to-medium sized custom fabrication and installation company (e.g., custom cabinetry, metalwork, specialized signage). They handle unique projects, requiring detailed quotes and flexible scheduling.


# Operations Manager Agent: API Documentation

This document details the programmatic interface (API) of the Operations Manager Agent, an LLM agent system designed to automate and streamline the initial customer inquiry and quoting process for central vacuum systems. It outlines the core functions, their parameters, return values, and examples of their usage, providing a clear reference for developers interacting with the system's backend logic.

## 1. System Overview

The Operations Manager Agent is composed of several modular Python functions, each representing an "agent" or a utility, orchestrated to perform a multi-step workflow. For a high-level architectural overview and workflow design, please refer to the [Operations Manager Agent: LLM Agent System Design Document](DESIGN.md) 

## 2. Authentication

The system requires access to the Google Gemini API for its Large Language Model (LLM) functionalities.

* **API Key:** A `GOOGLE_API_KEY` is required.

* **Configuration:** This key must be set as an environment variable or stored in a `.env` file in the project's root directory (e.g., `GOOGLE_API_KEY="YOUR_API_KEY_HERE"`). The system automatically loads this key using `python-dotenv`.

* **Security:** The `.env` file is excluded from version control via `.gitignore` to prevent accidental exposure of sensitive credentials.

## 3. Core Modules

The Operations Manager Agent's backend logic is primarily encapsulated in two Python modules:

* `database.py`: Manages all interactions with the SQLite database, including schema initialization, data seeding, and CRUD operations for project states and pricing information.

* `main.py`: Contains the core LLM agent logic, including the LangChain chains for request analysis, quoting, and email drafting, as well as the mock availability checking tool.

---

## 4. `database.py` Module API

**Summary:** This module provides functions for initializing the SQLite database (`custom_craft.db`), managing pricing data, and persisting the state of customer projects throughout the quoting workflow.

### `init_db()`

* **Summary:** Initializes the SQLite database by creating the `pricing` and `projects` tables if they do not already exist. This function should be called once at the application's start.

* **Parameters:** None

* **Returns:** `None`

* **Example Call:**

    ```python
    from database import init_db
    init_db()
    print("Database initialized.")
    ```

### `insert_initial_pricing_data()`

* **Summary:** Populates the `pricing` table with initial mock data for HausVac products and services. It uses `INSERT OR IGNORE` to prevent duplicate entries on successive calls.

* **Parameters:** None

* **Returns:** `None`

* **Example Call:**

    ```python
    from database import insert_initial_pricing_data
    insert_initial_pricing_data()
    print("Initial pricing data inserted.")
    ```

### `get_pricing_data()`

* **Summary:** Retrieves all current pricing data from the `pricing` table. This data is used as context (RAG) for the LLM during the quoting process.

* **Parameters:** None

* **Returns:** `list` of `tuple`s. Each tuple represents a row from the `pricing` table: `(item_type, material, unit_cost, unit)`.

* **Example Call:**

    ```python
    from database import get_pricing_data
    pricing_data = get_pricing_data()
    for item in pricing_data:
        print(f"Type: {item[0]}, Material: {item[1]}, Cost: ${item[2]} {item[3]}")
    ```

### `create_new_project(customer_request)`

* **Summary:** Creates a new entry in the `projects` table for a new customer inquiry, assigning a unique `project_id` and an initial status.

* **Parameters:**

    * `customer_request` (`str`): The raw, unstructured text of the customer's initial request.

* **Returns:** `str`. The unique `project_id` generated for the new project.

* **Example Call:**

    ```python
    from database import create_new_project
    customer_req = "I need a new PP650 vacuum and installation."
    new_project_id = create_new_project(customer_req)
    print(f"New project created with ID: {new_project_id}")
    ```

### `save_project_state(project_id, **kwargs)`

* **Summary:** Updates the state of an existing project in the `projects` table. This is a versatile function that allows updating one or more columns of a project record.

* **Parameters:**

    * `project_id` (`str`): The unique identifier of the project to update.

    * `**kwargs`: Keyword arguments where the key is the column name (e.g., `extracted_details`, `status`, `quote_draft`, `email_draft`, `availability_info`) and the value is the data to save. JSON objects should be `json.dumps`-ed into strings before passing.

* **Returns:** `None`

* **Example Call:**

    ```python
    from database import save_project_state
    # Assuming 'my_project_id' exists and 'extracted_data_dict' is a dictionary
    extracted_data_dict = {"item_requested": "PP650", "services": ["Installation"]}
    save_project_state(
        my_project_id,
        extracted_details=json.dumps(extracted_data_dict),
        status='extracted_details_approved'
    )
    print(f"Project {my_project_id} state updated.")
    ```

### `get_project_details(project_id)`

* **Summary:** Retrieves all stored details for a specific project from the `projects` table.

* **Parameters:**

    * `project_id` (`str`): The unique identifier of the project to retrieve.

* **Returns:** `dict` or `None`. A dictionary containing all column names as keys and their corresponding values for the specified project, or `None` if the project is not found.

* **Example Call:**

    ```python
    from database import get_project_details
    # Assuming 'my_project_id' exists
    project_info = get_project_details(my_project_id)
    if project_info:
        print(f"Project Status: {project_info['status']}")
        print(f"Customer Request: {project_info['customer_request']}")
    else:
        print(f"Project {my_project_id} not found.")
    ```

## 5. `main.py` Module API

**Summary:** This module contains the core LLM-powered agents that perform the intelligent processing steps of the Operations Manager Agent workflow. These functions are designed to be called sequentially by an orchestrator (like `app.py`).

### `analyze_request(customer_request)`

* **Summary:** Uses the Request Analysis Agent (an LLM chain) to parse a free-form customer request and extract structured details.

* **Parameters:**

    * `customer_request` (`str`): The raw text of the customer's inquiry.

* **Returns:** `dict` or `None`. A dictionary containing extracted details (e.g., `item_requested`, `model`, `services`, `customer_name`), or `None` if the analysis fails.

* **Example Request Format:**

    ```
    "I need a new PP600 vacuum unit with installation and a 50ft retractable hose. My name is John Doe and my address is 123 Main St."
    ```

* **Example Response Format (on success):**

    ```json
    {
        "item_requested": "power_unit",
        "model": "PP600",
        "services": ["New_System_Installation"],
        "hose_length_ft": 50,
        "attachment_set": "N/A",
        "parts_needed": [],
        "customer_name": "John Doe",
        "customer_address": "123 Main St"
    }
    ```

* **Example Call:**

    ```python
    from main import analyze_request
    customer_req = "I need a PP500 unit and a HEPA filter."
    extracted_data = analyze_request(customer_req)
    if extracted_data:
        print("Extracted Data:", json.dumps(extracted_data, indent=2))
    ```

### `check_availability_tool(service_type)`

* **Summary:** Simulates an external tool call to check for available service/installation slots. This function provides mock availability data.

* **Parameters:**

    * `service_type` (`str`): A comma-separated string of service types requested (e.g., "Installation, System Tune-Up").

* **Returns:** `dict`. A dictionary containing a list of `available_slots` (each with `date` and `time`) and a `note`.

* **Example Request Format:**

    ```
    "Installation, Repair"
    ```

* **Example Response Format:**

    ```json
    {
        "available_slots": [
            {"date": "2025-07-28", "time": "9:00 AM - 12:00 PM"},
            {"date": "2025-07-30", "time": "1:00 PM - 4:00 PM"}
        ],
        "note": "These are preliminary availability slots. A representative will confirm exact timing."
    }
    ```

* **Example Call:**

    ```python
    from main import check_availability_tool
    availability = check_availability_tool("New System Installation")
    print("Availability:", json.dumps(availability, indent=2))
    ```

### `generate_quote(approved_details)`

* **Summary:** Uses the Initial Quoting Agent (an LLM chain) to generate an itemized quote based on the extracted customer details and the system's pricing data.

* **Parameters:**

    * `approved_details` (`dict`): The structured details of the customer's request, typically after human approval (matching the output format of `analyze_request`).

* **Returns:** `dict` or `None`. A dictionary containing the `quote_items`, `subtotal`, `shipping`, `total_estimated_cost`, and `notes`, or `None` if generation fails.

* **Example Request Format (input to this function):**

    ```json
    {
        "item_requested": "power_unit",
        "model": "PP600",
        "services": ["New_System_Installation"],
        "hose_length_ft": 50,
        "parts_needed": [{"part_name": "HEPA_Filter", "quantity": 2}],
        "customer_name": "Alice Smith"
    }
    ```

* **Example Response Format (on success):**

    ```json
    {
        "quote_items": [
            {"item": "PP600 Power Unit", "quantity": 1, "unit_price": 950.00, "line_total": 950.00, "cost_breakdown": "1 unit @ $950.00/unit"},
            {"item": "New System Installation", "quantity": 1, "unit_price": 750.00, "line_total": 750.00, "cost_breakdown": "Flat fee"},
            {"item": "50ft Retractable Hose", "quantity": 1, "unit_price": 350.00, "line_total": 350.00, "cost_breakdown": "1 unit @ $350.00/unit"},
            {"item": "HEPA Filter", "quantity": 2, "unit_price": 75.00, "line_total": 150.00, "cost_breakdown": "2 units @ $75.00/unit"}
        ],
        "subtotal": 2200.00,
        "shipping": 50.00,
        "total_estimated_cost": 2250.00,
        "notes": "This is an estimated quote based on provided details and current pricing. Final pricing may vary upon site visit and detailed requirements."
    }
    ```

* **Example Call:**

    ```python
    from main import generate_quote
    approved_details = {"item_requested": "power_unit", "model": "PP600", "services": ["New_System_Installation"]}
    quote = generate_quote(approved_details)
    if quote:
        print("Generated Quote:", json.dumps(quote, indent=2))
    ```

### `draft_email(customer_request, extracted_details, final_quote, availability_info)`

* **Summary:** Uses the Communication Drafter Agent (an LLM chain) to generate a professional email draft for the customer, incorporating the original request, extracted details, the final approved quote, and availability information.

* **Parameters:**

    * `customer_request` (`str`): The original raw customer inquiry.

    * `extracted_details` (`dict`): The structured details of the customer's request (after human approval).

    * `final_quote` (`dict`): The final, human-approved quote details.

    * `availability_info` (`dict`): The availability information obtained from `check_availability_tool`.

* **Returns:** `str` or `None`. The drafted email content as a plain string, or `None` if drafting fails.

* **Example Request Format (inputs to this function):**

    ```python
    # customer_request: "I need a PP600 with installation. When can you install?"
    # extracted_details: {"item_requested": "power_unit", "model": "PP600", "services": ["New_System_Installation"], "customer_name": "John Doe"}
    # final_quote: {"quote_items": [...], "total_estimated_cost": 1700.00, ...}
    # availability_info: {"available_slots": [{"date": "2025-07-28", "time": "9:00 AM - 12:00 PM"}], "note": "..."}
    ```

* **Example Response Format (on success):**

    ```
    Subject: Your Operations Manager Agent Central Vacuum System Quote & Availability - John Doe

    Dear John Doe,

    Thank you for your recent inquiry regarding a central vacuum system. We're pleased to provide you with an estimated quote based on your request.

    Estimated Quote Summary:
    - PP600 Power Unit: $950.00
    - New System Installation: $750.00
    Total Estimated Cost: $1700.00

    Notes: This is an estimated quote based on provided details and current pricing. Final pricing may vary upon site visit and detailed requirements.

    Regarding your installation inquiry, we have some preliminary availability slots:
    - Date: 2025-07-28, Time: 9:00 AM - 12:00 PM
    - Date: 2025-07-30, Time: 1:00 PM - 4:00 PM
    These are preliminary availability slots. A representative will confirm exact timing.

    Please reply to this email or call us at [Your Phone Number] to discuss this quote further, confirm your preferred installation time, or schedule a site visit.

    We look forward to helping you achieve a cleaner home!

    Best regards,

    The Operations Manager Agent Team
    ```

* **Example Call:**

    ```python
    from main import draft_email
    # Assuming valid customer_req, approved_details, final_quote, availability_info
    email = draft_email(customer_req, approved_details, final_quote, availability_info)
    if email:
        print("Drafted Email:\n", email)
    ```
