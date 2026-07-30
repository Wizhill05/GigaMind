#!/usr/bin/env bash
# ==============================================================================
# GigaMind Deployed RAG Engine Edge-Case Test Suite
# Tests: Auth, Chunking Boundaries, Reranking, Cascading Delete, Profile & Stats
# Target: http://localhost:8000 (or DEPLOYED_URL env var)
# ==============================================================================

set -euo pipefail

# ANSI Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
    set -o allexport
    source "$PROJECT_ROOT/.env"
    set +o allexport
fi

DEPLOYED_URL="${DEPLOYED_URL:-http://localhost:8000}"
LOCAL_URL="${LOCAL_URL:-http://localhost:8000}"
API_KEY="${GIGAMIND_API_KEY:-gigamind-secret-key-change-me}"
VERBOSE="${VERBOSE:-0}"

PASSED_TESTS=0
FAILED_TESTS=0
TOTAL_TESTS=0

# Track created items for post-test database cleanup
CREATED_MEMORY_IDS=()
CREATED_RULE_IDS=()

cleanup_test_data() {
    echo -e "\n${BOLD}${YELLOW}=== CLEANING UP TEST DATA ===${NC}"

    # 1. Delete explicitly tracked memory IDs
    for mem_id in "${CREATED_MEMORY_IDS[@]}"; do
        if [ -n "$mem_id" ]; then
            http_request "DELETE" "/api/v1/memories/$mem_id" "Bearer $API_KEY" "" > /dev/null 2>&1 || true
        fi
    done

    # 2. Delete explicitly tracked profile rule IDs
    for rule_id in "${CREATED_RULE_IDS[@]}"; do
        if [ -n "$rule_id" ]; then
            http_request "DELETE" "/api/v1/profile/$rule_id" "Bearer $API_KEY" "" > /dev/null 2>&1 || true
        fi
    done

    # 3. Fallback category cleanup sweep
    TEST_CATEGORIES=("test_short" "test_long" "unicode_test" "b_599" "b_601" "rerank_test" "agent_test" "del_test" "test")
    for cat in "${TEST_CATEGORIES[@]}"; do
        resp=$(http_request "GET" "/api/v1/memories?category=$cat" "Bearer $API_KEY" "" 2>/dev/null || true)
        python3 -c "
import sys, json
try:
    data = json.loads('''$resp''')
    for m in data.get('memories', []):
        print(m['id'])
except Exception:
    pass
" | while read -r mid; do
            if [ -n "$mid" ]; then
                http_request "DELETE" "/api/v1/memories/$mid" "Bearer $API_KEY" "" > /dev/null 2>&1 || true
            fi
        done
    done

    # Fallback profile rule cleanup sweep
    resp_rules=$(http_request "GET" "/api/v1/get_profile?category=test_rule" "Bearer $API_KEY" "" 2>/dev/null || true)
    python3 -c "
import sys, json
try:
    data = json.loads('''$resp_rules''')
    for r in data.get('profile', []):
        print(r['id'])
except Exception:
    pass
" | while read -r rid; do
        if [ -n "$rid" ]; then
            http_request "DELETE" "/api/v1/profile/$rid" "Bearer $API_KEY" "" > /dev/null 2>&1 || true
        fi
    done

    echo -e "${GREEN}Database cleanup completed successfully.${NC}"
}

trap cleanup_test_data EXIT INT TERM

# Determine Target Server
echo -e "${BOLD}${CYAN}=====================================================${NC}"
echo -e "${BOLD}${CYAN}   GigaMind Deployed Engine Edge-Case Test Suite     ${NC}"
echo -e "${BOLD}${CYAN}=====================================================${NC}"

TARGET_URL=""
echo -n "Checking connectivity to deployed target ($DEPLOYED_URL)... "
if curl -s --max-time 10 "$DEPLOYED_URL/" > /dev/null 2>&1; then
    TARGET_URL="$DEPLOYED_URL"
    echo -e "${GREEN}[ONLINE]${NC}"
else
    echo -e "${YELLOW}[OFFLINE / TIMEOUT]${NC}"
    echo -n "Falling back to local instance ($LOCAL_URL)... "
    if curl -s --max-time 3 "$LOCAL_URL/" > /dev/null 2>&1; then
        TARGET_URL="$LOCAL_URL"
        echo -e "${GREEN}[ONLINE]${NC}"
    else
        echo -e "${RED}[FAILED] Both deployed and local targets unreachable!${NC}"
        exit 1
    fi
