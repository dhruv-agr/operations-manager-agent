import sqlite3
import uuid # To generate unique project IDs
import json # To store JSON data as strings in SQLite
import datetime # To record timestamps

DATABASE_NAME = "custom_craft.db"

def init_db():
    """
    Initializes the SQLite database by creating the 'pricing' and 'projects' tables
    if they do not already exist.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Create the 'pricing' table to store our mock HausVac product/service data
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pricing (
            item_type TEXT NOT NULL,  -- e.g., 'power_unit', 'hose', 'attachment_set', 'service', 'part'
            material TEXT NOT NULL,   -- Specific model, length, type, or service name
            unit_cost REAL NOT NULL,  -- The price per unit
            unit TEXT,                -- e.g., 'unit', 'linear_ft', 'flat_fee', 'per_hour'
            PRIMARY KEY (item_type, material) -- Ensures unique items/materials
        )
    ''')

    # Create the 'projects' table to store the state and history of each customer request
    # ADDED 'availability_info' column here
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            customer_request TEXT,
            extracted_details TEXT, -- Stores JSON string of extracted details from LLM
            quote_draft TEXT,      -- Stores JSON string of initial quote draft from LLM
            final_quote TEXT,      -- Stores JSON string of quote after human approval
            email_draft TEXT,      -- Stores the drafted email text
            availability_info TEXT, -- Stores JSON string of availability information
            status TEXT,           -- Current status: e.g., 'pending_extraction', 'pending_quote_approval', 'pending_email_approval', 'completed', 'aborted_by_human', 'extraction_failed', 'quote_failed', 'email_draft_failed'
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP -- When the project was created/last updated
        )
    ''')
    conn.commit()
    conn.close()

def insert_initial_pricing_data():
    """
    Inserts sample pricing data for HausVac products and services into the 'pricing' table.
    Uses INSERT OR IGNORE to prevent duplicates if run multiple times.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        # HausVac-specific mock pricing data: (item_type, material, unit_cost, unit)
        pricing_data = [
            # --- Power Units ---
            ('power_unit', 'PP650', 1200.00, 'unit'),
            ('power_unit', 'PP600', 950.00, 'unit'),
            ('power_unit', 'PP500', 700.00, 'unit'),

            # --- Hoses ---
            ('hose', '30ft_Crushproof', 150.00, 'unit'),
            ('hose', '50ft_Retractable', 350.00, 'unit'),
            ('hose', '60ft_Retractable', 400.00, 'unit'),

            # --- Attachment Sets ---
            ('attachment_set', 'Bare_Floor_Set', 120.00, 'unit'),
            ('attachment_set', 'Carpet_Comb_Electric_Pigtail_Set', 250.00, 'unit'),
            ('attachment_set', 'Premium_Tool_Kit', 180.00, 'unit'),

            # --- Parts ---
            ('part', 'HEPA_Filter', 75.00, 'unit'),
            ('part', 'Disposable_Bag_Pack', 40.00, 'unit'), # Assumed 6 bags
            ('part', 'Brush_Roll_Replacement', 60.00, 'unit'),
            ('part', 'Motor_Assembly', 450.00, 'unit'),
            ('part', 'Low_Voltage_Wiring', 3.50, 'linear_ft'), # For new inlets

            # --- Services ---
            ('service', 'New_System_Installation', 750.00, 'flat_fee'),
            ('service', 'Additional_Inlet_Installation', 250.00, 'unit'), # Per additional inlet
            ('service', 'Service_Call_Diagnostic', 120.00, 'flat_fee'),
            ('service', 'Labor_Rate', 85.00, 'per_hour'), # For general repair labor
            ('service', 'System_Tune_Up', 180.00, 'flat_fee'),
            ('service', 'Clog_Removal', 150.00, 'flat_fee'),
            ('service', 'Motor_Replacement_Labor', 170.00, 'flat_fee'), # Specific labor for motor replacement
            ('service', 'Shipping_Standard', 50.00, 'flat_fee')
        ]
        cursor.executemany("INSERT OR IGNORE INTO pricing VALUES (?, ?, ?, ?)", pricing_data)
        conn.commit()
        print("Initial HausVac pricing data inserted/checked.")
    except sqlite3.IntegrityError as e:
        print(f"Error inserting pricing data: {e}. Data might already exist.")
    finally:
        conn.close()

def get_pricing_data():
    """
    Retrieves all pricing data from the 'pricing' table.
    This data will be provided to the LLM as context for quoting.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT item_type, material, unit_cost, unit FROM pricing")
    data = cursor.fetchall()
    conn.close()
    return data

def create_new_project(customer_request):
    """
    Creates a new project entry in the 'projects' table with an initial status.
    Returns the newly generated project_id.
    """
    project_id = str(uuid.uuid4()) # Generate a unique ID for the project
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO projects (project_id, customer_request, status) VALUES (?, ?, ?)",
                   (project_id, customer_request, 'pending_extraction'))
    conn.commit()
    conn.close()
    return project_id

def save_project_state(project_id, **kwargs):
    """
    Updates the state of an existing project in the 'projects' table.
    Keyword arguments correspond to column names (e.g., extracted_details='{}', status='approved').
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # Build the SET part of the the SQL UPDATE query dynamically
    set_clauses = []
    values = []
    for key, value in kwargs.items():
        set_clauses.append(f"{key} = ?")
        values.append(value)

    query = f"UPDATE projects SET {', '.join(set_clauses)} WHERE project_id = ?"
    values.append(project_id) # Add project_id to the end of values for the WHERE clause

    cursor.execute(query, values)
    conn.commit()
    conn.close()

def get_project_details(project_id):
    """
    Retrieves all details for a specific project from the 'projects' table.
    Returns a dictionary of project details.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
    columns = [description[0] for description in cursor.description] # Get column names
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(zip(columns, row)) # Map column names to values
    return None

# This block runs only when database.py is executed directly (e.g., `python database.py`)
# It's useful for initial setup and testing the database functions.
if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Inserting initial pricing data...")
    insert_initial_pricing_data()
    print("Database setup complete. You can now run main.py.")

    # Optional: Test data retrieval
    # print("\nVerifying pricing data:")
    # pricing = get_pricing_data()
    # for item in pricing:
    #     print(item)

    # Optional: Test project creation and state saving
    # print("\nTesting project creation and state saving:")
    # test_request = "I need a new PP650 vacuum unit with installation."
    # new_proj_id = create_new_project(test_request)
    # print(f"Created project with ID: {new_proj_id}")
    # save_project_state(new_proj_id, status='extracted', extracted_details=json.dumps({"item": "PP650", "service": "installation"}))
    # updated_proj = get_project_details(new_proj_id)
    # print(f"Updated project status: {updated_proj['status']}")
    # print(f"Extracted details: {updated_proj['extracted_details']}")
