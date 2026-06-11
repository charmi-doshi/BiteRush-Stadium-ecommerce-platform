# import re
# import json
# from datetime import datetime

# def parse_agent_batches_to_es(agent_output: str, vendor_id: str = "V010") -> dict:
#     """
#     Parses strict-formatted text from BiteRush Copilot into an Elasticsearch 'hits' JSON array.
#     """
#     # Isolate individual batch blocks between the START and END delimiters
#     batch_pattern = re.compile(r'---BATCH_START---\n(.*?)\n---BATCH_END---', re.DOTALL)
#     raw_batches = batch_pattern.findall(agent_output)
    
#     hits = []
    
#     for i, batch_text in enumerate(raw_batches, start=1):
#         # Helper function to extract array elements formatted like: Field: [A, B]
#         def extract_list(field_name):
#             match = re.search(fr"{field_name}:\s*\[(.*?)\]", batch_text)
#             if match and match.group(1).strip():
#                 return [item.strip() for item in match.group(1).split(',')]
#             return []
            
#         # Helper function to extract single string values formatted like: Field: [Value]
#         def extract_string(field_name):
#             match = re.search(fr"{field_name}:\s*\[(.*?)\]", batch_text)
#             return match.group(1).strip() if match else ""
            
#         # 1. Generate sequential Cluster ID
#         cluster_id = f"CLU-{str(i).zfill(3)}"
        
#         # 2. Extract specific fields
#         order_ids = extract_list("Orders")
#         items = extract_list("Food")
#         route_steps = extract_string("Route")
        
#         # 3. Safely parse the integer out of the Max_Wait string (e.g., "10 mins" -> 10)
#         max_wait_str = extract_string("Max_Wait")
#         eta_match = re.search(r'\d+', max_wait_str)
#         total_eta_min = int(eta_match.group()) if eta_match else 0
        
#         # 4. Construct the Elasticsearch Hit document
#         hit_doc = {
#             "_index": "logistics-clusters",
#             "_id": cluster_id,
#             "_score": 1,
#             "_source": {
#                 "cluster_id": cluster_id,
#                 "order_ids": order_ids,
#                 "items": items,
#                 "vendor_id": vendor_id,
#                 "route_steps": route_steps,
#                 "total_eta_min": total_eta_min,
#                 "status": "PENDING",
#                 "created_at": datetime.utcnow().isoformat()
#             }
#         }
        
#         hits.append(hit_doc)
        
#     return {"hits": hits}

# # ==========================================
# # EXAMPLE USAGE
# # ==========================================

# mock_agent_output = """
# ---BATCH_START---
# Group: Ground Floor Express
# Orders: [ORD001, ORD003]
# Seats: [A-12, A-13]
# Food: [vadapav, vadapav]
# Max_Wait: [8 mins]
# Route: [Ground floor -> Left -> Row A/C]
# ---BATCH_END---

# ---BATCH_START---
# Group: Ground Floor Hot Item
# Orders: [ORD002]
# Seats: [G-5]
# Food: [indian samosa]
# Max_Wait: [5 mins]
# Route: [Ground floor -> Right -> Row G]
# ---BATCH_END---
# """

# # Run the parser and print as formatted JSON
# es_payload = parse_agent_batches_to_es(mock_agent_output)
# print(json.dumps(es_payload, indent=2))

import re
import json
from datetime import datetime

def parse_agent_batches_to_es(agent_output: str, vendor_id: str = "V010") -> dict:
    """Parses agent-formatted text into an Elasticsearch 'hits' JSON array."""
    batch_pattern = re.compile(r'---BATCH_START---\n(.*?)\n---BATCH_END---', re.DOTALL)
    raw_batches = batch_pattern.findall(agent_output)
    
    hits = []
    for i, batch_text in enumerate(raw_batches, start=1):
        def get_field(field_name):
            pattern = fr"{field_name}:\s*\[?(.*?)\]?$"
            match = re.search(pattern, batch_text, re.MULTILINE)
            return match.group(1).strip() if match else ""
        
        order_raw = get_field("Orders")
        food_raw = get_field("Food")
        route_steps = get_field("Route")
        max_wait_str = get_field("Max_Wait")
        
        eta_match = re.search(r'\d+', max_wait_str)
        total_eta_min = int(eta_match.group()) // 60 if eta_match else 0
        
        cluster_id = f"CLU-{str(i).zfill(3)}"
        
        hit_doc = {
            "_index": "logistics-clusters",
            "_id": cluster_id,
            "_score": 1,
            "_source": {
                "cluster_id": cluster_id,
                "order_ids": [o.strip() for o in order_raw.split(",")] if order_raw else [],
                "items": [f.strip() for f in food_raw.split(",")] if food_raw else [],
                "vendor_id": vendor_id,
                "route_steps": route_steps,
                "total_eta_min": total_eta_min,
                "status": "PENDING",
                "created_at": datetime.utcnow().isoformat()
            }
        }
        hits.append(hit_doc)
    return {"hits": hits}

# --- TEST DATA ---
mock_agent_response = """
---BATCH_START---
Group: Ground Floor Row G Single
Orders: ORD002
Seats: G-12
Food: indian samosa
Max_Wait: 120 seconds
Route: KITCHEN, Ground floor, Row G, Groundfloor-G-12
---BATCH_END---
"""

# --- EXECUTION ---
if __name__ == "__main__":
    result = parse_agent_batches_to_es(mock_agent_response)
    print("--- PARSED JSON OUTPUT ---")
    print(json.dumps(result, indent=2))