fi

echo -e "Active Target Endpoint: ${BOLD}${YELLOW}${TARGET_URL}${NC}\n"

# Helper HTTP Functions
http_request() {
    local method="$1"
    local endpoint="$2"
    local auth_header="$3"
    local body="$4"

    local full_url="${TARGET_URL}${endpoint}"
    local curl_cmd=(curl -s -w "\n%{http_code}" -X "$method" "$full_url" -H "Content-Type: application/json")

    if [ -n "$auth_header" ]; then
        curl_cmd+=(-H "Authorization: $auth_header")
    fi

    if [ -n "$body" ]; then
        curl_cmd+=(-d "$body")
    fi

    local response
    response=$("${curl_cmd[@]}")
    echo "$response"
}

run_test() {
    local test_num="$1"
    local desc="$2"
    local expected_status="$3"
    local actual_status="$4"
    local response_body="$5"
    local assert_script="$6"

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    echo -e "${BOLD}Test ${test_num}: ${desc}${NC}"

    if [ "$VERBOSE" -eq 1 ]; then
        echo -e "Expected HTTP Status: ${expected_status}, Got: ${actual_status}"
        echo -e "Response Body: ${response_body}"
    fi

    local py_res
    py_res=$(python3 -c "
import sys, json

status_code = int(sys.argv[1])
expected_status = int(sys.argv[2])
body_raw = sys.argv[3]
assert_code = sys.argv[4]

if status_code != expected_status:
    print(f'FAIL: Expected HTTP status {expected_status}, got {status_code}')
    sys.exit(1)

data = {}
if body_raw.strip():
    try:
        data = json.loads(body_raw)
    except Exception as e:
        print(f'FAIL: Invalid JSON response: {e}')
        sys.exit(1)

if assert_code.strip():
    try:
        exec(assert_code, {'data': data, 'status_code': status_code})
    except AssertionError as ae:
        print(f'FAIL Assertion: {ae}')
        sys.exit(1)
    except Exception as ex:
        print(f'FAIL Exception during assertion: {ex}')
        sys.exit(1)

print('SUCCESS')
" "$actual_status" "$expected_status" "$response_body" "$assert_script" 2>&1 || true)

    if [[ "$py_res" == "SUCCESS" ]]; then
        echo -e "${GREEN}[PASS] Test ${test_num} Passed${NC}\n"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "${RED}[FAIL] Test ${test_num} Failed: ${py_res}${NC}"
        echo -e "${RED}Detailed Response: ${response_body}${NC}\n"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
}

# ==============================================================================
# SECTION 1: AUTHENTICATION & SECURITY EDGE CASES
# ==============================================================================
echo -e "${BOLD}${YELLOW}=== SECTION 1: AUTHENTICATION & SECURITY ===${NC}"

# Test 1.1: Missing Auth Header
resp=$(http_request "POST" "/api/v1/search_memory" "" '{"query":"test"}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "1.1" "Missing Authorization Header (Expect 401)" "401" "$code" "$body" ""

# Test 1.2: Invalid Bearer Token
resp=$(http_request "POST" "/api/v1/search_memory" "Bearer invalid_token_xyz" '{"query":"test"}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "1.2" "Invalid Bearer Token (Expect 401)" "401" "$code" "$body" ""

# Test 1.3: Valid Bearer Token
resp=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"test"}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "1.3" "Valid Bearer Token (Expect 200)" "200" "$code" "$body" "assert 'results' in data"


# ==============================================================================
# SECTION 2: SMART TEXT CHUNKING EDGE CASES
# ==============================================================================
echo -e "${BOLD}${YELLOW}=== SECTION 2: SMART TEXT CHUNKING EDGE CASES ===${NC}"

# Test 2.1: Short Text (<600 chars)
SHORT_TEXT="Short memory content under threshold."
resp=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$SHORT_TEXT\",\"category\":\"test_short\"}")
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
SHORT_MEM_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$body" 2>/dev/null || true)
if [ -n "$SHORT_MEM_ID" ]; then CREATED_MEMORY_IDS+=("$SHORT_MEM_ID"); fi

run_test "2.1a" "Ingest Short Text (<600 chars) -> chunks_created == 1" "200" "$code" "$body" "
assert data['success'] == True
assert data['memory']['chunks_created'] == 1
"

# Search and check parent_id & chunk_info
resp=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"Short memory content","category":"test_short"}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "2.1b" "Search Short Text -> parent_id is None & chunk_info absent" "200" "$code" "$body" "
assert len(data['results']) > 0
item = data['results'][0]
assert item['parent_id'] is None
assert 'chunk_info' not in item
"

