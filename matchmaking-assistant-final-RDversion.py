"""
ACCURATE Matchmaking Assistant
=============================================
v32 New (based on the user-centric 4-layer protection design)：
  [Fix 1] Enhanced prompt extraction: Prevents compound sentences (e.g., “under X and higher Y”) from missing half of the conditions.
  [Fix 2] EEnhanced error messages: Provides extremely detailed and informative error prompts for Precision.
  [Fix 3] Debug Panel: Visualizes the inverse logic of IT numbers in “Detected Filter Conditions.”
  [Fix 4] Smart Correction Prompt (Info): When encountering valid ranges, proactively informs users of the system’s interpretation.

v31 Base Features：
  - Completely isolate the Precision logic to prevent semantic contamination of higher/lower
  - Unified conflict detector (Delivery, GHG, Yield, Precision)
  - Support for Delivery OR conditions
"""

import re
import ast
import json
import time
import streamlit as st
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from SPARQLWrapper import SPARQLWrapper, JSON as SPARQL_JSON
import os

# ──────────────────────────────────────────────
# Basic Settings
# ──────────────────────────────────────────────
st.set_page_config(page_title="ACCURATE Matchmaking Assistant", layout="wide")

FUSEKI_URL = os.environ.get(
    "FUSEKI_URL",
    "http://localhost:3030/accurateDB/sparql"
)
ACC = "http://accurate.de.iao.fraunhofer.de/ontologies/ACCURATE#"

# Session State Initialization
for key, default in [
    ("last_analysis_context", None),
    ("saved_flat_context", None),
    ("messages", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

CUSTOM_SCHEMA = """
acc:ManufacturingService a owl:Class .
acc:GHGEmission          a owl:Class .
acc:OnTimeDelivery       a owl:Class .
acc:hasCharacteristic    a owl:ObjectProperty .
acc:hasCharacteristicValue a owl:ObjectProperty .
acc:hasQuantity          a owl:ObjectProperty .
qudt:numericValue        a owl:DatatypeProperty .
qudt:unit                a owl:ObjectProperty .
"""

# ──────────────────────────────────────────────
# LLM Initialization
# ──────────────────────────────────────────────
try:
    OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_HOST",
    "http://host.docker.internal:11434"
    )
    llm = OllamaLLM(model="llama3.1", base_url=OLLAMA_BASE_URL, temperature=0)
except Exception as e:
    st.error(f"❌ Failed to initialize Ollama: {e}")
    st.stop()

# ──────────────────────────────────────────────
# [Fix 2] Combined Prompt: Router + Filter Extraction
# (V48: Adding the "Exact Match" dual-setting logic)
# ──────────────────────────────────────────────
combined_intent_filter_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are an intent classifier and constraint extractor for a manufacturing service chatbot.\n"
     "Analyze the user message and return ONE raw JSON object.\n\n"

     "=== ACTION RULES ===\n"
     "Set 'action' to 'NEW_SEARCH' when user wants to search, filter, find, list, or change criteria.\n"
     "Set 'action' to 'FOLLOW_UP' when user asks about the ALREADY-SHOWN results "
     "(e.g., 'in this table', 'which service in this list', 'why is MS02 ranked first').\n"
     "If 'has_prior_context' is false, ALWAYS set action to 'NEW_SEARCH'.\n"
     "For FOLLOW_UP, set ALL filter fields to null.\n\n"

     "=== KEYWORD MAPPING DICTIONARY ===\n"
     "Process each metric independently. Map words strictly to these JSON keys:\n\n"

     "[1. Delivery Time & GHG] (Smaller is better)\n"
     "- 'within X', 'under X', 'lower than X' => SET max_[field]: X (🚨 ALWAYS max! NEVER min!)\n"
     "- 'over X', 'higher than X', 'more than X' => SET min_[field]: X\n"
     "- 'between X and Y' => SET min_[field]: X AND max_[field]: Y\n"
     "- 'exactly X', 'equal to X', or standalone 'X' (e.g. 'of 15 days') => SET min_[field]: X AND max_[field]: X\n"
     "🚨 ANTI-SORTING RULE: If user asks a contradiction like 'GHG under 30 and over 45', you MUST strictly output max_ghg: 30, min_ghg: 45. DO NOT swap numbers to fix the math!\n\n"

     "[2. Yield Rate] (Larger is better)\n"
     "- 'over X', 'higher than X', 'greater than X' => SET min_yield: X\n"
     "- 'under X', 'lower than X', 'less than X' => SET max_yield: X\n"
     "- 'between X and Y' => SET min_yield: X AND max_yield: Y\n"
     "- 'exactly X', 'equal to X', or standalone 'X' => SET min_yield: X AND max_yield: X\n"
     "🚨 ANTI-SORTING RULE: If user asks 'lower than 84 and higher than 88', you MUST strictly output max_yield: 84, min_yield: 88. DO NOT swap numbers!\n\n"

     "[3. Precision / IT Grade] (INVERSE LOGIC: Smaller number = Better)\n"
     "- 'higher precision', 'better precision' => SET max_precision (e.g. 'higher IT6' -> max_precision: 6)\n"
     "- 'lower precision', 'worse precision', 'under ITX' => SET min_precision (e.g. 'under IT9' -> min_precision: 9)\n"
     "- 'between IT[X] and IT[Y]' => SET min_precision: X AND max_precision: Y "
     "(🚨 ALWAYS smaller number -> min_precision, larger number -> max_precision. Never swap!)\n"
     "- 'exactly IT[X]', 'equal to IT[X]', or standalone 'IT[X]' => SET min_precision: X AND max_precision: X\n\n"

     "[4. Material & Certifications]\n"
     "- 'I need AL6061' => target_material: 'AL6061'\n"
     "- 'don\\'t process AL6061' => excluded_material: 'AL6061'\n"
     "- 'must have ISO9001' => target_cert: 'ISO9001'\n"
     "- 'without TUV' => excluded_cert: 'TUV'\n"
     "- 'no ISO9001 and no TUV' => excluded_cert: 'ISO9001,TUV'\n\n"

     "=== BEHAVIORAL RULES ===\n"
     "1. NEVER auto-correct math contradictions. Output exactly what the dictionary maps.\n"
     "2. Do not mix up fields. Certs go to cert fields, materials to material fields.\n\n"

     "=== FEW-SHOT EXAMPLES ===\n"
     "User: 'delivery within 18 days'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"max_delivery_days\":18}}\n\n"

     "User: 'yield rate of over 81% and with a delivery time between 12 and 16 days'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"min_yield\":81,\"min_delivery_days\":12,\"max_delivery_days\":16}}\n\n"

     "User: 'under 11 days OR over 19 days'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"max_delivery_days\":11,\"min_delivery_days\":19,\"delivery_connector_word\":\"or\"}}\n\n"

     "User: 'precision between IT4 and IT8'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"min_precision\":4,\"max_precision\":8}}\n\n"

     "User: 'precision exactly IT8'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"min_precision\":8,\"max_precision\":8}}\n\n"

     "User: 'delivery time of 15 days'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"min_delivery_days\":15,\"max_delivery_days\":15}}\n\n"

     "User: 'no ISO9001 and no TUVH2.21'\n"
     "Output: {{\"action\":\"NEW_SEARCH\",\"excluded_cert\":\"ISO9001,TUVH2.21\"}}\n\n"

     "=== OUTPUT FORMAT ===\n"
     "Return ONLY this JSON structure (null for missing):\n"
     '{{"action":"NEW_SEARCH","target_material":null,"excluded_material":null,'
     '"target_cert":null,"excluded_cert":null,'
     '"min_delivery_days":null,"max_delivery_days":null,"delivery_connector_word":"and",'
     '"min_ghg":null,"max_ghg":null,'
     '"max_precision":null,"min_precision":null,"min_yield":null,"max_yield":null}}'
    ),
    ("human", "has_prior_context: {has_context}\nUser message: {question}")
])