# Test 2.2: Long Text (>600 chars, ~1500 chars)
LONG_TEXT=$(python3 -c "print('GigaMind memory engine test paragraph. ' * 40)")
resp=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$LONG_TEXT\",\"category\":\"test_long\"}")
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
PARENT_MEM_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$body")
if [ -n "$PARENT_MEM_ID" ]; then CREATED_MEMORY_IDS+=("$PARENT_MEM_ID"); fi

run_test "2.2a" "Ingest Long Text (>600 chars) -> chunks_created > 1" "200" "$code" "$body" "
assert data['success'] == True
assert data['memory']['chunks_created'] > 1
"

# Search and verify chunk_info & parent_id match
resp=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"GigaMind memory engine test","category":"test_long"}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "2.2b" "Search Long Text -> parent_id matches & chunk_info present" "200" "$code" "$body" "
assert len(data['results']) > 0
item = data['results'][0]
assert item['parent_id'] == '$PARENT_MEM_ID'
assert 'chunk_info' in item
assert 'index' in item['chunk_info']
assert 'total' in item['chunk_info']
"

# Test 2.3: Special Characters & Multi-byte Unicode
PAYLOAD=$(python3 -c '
import json
content = "Unicode test: 🧠🤖⚡ \"double quotes\" \\backslash '\''single'\'' \n newline def test(): pass\n 日本語 中文"
print(json.dumps({"content": content, "category": "unicode_test"}))
')
resp=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "$PAYLOAD")
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
UNI_MEM_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$body" 2>/dev/null || true)
if [ -n "$UNI_MEM_ID" ]; then CREATED_MEMORY_IDS+=("$UNI_MEM_ID"); fi

run_test "2.3a" "Ingest Unicode & Special Characters" "200" "$code" "$body" "assert data['success'] == True"

resp=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"日本語 中文 🧠🤖⚡","category":"unicode_test"}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "2.3b" "Search Exact Unicode Query -> Retrieved accurately" "200" "$code" "$body" "
assert len(data['results']) > 0
assert '🧠' in data['results'][0]['content'] or '日本語' in data['results'][0]['content']
"

# Test 2.4: Boundary Testing (Exact 599 vs 601 chars)
TXT_599=$(python3 -c "print('A' * 599)")
resp=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$TXT_599\",\"category\":\"b_599\"}")
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
B599_MEM_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$body" 2>/dev/null || true)
if [ -n "$B599_MEM_ID" ]; then CREATED_MEMORY_IDS+=("$B599_MEM_ID"); fi

run_test "2.4a" "Boundary Text Exact 599 chars -> chunks_created == 1" "200" "$code" "$body" "assert data['memory']['chunks_created'] == 1"

TXT_601=$(python3 -c "print('B' * 601)")
resp=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$TXT_601\",\"category\":\"b_601\"}")
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
B601_MEM_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$body" 2>/dev/null || true)
if [ -n "$B601_MEM_ID" ]; then CREATED_MEMORY_IDS+=("$B601_MEM_ID"); fi

run_test "2.4b" "Boundary Text Exact 601 chars -> chunks_created > 1" "200" "$code" "$body" "assert data['memory']['chunks_created'] > 1"


# ==============================================================================
# SECTION 3: 2-STAGE RETRIEVAL & RERANKING EDGE CASES
# ==============================================================================
echo -e "${BOLD}${YELLOW}=== SECTION 3: 2-STAGE RETRIEVAL & RERANKING ===${NC}"

# Ingest Candidate A (generic vector relevance)
CAND_A="General quantum physics and database engine architecture overview."
resp_ca=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$CAND_A\",\"category\":\"rerank_test\"}")
CA_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$(echo "$resp_ca" | sed '$d')" 2>/dev/null || true)
if [ -n "$CA_ID" ]; then CREATED_MEMORY_IDS+=("$CA_ID"); fi

# Ingest Candidate B (exact phrase keyword match)
CAND_B="Specific target phrase: quantum flux capacitor engine initialization sequence."
resp_cb=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$CAND_B\",\"category\":\"rerank_test\"}")
CB_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$(echo "$resp_cb" | sed '$d')" 2>/dev/null || true)
if [ -n "$CB_ID" ]; then CREATED_MEMORY_IDS+=("$CB_ID"); fi

# Test 3.1: Reranking Re-order Verification
resp=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"quantum flux capacitor engine","category":"rerank_test","limit":5}')
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
run_test "3.1" "Cross-Encoder Reranks Candidate B (exact phrase) Above Candidate A" "200" "$code" "$body" "
assert len(data['results']) >= 2
first_item = data['results'][0]
assert 'quantum flux capacitor' in first_item['content'].lower()
"

# Test 3.2: Score Presence Assertions
run_test "3.2" "Search Results Contain score, vector_score, rerank_score" "200" "$code" "$body" "
item = data['results'][0]
assert 'score' in item
assert 'vector_score' in item
assert 'rerank_score' in item
"

# Test 3.3: Limit Boundary Testing
resp1=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"test","limit":1}')
code=$(echo "$resp1" | tail -n1)
body1=$(echo "$resp1" | sed '$d')
run_test "3.3a" "Limit Boundary limit=1" "200" "$code" "$body1" "assert len(data['results']) <= 1"

resp5=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"test","limit":5}')
code=$(echo "$resp5" | tail -n1)
body5=$(echo "$resp5" | sed '$d')
run_test "3.3b" "Limit Boundary limit=5" "200" "$code" "$body5" "assert len(data['results']) <= 5"

# Test 3.4: Category Filtering
resp_cat=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"memory","category":"rerank_test"}')
code=$(echo "$resp_cat" | tail -n1)
body_cat=$(echo "$resp_cat" | sed '$d')
run_test "3.4" "Category Filtering -> Returns only requested category items" "200" "$code" "$body_cat" "
for item in data['results']:
    assert item['category'] == 'rerank_test'
"

# Test 3.5: Source Agent Filtering
resp_c1=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" '{"content":"Claude specific item","category":"agent_test","source_agent":"claude"}')
C1_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$(echo "$resp_c1" | sed '$d')" 2>/dev/null || true)
if [ -n "$C1_ID" ]; then CREATED_MEMORY_IDS+=("$C1_ID"); fi

resp_g1=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" '{"content":"GPT specific item","category":"agent_test","source_agent":"gpt"}')
G1_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$(echo "$resp_g1" | sed '$d')" 2>/dev/null || true)
if [ -n "$G1_ID" ]; then CREATED_MEMORY_IDS+=("$G1_ID"); fi

resp_agent=$(http_request "POST" "/api/v1/search_memory" "Bearer $API_KEY" '{"query":"item","category":"agent_test","source_agent":"claude"}')
code=$(echo "$resp_agent" | tail -n1)
body_agent=$(echo "$resp_agent" | sed '$d')
run_test "3.5" "Source Agent Filtering -> Respected strictly" "200" "$code" "$body_agent" "
for item in data['results']:
    assert item['source_agent'] == 'claude'
"


# ==============================================================================
# SECTION 4: CASCADING DELETION EDGE CASES
# ==============================================================================
echo -e "${BOLD}${YELLOW}=== SECTION 4: CASCADING DELETION EDGE CASES ===${NC}"

# Ingest multi-chunk memory
DEL_TEXT=$(python3 -c "print('Cascading deletion test document chunking content. ' * 30)")
resp=$(http_request "POST" "/api/v1/add_memory" "Bearer $API_KEY" "{\"content\":\"$DEL_TEXT\",\"category\":\"del_test\"}")
code=$(echo "$resp" | tail -n1)
body=$(echo "$resp" | sed '$d')
DEL_PARENT_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('memory', {}).get('id', ''))" "$body")

# Delete Parent Memory
resp_del=$(http_request "DELETE" "/api/v1/memories/$DEL_PARENT_ID" "Bearer $API_KEY" "")
code=$(echo "$resp_del" | tail -n1)
body_del=$(echo "$resp_del" | sed '$d')
run_test "4.1" "Delete Parent Memory Endpoint -> HTTP 200 OK" "200" "$code" "$body_del" "assert data['success'] == True"