combined_chain = combined_intent_filter_prompt | llm

# ──────────────────────────────────────────────
# [Fix 3] Response Prompt 
# (Restore the missing output format example to ensure the LLM remembers to use the <answer> tag)
# ──────────────────────────────────────────────
response_generation_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a helpful Supply Chain Consultant. Provide clear answers with brief context.\n\n"

     "*** CRITICAL WARNING - READ THIS FIRST ***\n"
     "1. IF Action = NEW_SEARCH:\n"
     "   - Read the STATUS in the SYSTEM DIRECTIVE provided in the context.\n"
     "   - IF STATUS is 'SUCCESS_MATCH': You MUST blindly recommend the EXACT service inside 'Recommended Service'. Do NOT pick randomly! The table is 100% correct.\n"
     "   - IF STATUS is 'EMPTY_RESULT': Tell the user no services matched. Suggest relaxing the requirement.\n"
     "2. IF Action = FOLLOW_UP: ANSWER THE SPECIFIC QUESTION ASKED. DO NOT recommend any service unless asked.\n"
     "******************************************\n\n"

     "=== STEP 1: PRECISION (IT) KNOWLEDGE ===\n"
     "Lower IT number = HIGHER precision quality (IT6 > IT7 > IT8 > IT9).\n"
     "  'between IT7 and IT9' = IT7 ≤ IT ≤ IT9.\n\n"

     "=== STEP 2: ANSWER CONTENT BY ACTION ===\n\n"

     "👉 IF ACTION IS 'NEW_SEARCH':\n"
     "  - For SUCCESS_MATCH: State the recommended service and score. Mention 1-2 features. List ALL OTHER services shown in the table.\n"
     "  🚨 FATAL ERROR TO AVOID: NEVER output placeholders like [Recommended Service] or invent XML tags. Write naturally!\n\n"

     "👉 IF ACTION IS 'FOLLOW_UP':\n"
     "  - COMPARATIVE ('which has higher/better...'): You MUST mathematically compare the values. Name ONLY the winner(s).\n"
     "    * Rule: Lower IT number = HIGHER/BETTER precision.\n"
     "    * Rule: Lower Delivery/GHG = Better. Higher Yield = Better.\n"
     "  - Positive Lookup: Scan every row. List ALL matching services.\n"
     "  - NEGATIVE Lookup: Look for 'None' or non-matching attributes.\n\n"

     "=== STEP 3: STRICT OUTPUT FORMAT ===\n"
     "You MUST ALWAYS start with a <thinking> block, followed by an <answer> block.\n\n"

     "Example for NEW_SEARCH (SUCCESS_MATCH):\n"
     "<thinking>\n"
     "Action is NEW_SEARCH and STATUS is SUCCESS_MATCH.\n"
     "Recommended service is MS02.\n"
     "</thinking>\n"
     "<answer>\n"
     "Based on your criteria, I recommend MS02 which achieved the highest score (69.2). It offers fast delivery and high yield.\n\n"
     "The table also shows MS05 and MS07 meet your current criteria. Since there are multiple options, you can refer to the highest-scoring service MS02, or please provide more specific requirements so I can filter them further for you!\n"
     "</answer>\n\n"

     "Example for FOLLOW_UP:\n"
     "<thinking>\n"
     "Action is FOLLOW_UP. Question asks 'which service has a higher precision level'.\n"
     "MS06 is IT6, MS05 is IT7. IT6 is smaller, so it's higher precision.\n"
     "</thinking>\n"
     "<answer>\n"
     "Based on the table, MS06 has a higher precision level (IT6) compared to MS05 (IT7).\n"
     "</answer>"
    ),
    ("human",
     "User Question: {question}\n\n"
     "Action: {action}\n\n"
     "Context:\n{context}\n\n"
     "Output:"
    )
])

response_chain = response_generation_prompt | llm

# ──────────────────────────────────────────────
# SPARQL Queries and Utility Functions (Remains Unchanged)
# ──────────────────────────────────────────────
PREFIXES = """
PREFIX acc:  <http://accurate.de.iao.fraunhofer.de/ontologies/ACCURATE#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX qudt: <http://qudt.org/schema/qudt/>
"""

SERVICE_QUERY = PREFIXES + """
SELECT DISTINCT
  ?service ?ghgValue ?deliveryTime
  ?materialName ?precisionVal ?yieldVal
  ?qualityCert ?energyCert
WHERE {
    ?service a acc:ManufacturingService .

    OPTIONAL {
        ?service acc:hasCharacteristic ?ghgChar .
        ?ghgChar acc:hasQuantity ?ghgQty .
        ?ghgQty  a acc:GHGEmission .
        ?ghgQty  qudt:numericValue ?ghgValue .
    }
    OPTIONAL {
        ?service acc:hasCharacteristic ?timeChar .
        ?timeChar acc:hasQuantity ?timeQty .
        ?timeQty  a acc:OnTimeDelivery .
        ?timeQty  qudt:numericValue ?deliveryTime .
    }
    OPTIONAL {
        ?service acc:hasCharacteristic ?matChar .
        ?matChar  a acc:UnquantifiedCharacteristic .
        FILTER (CONTAINS(STR(?matChar), "Material"))
        ?matChar acc:hasCharacteristicValue ?materialName .
    }
    OPTIONAL {
        ?service acc:hasCharacteristic ?precChar .
        FILTER (CONTAINS(STR(?precChar), "Precision"))
        OPTIONAL { ?precChar qudt:numericValue ?precisionVal . }
        OPTIONAL {
            ?precChar acc:hasQuantity ?pq .
            ?pq qudt:numericValue ?precisionVal .
        }
    }
    OPTIONAL {
        ?service acc:hasCharacteristic ?yieldChar .
        FILTER (CONTAINS(STR(?yieldChar), "Yield"))
        OPTIONAL { ?yieldChar qudt:numericValue ?yieldVal . }
        OPTIONAL {
            ?yieldChar acc:hasQuantity ?yq .
            ?yq qudt:numericValue ?yieldVal .
        }
    }
    OPTIONAL {
        ?service acc:hasCharacteristic ?qualCertChar .
        ?qualCertChar a acc:UnquantifiedCharacteristic .
        FILTER (CONTAINS(STR(?qualCertChar), "QualityCertificate")
             || CONTAINS(STR(?qualCertChar), "ISO9001"))
        ?qualCertChar acc:hasCharacteristicValue ?qualityCert .
    }
    OPTIONAL {
        ?service acc:hasCharacteristic ?energyCertChar .
        ?energyCertChar a acc:UnquantifiedCharacteristic .
        FILTER (CONTAINS(STR(?energyCertChar), "Energy")
             || CONTAINS(STR(?energyCertChar), "TUV"))
        ?energyCertChar acc:hasCharacteristicValue ?energyCert .
    }
}
ORDER BY ?service
"""

REQUIREMENT_QUERY = PREFIXES + """
SELECT ?ruleType ?thresholdValue ?valueType
WHERE {
    ?req  a ?ruleType .
    FILTER (CONTAINS(STR(?ruleType), "Requirement"))
    ?req  acc:hasReferenceValue ?refValObj .
    ?refValObj qudt:numericValue ?thresholdValue .
    ?refValObj a ?valueType .
}
"""

@st.cache_data(ttl=300)
def fetch_all_sparql_data():
    try:
        sparql = SPARQLWrapper(FUSEKI_URL)
        sparql.setMethod("POST")
        sparql.setReturnFormat(SPARQL_JSON)

        sparql.setQuery(SERVICE_QUERY)
        service_results = sparql.query().convert()

        sparql.setQuery(REQUIREMENT_QUERY)
        requirement_results = sparql.query().convert()

        return service_results, requirement_results, None
    except Exception as e:
        return None, None, str(e)

def sanitize_filter_val(val):
    if val is None:
        return None
    if isinstance(val, dict):
        for key in ["value", "amount", "limit", "min", "max"]:
            if key in val:
                return val[key]
        for v in val.values():
            if isinstance(v, (int, float)):
                return v
        return None
    if isinstance(val, list):
        return val[0] if val else None
    return val

def clean_val(val):
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if not s or s.lower() in ("n/a", "none"):
            return None
        m = re.search(r"[-+]?\d*\.?\d+", s)
        return float(m.group()) if m else None
    except Exception:
        return None

# ──────────────────────────────────────────────
# [Fix 4] LLM Query Preprocessing (Query Normalization)
# Purpose: Before feeding the query into the LLM, replace semantically ambiguous terms with standard vocabulary that the LLM recognizes most reliably.
# ──────────────────────────────────────────────
def normalize_query(text: str) -> str:
    """In the process of feeding the query into the LLM, replace semantically ambiguous terms with standard vocabulary that the LLM recognizes most reliably."""

    # 1. Maximum delivery time: within / at most / maximum X days → under X days
    text = re.sub(
        r'\b(?:within|at most|maximum|no more than)\s+(\d+)\s+days?\b',
        r'under \1 days',
        text,
        flags=re.IGNORECASE
    )
    
    # 2. Lower limit of yield rate: yield rate of over X% → yield over X% (simplified sentence structure to reduce confusion)
    text = re.sub(
        r'\byield\s+(?:rate\s+)?(?:of\s+)?(?:over|above)\s+(\d+)\s*%?\b',
        r'yield over \1',
        text,
        flags=re.IGNORECASE
    )
    
    return text