# Verify parent and all child chunks erased from memories list & search
resp_mem_list=$(http_request "GET" "/api/v1/memories?category=del_test" "Bearer $API_KEY" "")
code=$(echo "$resp_mem_list" | tail -n1)
body_mem_list=$(echo "$resp_mem_list" | sed '$d')
run_test "4.2" "Cascading Deletion Verification -> Parent & child chunks removed" "200" "$code" "$body_mem_list" "
for mem in data['memories']:
    assert mem['id'] != '$DEL_PARENT_ID'
    assert mem['parent_id'] != '$DEL_PARENT_ID'
"


# ==============================================================================
# SECTION 5: PROFILE RULES & STATS VERIFICATION
# ==============================================================================
echo -e "${BOLD}${YELLOW}=== SECTION 5: PROFILE RULES & STATS VERIFICATION ===${NC}"

# Test 5.1: Profile Rule Lifecycle
resp_prof=$(http_request "POST" "/api/v1/set_profile_rule" "Bearer $API_KEY" '{"key":"edgecase_rule_key","value":"edgecase_rule_val","category":"test_rule"}')
code=$(echo "$resp_prof" | tail -n1)
body_prof=$(echo "$resp_prof" | sed '$d')
run_test "5.1a" "Upsert Profile Rule" "200" "$code" "$body_prof" "assert data['success'] == True"

RULE_ID=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(data.get('rule', {}).get('id', ''))" "$body_prof")
if [ -n "$RULE_ID" ]; then CREATED_RULE_IDS+=("$RULE_ID"); fi

resp_get_prof=$(http_request "GET" "/api/v1/get_profile?category=test_rule" "Bearer $API_KEY" "")
code=$(echo "$resp_get_prof" | tail -n1)
body_get_prof=$(echo "$resp_get_prof" | sed '$d')
run_test "5.1b" "Fetch Profile Rules -> Verified rule present" "200" "$code" "$body_get_prof" "
rules = [r for r in data['profile'] if r['key'] == 'edgecase_rule_key']
assert len(rules) == 1
assert rules[0]['value'] == 'edgecase_rule_val'
"

resp_del_prof=$(http_request "DELETE" "/api/v1/profile/$RULE_ID" "Bearer $API_KEY" "")
code=$(echo "$resp_del_prof" | tail -n1)
body_del_prof=$(echo "$resp_del_prof" | sed '$d')
run_test "5.1c" "Delete Profile Rule" "200" "$code" "$body_del_prof" "assert data['success'] == True"

# Test 5.2: Stats Endpoint Verification
resp_stats=$(http_request "GET" "/api/v1/stats" "Bearer $API_KEY" "")
code=$(echo "$resp_stats" | tail -n1)
body_stats=$(echo "$resp_stats" | sed '$d')
run_test "5.2" "Engine Stats Endpoint -> Valid counts & source distribution" "200" "$code" "$body_stats" "
assert 'total_memories' in data
assert 'total_profile_rules' in data
assert 'total_chat_logs' in data
assert 'total_task_sessions' in data
assert 'source_distribution' in data
assert isinstance(data['source_distribution'], dict)
"


# ==============================================================================
# EXECUTION SUMMARY
# ==============================================================================
echo -e "${BOLD}${CYAN}=====================================================${NC}"
echo -e "${BOLD}${CYAN}                 EXECUTION SUMMARY                  ${NC}"
echo -e "${BOLD}${CYAN}=====================================================${NC}"
echo -e "Total Tests Executed : ${BOLD}${TOTAL_TESTS}${NC}"
echo -e "Passed               : ${BOLD}${GREEN}${PASSED_TESTS}${NC}"
echo -e "Failed               : ${BOLD}${RED}${FAILED_TESTS}${NC}"

if [ "$FAILED_TESTS" -eq 0 ]; then
    echo -e "${BOLD}${GREEN}ALL EDGE-CASE TESTS PASSED SUCCESSFULLY!${NC}"
    exit 0
else
    echo -e "${BOLD}${RED}TEST SUITE FAILED WITH $FAILED_TESTS FAILURES!${NC}"
    exit 1
fi