# ──────────────────────────────────────────────
# [Fix 5] New: LLM Output Post-processing Guardrails
# Purpose: Force correct LLM's semantic biases and mathematical ordering biases, and intelligently fill in "Exact Match"
# ──────────────────────────────────────────────
def fix_llm_field_swaps(parsed: dict, normalized_prompt: str) -> dict:
    if not parsed:
        return parsed

    prompt_lower = normalized_prompt.lower()

    # --- Phase A: Fixing the issue where a single boundary is placed in the wrong field ---
    upper_bound_keywords = ["under", "lower than", "less than", "within", "at most", "maximum", "no more than"]
    if any(kw in prompt_lower for kw in upper_bound_keywords):
        if parsed.get("min_delivery_days") is not None and parsed.get("max_delivery_days") is None:
            parsed["max_delivery_days"] = parsed.pop("min_delivery_days")
        if parsed.get("min_ghg") is not None and parsed.get("max_ghg") is None:
            parsed["max_ghg"] = parsed.pop("min_ghg")

    lower_bound_keywords = ["over", "higher than", "greater than", "above", "minimum", "more than"]
    if any(kw in prompt_lower for kw in lower_bound_keywords):
        if parsed.get("max_yield") is not None and parsed.get("min_yield") is None:
            parsed["min_yield"] = parsed.pop("max_yield")

    # --- Phase B: Fixing the issue where contradictory constraints are improperly ordered by the LLM ---
    if "between" not in prompt_lower:
        has_under = any(kw in prompt_lower for kw in upper_bound_keywords)
        has_over = any(kw in prompt_lower for kw in lower_bound_keywords)
        
        if has_under and has_over:
            min_g, max_g = parsed.get("min_ghg"), parsed.get("max_ghg")
            if min_g is not None and max_g is not None and min_g < max_g:
                parsed["min_ghg"], parsed["max_ghg"] = max_g, min_g

            min_y, max_y = parsed.get("min_yield"), parsed.get("max_yield")
            if min_y is not None and max_y is not None and min_y < max_y:
                parsed["min_yield"], parsed["max_yield"] = max_y, min_y

    # --- Phase C: Intelligent filling of exact matches (Exact Match) ---
    def check_and_fill_exact_match(min_key, max_key):
        val_min = parsed.get(min_key)
        val_max = parsed.get(max_key)
        
        # The check is performed only when “one side has a value and the other is None”
        if val_min is not None and val_max is None:
            target_val = val_min
            missing_key = max_key
        elif val_max is not None and val_min is None:
            target_val = val_max
            missing_key = min_key
        else:
            return 
            
        # Prevent decimal points like “85.0” from interfering with string comparisons
        if isinstance(target_val, float) and target_val.is_integer():
            val_str = str(int(target_val))
        else:
            val_str = str(target_val)

        # Find the position of the number in the sentence (supports IT8, a format where numbers are placed immediately after letters)
        matches = list(re.finditer(rf'(?:it)?\s*{val_str}(?!\d)', prompt_lower))
        
        if matches:
            for match in matches:
                # Take the first 35 characters of the number as the “semantic analysis zone”
                start_idx = max(0, match.start() - 35)
                context_before = prompt_lower[start_idx:match.start()]
                
                # Separate with punctuation or “and,” and select only the clause “closest to that number” (to prevent contamination from compound sentences)
                context_chunk = re.split(r'[,.;]|\band\b', context_before)[-1]
                
                # Define directional terms
                directional_words = ["under", "over", "less", "more", "higher", "lower", "better", "worse", "between", "within", "at most", "maximum", "minimum"]
                has_direction = any(dw in context_chunk for dw in directional_words)
                
                # If there are no directional words (indicating it's "of 15"), or if "exactly" is explicitly written, force trigger the exact match!
                if not has_direction or "exactly" in context_chunk or "equal" in context_chunk:
                    parsed[missing_key] = target_val
                    break

    # Scan the four major numerical indicators
    check_and_fill_exact_match("min_delivery_days", "max_delivery_days")
    check_and_fill_exact_match("min_ghg", "max_ghg")
    check_and_fill_exact_match("min_yield", "max_yield")
    check_and_fill_exact_match("min_precision", "max_precision")

    return parsed

def clean_str(s):
    if not s:
        return ""
    return str(s).lower().replace(" ", "").replace("_", "").replace("ü", "u").strip()

def normalize(val, min_v, max_v, is_lower_better=True):
    try:
        if any(x is None for x in (val, min_v, max_v)):
            return 0.0
        if max_v == min_v:
            return 1.0
        if is_lower_better:
            return (max_v - val) / (max_v - min_v)
        return (val - min_v) / (max_v - min_v)
    except Exception:
        return 0.0

def parse_combined_intent_json(raw_str):
    try:
        s = raw_str.replace("```json", "").replace("```", "").strip()
        s = re.sub(r"//.*", "", s)
        s = re.sub(r"#.*", "", s)
        s = re.sub(r'(?<!")\b(\w+)\b(?!")(?=\s*:)', r'"\1"', s)

        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m: return None, "Unable to find JSON braces in LLM output"
        candidate = m.group(0)

        try:
            return json.loads(candidate), None
        except json.JSONDecodeError:
            pass

        try:
            translated = (candidate.replace("null", "None").replace("true", "True").replace("false", "False"))
            return ast.literal_eval(translated), None
        except Exception:
            pass
        return None, f"Unable to parse JSON, original string: {candidate[:200]}"
    except Exception as e:
        return None, str(e)

# ──────────────────────────────────────────────
# Streamlit Frontend and Main Logic
# ──────────────────────────────────────────────
st.title("🤖 ACCURATE Smart Matchmaking Assistant")

with st.expander("Check Ontology Schema"):
    st.code(CUSTOM_SCHEMA, language="turtle")

WEIGHTS = {
    "DeliveryTime": 0.25,
    "GHG":          0.15,
    "Precision":    0.22,
    "Yield":        0.18,
    "QualityCert":  0.15,
    "EnergyCert":   0.05,
}

def combined_chain_call_no_cache(has_context: str, question: str):
    raw_result = combined_chain.invoke({"has_context": has_context, "question": question})
    return raw_result.content if hasattr(raw_result, "content") else str(raw_result)

def generate_response_fixed(question: str, action: str, context: str):
    full_text = ""
    for chunk in response_chain.stream({"question": question, "action": action, "context": context}):
        full_text += chunk
    
    # 1. Extract the “thinking” section
    thinking_matches = re.findall(r"<thinking>(.*?)(?:</thinking>|$)", full_text, re.DOTALL)
    thinking_content = thinking_matches[-1].strip() if thinking_matches else ""
    
    # 2. Extract the “answer” section
    answer_matches = re.findall(r"<answer>(.*?)(?:</answer>|$)", full_text, re.DOTALL)

    if answer_matches:
        valid_matches = [m.strip() for m in answer_matches if m.strip() and m.strip() != "..."]
        if valid_matches: return valid_matches[-1], thinking_content, full_text
        elif answer_matches: return answer_matches[-1].strip(), thinking_content, full_text
        
    # 3. 🚨 Ultimate Fallback Mechanism: If LLM forgets to write the <answer> tag, forcefully remove the <thinking> section from the string!
    fallback_answer = re.sub(r"<thinking>.*?(?:</thinking>|$)", "", full_text, flags=re.DOTALL).strip()
    
    # 4. 🛡️ [User Safety Net] Boundary Protection: If nothing remains after removing “thinking” (e.g., the model terminates prematurely)
    if not fallback_answer:
        fallback_answer = "I'm sorry, I encountered an error while formulating my recommendation. Please try asking your question again."
    
    return fallback_answer, thinking_content, full_text

# [Fix 4] Smart Correction Tip (Info)
def smart_precision_correction(filters):
    min_it = filters.get("min_precision")
    max_it = filters.get("max_precision")
    if min_it and max_it:
        try:
            min_f = float(min_it)
            max_f = float(max_it)
            if min_f < max_f:
                st.info(
                    f"ℹ️ **Precision Range Detected**: IT{int(min_f)} to IT{int(max_f)}\n\n"
                    f"This matches services with precision grades in this range (inclusive).\n\n"
                    f"**Reminder**: Lower IT number = Better precision.\n"
                    f"- IT{int(min_f)} is better (more precise) than IT{int(max_f)}"
                )
        except ValueError:
            pass

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What kind of manufacturing services are you looking for?"):
    # 1. The screen displays the user's “raw input” (to maintain a natural user experience)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        action = "NEW_SEARCH"
        user_filters = {}
        has_context = st.session_state.last_analysis_context is not None

        # ── 🚨 Key Change 1: Apply preprocessing ──
        normalized_prompt = normalize_query(prompt)
        
        # ── 🛠️ Key Change 2: Preserve Debug Messages for Easy Development Phase Tracking ──
        st.caption(f"🔧 [System-Level Rewrite]: {normalized_prompt}") 

        DEFINITE_FOLLOW_UP_SIGNALS = [
            "in this table", "in the table", "in this list", "from the table",
            "from the list", "from the results", "among these", "among them",
            "does ms", "is ms", "can ms", "has ms", "why is ms", "why does ms", " vs ", " versus ",
        ]
        
        # ── 🚨 Key Change 3: Use normalized_prompt for all subsequent judgments ──
        prompt_lower = normalized_prompt.lower()
        python_forced_followup = has_context and any(sig in prompt_lower for sig in DEFINITE_FOLLOW_UP_SIGNALS)

        if python_forced_followup:
            action = "FOLLOW_UP"
            st.caption(f"⚡ Python Fast Routing: [FOLLOW_UP]")
        else:
            with st.spinner("🧠 Understanding Requirements (1/2)..."):
                raw_combined_content = combined_chain_call_no_cache(
                    has_context=str(has_context), 
                    question=normalized_prompt
                )
                parsed, parse_error = parse_combined_intent_json(raw_combined_content)

                # ── 🚨 Key Change: Apply Post-Processing Force Correction ──
                if parsed is not None:
                    parsed = fix_llm_field_swaps(parsed, normalized_prompt)

                if parsed is None:
                    st.warning("⚠️ Unable to parse requirements, system has switched to \"Show All Services\" mode.")
                    action = "NEW_SEARCH"
                    user_filters = {}
                else:
                    action = parsed.get("action", "NEW_SEARCH")
                    for k, v in parsed.items():
                        if k != "action":
                            cleaned = sanitize_filter_val(v)
                            if cleaned is not None:
                                user_filters[k] = cleaned

        st.caption(f"🤖 Execution Mode: **[{action}]**")

        # [Fix 3] Diagnostic Panel (Debug)
        if user_filters:
            with st.expander("🔍 Detected filter criteria"):
                st.json(user_filters)
                if "min_precision" in user_filters or "max_precision" in user_filters:
                    min_it = user_filters.get("min_precision")
                    max_it = user_filters.get("max_precision")
                    st.markdown("**🎯 Precision Extraction Diagnosis: **")
                    if min_it:
                        st.text(f"  min_precision = {min_it}\n  → Meaning: Precision lower than IT{min_it} (looser tolerance, larger IT numbers like IT{int(min_it)+1}, IT{int(min_it)+2}...)")
                    if max_it:
                        st.text(f"  max_precision = {max_it}\n  → Meaning: Precision higher than IT{max_it} (tighter tolerance, smaller IT numbers like IT{int(max_it)-1}, IT{int(max_it)-2}...)")
                    if min_it and max_it:
                        if float(min_it) > float(max_it):
                            st.warning(f"  ⚠️ Mathematically Contradictory: min ({min_it}) > max ({max_it})")
                        else:
                            st.success(f"  ✅ Logically Consistent: min ({min_it}) ≤ max ({max_it})")

        # Call Info Prompt
        if action == "NEW_SEARCH" and user_filters:
            smart_precision_correction(user_filters)

        # ── Universal Contradiction Check ──
        metrics_to_check = [
            ("delivery_days", "Delivery Time", "days"),
            ("ghg", "GHG Emission", "kg"),
            ("precision", "Precision", "(IT Grade)"), 
            ("yield", "Yield Rate", "%")
        ]

        raw_connector = user_filters.get("delivery_connector_word", "and")
        delivery_mode = str(raw_connector).strip().upper()

        for metric_key, metric_name, unit in metrics_to_check:
            min_val = user_filters.get(f"min_{metric_key}")
            max_val = user_filters.get(f"max_{metric_key}")
            
            if metric_key == "delivery_days" and delivery_mode == "OR": continue
                
            if min_val is not None and max_val is not None:
                try:
                    min_f = float(min_val)
                    max_f = float(max_val)
                    
                    if min_f > max_f:
                        # [Fix 2] Amplify conflicting information
                        if metric_key == "precision":
                            msg = (
                                f"⚠️ **Contradictory Precision Requirements Detected**\n\n"
                                f"**Your query implies:**\n"
                                f"- Precision worse than IT{int(min_f)} (looser tolerance, larger IT numbers like IT{int(min_f)+1}, IT{int(min_f)+2}...)\n"
                                f"- AND precision better than IT{int(max_f)} (tighter tolerance, smaller IT numbers like IT{int(max_f)-1}, IT{int(max_f)-2}...)\n\n"
                                f"**Why this is impossible:**\n"
                                f"There is NO IT grade that is simultaneously worse than IT{int(min_f)} AND better than IT{int(max_f)}.\n\n"
                                f"**💡 Did you mean one of these?**\n"
                                f"- *'Precision between IT{int(max_f)} and IT{int(min_f)}'* (inclusive range)\n"
                                f"- *'Precision better than IT{int(min_f)}'* (only the better part)\n"
                                f"- *'Precision worse than IT{int(max_f)}'* (only the worse part)\n"
                            )
                        else:
                            msg = f"⚠️ **Contradictory Conditions**: Your request for {metric_name} requires values to be simultaneously 'under {int(max_f)} {unit}' AND 'over {int(min_f)} {unit}', which is logically impossible.\n\n💡 **Suggestion**: Please adjust your requirements so the range does not conflict."
                        
                        with st.chat_message("assistant"):
                            st.warning(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.stop()
                except Exception:
                    pass

        final_context_data = None

        if action == "NEW_SEARCH":
            with st.spinner("📡 Search the knowledge base（2/2）..."):
                service_results, requirement_results, fetch_error = fetch_all_sparql_data()

                if fetch_error:
                    st.error(f"❌ Fuseki Search Failed: {fetch_error}")
                    st.stop()

                dt_limit, ghg_limit = None, None
                if requirement_results:
                    for b in requirement_results["results"]["bindings"]:
                        val_type = b.get("valueType", {}).get("value", "")
                        threshold = b.get("thresholdValue", {}).get("value")
                        if threshold:
                            try:
                                v = float(threshold)
                                if "OnTimeDelivery" in val_type: dt_limit = int(v)
                                elif "GHGEmission" in val_type: ghg_limit = int(v)
                            except Exception: pass

                all_raw_data = []
                if service_results:
                    for b in service_results["results"]["bindings"]:
                        def gv(key): return b[key]["value"] if key in b else "N/A"
                        svc_uri = gv("service")
                        svc_name = svc_uri.split("#")[-1] if "#" in svc_uri else svc_uri.split("/")[-1]
                        dt_val = gv("deliveryTime")
                        ghg_val = gv("ghgValue")
                        prec_val = gv("precisionVal")
                        yield_val = gv("yieldVal")
                        material = gv("materialName").split("#")[-1]
                        q_cert = gv("qualityCert").split("#")[-1]
                        e_cert = gv("energyCert").split("#")[-1]
                        if q_cert == "N/A": q_cert = "None"
                        if e_cert == "N/A": e_cert = "None"
                        all_raw_data.append({
                            "Service": svc_name, "DeliveryTime": dt_val, "GHG": ghg_val,
                            "Precision": prec_val, "Yield": yield_val, "Material": material,
                            "Quality_Cert": q_cert, "Energy_Cert": e_cert,
                        })

                def collect_vals(key): return [clean_val(i[key]) for i in all_raw_data if clean_val(i[key]) is not None]
                vals_dt = collect_vals("DeliveryTime")
                vals_ghg = collect_vals("GHG")
                vals_prec = collect_vals("Precision")
                vals_yield = collect_vals("Yield")

                min_dt, max_dt = (min(vals_dt), max(vals_dt)) if vals_dt else (0.0, 100.0)
                min_ghg, max_ghg = (min(vals_ghg), max(vals_ghg)) if vals_ghg else (0.0, 100.0)
                min_prec, max_prec = (min(vals_prec), max(vals_prec)) if vals_prec else (0.0, 100.0)
                min_yield, max_yield = (min(vals_yield), max(vals_yield)) if vals_yield else (0.0, 100.0)

                target_mat = user_filters.get("target_material")
                excluded_mat = user_filters.get("excluded_material")
                target_c = user_filters.get("target_cert")
                excluded_c = user_filters.get("excluded_cert")
                max_days = user_filters.get("max_delivery_days")
                min_days = user_filters.get("min_delivery_days")
                max_ghg_f = user_filters.get("max_ghg")
                min_ghg_f = user_filters.get("min_ghg")
                max_it_f = user_filters.get("max_precision")
                min_it_f = user_filters.get("min_precision")
                min_yield_f = user_filters.get("min_yield")
                max_yield_f = user_filters.get("max_yield")

                processed_report = []
                debug_filter_log = []

                for item in all_raw_data:
                    keep, reason = True, ""

                    # ── [Update] Material Filter (Supports multiple materials separated by commas) ──
                    mat_str = clean_str(item["Material"])
                    if target_mat:
                        # Split the string by commas and check each part individually (must match all targets)
                        for t_mat in str(target_mat).split(','):
                            if clean_str(t_mat) not in mat_str:
                                keep, reason = False, f"Material mismatch (missing {t_mat})"
                                break
                    if keep and excluded_mat:
                        # Split the string into individual elements using commas and check them one by one (if any match the excluded list, it is eliminated)
                        for e_mat in str(excluded_mat).split(','):
                            if clean_str(e_mat) in mat_str:
                                keep, reason = False, f"Excluded material '{e_mat}'"
                                break

                    # ── [Update] Certificate Filter (Supports multiple certificates separated by commas) ──
                    if keep:
                        certs = clean_str(item["Quality_Cert"]) + clean_str(item["Energy_Cert"])
                        if target_c:
                            for t_c in str(target_c).split(','):
                                if clean_str(t_c) not in certs:
                                    keep, reason = False, f"Missing cert '{t_c}'"
                                    break
                        if keep and excluded_c:
                            for e_c in str(excluded_c).split(','):
                                if clean_str(e_c) in certs:
                                    keep, reason = False, f"Has banned cert '{e_c}'"
                                    break
                    if keep:
                        v = clean_val(item["DeliveryTime"])
                        if v is not None and (max_days is not None or min_days is not None):
                            if delivery_mode == "OR":
                                cond_max = (max_days is None) or (v <= float(max_days))
                                cond_min = (min_days is None) or (v >= float(min_days))
                                if not (cond_max or cond_min): keep, reason = False, "fails OR condition"
                            else:
                                if max_days and v > float(max_days): keep, reason = False, "DT too high"
                                if keep and min_days and v < float(min_days): keep, reason = False, "DT too low"
                    if keep:
                        v = clean_val(item["GHG"])
                        if v is not None:
                            if max_ghg_f and v > float(max_ghg_f): keep, reason = False, "GHG too high"
                            if keep and min_ghg_f and v < float(min_ghg_f): keep, reason = False, "GHG too low"
                    if keep:
                        v = clean_val(item["Precision"])
                        if v is not None:
                            if max_it_f and v > float(max_it_f): keep, reason = False, "IT too high (worse)"
                            if keep and min_it_f and v < float(min_it_f): keep, reason = False, "IT too low (better)"
                    if keep:
                        v = clean_val(item["Yield"])
                        if v is not None:
                            if min_yield_f and v < float(min_yield_f): keep, reason = False, "Yield too low"
                            if keep and max_yield_f and v > float(max_yield_f): keep, reason = False, "Yield too high"

                    debug_filter_log.append(f"{'✅' if keep else '❌'} {item['Service']}: {'Kept' if keep else reason}")
                    if not keep: continue

                    score = 0.0
                    v = clean_val(item["GHG"])
                    if v is not None: score += normalize(v, min_ghg, max_ghg, True) * WEIGHTS["GHG"]
                    v = clean_val(item["DeliveryTime"])
                    if v is not None: score += normalize(v, min_dt, max_dt, True) * WEIGHTS["DeliveryTime"]
                    v = clean_val(item["Precision"])
                    if v is not None: score += normalize(v, min_prec, max_prec, True) * WEIGHTS["Precision"]
                    v = clean_val(item["Yield"])
                    if v is not None: score += normalize(v, min_yield, max_yield, False) * WEIGHTS["Yield"]
                    if item["Quality_Cert"] != "None": score += WEIGHTS["QualityCert"]
                    if item["Energy_Cert"] != "None": score += WEIGHTS["EnergyCert"]

                    item["Total_Score"] = round(score * 100, 1)
                    processed_report.append(item)

                processed_report.sort(key=lambda x: x["Total_Score"], reverse=True)

                with st.expander("🕵️ Filter Diagnosis Log"):
                    for log in debug_filter_log: st.text(log)

                if processed_report:
                    header = "| Rank | Service | Score | Delivery (Day) | GHG (kg) | Material | Precision (IT) | Yield (%) | Quality Cert | Energy Cert |"
                    divider = "|---|---|---|---|---|---|---|---|---|---|"
                    rows = [f"| {i+1} | {r['Service']} | {r['Total_Score']} | {r['DeliveryTime']} | {r['GHG']} | {r['Material']} | {r['Precision']} | {r['Yield']} | {r['Quality_Cert']} | {r['Energy_Cert']} |" for i, r in enumerate(processed_report)]
                    final_table = header + "\n" + divider + "\n" + "\n".join(rows)
                else:
                    final_table = "_No services matched your criteria._"

                top_info = {"Name": "None", "Score": "N/A"}
                if processed_report:
                    top_info = {"Name": processed_report[0]["Service"], "Score": processed_report[0]["Total_Score"]}

                combined_context = {
                    "Database_Extremes": {"min_dt": min_dt, "min_ghg": min_ghg, "min_prec": min_prec, "max_yield": max_yield},
                    "Top_Recommendation": top_info,
                    "Processed_Report_Raw": processed_report,
                    "Pre_Generated_Table": final_table,
                }
                st.session_state.last_analysis_context = combined_context
                final_context_data = combined_context

        else:
            if st.session_state.last_analysis_context is None:
                st.warning("💡 No previous search results available. Please describe your requirements first.")
                st.stop()
            final_context_data = st.session_state.last_analysis_context
            st.info("💡 Follow-up questions based on the previous search results (using cached data)")

        if final_context_data:
            weights_info = (
                "=== HOW TO READ THIS DATA ===\n"
                "Each row represents ONE service with ALL its attributes.\n"
                "Material column shows ONLY the material that service can process.\n"
                "=== PRECISION (IT) SCALE ===\n"
                "Lower IT number = HIGHER precision quality.\n"
                "  IT6 > IT7 > IT8 > IT9 (precision ranking)\n\n"
            )

            if action == "NEW_SEARCH":
                report = final_context_data.get("Processed_Report_Raw", [])
                top = final_context_data.get("Top_Recommendation", {})
                extremes = final_context_data.get("Database_Extremes", {})

                if not report:
                    db_min_dt = extremes.get("min_dt", "N/A")
                    db_min_ghg = extremes.get("min_ghg", "N/A")
                    db_min_prec = extremes.get("min_prec", "N/A")
                    db_max_yield = extremes.get("max_yield", "N/A")
                    flat_data = (
                        "=== SYSTEM DIRECTIVE ===\n"
                        "⚠️ STATUS: EMPTY_RESULT ⚠️\n"
                        "System Note: 0 services matched the criteria. The table is completely EMPTY.\n"
                        "You MUST tell the user no services meet ALL criteria simultaneously.\n\n"
                        "=== DATABASE LIMITS REFERENCE ===\n"
                        f"- Best Delivery Time available in DB: {db_min_dt} days\n"
                        f"- Lowest GHG Emission available in DB: {db_min_ghg} kg\n"
                        f"- Highest Precision available in DB: IT{db_min_prec}\n"
                        f"- Highest Yield available in DB: {db_max_yield}%\n"
                    )
                else:
                    top_service = top.get("Name", "None")
                    top_score = top.get("Score", "N/A")
                    all_services = [r["Service"] for r in report]
                    services_list_str = ", ".join(all_services)

                    # [Perfect Adoption of User Ideas] Add extremely strong visual anchors to dispel negative wording illusions
                    header = (
                        f"=== SYSTEM DIRECTIVE ===\n"
                        f"⚠️ STATUS: SUCCESS_MATCH ⚠️\n"
                        f"⚠️ THE TABLE IS NOT EMPTY. There are {len(report)} matching services! ⚠️\n"
                        f"Recommended Service: {top_service}\n"
                        f"Recommended Score: {top_score}\n"
                        f"All Services in Table: {services_list_str}\n"
                        f"========================\n\n"
                    )
                    rows_str = "\n".join(
                        f"Rank {i+1}: Service={r['Service']}, Score={r.get('Total_Score',0)}, "
                        f"Material={r['Material']}, Delivery={r['DeliveryTime']} days, "
                        f"Precision=IT{r['Precision']}, Yield={r['Yield']}%, "
                        f"Quality_Cert={r['Quality_Cert']}, Energy_Cert={r['Energy_Cert']}, GHG={r['GHG']} kg"
                        for i, r in enumerate(report)
                    )
                    flat_data = header + weights_info + rows_str

                st.session_state.saved_flat_context = flat_data
            else:
                report = final_context_data.get("Processed_Report_Raw", [])
                if not report:
                    flat_data = "No data available from previous search."
                else:
                    rows_str = "\n".join(
                        f"Service={r['Service']}, Score={r.get('Total_Score',0)}, "
                        f"Material={r['Material']}, Delivery={r['DeliveryTime']} days, "
                        f"Precision=IT{r['Precision']}, Yield={r['Yield']}%, "
                        f"Quality_Cert={r['Quality_Cert']}, Energy_Cert={r['Energy_Cert']}, GHG={r['GHG']} kg"
                        for r in report
                    )
                    flat_data = (
                        "=== DATA FROM PREVIOUS SEARCH ===\n"
                        "The following services were found in the last search.\n"
                        "IMPORTANT: When listing services that match a criterion, you MUST list ALL services that match. Do not omit any.\n\n"
                        + rows_str + "\n\n"
                        "=== PRECISION (IT) REMINDER ===\n"
                        "Lower IT number = HIGHER precision (IT6 > IT7 > IT8 > IT9)\n"
                    )

            if action == "NEW_SEARCH":
                table = final_context_data.get("Pre_Generated_Table", "")
                st.markdown("### 📊 Weighted Scoring Table\n\n" + table)
                st.markdown("### 💬 Interpretation")

            clean_answer, thinking_content, full_llm_output = generate_response_fixed(question=prompt, action=action, context=flat_data)
            clean_answer_escaped = clean_answer.replace(">", "\\>")

            with st.expander("🐛 [DEBUG] Full LLM output"):
                if thinking_content:
                    st.markdown("**🧠 Thinking Process:**")
                    st.code(thinking_content, language="text")
                st.markdown("**📄 Full Output:**")
                st.code(full_llm_output, language="text")

            stream_placeholder = st.empty()
            if len(clean_answer_escaped) < 100:
                stream_placeholder.markdown(clean_answer_escaped)
            else:
                words = clean_answer_escaped.split()
                displayed = ""
                for i, word in enumerate(words):
                    displayed += word + " "
                    if i % 8 == 0 or i == len(words) - 1:
                        stream_placeholder.markdown(displayed.strip() + (" ▌" if i < len(words) - 1 else ""))
                        time.sleep(0.05)
                stream_placeholder.markdown(clean_answer_escaped)

            if action == "NEW_SEARCH":
                table = final_context_data.get("Pre_Generated_Table", "")
                display = f"### 📊 Weighted Scoring Table\n\n{table}\n\n### 💬 Interpretation\n\n{clean_answer}"
            else:
                display = clean_answer

            st.session_state.messages.append({"role": "assistant", "content": display})
        else:
            st.error("System error: Unable to retrieve analytics data. Please reload the page or enter new search criteria.")